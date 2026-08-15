"""教师逐字稿工具集：共享 helper（锁定/作用域/人工确认令牌）。

所有修改工具必须：
- 校验目标场景/章节 ID 存在（_builder 定位）；
- 检查修改范围是否属于本轮意图（_scope_guard）；
- 检查锁定路径及其祖先/后代路径（_lock_guard）；
- 对删除章节、解绑场景等高风险操作要求有效的人工确认令牌（_require_confirmation）。
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.registry import ToolContext


def _builder(tc: ToolContext):
    builder = tc.extra.get("builder")
    if builder is None:
        raise ValueError("候选稿 Builder 未初始化")
    return builder


def _video_script_raw(tc: ToolContext) -> dict[str, Any] | None:
    """从运行态读取源视频脚本（V3/V4 投影为扁平 scenes）。"""
    runtime = getattr(tc, "runtime", None)
    raw = getattr(runtime, "video_script_raw", None) if runtime else None
    if raw:
        return raw
    knowledge = getattr(runtime, "knowledge_context", None) if runtime else None
    knowledge = knowledge or (dict(tc.ctx.knowledge) if tc.ctx is not None and getattr(tc.ctx, "knowledge", None) else {})
    for key in ("video_script",):
        value = knowledge.get("sibling_artifacts", {}).get(key) or knowledge.get("hard_dependencies", {}).get(key)
        if isinstance(value, dict):
            content = value.get("content") or value
            return content if isinstance(content, dict) else None
    return None


def _lock_paths(tc: ToolContext) -> list[str]:
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    result: list[str] = []
    for lock in (locks or []):
        path = getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        if path:
            result.append(path)
    return result


def _tokenize_path(path: str) -> list[str]:
    cleaned = path.strip().lstrip("$").lstrip(".")
    if not cleaned:
        return []
    parts: list[str] = []
    for segment in re.split(r"\.|(?=\[)", cleaned):
        segment = segment.strip()
        if not segment:
            continue
        bracket = re.match(r"\[([^\]]+)\]$", segment)
        if bracket:
            parts.append(segment[: segment.find("[")])
            parts.append(bracket.group(1))
        else:
            parts.append(segment)
    return parts


def _path_conflicts(lock_path: str, change_path: str) -> bool:
    lock_tokens = _tokenize_path(lock_path)
    change_tokens = _tokenize_path(change_path)
    if not lock_tokens or not change_tokens:
        return False

    def _prefix(a: list[str], b: list[str]) -> bool:
        if len(a) > len(b):
            return False
        for i, token in enumerate(a):
            if token != b[i]:
                return False
        return True

    if _prefix(lock_tokens, change_tokens) or _prefix(change_tokens, lock_tokens):
        return True
    return False


def _lock_guard(tc: ToolContext, change_paths: list[str]) -> None:
    locked = _lock_paths(tc)
    if any(path in {"", "$"} for path in locked):
        raise ValueError("当前任务文件已整体锁定，不允许修改")
    for lock_path in locked:
        if not lock_path or lock_path in {"", "$"}:
            continue
        for change_path in change_paths:
            if change_path and _path_conflicts(lock_path, change_path):
                raise ValueError(
                    f"路径 {change_path} 与锁定路径 {lock_path} 冲突（含祖先/后代），"
                    "请先解除锁定或缩小修改范围"
                )


def _scope_guard(tc: ToolContext, section_ids: list[str] | None = None) -> None:
    """检查修改范围是否属于本轮意图。

    intent_plan.target_section_ids 非空时，工具只允许修改这些章节；空（全局意图）不限。
    """
    runtime = getattr(tc, "runtime", None)
    plan = getattr(runtime, "intent_plan", None) if runtime else None
    if plan is None:
        return
    target_sections = list(getattr(plan, "target_section_ids", None) or [])
    if target_sections and section_ids:
        for section_id in section_ids:
            if section_id not in target_sections:
                raise ValueError(
                    f"章节 {section_id} 不属于本轮意图范围（本轮目标章节：{target_sections}），"
                    "请缩小修改范围或发起新指令"
                )


def _confirmation_tokens(tc: ToolContext) -> list[str]:
    runtime = getattr(tc, "runtime", None)
    return list(getattr(runtime, "confirmation_tokens", None) or []) if runtime else []


def _require_confirmation(tc: ToolContext, token: str | None = None, *, operation: str = "删除章节或解绑场景") -> None:
    """高风险操作（删除章节/解绑场景等）要求有效的人工确认令牌。"""
    tokens = _confirmation_tokens(tc)
    if not token or token not in tokens:
        raise ValueError(
            f"{operation}属于高风险操作，需要教师人工确认后才能执行；"
            "请先提交人工确认并携带有效确认令牌"
        )
