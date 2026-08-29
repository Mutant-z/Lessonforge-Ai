"""学习任务单工具集：共享 helper（锁定/作用域/人工确认令牌）。

所有修改工具必须：
- 校验目标 ID、知识点 ID、教学环节 ID 与稳定任务 ID；
- 检查修改范围是否属于本轮意图（_scope_guard）；
- 检查锁定路径及其祖先/后代路径（_lock_guard）；
- 对删除、目标解绑等高风险操作要求有效的人工确认令牌（_require_confirmation）。
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.core.error import ToolConfirmationRequired
from app.agent.core.gates import gates_active
from app.agent.registry import ToolContext


def _builder(tc: ToolContext):
    builder = tc.extra.get("builder")
    if builder is None:
        raise ValueError("候选稿 Builder 未初始化")
    return builder


def _lock_paths(tc: ToolContext) -> list[str]:
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    result: list[str] = []
    for lock in (locks or []):
        path = getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        if path:
            result.append(path)
    return result


def _tokenize_path(path: str) -> list[str]:
    """把 JSON 路径归一化为段序列：$.sections[SEC-1].blocks[T-01] → ['sections', 'SEC-1', 'blocks', 'T-01']。"""
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
    """判断锁定路径与修改路径是否冲突（相等 / 祖先 / 后代）。"""
    lock_tokens = _tokenize_path(lock_path)
    change_tokens = _tokenize_path(change_path)
    if not lock_tokens or not change_tokens:
        return False

    def _prefix(a: list[str], b: list[str]) -> bool:
        """a 是否为 b 的 token 前缀（a 是 b 的祖先路径）。"""
        if len(a) > len(b):
            return False
        for i, token in enumerate(a):
            if token != b[i]:
                return False
        return True

    # 精确 token 前缀判定：锁定祖先路径覆盖其全部后代，修改祖先路径覆盖锁定的后代。
    if _prefix(lock_tokens, change_tokens) or _prefix(change_tokens, lock_tokens):
        return True
    return False


def _lock_guard(tc: ToolContext, change_paths: list[str]) -> None:
    """锁定路径及其祖先/后代路径检查；违规抛 ValueError（可修复错误）。"""
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


def _scope_guard(tc: ToolContext, task_ids: list[str] | None = None, phases: list[str] | None = None) -> None:
    """检查修改范围是否属于本轮意图（方案 §2.3）。

    intent_plan.target_task_ids / target_phases 非空时，工具只允许修改这些任务/环节；
    空（全局意图）不限。relaxed 门禁模式：不拒绝调用，仅由提示词引导优先修改目标。
    """
    if not gates_active():
        return
    runtime = getattr(tc, "runtime", None)
    plan = getattr(runtime, "intent_plan", None) if runtime else None
    if plan is None:
        return
    target_tasks = list(plan.target_task_ids or [])
    target_phases = list(plan.target_phases or [])
    if target_tasks and task_ids:
        for task_id in task_ids:
            if task_id not in target_tasks:
                raise ValueError(
                    f"任务 {task_id} 不属于本轮意图范围（本轮目标任务：{target_tasks}），"
                    "请缩小修改范围或发起新指令"
                )
    if target_phases and phases:
        for phase in phases:
            if phase not in target_phases:
                raise ValueError(
                    f"环节 {phase} 不属于本轮意图范围（本轮目标环节：{target_phases}）"
                )


def _confirmation_tokens(tc: ToolContext) -> list[str]:
    runtime = getattr(tc, "runtime", None)
    return list(getattr(runtime, "confirmation_tokens", None) or []) if runtime else []


def _require_confirmation(tc: ToolContext, token: str | None = None, *, operation: str = "删除或目标解绑") -> None:
    """高风险操作（删除/目标解绑等）要求有效的人工确认令牌。

    relaxed 门禁模式：删除/解绑直接执行，不再要求确认令牌。
    """
    if not gates_active():
        return
    tokens = _confirmation_tokens(tc)
    if not token or token not in tokens:
        raise ToolConfirmationRequired(
            f"{operation}属于高风险操作，需要教师人工确认后才能执行；"
            "请先提交人工确认并携带有效确认令牌",
            operation=operation,
        )
