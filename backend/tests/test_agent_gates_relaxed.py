"""relaxed 门禁模式（默认）专项测试。

存量套件在 strict 模式下运行（见 conftest.py），验证门禁机制本身；
本文件验证 relaxed 模式下各门禁点被旁路：交互修改按教师意图直接执行。
"""

from __future__ import annotations

import copy

import pytest

from app.agent.agents.task_sheet.builder import build_initial_builder
from app.agent.agents.task_sheet.intents import TaskSheetIntentDecision
from app.agent.core.gates import gates_active
from app.agent.registry import ToolContext, execute_tool
from tests.test_task_sheet_agentic import BP


@pytest.fixture
def relaxed_gates(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_gates_mode", "relaxed")
    yield
    assert not gates_active()


def _tool_context(builder=None, *, intent_plan=None, locks=None, confirmation_tokens=None):
    class _Ctx:
        blueprint = copy.deepcopy(BP)
        upstream = {}
        knowledge = {}

    class _Runtime:
        def __init__(self):
            self.intent_plan = intent_plan
            self.locks = locks or []
            self.confirmation_tokens = confirmation_tokens or []
            self.active_intent = "TASK_EDIT"
            self.knowledge_context = {}
            self.source_artifact = None

    return ToolContext(ctx=_Ctx(), runtime=_Runtime(), extra={"builder": builder})


@pytest.fixture
def v3_builder():
    return build_initial_builder(BP)


# ---------------------------------------------------------------------------
# 意图作用域守卫：relaxed 不再拒绝范围外修改
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relaxed_scope_guard_allows_out_of_scope_edit(relaxed_gates, v3_builder):
    """strict 下 T-02 不在意图目标内会被拒绝；relaxed 直接放行。"""
    plan = TaskSheetIntentDecision(intent="TASK_EDIT", target_task_ids=["T-01"])
    tc = _tool_context(v3_builder, intent_plan=plan)
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-02", "patch": {"estimated_minutes": 5},
    })
    assert result.ok, result.error


@pytest.mark.asyncio
async def test_strict_scope_guard_still_rejects(v3_builder, monkeypatch):
    """同一调用在 strict 模式下保持历史拒绝行为（对照）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_gates_mode", "strict")
    plan = TaskSheetIntentDecision(intent="TASK_EDIT", target_task_ids=["T-01"])
    tc = _tool_context(v3_builder, intent_plan=plan)
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-02", "patch": {"estimated_minutes": 5},
    })
    assert not result.ok
    assert "不属于本轮意图范围" in (result.error or "")


# ---------------------------------------------------------------------------
# 高风险操作确认令牌：relaxed 删除/解绑直接执行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relaxed_delete_task_without_token_succeeds(relaxed_gates, v3_builder):
    tc = _tool_context(v3_builder)
    result = await execute_tool("task_sheet_delete_task", tc, {
        "task_id": "T-01", "reason": "教师要求",
    })
    assert result.ok, result.error
    assert "删除任务 T-01" in result.output.get("summary", "")


# ---------------------------------------------------------------------------
# PPT 润色：relaxed 不再因歧义/低置信度要求人工确认
# ---------------------------------------------------------------------------


def test_relaxed_polish_command_never_requires_confirmation(relaxed_gates):
    from app.agent.polish_command import resolve_polish_command

    # 无法解析出任何操作 → strict 下 confidence=0.45 必然触发确认
    command = resolve_polish_command("帮我把这里弄好看一点")
    assert command.needs_confirmation is False


def test_strict_polish_command_low_confidence_still_confirms(monkeypatch):
    from app.core.config import get_settings
    from app.agent.polish_command import resolve_polish_command

    monkeypatch.setattr(get_settings(), "agent_gates_mode", "strict")
    command = resolve_polish_command("帮我把这里弄好看一点")
    assert command.needs_confirmation is True


# ---------------------------------------------------------------------------
# lesson_plan 守卫：relaxed 下 MutationPolicy 越权不再致命
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relaxed_lesson_policy_violation_not_raised(relaxed_gates):
    from app.agent.agents.lesson_plan.tools._common import (
        MutationPolicy, ToolGuardError, guard_paths,
    )

    class _Runtime:
        mutation_policy = MutationPolicy(allowed_section_ids={"SEC-1"}, allowed_core_keys=set())

    class _Ctx:
        blueprint = {}
        upstream = {}
        knowledge = {}

    tc = ToolContext(ctx=_Ctx(), runtime=_Runtime(), extra={})
    # 不抛异常即通过（strict 下会抛 section_scope_violation）
    guard_paths(tc, ["$.pedagogical_core"], section_ids=["SEC-OTHER"])


def test_strict_lesson_policy_violation_still_raised(monkeypatch):
    from app.core.config import get_settings
    from app.agent.agents.lesson_plan.tools._common import (
        MutationPolicy, ToolGuardError, guard_paths,
    )

    monkeypatch.setattr(get_settings(), "agent_gates_mode", "strict")

    class _Runtime:
        mutation_policy = MutationPolicy(allowed_section_ids={"SEC-1"}, allowed_core_keys=set())

    class _Ctx:
        blueprint = {}
        upstream = {}
        knowledge = {}

    tc = ToolContext(ctx=_Ctx(), runtime=_Runtime(), extra={})
    with pytest.raises(ToolGuardError) as exc_info:
        guard_paths(tc, ["$.pedagogical_core"], section_ids=["SEC-OTHER"])
    assert exc_info.value.code == "section_scope_violation"
