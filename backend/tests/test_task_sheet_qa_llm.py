"""任务单 QA 深度 LLM 化测试：LLM 教学质询全权裁决 + 确定性兜底。

覆盖：
- 真 LLM provider → issues/blocking/passed/fingerprint 以 LLM 质询为准（source=llm）；
- 流式异常 → 回退 structured；
- LLM 全程失败 → 回退确定性门禁（source=deterministic）；
- 非法输出 → normalize_llm_issues 归一化不崩溃；
- 结构非法候选稿 → 直接确定性 critical，不调 LLM；
- Mock provider → 走确定性门禁，与原 validate_task_sheet_v3 一致。
"""

from __future__ import annotations

import copy

import pytest

from app.agent.agents.task_sheet.agents import TASK_SHEET_QA
from app.agent.agents.task_sheet.builder import TaskSheetBuilder, build_initial_builder
from app.agent.agents.task_sheet.qa import (
    LlmTaskSheetQaResult,
    build_llm_qa_prompt,
    fingerprint,
    llm_qa_system_prompt,
    normalize_llm_issues,
    validate_task_sheet_v3,
)
from app.agent.registry import ToolContext
from app.providers.llm.mock import MockProvider
from tests.test_task_sheet_agentic import BP


class _Ctx:
    blueprint = copy.deepcopy(BP)
    upstream = {}
    knowledge = {}


class _FakeRuntime:
    """轻量 runtime：decide 只读取 provider / locks / token_usage。"""

    def __init__(self, provider):
        self.provider = provider
        self.locks = []
        self.intent_plan = None
        self.knowledge_context = {}
        self.source_artifact = None
        self.token_usage = {"llm_calls": 0, "tokens": 0}


def _tool_context(builder, provider=None):
    return ToolContext(
        ctx=_Ctx(), runtime=_FakeRuntime(provider), extra={"builder": builder},
    )


@pytest.fixture
def v3_builder():
    return build_initial_builder(BP)


# ---------------------------------------------------------------------------
# 假 provider
# ---------------------------------------------------------------------------


class _StreamingQaProvider:
    """真 LLM provider 形态：stream_decision 返回固定质询结果。"""

    async def stream_decision(self, system, prompt, schema):
        yield ("thought_delta", "正在检查任务梯度与完成标准……")
        yield ("decision_ready", schema.model_validate({
            "issues": [
                {
                    "severity": "major",
                    "dimension": "usability",
                    "path": "$.sections[SEC-TASKS].blocks[T-01]",
                    "description": "任务一的完成标准缺少可判断的动词",
                    "suggestion": "补充可观察的完成标准",
                    "target_role": "task_designer",
                },
                {
                    "severity": "critical",
                    "dimension": "coverage",
                    "path": "$",
                    "description": "蓝图目标 OBJ-02 没有被任何学习任务覆盖",
                    "suggestion": "补充覆盖 OBJ-02 的学习任务",
                    "target_role": "task_architect",
                },
            ],
            "summary": "发现两个阻断问题",
        }))


class _StreamFailsThenStructuredProvider:
    """流式异常 → 回退 provider.structured。"""

    async def stream_decision(self, system, prompt, schema):
        yield ("thought_delta", "x")
        raise RuntimeError("stream 不可用")

    async def structured(self, system, prompt, schema):
        return schema.model_validate({
            "issues": [
                {
                    "severity": "critical",
                    "dimension": "boundary",
                    "path": "$",
                    "description": "候选稿出现参考答案内容",
                    "suggestion": "移除教师侧内容",
                    "target_role": "task_designer",
                },
            ],
            "summary": "发现教师侧内容",
        })


class _FailingProvider:
    """LLM 全程不可用 → 确定性兜底。"""

    async def stream_decision(self, system, prompt, schema):
        yield ("thought_delta", "x")
        raise RuntimeError("boom")

    async def structured(self, system, prompt, schema):
        raise RuntimeError("structured 也不可用")


class _CountingProvider:
    """记录是否真的触发了 LLM 调用（结构非法时不应调用）。"""

    def __init__(self):
        self.calls = 0

    async def stream_decision(self, system, prompt, schema):
        self.calls += 1
        yield ("decision_ready", schema.model_validate({"issues": [], "summary": "ok"}))

    async def structured(self, system, prompt, schema):
        self.calls += 1
        return schema.model_validate({"issues": [], "summary": "ok"})


# ---------------------------------------------------------------------------
# LLM 全权裁决
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_qa_decision_takes_llm_issues(v3_builder):
    tc = _tool_context(v3_builder, _StreamingQaProvider())
    decision = await TASK_SHEET_QA.decide(tc)
    assert decision.completed
    output = decision.output
    assert output["source"] == "llm"
    # LLM 质询的问题成为唯一裁决依据
    assert {item["severity"] for item in output["issues"]} == {"critical", "major"}
    assert output["blocking"] == output["issues"]
    assert output["passed"] is False
    # fingerprint 可由 LLM 问题稳定计算（防空转复用）
    assert output["fingerprint"] == fingerprint(output["issues"])
    assert output["score"] == max(0, 100 - len(output["blocking"]) * 15)
    assert decision.summary.startswith("LLM 教学质询")


@pytest.mark.asyncio
async def test_llm_qa_stream_failure_falls_back_to_structured(v3_builder):
    tc = _tool_context(v3_builder, _StreamFailsThenStructuredProvider())
    decision = await TASK_SHEET_QA.decide(tc)
    assert decision.completed
    output = decision.output
    assert output["source"] == "llm"
    assert {item["severity"] for item in output["issues"]} == {"critical"}
    assert any(item["dimension"] == "boundary" for item in output["issues"])


@pytest.mark.asyncio
async def test_llm_qa_total_failure_falls_back_to_deterministic(v3_builder):
    tc = _tool_context(v3_builder, _FailingProvider())
    decision = await TASK_SHEET_QA.decide(tc)
    assert decision.completed
    output = decision.output
    assert output["source"] == "deterministic"
    # 兜底结果与确定性门禁完全一致
    from app.schemas.blueprint import CourseBlueprintSchema

    expected = validate_task_sheet_v3(CourseBlueprintSchema.model_validate(BP), v3_builder.to_content())
    assert output["issues"] == expected
    assert output["fingerprint"] == fingerprint(expected)


@pytest.mark.asyncio
async def test_llm_qa_token_usage_recorded(v3_builder):
    tc = _tool_context(v3_builder, _StreamingQaProvider())
    await TASK_SHEET_QA.decide(tc)
    runtime = tc.runtime
    assert runtime.token_usage["llm_calls"] == 1
    assert runtime.token_usage["tokens"] > 0


# ---------------------------------------------------------------------------
# 非法输出归一化
# ---------------------------------------------------------------------------


def test_normalize_llm_issues_handles_garbage():
    raw = {
        "issues": [
            {"severity": "fatal", "dimension": "usability", "path": "$", "description": "非法级别降级"},
            {"severity": "major", "description": "缺路径用默认值"},
            {"severity": "minor", "path": "$", "description": ""},
            "不是 dict",
            {"severity": "minor", "path": "$", "description": "重复项"},
            {"severity": "minor", "path": "$", "description": "重复项"},
            {"severity": "major", "path": "$", "description": "目标角色非法回退", "target_role": "nobody"},
        ]
    }
    issues = normalize_llm_issues(raw)
    assert len(issues) == 4
    assert issues[0]["severity"] == "minor"
    assert issues[0]["dimension"] == "usability"
    assert issues[1]["path"] == "$"
    assert issues[1]["severity"] == "major"
    assert issues[-1]["target_role"] == "task_designer"
    # 统一问题结构字段齐全
    for item in issues:
        assert item["id"]
        assert item["severity"] in {"critical", "major", "minor"}
        assert item["path"]
        assert item["description"]
        assert item["target_role"] in {"task_designer", "task_architect", "task_sheet_qa"}
        assert item["location"] == item["path"]
    # 非 dict 输入 → 空列表
    assert normalize_llm_issues(None) == []
    assert normalize_llm_issues([42]) == []


def test_normalize_llm_issues_accepts_plain_list():
    raw = [{"severity": "major", "path": "$", "description": "直接列表"}]
    issues = normalize_llm_issues(raw)
    assert len(issues) == 1
    assert issues[0]["description"] == "直接列表"


# ---------------------------------------------------------------------------
# 结构安全底线（不送 LLM）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_structure_does_not_call_llm(v3_builder):
    content = v3_builder.to_content()
    content["sections"] = []
    broken = TaskSheetBuilder(content)
    counting = _CountingProvider()
    tc = _tool_context(broken, counting)
    decision = await TASK_SHEET_QA.decide(tc)
    assert counting.calls == 0
    assert decision.completed
    output = decision.output
    assert output["source"] == "deterministic"
    assert output["blocking"]
    assert any(item["dimension"] == "integrity" and item["severity"] == "critical" for item in output["issues"])


# ---------------------------------------------------------------------------
# Mock provider → 确定性门禁（与原行为一致）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_provider_uses_deterministic_gate(v3_builder):
    tc = _tool_context(v3_builder, MockProvider())
    decision = await TASK_SHEET_QA.decide(tc)
    assert decision.completed
    output = decision.output
    assert output["source"] == "deterministic"
    from app.schemas.blueprint import CourseBlueprintSchema

    expected = validate_task_sheet_v3(CourseBlueprintSchema.model_validate(BP), v3_builder.to_content())
    assert output["issues"] == expected
    # Mock 下不产生 LLM token 消耗
    assert tc.runtime.token_usage["llm_calls"] == 0


# ---------------------------------------------------------------------------
# prompt / 系统角色
# ---------------------------------------------------------------------------


def test_llm_qa_prompt_contains_candidate_and_facts(v3_builder):
    from app.schemas.blueprint import CourseBlueprintSchema

    prompt = build_llm_qa_prompt(
        v3_builder.to_content(),
        CourseBlueprintSchema.model_validate(BP),
        locked_paths=["$.sections[SEC-RECORD]"],
    )
    assert "候选稿全文" in prompt
    assert "蓝图目标" in prompt
    assert "教学环节" in prompt
    assert "锁定路径" in prompt
    assert "SEC-RECORD" in prompt
    assert "OBJ-01" in prompt


def test_llm_qa_system_prompt_has_severity_rules():
    prompt = llm_qa_system_prompt()
    assert "critical" in prompt
    assert "major" in prompt
    assert "summary" in prompt
    assert "target_role" in prompt
