"""Shared helpers for lesson-plan tools with MutationPolicy support."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from app.agent.core.gates import gates_active
from app.agent.registry import ToolContext
from app.schemas.blueprint import CourseBlueprintSchema

T = TypeVar("T")


class ToolGuardError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        requested_target: Any = None,
        allowed_scope: Any = None,
        suggestion: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.requested_target = requested_target
        self.allowed_scope = allowed_scope
        self.suggestion = suggestion


@dataclass
class MutationPolicy:
    """本轮运行的细粒度修改权限策略。"""

    allowed_section_ids: set[str] = field(default_factory=set)
    new_section_ids: set[str] = field(default_factory=set)
    allowed_core_keys: set[str] = field(default_factory=set)
    allow_structure_ops: bool = True
    allow_top_level_add: bool = True
    forbidden_paths: list[str] = field(default_factory=list)
    preserved_section_hashes: dict[str, str] = field(default_factory=dict)


@dataclass
class MutationReceipt:
    """每次写操作返回的可验证修改凭证。

    执行器校验（contract/scope/before_hash/幂等）通过后由工具填充并返回；
    runtime 据此判定 changed / 触发 patch.operation.applied 事件。
    """

    operation_id: str = ""
    tool_name: str = ""
    target_paths: list[str] = field(default_factory=list)
    before_hash: str = ""
    after_hash: str = ""
    changed: bool = False
    changed_section_ids: list[str] = field(default_factory=list)
    changed_core_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _content_hash(content: dict[str, Any]) -> str:
    import hashlib

    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_mutation_receipt(
    tc: ToolContext,
    *,
    tool_name: str,
    change_paths: list[str],
    before_content: dict[str, Any],
    after_content: dict[str, Any],
    section_ids: list[str] | None = None,
    core_keys: list[str] | None = None,
) -> MutationReceipt:
    """构造 MutationReceipt：校验 before/after 哈希，登记变化范围。"""
    before_hash = _content_hash(before_content)
    after_hash = _content_hash(after_content)
    changed = before_hash != after_hash
    changed_sections = [sid for sid in (section_ids or []) if sid]
    changed_core = list(core_keys or [])
    receipt = MutationReceipt(
        operation_id=f"op-{tool_name}-{_content_hash({'p': change_paths, 'b': before_hash})[:10]}",
        tool_name=tool_name,
        target_paths=list(change_paths),
        before_hash=before_hash,
        after_hash=after_hash,
        changed=changed,
        changed_section_ids=changed_sections,
        changed_core_keys=changed_core,
    )
    runtime = getattr(tc, "runtime", None)
    if runtime is not None and hasattr(runtime, "record_mutation"):
        runtime.record_mutation(receipt)
    return receipt


def builder_for(tc: ToolContext):
    builder = tc.extra.get("builder")
    if builder is None:
        raise ValueError("候选稿 Builder 未初始化")
    return builder


def blueprint_data(tc: ToolContext) -> dict[str, Any]:
    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    if blueprint is None:
        raise LookupError("上下文缺少课程蓝图")
    if hasattr(blueprint, "model_dump"):
        return blueprint.model_dump()
    if isinstance(blueprint, dict):
        return dict(blueprint)
    # 兼容对象属性
    return {
        "course_identity": getattr(blueprint, "course_identity", {}),
        "objectives": getattr(blueprint, "objectives", []),
        "knowledge_points": getattr(blueprint, "knowledge_points", []),
        "timeline": getattr(blueprint, "timeline", []),
        "assessment_plan": getattr(blueprint, "assessment_plan", []),
    }


def blueprint_schema(tc: ToolContext) -> CourseBlueprintSchema:
    data = blueprint_data(tc)
    return CourseBlueprintSchema.model_validate(data)


def lock_paths(tc: ToolContext) -> list[str]:
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    result = []
    for lock in locks or []:
        path = getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        if path is not None:
            result.append(str(path))
    return result


def _tokens(path: str) -> list[str]:
    cleaned = path.strip().lstrip("$").lstrip(".")
    return [part for part in re.split(r"\.|\[|\]", cleaned) if part]


def _conflicts(left: str, right: str) -> bool:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return True
    return a == b[: len(a)] or b == a[: len(b)]


def _indexed_section_path(tc: ToolContext, section_id: str) -> str | None:
    builder = builder_for(tc)

    def visit(items: list[dict[str, Any]], prefix: str) -> str | None:
        for index, item in enumerate(items):
            path = f"{prefix}[{index}]"
            if str(item.get("id") or "") == section_id:
                return path
            found = visit(list(item.get("children") or []), f"{path}.children")
            if found:
                return found
        return None

    return visit(builder.outline, "$.outline.sections")


def _expand_change_paths(tc: ToolContext, paths: list[str]) -> list[str]:
    expanded = list(paths)
    for path in paths:
        match = re.search(r"\$\.outline\.sections\[([^\]]+)\]", path)
        if not match:
            continue
        indexed = _indexed_section_path(tc, match.group(1))
        if indexed:
            suffix = path[match.end():]
            expanded.append(indexed + suffix)
    return list(dict.fromkeys(expanded))


def get_mutation_policy(tc: ToolContext) -> MutationPolicy | None:
    """获取当前注入的 MutationPolicy。"""
    if tc.runtime and hasattr(tc.runtime, "mutation_policy"):
        return getattr(tc.runtime, "mutation_policy")
    return tc.extra.get("mutation_policy")


def guard_paths(
    tc: ToolContext,
    change_paths: list[str],
    *,
    section_ids: list[str] | None = None,
    global_change: bool = False,
    is_add_section: bool = False,
    is_split_section: bool = False,
    core_keys: list[str] | None = None,
) -> None:
    locked = lock_paths(tc)
    if any(path in {"", "$"} for path in locked):
        raise ToolGuardError("artifact_locked", "当前任务文件已整体锁定，不允许修改")
    effective_paths = _expand_change_paths(tc, change_paths)
    for lock_path in locked:
        for change_path in effective_paths:
            if _conflicts(lock_path, change_path):
                raise ToolGuardError(
                    "locked_path_conflict",
                    f"修改路径 {change_path} 与锁定路径 {lock_path} 冲突",
                    requested_target=change_path,
                    allowed_scope=locked,
                )

    # relaxed 门禁模式：教师锁定仍然生效；MutationPolicy 与选中范围只作为
    # 提示词引导，不再拒绝工具调用（避免意图解析偏差导致合法修改被拒）。
    if not gates_active():
        return

    policy = get_mutation_policy(tc)
    runtime = getattr(tc, "runtime", None)
    current_agent = getattr(runtime, "current_agent_key", "")
    content_policy = getattr(runtime, "content_policy", "")
    selected = list(getattr(runtime, "selected_section_ids", None) or [])

    # 如果有细粒度 MutationPolicy
    if policy is not None:
        if not policy.allow_structure_ops and (is_add_section or is_split_section):
            raise ToolGuardError(
                "structure_modification_forbidden",
                "本轮修改契约不允许执行目录结构调整",
                suggestion="如需调整结构，请切换为结构模式或在指令中明确提出",
            )
        if core_keys:
            unauthorized = [k for k in core_keys if k not in policy.allowed_core_keys]
            if unauthorized:
                raise ToolGuardError(
                    "core_field_unauthorized",
                    f"未授权修改教学内核字段：{unauthorized}",
                    requested_target=unauthorized,
                    allowed_scope=list(policy.allowed_core_keys),
                    suggestion=f"本轮仅允许修改内核字段：{list(policy.allowed_core_keys)}",
                )
        if section_ids and not (is_add_section or is_split_section):
            allowed_sections = policy.allowed_section_ids | policy.new_section_ids
            if allowed_sections:
                for sid in section_ids:
                    if sid and sid not in allowed_sections:
                        raise ToolGuardError(
                            "section_scope_violation",
                            f"章节 {sid} 不属于本轮允许修改的章节范围",
                            requested_target=sid,
                            allowed_scope=list(allowed_sections),
                            suggestion=f"允许修改的章节：{list(allowed_sections)}",
                        )
        return

    # 回退到基础 content_policy 与 selected 判定
    if content_policy == "preserve" and current_agent == "lesson_designer":
        allowed = set(runtime.content_mutable_section_ids()) if hasattr(runtime, "content_mutable_section_ids") else set()
        if global_change and not is_add_section and not is_split_section:
            raise ToolGuardError(
                "content_policy_violation",
                "纯目录结构调整不允许修改教学内核或应用全局内容补丁",
            )
        for section_id in section_ids or []:
            if section_id and section_id not in allowed:
                raise ToolGuardError(
                    "content_policy_violation",
                    f"结构调整期间不得改写非目标章节正文：{section_id}",
                    requested_target=section_id,
                    allowed_scope=list(allowed),
                )
    if not selected:
        return

    # 如果是新增一级章节或拆分，且契约允许结构变更，不视为越权全局修改
    if is_add_section or is_split_section:
        return

    if global_change:
        raise ToolGuardError(
            "section_scope_violation",
            "当前运行限定了章节范围，不允许修改全局教学内核或完整目录",
            requested_target="global",
            allowed_scope=selected,
        )
    for section_id in section_ids or []:
        if section_id and section_id not in selected:
            # 未选中的章节一律拒绝，不隐含放行；本轮新建章节已通过
            # is_add_section/is_split_section 提前返回。
            raise ToolGuardError(
                "section_scope_violation",
                f"章节 {section_id} 不属于本轮选中范围：{selected}",
                requested_target=section_id,
                allowed_scope=selected,
            )


def atomic_edit(
    tc: ToolContext,
    mutator: Callable[[Any], T],
    *,
    change_paths: list[str],
    section_ids: list[str] | None = None,
    global_change: bool = False,
    is_add_section: bool = False,
    is_split_section: bool = False,
    core_keys: list[str] | None = None,
) -> T:
    """Apply to a clone, validate, then replace the live candidate."""
    from app.agent.agents.lesson_plan.builder import LessonPlanBuilder

    guard_paths(
        tc,
        change_paths,
        section_ids=section_ids,
        global_change=global_change,
        is_add_section=is_add_section,
        is_split_section=is_split_section,
        core_keys=core_keys,
    )
    live = builder_for(tc)
    before_content = live.to_content()
    clone = LessonPlanBuilder(before_content)
    result = mutator(clone)
    validation = clone.validate_content()
    if not validation.get("ok"):
        raise ToolGuardError("candidate_invalid", f"修改后候选稿结构非法：{validation.get('error')}")
    live.replace_content(clone.to_content())

    # 记录本轮新建的章节
    if is_add_section and section_ids:
        policy = get_mutation_policy(tc)
        if policy is not None:
            policy.new_section_ids.update(section_ids)

    # 写操作返回可验证的 MutationReceipt（runtime 据此判定 changed / 触发事件）。
    receipt = build_mutation_receipt(
        tc,
        tool_name=_current_tool_name(tc),
        change_paths=change_paths,
        before_content=before_content,
        after_content=live.to_content(),
        section_ids=section_ids,
        core_keys=core_keys,
    )
    tc.extra["last_mutation_receipt"] = receipt

    return result


def _current_tool_name(tc: ToolContext) -> str:
    """返回正在执行的工具名（由 core/loop 在调用前设置）。"""
    runtime = getattr(tc, "runtime", None)
    current = getattr(runtime, "current_agent_key", "") if runtime else ""
    last = getattr(tc, "_current_tool_name", "")
    return last or f"lesson_mutation_by_{current}"


def patch_paths(value: Any, prefix: str = "$") -> list[str]:
    if not isinstance(value, dict):
        return [prefix]
    result: list[str] = []
    for key, child in value.items():
        path = f"{prefix}.{key}"
        result.extend(patch_paths(child, path) if isinstance(child, dict) else [path])
    return result or [prefix]


# ---------------------------------------------------------------------------
# LLM block 归一化：把模型写出的变体形状转换为 LessonBlock schema 规范形状。
# 真实失败案例：模型写 {"type": "table", "header": [...]}（schema 要求
# kind/columns/rows[{cells}]），union 校验落到 LessonParagraphBlock 报
# "text Field required" → candidate_invalid → 反复重试直至工具轮次耗尽。
# 在工具边界归一化，保证写入一次成功。
# ---------------------------------------------------------------------------

_KIND_ALIASES = {
    "paragraph": "paragraph", "text": "paragraph", "p": "paragraph",
    "heading": "paragraph", "headline": "paragraph", "quote": "paragraph", "code": "paragraph",
    "bullets": "bullets", "bullet": "bullets", "bullet_list": "bullets",
    "list": "bullets", "bullet_points": "bullets", "unordered": "bullets",
    "numbered_list": "bullets",
    "steps": "steps", "step": "steps", "step_list": "steps",
    "table": "table", "markdown_table": "table",
    "process_table": "process_table", "process": "process_table",
    "teaching_process": "process_table", "process_steps": "process_table",
    "note": "note", "callout": "note", "tip": "note", "tip_block": "note",
    "checklist": "checklist", "check_list": "checklist", "todo": "checklist",
}


def _coerce_text(value: Any) -> str:
    """把任意标量/嵌套结构摊平为一段文本；空返回空串。"""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "title", "detail", "value", "body"):
            if key in value:
                coerced = _coerce_text(value[key])
                if coerced:
                    return coerced
        return ""
    if isinstance(value, (list, tuple)):
        parts = [item for item in (_coerce_text(child) for child in value) if item]
        return "；".join(parts)
    return str(value).strip()


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [item for item in (_coerce_text(child) for child in value) if item]
    text = _coerce_text(value)
    return [text] if text else []


def _infer_kind(block: dict[str, Any]) -> str:
    for key in ("kind", "type", "block_type", "block"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return _KIND_ALIASES.get(value.strip().lower(), value.strip().lower())
    if any(key in block for key in ("columns", "header", "headers")) or (
        "rows" in block and isinstance(block.get("rows"), list)
    ):
        return "table"
    if "steps" in block and isinstance(block.get("steps"), list):
        return "steps"
    if any(key in block for key in ("items", "points", "entries", "list")) and isinstance(
        block.get("items") or block.get("points") or block.get("entries") or block.get("list"), list
    ):
        return "bullets"
    return "paragraph"


def _normalize_paragraph(raw: dict[str, Any], *, code: bool = False) -> dict[str, Any] | None:
    kind_hint = str(raw.get("type") or raw.get("kind") or "").lower()
    code_body = raw.get("code") if isinstance(raw.get("code"), str) else ""
    if code or kind_hint == "code" or code_body:
        # schema 没有 code 块：转成围栏代码段落，内容不丢
        body = code_body or _coerce_text(raw.get("text") or raw.get("content") or raw.get("body"))
        if body:
            language = str(raw.get("language") or "")
            return {"kind": "paragraph", "text": f"```{language}\n{body}\n```"}
    text = _coerce_text(raw.get("text") or raw.get("content") or raw.get("body")
                        or raw.get("paragraph") or raw.get("value") or raw.get("markdown"))
    if not text:
        text = _coerce_text({k: v for k, v in raw.items() if k not in {"kind", "type", "block_type", "block"}})
    if not text:
        return None
    return {"kind": "paragraph", "text": text}


def _normalize_bullets(raw: dict[str, Any]) -> dict[str, Any] | None:
    items_raw = (raw.get("items") or raw.get("points") or raw.get("entries")
                 or raw.get("list") or raw.get("bullets"))
    items = _coerce_str_list(items_raw)
    if not items:
        return None
    return {
        "kind": "bullets",
        "items": items,
        "numbered": bool(raw.get("numbered") or raw.get("ordered")),
    }


def _normalize_steps(raw: dict[str, Any]) -> dict[str, Any] | None:
    steps_raw = raw.get("steps") or raw.get("items") or raw.get("stages")
    if not isinstance(steps_raw, list) or not steps_raw:
        text = _coerce_text(steps_raw)
        return {"kind": "steps", "steps": [{"title": text}]} if text else None
    steps: list[dict[str, Any]] = []
    for index, entry in enumerate(steps_raw, start=1):
        if isinstance(entry, dict):
            title = _coerce_text(entry.get("title") or entry.get("name") or entry.get("step")
                                 or entry.get("text") or f"步骤 {index}")
            detail = _coerce_text(entry.get("detail") or entry.get("content")
                                  or entry.get("description") or entry.get("text"))
        else:
            title = _coerce_text(entry) or f"步骤 {index}"
            detail = ""
        if title:
            steps.append({"title": title, "detail": detail})
    return {"kind": "steps", "steps": steps} if steps else None


def _normalize_table(raw: dict[str, Any]) -> dict[str, Any] | None:
    columns_raw = (raw.get("columns") or raw.get("header") or raw.get("headers")
                   or raw.get("fields") or raw.get("col"))
    columns: list[str] = []
    if isinstance(columns_raw, (list, tuple)):
        for entry in columns_raw:
            if isinstance(entry, dict):
                columns.append(_coerce_text(entry.get("name") or entry.get("column")
                                            or entry.get("title") or entry.get("text")))
            else:
                columns.append(_coerce_text(entry))
    elif isinstance(columns_raw, str):
        columns = [part.strip() for part in columns_raw.split("|") if part.strip()]
    columns = [item for item in columns if item]
    if not columns:
        return None
    rows_out: list[dict[str, Any]] = []
    rows_raw = raw.get("rows") if raw.get("rows") is not None else raw.get("data")
    if isinstance(rows_raw, list):
        for entry in rows_raw:
            if isinstance(entry, (list, tuple)):
                cells = [_coerce_text(cell) for cell in entry]
            elif isinstance(entry, dict):
                cells = [entry.get(column) for column in columns]
            else:
                cells = [_coerce_text(entry)]
            cells = cells[: len(columns)] + [""] * (len(columns) - len(cells))
            rows_out.append({"cells": cells})
    return {"kind": "table", "title": _coerce_text(raw.get("title") or raw.get("caption")),
            "columns": columns, "rows": rows_out}


def _normalize_process_table(raw: dict[str, Any]) -> dict[str, Any] | None:
    steps_raw = raw.get("steps") or raw.get("stages") or raw.get("processes")
    if not isinstance(steps_raw, list) or not steps_raw:
        return None
    steps: list[dict[str, Any]] = []
    for index, entry in enumerate(steps_raw, start=1):
        if not isinstance(entry, dict):
            title = _coerce_text(entry)
            if title:
                steps.append({"stage_id": f"STAGE-{index:02d}", "title": title,
                              "duration_minutes": 5.0})
            continue
        title = _coerce_text(entry.get("title") or entry.get("name") or entry.get("stage"))
        if not title:
            continue
        try:
            duration = float(entry.get("duration_minutes") or entry.get("duration")
                             or entry.get("minutes") or entry.get("时长") or 5.0)
        except (TypeError, ValueError):
            duration = 5.0
        steps.append({
            "stage_id": _coerce_text(entry.get("stage_id") or entry.get("id")) or f"STAGE-{index:02d}",
            "title": title,
            "duration_minutes": max(duration, 0.5),
            "teacher_activity": _coerce_text(entry.get("teacher_activity") or entry.get("teacher")),
            "learner_activity": _coerce_text(entry.get("learner_activity") or entry.get("learner")
                                             or entry.get("student_activity")),
            "design_intent": _coerce_text(entry.get("design_intent") or entry.get("intent")),
            "assessment": _coerce_text(entry.get("assessment")),
        })
    return {"kind": "process_table", "title": _coerce_text(raw.get("title")) or "教学过程",
            "steps": steps} if steps else None


def _normalize_checklist(raw: dict[str, Any]) -> dict[str, Any] | None:
    items_raw = raw.get("items") or raw.get("entries") or raw.get("checks")
    if not isinstance(items_raw, list) or not items_raw:
        return None
    items: list[dict[str, Any]] = []
    for entry in items_raw:
        if isinstance(entry, dict):
            text = _coerce_text(entry.get("text") or entry.get("title") or entry.get("content"))
            checked = bool(entry.get("checked") or entry.get("done"))
        else:
            text = _coerce_text(entry)
            checked = False
        if text:
            items.append({"text": text, "checked": checked})
    return {"kind": "checklist", "title": _coerce_text(raw.get("title")), "items": items} if items else None


_BLOCK_VALIDATOR = None


def normalize_blocks(blocks: Any) -> list[dict[str, Any]]:
    """把 LLM 写出的 blocks 尽力归一化为 LessonBlock 规范形状。

    逐块转换后用 schema 校验兜底；仍不合法的块摊平为段落保留内容，
    保证写入一次成功而不是 candidate_invalid 反复重试。
    """
    global _BLOCK_VALIDATOR
    if not isinstance(blocks, list):
        return []
    from app.schemas.lesson_plan import LessonBlock

    if _BLOCK_VALIDATOR is None:
        from pydantic import TypeAdapter

        _BLOCK_VALIDATOR = TypeAdapter(LessonBlock)

    normalized: list[dict[str, Any]] = []
    for raw in blocks:
        if not isinstance(raw, dict):
            text = _coerce_text(raw)
            if text:
                normalized.append({"kind": "paragraph", "text": text})
            continue
        kind = _infer_kind(raw)
        if kind == "paragraph":
            block = _normalize_paragraph(raw)
        elif kind == "bullets":
            block = _normalize_bullets(raw)
        elif kind == "steps":
            block = _normalize_steps(raw)
        elif kind == "table":
            block = _normalize_table(raw)
        elif kind == "process_table":
            block = _normalize_process_table(raw)
        elif kind == "checklist":
            block = _normalize_checklist(raw)
        else:
            block = _normalize_note(raw) if kind == "note" else _normalize_paragraph(raw)
        if block is None:
            continue
        try:
            validated = _BLOCK_VALIDATOR.validate_python(block)
            normalized.append(validated.model_dump())
        except Exception:  # noqa: BLE001  转换失败也保留内容：摊平为段落
            text = _coerce_text(raw)
            if text:
                normalized.append({"kind": "paragraph", "text": text})
    return normalized


def _normalize_note(raw: dict[str, Any]) -> dict[str, Any] | None:
    text = _coerce_text(raw.get("text") or raw.get("content") or raw.get("note") or raw.get("body"))
    return {"kind": "note", "text": text} if text else None


def normalize_outline_sections(sections: Any) -> list[dict[str, Any]]:
    """递归归一化目录树中每个章节的 blocks（lesson_create_outline 用）。"""
    if not isinstance(sections, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in sections:
        if not isinstance(raw, dict):
            continue
        node = dict(raw)
        if "blocks" in node:
            node["blocks"] = normalize_blocks(node.get("blocks"))
        if isinstance(node.get("children"), list):
            node["children"] = normalize_outline_sections(node.get("children"))
        result.append(node)
    return result
