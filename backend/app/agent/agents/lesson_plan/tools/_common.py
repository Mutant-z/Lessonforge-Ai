"""Shared helpers for lesson-plan tools with MutationPolicy support."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

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
