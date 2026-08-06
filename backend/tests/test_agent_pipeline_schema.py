"""Agent 流水线结构化协议单测（AgentDecision / ToolResult / AgentSpec / PipelinePlan）。"""
import pytest
from pydantic import ValidationError

from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan, ToolCall, ToolResult


def test_decision_allows_tool_calls():
    decision = AgentDecision(tool_calls=[ToolCall(tool_name="get_blueprint", input={})])
    assert not decision.completed
    assert decision.tool_calls[0].tool_name == "get_blueprint"


def test_decision_allows_completed_with_output():
    decision = AgentDecision(completed=True, output={"slides": []}, summary="完成")
    assert decision.completed
    assert decision.output == {"slides": []}


def test_decision_rejects_tools_and_completed_together():
    with pytest.raises(ValidationError):
        AgentDecision(tool_calls=[ToolCall(tool_name="x", input={})], completed=True)


def test_decision_rejects_empty():
    with pytest.raises(ValidationError):
        AgentDecision()


def test_tool_result_defaults():
    result = ToolResult()
    assert result.ok is True
    assert result.output == {}
    assert result.error is None


def test_agent_spec_and_plan_defaults():
    spec = AgentSpec(key="layout", role="布局")
    assert spec.max_steps == 8
    plan = PipelinePlan(agents=[spec])
    assert plan.revision_rounds == 3
    assert plan.keys() == ["layout"]
