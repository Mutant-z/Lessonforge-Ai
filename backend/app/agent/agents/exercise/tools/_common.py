"""课后练习工具集：共享 helper（锁定/作用域/人工确认令牌）。

所有修改工具必须：
- 校验目标 ID、知识点 ID、教学环节 ID 与稳定题目 ID；
- 检查修改范围是否属于本轮意图（_scope_guard）；
- 检查锁定路径及其祖先/后代路径（_lock_guard）；
- 对删除等高风险操作要求有效的人工确认令牌（_require_confirmation）。
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


def _lock_paths(tc: ToolContext) -> list[str]:
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    result: list[str] = []
    for lock in (locks or []):
        path = getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        if path:
            result.append(path)
    return result


def _tokenize_path(path: str) -> list[str]:
    """把 JSON 路径归一化为段序列：$.sections[0].blocks[1] → ['sections', '0', 'blocks', '1']。"""
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


def _scope_guard(tc: ToolContext, question_ids: list[str] | None = None,
                 section_ids: list[str] | None = None) -> None:
    """检查修改范围是否属于本轮意图。

    intent_plan.target_question_ids / target_section_ids 非空时，工具只允许修改
    这些题目/分区；空（全局意图）不限。

    目标 ID 若在文档中不存在（如模型编造的 ID），视为无效并忽略——避免用 LLM
    幻觉 ID 拦截真实 ID 的修改（真实场景：意图识别把"第六题"猜成 q6，而文档
    真实 ID 是 ex_06，此时应放行全局修改而不是误拦）。
    """
    runtime = getattr(tc, "runtime", None)
    plan = getattr(runtime, "intent_plan", None) if runtime else None
    if plan is None:
        return
    target_questions = list(plan.target_question_ids or [])
    target_sections = list(plan.target_section_ids or [])
    builder = tc.extra.get("builder")
    if builder is not None:
        valid_questions = set(builder.all_question_ids())
        valid_sections = {item.get("id") for item in builder.sections}
        target_questions = [item for item in target_questions if item in valid_questions]
        target_sections = [item for item in target_sections if item in valid_sections]
    if not target_questions and not target_sections:
        # 无有效目标（或全局意图）→ 不限范围，避免幻觉 ID 阻塞真实修改。
        return
    if target_questions and question_ids:
        for question_id in question_ids:
            if question_id not in target_questions:
                raise ValueError(
                    f"题目 {question_id} 不属于本轮意图范围（本轮目标题目：{target_questions}），"
                    "请缩小修改范围或发起新指令"
                )
    if target_sections and section_ids:
        for section_id in section_ids:
            if section_id not in target_sections:
                raise ValueError(
                    f"分区 {section_id} 不属于本轮意图范围（本轮目标分区：{target_sections}）"
                )


def _confirmation_tokens(tc: ToolContext) -> list[str]:
    runtime = getattr(tc, "runtime", None)
    return list(getattr(runtime, "confirmation_tokens", None) or []) if runtime else []


def _require_confirmation(tc: ToolContext, token: str | None = None, *, operation: str = "删除或结构调整") -> None:
    """高风险操作（删除分区/题目/题组等）要求有效的人工确认令牌。"""
    tokens = _confirmation_tokens(tc)
    if not token or token not in tokens:
        raise ValueError(
            f"{operation}属于高风险操作，需要教师人工确认后才能执行；"
            "请先提交人工确认并携带有效确认令牌"
        )
