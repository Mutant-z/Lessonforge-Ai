"""教学设计 Runtime 集成测试：多轮 LLM、工具调用回喂、QA 返修、发布门禁。

用脚本化 Provider 模拟一次教师指令发生多次 LLM 调用：意图规划 → 角色决策 →
工具调用 → 结果回喂 → 再决策 → QA → 终稿。验证 plan 中"一次对话多次 LLM +
tools calling + 验证返修"的核心闭环，且不依赖真实 DB（runtime 字段允许
generation_run/pipeline_run 为 None 时跳过 checkpoint/工具落库副作用）。
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.agent.agents.lesson_plan.builder import LessonPlanBuilder
from app.agent.agents.lesson_plan.intents import LessonPlanIntentDecision
from app.agent.agents.lesson_plan.runtime import LessonPlanAgentRuntime
from app.agent.core.error import AgentError
from app.agent.core.loop import run_agent_loop as run_core_agent_loop
from app.agent.core.state import AgentRuntimeState
from app.agent.context import ContextState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan, ToolCall
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.lesson_plan import LessonPlanContentV2, make_lesson_plan_v2
from tests.test_lesson_plan_v2 import make_bp


class _ScriptedProvider:
    """分派型脚本 provider：intent 识别 → 预置意图；AgentDecision → 决策队列。

    实现 stream_decision 与 structured 双路径（intent 识别走 structured，
    LLM 角色走 stream_decision）。新架构下全部节点在真实 Provider 时都会尝试
    LLM 深度分析；本 harness 只为真正的 LLM 驱动节点（目录设计/教学设计）消费
    脚本决策，其余节点（意图规划/调研/格式/质询/终稿等）返回默认完成决策，
    由确定性 decide() 保底——保持测试聚焦在工具修改与发布门禁行为上。
    """

    #: 真正由 LLM 驱动的角色（build_system_prompt 中「名称」精确匹配）。
    _LLM_DRIVER_NAMES = ("「目录设计」", "「教学设计」", "「问答答复」")

    def __init__(self, intent: LessonPlanIntentDecision, decisions: list[AgentDecision]):
        self._intent = intent
        self._decisions = list(decisions)
        self.calls = 0
        self.prompts: list[str] = []

    def _default_decision(self) -> AgentDecision:
        return AgentDecision(completed=True, output={}, summary="默认完成（未预置脚本决策）")

    async def structured(self, system, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        if schema is LessonPlanIntentDecision:
            return self._intent
        if schema is AgentDecision:
            return self._decisions.pop(0) if self._decisions else self._default_decision()
        raise TypeError(f"未预期的 schema：{schema}")

    async def stream_decision(self, system, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        if any(name in system for name in self._LLM_DRIVER_NAMES):
            decision = self._decisions.pop(0) if self._decisions else self._default_decision()
        else:
            decision = self._default_decision()
        yield ("thought_delta", "正在分析教师指令与现有目录结构。\n")
        yield ("decision_ready", decision)


class _FakeArtifacts:
    """模拟 PipelineArtifactManager 的最小实现（latest/create 内存版）。"""

    def __init__(self):
        self.store: dict[str, dict] = {}

    async def create(self, artifact_type, name, data, **kwargs):
        payload = {
            "id": f"a-{artifact_type}", "artifact_type": artifact_type, "name": name,
            "version": 1, "status": "validated", "data": data, "file_path": "",
            "producer_agent": kwargs.get("producer_agent", ""), "producer_tool": "",
            "created_by_step_index": kwargs.get("step_index", 0),
            "dependencies": [], "created_at": "", "updated_at": "",
        }
        self.store[artifact_type] = payload
        return payload

    async def latest(self, artifact_type, name="default"):
        return self.store.get(artifact_type)


def _make_runtime(provider, *, trigger="message", instruction="把教学过程重排，增加一个探究环节", mode="structure"):
    bp_content = make_bp().model_dump()
    context = ContextState(
        blueprint=bp_content, profile=None, knowledge={},
        user_instruction=instruction, locks=[],
    )
    runtime = LessonPlanAgentRuntime(
        course=None, task=None,
        blueprint=SimpleNamespace(content_json=bp_content),
        generation_run=None, pipeline_run=None, profile=None,
        provider=provider, config=None, knowledge_context={},
        source_versions={}, locks=[], source_artifact=None,
        user_message=None, trigger_type=trigger,
        context=context, artifacts=_FakeArtifacts(), emitter=None,
        request_metadata={"mode": mode},
    )
    return runtime


async def _prepare(runtime: LessonPlanAgentRuntime):
    """完成 _prepare 的 builder/tool_context 装配。"""
    await runtime._prepare()
    return runtime


class _LoopAgent:
    name = "测试角色"

    def __init__(self, allowed_tools):
        self.allowed_tools = allowed_tools


def _core_runtime():
    from app.agent.agents.lesson_plan.tools import register_lesson_plan_tools

    register_lesson_plan_tools()
    builder = LessonPlanBuilder(make_lesson_plan_v2(make_bp()).model_dump())
    runtime = AgentRuntimeState(context=ContextState(blueprint=make_bp().model_dump()))
    runtime.tool_context = ToolContext(
        ctx=runtime.context, runtime=runtime, extra={"builder": builder},
    )
    return runtime, builder


async def _no_artifact(*_args, **_kwargs):
    return None


def test_core_loop_denies_tool_outside_agent_whitelist():
    runtime, builder = _core_runtime()
    before = builder.to_content()
    decisions = [
        AgentDecision(tool_calls=[ToolCall(tool_name="lesson_update_core", input={"patch": {"reflection": "越权"}})]),
        AgentDecision(completed=True, output={}, summary="完成"),
    ]

    async def call_agent(*_args):
        return decisions.pop(0)

    asyncio.run(run_core_agent_loop(
        runtime,
        PipelinePlan(agents=[AgentSpec(key="control", role="control", max_steps=2)]),
        agent_registry={"control": _LoopAgent([])},
        call_agent=call_agent,
        persist_artifact=_no_artifact,
    ))
    assert builder.to_content() == before
    failure = runtime.unresolved_tool_failures["control:lesson_update_core"]
    assert failure["error_code"] == "tool_not_allowed"


def test_core_loop_detects_repeated_idempotent_reads():
    runtime, _ = _core_runtime()
    repeated = AgentDecision(tool_calls=[ToolCall(tool_name="lesson_get_source", input={"view": "outline"})])

    async def call_agent(*_args):
        return repeated

    with pytest.raises(AgentError) as caught:
        asyncio.run(run_core_agent_loop(
            runtime,
            PipelinePlan(agents=[AgentSpec(key="reader", role="reader", max_steps=4)]),
            agent_registry={"reader": _LoopAgent(["lesson_get_source"])},
            call_agent=call_agent,
            persist_artifact=_no_artifact,
        ))
    assert caught.value.code == "agent_no_progress"
    assert runtime.agent_stats["reader"]["repeated_tool_calls"] >= 2


def test_core_loop_resets_no_progress_after_a_new_read():
    runtime, _ = _core_runtime()
    decisions = [
        AgentDecision(tool_calls=[
            ToolCall(tool_name="lesson_get_profile", input={}),
            ToolCall(tool_name="lesson_get_locks", input={}),
        ]),
        AgentDecision(tool_calls=[
            ToolCall(tool_name="lesson_get_profile", input={}),
            ToolCall(tool_name="lesson_get_locks", input={}),
        ]),
        AgentDecision(tool_calls=[
            ToolCall(tool_name="lesson_get_blueprint", input={}),
            ToolCall(tool_name="lesson_get_profile", input={}),
        ]),
        AgentDecision(completed=True, output={}, summary="完成"),
    ]

    async def call_agent(*_args):
        return decisions.pop(0)

    asyncio.run(run_core_agent_loop(
        runtime,
        PipelinePlan(agents=[AgentSpec(key="reader", role="reader", max_steps=4)]),
        agent_registry={"reader": _LoopAgent([
            "lesson_get_profile", "lesson_get_locks", "lesson_get_blueprint",
        ])},
        call_agent=call_agent,
        persist_artifact=_no_artifact,
    ))

    assert runtime.agent_stats["reader"]["completed"] is True
    assert runtime.agent_stats["reader"]["cache_hits"] == 3
    assert runtime.no_progress_rounds["reader"] == 0
    assert runtime.unresolved_tool_failures == {}


def test_core_loop_builder_change_invalidates_read_cache():
    runtime, builder = _core_runtime()
    section_id = builder.outline[0]["id"]
    decisions = [
        AgentDecision(tool_calls=[ToolCall(tool_name="lesson_get_source", input={"view": "outline"})]),
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_rename_section", input={"section_id": section_id, "title": "缓存失效后的标题"},
        )]),
        AgentDecision(tool_calls=[ToolCall(tool_name="lesson_get_source", input={"view": "outline"})]),
        AgentDecision(completed=True, output={}, summary="完成"),
    ]

    async def call_agent(*_args):
        return decisions.pop(0)

    asyncio.run(run_core_agent_loop(
        runtime,
        PipelinePlan(agents=[AgentSpec(key="editor", role="editor", max_steps=4)]),
        agent_registry={"editor": _LoopAgent(["lesson_get_source", "lesson_rename_section"])},
        call_agent=call_agent,
        persist_artifact=_no_artifact,
    ))

    assert runtime.agent_stats["editor"]["cache_hits"] == 0
    assert builder.find_section(section_id)["title"] == "缓存失效后的标题"


def test_core_loop_tool_round_exhaustion_is_failure():
    runtime, _ = _core_runtime()

    async def call_agent(*_args):
        return AgentDecision(tool_calls=[ToolCall(tool_name="lesson_get_source", input={})])

    with pytest.raises(AgentError) as caught:
        asyncio.run(run_core_agent_loop(
            runtime,
            PipelinePlan(agents=[AgentSpec(key="reader", role="reader", max_steps=1)]),
            agent_registry={"reader": _LoopAgent(["lesson_get_source"])},
            call_agent=call_agent,
            persist_artifact=_no_artifact,
        ))
    assert caught.value.code == "agent_tool_round_exhausted"
    assert runtime.agent_stats["reader"]["completed"] is False


def test_core_loop_enforces_cumulative_token_budget():
    runtime, _ = _core_runtime()

    async def call_agent(*_args):
        runtime.token_usage["tokens"] = 60_001
        return AgentDecision(completed=True, output={}, summary="不应完成")

    with pytest.raises(AgentError) as caught:
        asyncio.run(run_core_agent_loop(
            runtime,
            PipelinePlan(agents=[AgentSpec(key="budget", role="budget", max_steps=1)]),
            agent_registry={"budget": _LoopAgent([])},
            call_agent=call_agent,
            persist_artifact=_no_artifact,
        ))
    assert caught.value.code == "agent_token_budget_exceeded"


def test_context_researcher_is_deterministic_and_complete():
    from app.agent.agents.lesson_plan.agents import CONTEXT_RESEARCHER, READ_TOOLS
    from app.agent.agents.lesson_plan.runtime import _call_agent

    provider = _ScriptedProvider(LessonPlanIntentDecision(intent="RESTRUCTURE"), [])
    runtime = _make_runtime(provider)
    runtime.profile = SimpleNamespace(context_json={"mission": "建立目标、活动与评价的一致性"})
    runtime.knowledge_context = {
        "materials": [{"id": "M-1", "title": "浮力实验材料", "summary": "实验步骤"}],
        "sibling_artifacts": {"task_sheet": {"id": "TS-1", "title": "预习任务单"}},
    }
    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime.source_artifact = SimpleNamespace(content_json=source, version=16)
    asyncio.run(_prepare(runtime))

    decision = asyncio.run(_call_agent(runtime, "context_researcher", CONTEXT_RESEARCHER, 0))

    # 新架构：真实 Provider 下 context_researcher 也深度调用 LLM 分析（1 次），
    # 确定性产物作为基础，LLM 分析附加到 llm_analysis 字段。
    assert provider.calls == 1
    assert CONTEXT_RESEARCHER.allowed_tools == READ_TOOLS
    assert decision.completed is True
    assert decision.output["profile_summary"]["mission"]
    assert decision.output["materials_summary"][0]["id"] == "M-1"
    assert decision.output["source_summary"]["version"] == 16
    assert decision.output["source_summary"]["section_ids"]
    assert decision.output.get("llm_analysis") is not None


def test_compact_context_keeps_recent_results_and_valid_json_under_budget():
    import json
    from app.agent.agents.lesson_plan.runtime import _compact_context_text

    runtime = _make_runtime(SimpleNamespace())
    asyncio.run(_prepare(runtime))
    runtime.knowledge_context = {
        "materials": [{"id": "M-1", "title": "超长材料", "summary": "材" * 50_000}],
        "sibling_artifacts": {"ppt": {"id": "P-1", "content": "页" * 50_000}},
    }
    runtime.context.append_tool_result(
        "tool-1", "outline_architect", "lesson_get_source",
        {"sentinel": "LATEST_RESULT_MUST_SURVIVE", "huge": "值" * 50_000},
    )

    text = _compact_context_text(runtime, "outline_architect")
    payload = json.loads(text)
    result_payload = json.loads(payload["recent_tool_results"][0]["result_json"])

    assert len(text) <= 12_000
    assert result_payload["result"]["output"]["sentinel"] == "LATEST_RESULT_MUST_SURVIVE"
    assert payload["successfully_obtained_tools"] == ["lesson_get_source"]


def test_agent_error_keeps_stable_code_in_task_failure_payload():
    from app.services.course_task_service import _task_failure_payload

    error, internal = _task_failure_payload(AgentError(
        "agent_no_progress", "连续两轮没有新信息", retryable=True,
        details={"agent": "outline_architect"},
    ))

    assert internal == "连续两轮没有新信息"
    assert error == {
        "code": "agent_no_progress",
        "message": "连续两轮没有新信息",
        "retryable": True,
        "details": {"agent": "outline_architect"},
    }


def test_failed_pipeline_persists_runtime_telemetry(monkeypatch):
    from app.services import lesson_plan_pipeline_service as service

    row = SimpleNamespace(
        status="running", token_usage_json={}, error_json=None, plan_json={},
        current_agent="", finished_at=None,
    )

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _model, _row_id):
            return row

        async def commit(self):
            return None

    monkeypatch.setattr(service, "SessionLocal", lambda: FakeSession())
    runtime = _make_runtime(SimpleNamespace())
    runtime.pipeline_run = SimpleNamespace(id="pipeline-1")
    runtime.token_usage = {"llm_calls": 4, "tokens": 12_345}
    runtime.current_agent_key = "outline_architect"
    runtime.termination_reason = "agent_no_progress"
    runtime.agent_stats = {
        "outline_architect": {
            "decision_rounds": 3, "tool_calls": 6, "cache_hits": 4,
            "failed_tool_calls": 0, "no_progress_rounds": 2,
        },
    }

    asyncio.run(service._persist_pipeline_state(runtime, "failed", {
        "code": "agent_no_progress", "message": "没有新进展", "retryable": True,
    }))

    assert row.status == "failed"
    assert row.token_usage_json == {"llm_calls": 4, "tokens": 12_345}
    assert row.error_json["code"] == "agent_no_progress"
    assert row.plan_json["termination_reason"] == "agent_no_progress"
    assert row.plan_json["agent_stats"]["outline_architect"]["cache_hits"] == 4
    assert row.current_agent == "outline_architect"


# ---------------------------------------------------------------------------
# message 路径：意图 → 工具修改候选稿 → QA → 终稿（多次 LLM）
# ---------------------------------------------------------------------------


def test_message_run_invokes_multiple_llm_calls_and_tool_results_feed_back():
    intent = LessonPlanIntentDecision(
        intent="RESTRUCTURE", affected_section_ids=[], structural=True,
        summary="重组目录并更新教学难点", rationale="教师要求重排并补充内容",
        required_change_kinds=["outline_structure", "core_content"],
    )
    provider = _ScriptedProvider(intent, [
        # outline_architect 第 1 轮：工具调用（新增探究章节）
        AgentDecision(thinking="", tool_calls=[
            ToolCall(tool_name="lesson_add_section", input={"section_id": "SEC-INQUIRY", "title": "探究环节", "parent_id": "", "blocks": [{"kind": "paragraph", "text": "学生分组探究勾股定理。"}]}),
        ], completed=False),
        # outline_architect 第 2 轮：completed（工具结果已回喂）
        AgentDecision(completed=True, output={"outline": [{"id": "SEC-INQUIRY", "title": "探究环节"}], "section_count": 8}, summary="目录已调整"),
        # lesson_designer 第 1 轮：工具调用（更新内核）
        AgentDecision(tool_calls=[
            ToolCall(tool_name="lesson_update_core", input={"patch": {"difficulty_points": ["逆定理判定", "探究迁移"]}}),
        ], completed=False),
        # lesson_designer 第 2 轮：completed
        AgentDecision(completed=True, output={"core": {"difficulty_points": ["逆定理判定", "探究迁移"]}}, summary="内容已更新"),
        # finalizer（LLM）
        AgentDecision(completed=True, output={"content": {}, "schema_version": "2.0"}, summary="终稿整合完成"),
    ])
    runtime = _make_runtime(provider, mode="auto", instruction="请优化教学过程设计，把探究环节调整到更合理的位置，并补充教学难点")
    asyncio.run(_prepare(runtime))
    asyncio.run(runtime.run())

    # 新架构：真实 Provider 下全部节点都深度调用 LLM 分析——
    # intent 1 + 确定性节点（intent_planner/context_researcher/pedagogy_qa/finalizer 各 1）4
    # + outline_architect 2 + lesson_designer 2 = 9 次模型调用。
    # 注意：mode=structure 是硬约束（意图优先级第一位），会确定性命中 RESTRUCTURE
    # 并跳过 LLM；此处用 mode=auto + 不命中确定性规则的中性指令，让脚本化
    # provider 的意图契约驱动执行链（RESTRUCTURE + core_content → 含 lesson_designer）。
    assert provider.calls == 9, f"全节点 LLM 化后应为 9 次模型调用，实际 {provider.calls}"
    assert runtime.agent_stats["intent_planner"]["tool_calls"] == 0
    assert runtime.agent_stats["context_researcher"]["decision_rounds"] == 1
    # Finalizer 有 LLM 深度分析，但不进入工具循环、不修改候选稿。
    assert runtime.agent_stats["finalizer"]["tool_calls"] == 0
    # 工具结果回喂到上下文（下一轮决策可读）。
    assert runtime.context.has_tool_result("lesson_add_section"), "lesson_add_section 工具结果未回喂"
    assert runtime.context.has_tool_result("lesson_update_core"), "lesson_update_core 工具结果未回喂"
    # 候选稿被工具真实修改。
    content = runtime.builder.to_content()
    assert any(section.get("id") == "SEC-INQUIRY" for section in content["outline"]["sections"]), "新增章节未进入候选稿"
    assert "探究迁移" in content["pedagogical_core"]["difficulty_points"], "内核补丁未生效"
    # 发布：无阻断问题 → applied，候选稿是合法 V2。
    assert runtime.result_status == "applied"
    assert runtime.publishable is True
    LessonPlanContentV2.model_validate(runtime.draft_content)


def test_assessment_and_reflection_split_requires_distinct_top_level_sections():
    instruction = "教学评价与教学反思应该分成两个部分"
    intent = LessonPlanIntentDecision(
        intent="RESTRUCTURE", structural=True, summary="拆分章节",
        required_separate_facts=["assessment_plan", "reflection"],
        must_be_distinct_top_level=True,
        required_change_kinds=["outline_structure", "section_content"],
    )
    provider = _ScriptedProvider(intent, [
        AgentDecision(tool_calls=[
            ToolCall(tool_name="lesson_add_section", input={
                "section_id": "SEC-ASSESSMENT", "title": "教学评价", "parent_id": "",
                "coverage_refs": ["assessment_plan"], "summary": "独立呈现教学评价方案",
                "blocks": [{"kind": "paragraph", "text": "形成性评价、总结性评价与学生自评。"}],
            }),
        ]),
        AgentDecision(completed=True, output={"outline": []}, summary="评价与反思已拆分"),
        # 即便旧模型缓存了曾经暴露的 full 参数，这个无副作用的只读拒绝也不能
        # 覆盖随后生成的完整内容、QA 与终稿产物，更不能误报“没有生成内容”。
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_get_source", input={"view": "full"},
        )]),
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_write_section",
            input={
                "section_id": "SEC-REFLECTION",
                "blocks": [{"kind": "paragraph", "text": "一、教师课后反思框架（迁移后的反思正文）。"}],
            },
        )]),
        AgentDecision(completed=True, output={"core": {}}, summary="内核保持一致"),
        AgentDecision(completed=True, output={"content": {}}, summary="终稿"),
    ])
    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime = _make_runtime(provider, instruction=instruction, mode="structure")
    runtime.source_artifact = SimpleNamespace(content_json=source)
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.intent_gate["passed"] is True
    assert runtime.intent_gate["fact_owners"].keys() == {"assessment_plan", "reflection"}
    assert runtime.diff_summary["outline_structure_changed"] is True
    assert runtime.unresolved_tool_failures[
        "lesson_designer:lesson_get_source"
    ]["error_code"] == "source_view_forbidden"


def test_assessment_reflection_text_only_change_is_rejected():
    instruction = "教学评价与教学反思应该分成两个部分"
    intent = LessonPlanIntentDecision(
        intent="RESTRUCTURE", structural=True, summary="拆分章节",
        required_separate_facts=["assessment_plan", "reflection"],
        must_be_distinct_top_level=True,
        required_change_kinds=["outline_structure", "section_content"],
    )
    provider = _ScriptedProvider(intent, [
        AgentDecision(completed=True, output={"outline": []}, summary="未实际调整目录"),
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_write_section",
            input={
                "section_id": "SEC-REFLECTION",
                "blocks": [{"kind": "paragraph", "text": "只调整反思文本，没有拆分目录"}],
            },
        )]),
        AgentDecision(completed=True, output={"core": {}}, summary="文本已调整"),
        AgentDecision(completed=True, output={"content": {}}, summary="终稿"),
    ])
    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime = _make_runtime(provider, instruction=instruction, mode="structure")
    runtime.source_artifact = SimpleNamespace(content_json=source)
    asyncio.run(runtime.run())

    assert runtime.result_status == "rejected"
    assert runtime.intent_gate["code"] == "intent_unfulfilled"
    assert "required_change_missing:outline_structure" in runtime.intent_gate["failures"]


def test_initial_run_produces_valid_v2_without_source():
    from app.providers.llm.mock import MockProvider

    provider = MockProvider()
    runtime = _make_runtime(provider, trigger="initial", instruction="")
    asyncio.run(_prepare(runtime))
    asyncio.run(runtime.run())
    assert runtime.active_intent == "GENERATE"
    assert runtime.result_status == "applied"
    v2 = LessonPlanContentV2.model_validate(runtime.draft_content)
    assert len(v2.pedagogical_core.stages) >= 3
    assert len(v2.outline.sections) >= 2


def test_no_change_when_candidate_matches_source():
    """message 修订后候选稿与源完全一致 → no_change，不创建空版本。"""
    from app.agent.agents.lesson_plan.builder import LessonPlanBuilder

    bp_content = make_bp().model_dump()
    source_content = make_lesson_plan_v2(
        CourseBlueprintSchema.model_validate(bp_content),
    ).model_dump()
    provider = _ScriptedProvider(LessonPlanIntentDecision(intent="QA_ONLY", summary="仅质检"), [
        AgentDecision(completed=True, output={"content": {}, "schema_version": "2.0"}, summary="终稿"),
    ])
    runtime = _make_runtime(provider, instruction="检查一下质量", mode="qa")
    runtime.source_artifact = SimpleNamespace(content_json=source_content)
    runtime.builder = LessonPlanBuilder(source_content)
    asyncio.run(runtime.run())
    assert runtime.result_status == "no_change"
    assert runtime.changed is False


def test_rejected_when_qa_blocking_issues_unresolved():
    """返修后仍存在阻断问题 → rejected（保留原版，候选稿留在 PipelineArtifact）。"""
    from app.agent.agents.lesson_plan.builder import LessonPlanBuilder

    bp_content = make_bp().model_dump()
    source_content = make_lesson_plan_v2(
        CourseBlueprintSchema.model_validate(bp_content),
    ).model_dump()
    provider = _ScriptedProvider(LessonPlanIntentDecision(intent="SECTION_EDIT", summary="修改章节"), [
        AgentDecision(completed=True, output={"intent": "SECTION_EDIT", "affected_section_ids": [], "structural": False}, summary="意图"),
        AgentDecision(completed=True, output={"blueprint_summary": {}}, summary="调研"),
        AgentDecision(completed=True, output={"outline": []}, summary="目录"),
        AgentDecision(completed=True, output={"core": {}}, summary="内容"),
        AgentDecision(completed=True, output={"content": {}, "schema_version": "2.0"}, summary="终稿"),
    ])
    runtime = _make_runtime(provider, instruction="把大纲改成只保留一个章节")
    runtime.source_artifact = SimpleNamespace(content_json=source_content)
    # 候选稿与源不同（真实发生修改），再注入阻断问题验证 rejected 门禁。
    modified = copy.deepcopy(source_content)
    modified["outline"]["sections"][0]["title"] = "教学内容与学情（已调整）"
    runtime.builder = LessonPlanBuilder(modified)
    # 人为注入阻断问题，模拟 QA 未收敛。
    runtime.blocking_issues = [{"severity": "major", "location": "$", "dimension": "structure",
                                "description": "一级章节数量不足", "suggestion": "x", "target_agent": "lesson_plan_agent", "required_action": "revise", "artifact_type": "lesson_plan", "evidence": "e"}]
    asyncio.run(runtime._finalize())
    assert runtime.result_status == "rejected"
    assert runtime.publishable is False


def test_missing_required_artifacts_block_publish():
    source = make_lesson_plan_v2(make_bp()).model_dump()
    modified = copy.deepcopy(source)
    modified["outline"]["sections"][0]["title"] = "已修改但流水线产物不完整"
    runtime = _make_runtime(SimpleNamespace())
    runtime.source_artifact = SimpleNamespace(content_json=source)
    runtime.builder = LessonPlanBuilder(modified)
    runtime.active_intent = "SECTION_EDIT"
    runtime.resolved_intent = LessonPlanIntentDecision(intent="SECTION_EDIT", summary="修改章节")

    asyncio.run(runtime._finalize())

    assert runtime.result_status == "rejected"
    assert runtime.publishable is False
    assert runtime.intent_gate["code"] == "required_artifact_missing"
    assert "lesson_intent" in runtime.intent_gate["missing_artifacts"]


def test_unresolved_tool_failure_blocks_publish_even_with_required_artifacts():
    source = make_lesson_plan_v2(make_bp()).model_dump()
    modified = copy.deepcopy(source)
    modified["outline"]["sections"][0]["title"] = "已修改但工具失败未解除"
    runtime = _make_runtime(SimpleNamespace())
    runtime.source_artifact = SimpleNamespace(content_json=source)
    runtime.builder = LessonPlanBuilder(modified)
    runtime.active_intent = "SECTION_EDIT"
    runtime.resolved_intent = LessonPlanIntentDecision(intent="SECTION_EDIT", summary="修改章节")
    for artifact_type in (
        "lesson_intent", "lesson_research", "lesson_outline", "lesson_content", "lesson_qa", "lesson_plan_draft",
    ):
        asyncio.run(runtime.artifacts.create(artifact_type, "default", {}))
    runtime.unresolved_tool_failures["lesson_designer:lesson_update_core"] = {
        "agent_key": "lesson_designer", "tool_name": "lesson_update_core",
        "error_code": "candidate_invalid", "message": "候选稿非法", "retryable": False,
    }

    asyncio.run(runtime._finalize())

    assert runtime.result_status == "rejected"
    assert runtime.publishable is False
    assert runtime.intent_gate["code"] == "unresolved_tool_failure"


def test_content_regression_blocks_publish_when_existing_sections_are_emptied():
    source = make_lesson_plan_v2(make_bp()).model_dump()
    modified = copy.deepcopy(source)
    for section in modified["outline"]["sections"]:
        section["summary"] = ""
        section["blocks"] = []
    modified["outline"]["sections"].append({
        "id": "SEC-ASSESSMENT", "title": "教学评价", "summary": "",
        "coverage_refs": ["assessment_plan"], "blocks": [], "children": [],
    })
    runtime = _make_runtime(SimpleNamespace(), instruction="教学评价与教学反思分成两个部分", mode="structure")
    runtime.source_artifact = SimpleNamespace(content_json=source)
    runtime.builder = LessonPlanBuilder(modified)
    runtime.baseline_content = copy.deepcopy(source)
    runtime.active_intent = "RESTRUCTURE"
    runtime.resolved_intent = LessonPlanIntentDecision(
        intent="RESTRUCTURE", structural=True,
        required_change_kinds=["outline_structure"],
        required_separate_facts=["assessment_plan", "reflection"],
        must_be_distinct_top_level=True,
    )
    for artifact_type in (
        "lesson_intent", "lesson_research", "lesson_outline", "lesson_content", "lesson_qa", "lesson_plan_draft",
    ):
        asyncio.run(runtime.artifacts.create(artifact_type, "default", {}))

    asyncio.run(runtime._finalize())

    assert runtime.result_status == "rejected"
    # 保留章节（非目标章节）被清空同时触发内容退化与作用域门禁；作用域门禁
    # （保留章节逐字不变）是更严格的不变式，优先呈现。
    assert runtime.intent_gate["code"] == "scope_gate_failed"
    assert runtime.diff_summary["emptied_sections"]


def test_repair_loop_stops_on_repeated_fingerprint():
    """相同 QA 指纹连续出现 → 停止返修空转。"""
    from app.agent.agents.lesson_plan.builder import LessonPlanBuilder
    from app.agent.agents.lesson_plan.qa import fingerprint as _fp
    from app.agent.schemas import PipelinePlan

    bp_content = make_bp().model_dump()
    source_content = make_lesson_plan_v2(
        CourseBlueprintSchema.model_validate(bp_content),
    ).model_dump()
    provider = _ScriptedProvider(LessonPlanIntentDecision(intent="SECTION_EDIT", summary="修改"), [
        AgentDecision(completed=True, output={"intent": "SECTION_EDIT", "affected_section_ids": [], "structural": False}, summary="意图"),
        AgentDecision(completed=True, output={"blueprint_summary": {}}, summary="调研"),
        AgentDecision(completed=True, output={"outline": []}, summary="目录"),
        AgentDecision(completed=True, output={"core": {}}, summary="内容"),
        AgentDecision(completed=True, output={"content": {}, "schema_version": "2.0"}, summary="终稿"),
    ])
    runtime = _make_runtime(provider)
    runtime.source_artifact = SimpleNamespace(content_json=source_content)
    # 候选稿与源不同：深拷贝后修改第一个章节标题（结构仍合法）。
    modified = copy.deepcopy(source_content)
    modified["outline"]["sections"][0]["title"] = "教学内容与学情（已调整）"
    runtime.builder = LessonPlanBuilder(modified)
    issue = {"severity": "major", "location": "$", "dimension": "structure",
             "description": "阻塞", "suggestion": "x", "target_agent": "lesson_plan_agent",
             "required_action": "revise", "artifact_type": "lesson_plan", "evidence": "e"}
    # 第一次指纹与第二次相同 → 停止。
    runtime.repair_fingerprint = _fp([issue])
    runtime.blocking_issues = [issue]
    asyncio.run(runtime._finalize())
    assert runtime.result_status == "rejected"


# ---------------------------------------------------------------------------
# 意图识别修复：SECTION_FORMAT_EDIT / 修改优先于问答 / 确定性稳定
# ---------------------------------------------------------------------------


def test_numbering_defect_phrase_is_stable_section_format_edit():
    """精确短语 20 次运行结果一致：SECTION_FORMAT_EDIT + SEC-REFLECTION，绝不 ANSWER_ONLY。"""
    from app.agent.agents.lesson_plan.intents import infer_lesson_plan_intent

    phrase = "教学反思的序号有问题，作为一个新的点序号为什么是二"
    results = []
    for _ in range(20):
        decision = asyncio.run(infer_lesson_plan_intent(None, "message", phrase, ["reflection"], None))
        results.append((decision.intent, tuple(decision.target_section_ids)))
    assert len(set(results)) == 1, f"20 次运行结果不一致：{set(results)}"
    intent, targets = results[0]
    assert intent == "SECTION_FORMAT_EDIT"
    assert targets == ("SEC-REFLECTION",)
    assert "ANSWER_ONLY" not in {item[0] for item in results}


def test_numbering_defect_contract_metadata():
    from app.agent.agents.lesson_plan.intents import infer_lesson_plan_intent

    decision = asyncio.run(infer_lesson_plan_intent(
        None, "message", "教学反思的序号有问题，作为一个新的点序号为什么是二", ["reflection"], None,
    ))
    assert decision.rule_match == "coarse-format"
    assert decision.classifier_version == "v4"
    assert decision.raw_section_ids == ["reflection"]
    assert decision.required_change_kinds == ["formatting"]
    assert "core_content" in decision.forbidden_change_kinds
    assert decision.strip_hardcoded_numbering is True


def test_edit_signal_beats_question_only():
    from app.agent.agents.lesson_plan.intents import infer_lesson_plan_intent

    # 含编辑信号（有问题/序号）绝不判为 ANSWER_ONLY。
    decision = asyncio.run(infer_lesson_plan_intent(None, "message", "为什么教学反思编号是二？", None, None))
    assert decision.intent in {"SECTION_FORMAT_EDIT", "SECTION_EDIT"}
    # 纯解释性问题（无编辑信号）才进入 ANSWER_ONLY。
    pure = asyncio.run(infer_lesson_plan_intent(None, "message", "教学目标为什么要用行为动词描述？", None, None))
    assert pure.intent == "ANSWER_ONLY"


def test_new_section_request_routes_to_restructure():
    from app.agent.agents.lesson_plan.intents import infer_lesson_plan_intent

    decision = asyncio.run(infer_lesson_plan_intent(None, "message", "新增一个教学反思章节", None, None))
    assert decision.intent == "RESTRUCTURE"


# ---------------------------------------------------------------------------
# 章节 ID 规范化
# ---------------------------------------------------------------------------


def test_section_scope_canonicalizes_alias_and_rejects_unknown():
    from app.services.lesson_plan_pipeline_service import _section_scope
    from app.agent.core.error import AgentError

    source = make_lesson_plan_v2(make_bp()).model_dump()
    source_artifact = SimpleNamespace(content_json=source)

    # 别名 reflection → SEC-REFLECTION（仅入口转换）。
    message = SimpleNamespace(metadata_json={
        "selected_section_ids": ["reflection"], "active_section_id": "",
    })
    assert _section_scope(message, source_artifact) == ["SEC-REFLECTION"]

    # 未知 ID 立即抛结构化错误，不进入工具层。
    message = SimpleNamespace(metadata_json={
        "selected_section_ids": ["SEC-NOPE"], "active_section_id": "",
    })
    try:
        _section_scope(message, source_artifact)
        assert False, "未知章节 ID 应抛出 invalid_section_id"
    except AgentError as exc:
        assert exc.code == "invalid_section_id"
        assert exc.retryable is False

    # active_section_id 也参与规范化。
    message = SimpleNamespace(metadata_json={
        "selected_section_ids": [], "active_section_id": "reflection",
    })
    assert _section_scope(message, source_artifact) == ["SEC-REFLECTION"]


def test_runtime_canonicalizes_selected_sections():
    from app.agent.agents.lesson_plan.section_refs import build_section_index, canonicalize_section_ids

    source = make_lesson_plan_v2(make_bp()).model_dump()
    index = build_section_index(source)
    canonical, invalid = canonicalize_section_ids(["reflection", "SEC-OBJECTIVES", "SEC-NOPE"], index)
    assert canonical == ["SEC-REFLECTION", "SEC-OBJECTIVES"]
    assert invalid == ["SEC-NOPE"]


# ---------------------------------------------------------------------------
# SECTION_FORMAT_EDIT 执行链：禁止内核修改、确定性清理、致命错误终止
# ---------------------------------------------------------------------------


def test_format_edit_policy_denies_core_update_and_loop_terminates_fatally():
    """SECTION_FORMAT_EDIT 下 lesson_update_core 被 core_field_unauthorized 致命拦截：
    core/loop 立即抛 fatal_tool_error（不伪装 agent_no_progress），编辑工具返回
    retryable=False 且携带 allowed_scope/suggestion。"""
    from app.agent.core.error import AgentError
    from app.agent.registry import execute_tool

    intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True,
        rule_match="numbering_defect", classifier_version="v3",
    )
    # 直接构造带 SECTION_FORMAT_EDIT 契约的 runtime，验证工具层权限收紧。
    runtime = _make_runtime(_ScriptedProvider(intent, []), mode="content")
    runtime.source_artifact = SimpleNamespace(content_json=make_lesson_plan_v2(make_bp()).model_dump(), version=16)
    asyncio.run(_prepare(runtime))
    asyncio.run(runtime._resolve_intent())
    assert runtime.mutation_policy.allowed_core_keys == set()

    # 工具层：lesson_update_core 返回不可重试的 core_field_unauthorized。
    result = asyncio.run(execute_tool(
        "lesson_update_core", runtime.tool_context, {"patch": {"reflection": "越权改写内核"}},
    ))
    assert result.ok is False
    assert result.error_code == "core_field_unauthorized"
    assert result.retryable is False
    assert result.output["allowed_scope"] == []
    assert result.output["suggestion"]

    # core/loop：工具返回致命错误 → 立即抛 fatal_tool_error（非 agent_no_progress）。
    decisions = [
        AgentDecision(tool_calls=[ToolCall(
            tool_name="lesson_update_core", input={"patch": {"reflection": "越权改写内核"}},
        )]),
        AgentDecision(completed=True, output={"content": {}}, summary="终稿"),
    ]

    async def call_agent(*_args):
        return decisions.pop(0)

    with pytest.raises(AgentError) as caught:
        asyncio.run(run_core_agent_loop(
            runtime,
            PipelinePlan(agents=[AgentSpec(key="editor", role="editor", max_steps=2)]),
            agent_registry={"editor": _LoopAgent(["lesson_update_core"])},
            call_agent=call_agent,
            persist_artifact=_no_artifact,
        ))
    assert caught.value.code == "fatal_tool_error"
    assert caught.value.retryable is False
    assert caught.value.details["error_code"] == "core_field_unauthorized"
    assert runtime.termination_reason != "agent_no_progress"
    # runtime 捕获致命错误 → rejected 发布门禁。
    runtime.fatal_tool_error = dict(caught.value.details)
    asyncio.run(runtime._finalize())
    assert runtime.result_status == "rejected"
    assert runtime.intent_gate["code"] == "fatal_tool_error"


def test_format_edit_normalizes_without_core_update():
    """合法 SECTION_FORMAT_EDIT：format_normalizer 确定性清理序号，result applied，内核未改。"""
    intent = LessonPlanIntentDecision(
        intent="SECTION_FORMAT_EDIT", target_section_ids=["SEC-REFLECTION"],
        target_fact_keys=["reflection"],
        required_change_kinds=["formatting"],
        forbidden_change_kinds=["outline_structure", "core_content", "timing"],
        strip_hardcoded_numbering=True,
        rule_match="numbering_defect", classifier_version="v3",
    )
    source = make_lesson_plan_v2(make_bp()).model_dump()
    for section in source["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{
                "kind": "paragraph",
                "text": "一、教师课后反思框架：\n1. 目标达成情况检查。",
            }]
    runtime = _make_runtime(provider := _ScriptedProvider(intent, [
        AgentDecision(completed=True, output={"content": {}, "schema_version": "2.0"}, summary="终稿"),
    ]), instruction="教学反思的序号有问题，作为一个新的点序号为什么是二", mode="content")
    runtime.source_artifact = SimpleNamespace(content_json=source)
    asyncio.run(runtime.run())

    assert runtime.result_status == "applied"
    assert runtime.fatal_tool_error is None
    assert runtime.executed_chain == ["intent_planner", "context_researcher", "format_normalizer", "pedagogy_qa", "finalizer"]
    reflection = next(
        item for item in runtime.draft_content["outline"]["sections"] if item["id"] == "SEC-REFLECTION"
    )
    assert "一、" not in reflection["blocks"][0]["text"]
    # 其他章节与内核完全未变。
    for section in runtime.draft_content["outline"]["sections"]:
        if section["id"] != "SEC-REFLECTION":
            assert section["blocks"] == next(
                item for item in source["outline"]["sections"] if item["id"] == section["id"]
            )["blocks"]
    assert runtime.draft_content["pedagogical_core"] == source["pedagogical_core"]


# ---------------------------------------------------------------------------
# 不可变上下文快照
# ---------------------------------------------------------------------------


def test_snapshot_created_before_execution_with_full_scope():
    """快照在执行链前创建：source_version/snapshot_hash/requested/resolved/preserved 齐备，
    resolved 取自规范化契约而非执行后 diff。"""
    intent = LessonPlanIntentDecision(
        intent="SECTION_EDIT", target_section_ids=["SEC-REFLECTION"],
        resolved_scope=["SEC-REFLECTION"], required_change_kinds=["section_content"],
    )
    source = make_lesson_plan_v2(make_bp()).model_dump()
    runtime = _make_runtime(_ScriptedProvider(intent, [
        # lesson_designer（LLM）：完成内容写入。
        AgentDecision(completed=True, output={"core": {}}, summary="内容已写入"),
        # finalizer（LLM）：终稿。
        AgentDecision(completed=True, output={"content": {}, "schema_version": "2.0"}, summary="终稿"),
    ]), instruction="修改教学反思内容", mode="content")
    runtime.source_artifact = SimpleNamespace(content_json=source, version=17)
    runtime.selected_section_ids = ["SEC-REFLECTION"]
    asyncio.run(runtime.run())

    snapshot = runtime.context_snapshot
    assert snapshot is not None
    assert snapshot.snapshot_id
    assert snapshot.snapshot_hash
    assert snapshot.source_version == "v17"
    assert snapshot.resolved_section_ids == ["SEC-REFLECTION"]
    assert "SEC-REFLECTION" in snapshot.requested_section_ids
    assert snapshot.preserved_section_ids
    assert "SEC-REFLECTION" not in snapshot.preserved_section_ids
    assert snapshot.fact_owner_map.get("reflection") == "SEC-REFLECTION"
    # 契约写回快照标识（所有 Agent 共享同一快照）。
    assert runtime.resolved_intent.context_snapshot_id == snapshot.snapshot_id
    assert runtime.resolved_intent.context_snapshot_hash == snapshot.snapshot_hash


# ---------------------------------------------------------------------------
# ANSWER_ONLY 独立完成协议
# ---------------------------------------------------------------------------


def test_answer_only_returns_no_change_with_lesson_answer():
    """纯问答：不要求 lesson_content、不创建版本、返回 lesson_answer、no_change。"""
    from app.agent.agents.lesson_plan.agents import ANSWER_FINALIZER

    intent = LessonPlanIntentDecision(
        intent="ANSWER_ONLY", required_change_kinds=["answer_only"],
        forbidden_change_kinds=["outline_structure", "section_content", "core_content", "timing"],
    )
    provider = _ScriptedProvider(intent, [
        AgentDecision(completed=True, output={
            "answer": "教学目标使用行为动词是为了可观测、可判定。", "mode": "answer_only",
        }, summary="已回答"),
    ])
    runtime = _make_runtime(provider, instruction="教学目标为什么要用行为动词描述？", mode="auto")
    runtime.source_artifact = SimpleNamespace(content_json=make_lesson_plan_v2(make_bp()).model_dump(), version=16)
    asyncio.run(runtime.run())

    assert runtime.active_intent == "ANSWER_ONLY"
    assert runtime.result_status == "no_change"
    assert runtime.changed is False
    assert runtime.publishable is False
    # 产物协议：lesson_answer 存在，且没有把缺 lesson_content 当作失败。
    assert runtime.draft_answer.get("answer")
    missing = asyncio.run(runtime._missing_required_artifacts())
    assert missing == []
    # 纯问答绝不创建 lesson_content 产物。
    assert asyncio.run(runtime.artifacts.latest("lesson_content")) is None


def test_answer_only_chain_uses_answer_finalizer():
    from app.agent.agents.lesson_plan.intents import agent_chain_for_intent

    chain = agent_chain_for_intent("ANSWER_ONLY", "message")
    assert chain == ["context_researcher", "answer_finalizer"]
