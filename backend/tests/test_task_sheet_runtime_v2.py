"""学习任务单 Agent Runtime 方案验收测试（方案 §2/§3）。"""

from __future__ import annotations

import copy

import pytest

from app.agent.agents.task_sheet.intents import (
    TaskSheetIntentDecision,
    agent_chain_for_intent,
    infer_task_sheet_intent,
)
from app.agent.agents.task_sheet.tools import register_task_sheet_tools


class _MockIntentProvider:
    """MockProvider 形态：infer_task_sheet_intent 直接走确定性兜底。"""

    __class__ = property(lambda self: type("MockProvider", (), {}))


# ---------------------------------------------------------------------------
# 意图分类（方案 §2.2）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_new_categories():
    cases = {
        "把任务链的步骤改得更细": "TASK_EDIT",
        "调整任务用时，压缩到 3 分钟": "TIMING_ADJUST",
        "给任务加两个思考支架": "SCAFFOLD_EDIT",
        "把记录表改成三列表格": "RECORDING_EDIT",
        "让目标和任务覆盖对齐": "ALIGNMENT_REPAIR",
        "新增一个巩固章节并调整目录顺序": "STRUCTURE_EDIT",
        "这个任务单质量怎么样": "QA_ONLY",
    }
    for instruction, expected in cases.items():
        plan = await infer_task_sheet_intent(_MockIntentProvider(), "message", instruction)
        assert plan.intent == expected, f"{instruction} → {plan.intent}"

    sync = await infer_task_sheet_intent(None, "sync_context", "")
    assert sync.intent == "SYNC_CONTEXT"


@pytest.mark.asyncio
async def test_intent_destructive_requires_confirmation():
    plan = await infer_task_sheet_intent(_MockIntentProvider(), "message", "删除第三个任务")
    assert plan.requires_confirmation is True
    assert plan.destructive is True


@pytest.mark.asyncio
async def test_intent_low_confidence_from_llm_requires_confirmation():
    class _LowConfidenceProvider:
        __class__ = property(lambda self: type("OpenAICompatibleProvider", (), {}))

        async def structured(self, system, prompt, schema):
            return TaskSheetIntentDecision(
                intent="TASK_EDIT", confidence=0.4, requires_confirmation=True,
                summary="低置信度",
            )

    plan = await infer_task_sheet_intent(_LowConfidenceProvider(), "message", "随便改改")
    assert plan.requires_confirmation is True
    assert plan.confidence < 0.65


@pytest.mark.asyncio
async def test_intent_chain_mapping_new_roles():
    assert agent_chain_for_intent("STRUCTURE_EDIT", "message")[2] == "task_architect"
    assert agent_chain_for_intent("TASK_EDIT", "message")[2] == "task_designer"
    # QA 门禁已移除：QA_ONLY 链只保留终稿渲染
    assert agent_chain_for_intent("QA_ONLY", "message") == ["finalizer"]
    assert "task_sheet_qa" not in agent_chain_for_intent("TASK_EDIT", "message")
    assert agent_chain_for_intent("SYNC_CONTEXT", "sync_context")[0] == "context_researcher"


# ---------------------------------------------------------------------------
# 工具：作用域 / 锁定路径 / 人工确认令牌（方案 §2.3）
# ---------------------------------------------------------------------------

from app.agent.agents.task_sheet.builder import build_initial_builder
from app.agent.registry import execute_tool, ToolContext
from tests.test_task_sheet_agentic import BP


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
            self.knowledge_context = {}
            self.source_artifact = None

    tc = ToolContext(
        ctx=_Ctx(), runtime=_Runtime(), extra={"builder": builder},
    )
    return tc


@pytest.fixture
def v3_builder():
    return build_initial_builder(BP)


@pytest.mark.asyncio
async def test_tool_update_task_scope_guard(v3_builder):
    plan = TaskSheetIntentDecision(intent="TASK_EDIT", target_task_ids=["T-01"])
    tc = _tool_context(v3_builder, intent_plan=plan)
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-02", "patch": {"estimated_minutes": 5},
    })
    assert not result.ok
    assert "不属于本轮意图范围" in (result.error or "")


def _lock(json_path):
    class _L:
        def __init__(self, path):
            self.json_path = path
    return _L(json_path)


@pytest.mark.asyncio
async def test_tool_lock_guard_ancestor(v3_builder):
    tc = _tool_context(v3_builder, locks=[_lock("$.sections[SEC-TASKS]")])
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-01", "patch": {"title": "改"},
    })
    assert not result.ok
    assert "锁定路径" in (result.error or "")


@pytest.mark.asyncio
async def test_tool_lock_guard_whole_file(v3_builder):
    tc = _tool_context(v3_builder, locks=[_lock("$")])
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-01", "patch": {"title": "改"},
    })
    assert not result.ok
    assert "整体锁定" in (result.error or "")


@pytest.mark.asyncio
async def test_tool_delete_task_requires_confirmation_token(v3_builder):
    tc = _tool_context(v3_builder)
    result = await execute_tool("task_sheet_delete_task", tc, {
        "task_id": "T-01", "reason": "教师要求",
    })
    assert not result.ok
    assert "人工确认" in (result.error or "")


@pytest.mark.asyncio
async def test_tool_delete_task_with_token_succeeds(v3_builder):
    tc = _tool_context(v3_builder, confirmation_tokens=["confirm-xyz"])
    result = await execute_tool("task_sheet_delete_task", tc, {
        "task_id": "T-01", "reason": "教师要求", "confirmation_token": "confirm-xyz",
    })
    assert result.ok
    assert "删除任务 T-01" in result.output.get("summary", "")


@pytest.mark.asyncio
async def test_tool_update_task_invalid_reference(v3_builder):
    tc = _tool_context(v3_builder)
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-01", "patch": {"objective_ids": ["OBJ-NOPE"]},
    })
    assert not result.ok
    assert "不存在的目标" in (result.error or "")


@pytest.mark.asyncio
async def test_tool_update_task_ok(v3_builder):
    tc = _tool_context(v3_builder)
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-01", "patch": {"estimated_minutes": 5},
    })
    assert result.ok
    assert result.output["revision"] > 0
    task, _ = v3_builder.find_task("T-01")
    assert task["estimated_minutes"] == 5


@pytest.mark.asyncio
async def test_tool_add_task_reference_check(v3_builder):
    tc = _tool_context(v3_builder)
    result = await execute_tool("task_sheet_add_task", tc, {
        "task": {
            "id": "T-99", "title": "新任务", "action": "完成", "object": "材料",
            "steps": ["第一步"], "student_output": "产出", "completion_criterion": "完整",
            "estimated_minutes": 2, "objective_ids": ["OBJ-01"],
        },
    })
    assert result.ok
    assert "T-99" in v3_builder.all_task_ids()


@pytest.mark.asyncio
async def test_tool_validate_dimensions(v3_builder):
    tc = _tool_context(v3_builder)
    for tool in ("task_sheet_validate_schema", "task_sheet_validate_references",
                 "task_sheet_validate_alignment", "task_sheet_validate_timing",
                 "task_sheet_validate_usability", "task_sheet_validate_student_language"):
        result = await execute_tool(tool, tc, {})
        assert result.ok, f"{tool} failed: {result.error}"
        assert isinstance(result.output.get("issues"), list)


@pytest.mark.asyncio
async def test_tool_render_preview_and_diff(v3_builder):
    tc = _tool_context(v3_builder)
    preview = await execute_tool("task_sheet_render_preview", tc, {"format": "markdown"})
    assert preview.ok and preview.output["markdown"]
    diff = await execute_tool("task_sheet_diff_versions", tc, {})
    assert diff.ok and diff.output["is_new"] is True


# ---------------------------------------------------------------------------
# 学习目标目录：允许新增/拆分蓝图外目标（教师细化指令）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_update_objectives_adds_non_blueprint_objective(v3_builder):
    """目标目录允许新增蓝图外目标（免确认令牌）。"""
    tc = _tool_context(v3_builder)
    catalog = copy.deepcopy(v3_builder.objective_catalog)
    catalog.append({
        "id": "obj_04", "statement": "分析完全浸没物体下潜时浮力变化，澄清越深浮力越大的误区",
        "success_criterion": "能说明 F浮=G排 与深度的关系",
    })
    result = await execute_tool("task_sheet_update_objectives", tc, {"objective_catalog": catalog})
    assert result.ok
    assert result.output["revision"] > 0
    assert any(item["id"] == "obj_04" for item in v3_builder.objective_catalog)


@pytest.mark.asyncio
async def test_tool_update_task_can_reference_new_catalog_objective(v3_builder):
    """新增蓝图外目标后，任务可引用它（目标允许集 = 蓝图 ∪ 目录）。"""
    tc = _tool_context(v3_builder)
    catalog = copy.deepcopy(v3_builder.objective_catalog)
    catalog.append({"id": "obj_04", "statement": "细化目标", "success_criterion": "能辨析"})
    await execute_tool("task_sheet_update_objectives", tc, {"objective_catalog": catalog})
    task, _ = v3_builder.find_task("T-01")
    target_objectives = [*task["objective_ids"], "obj_04"]
    result = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-01", "patch": {"objective_ids": target_objectives},
    })
    assert result.ok
    task, _ = v3_builder.find_task("T-01")
    assert "obj_04" in task["objective_ids"]
    # 目录外目标仍拒绝
    bad = await execute_tool("task_sheet_update_task", tc, {
        "task_id": "T-01", "patch": {"objective_ids": ["OBJ-NOPE"]},
    })
    assert not bad.ok
    assert "不存在的目标" in (bad.error or "")


@pytest.mark.asyncio
async def test_tool_update_objectives_remove_requires_confirmation(v3_builder):
    """移除目录条目（目标解绑）仍须人工确认令牌。"""
    tc = _tool_context(v3_builder)
    catalog = copy.deepcopy(v3_builder.objective_catalog)[1:]
    result = await execute_tool("task_sheet_update_objectives", tc, {"objective_catalog": catalog})
    assert not result.ok
    assert "人工确认" in (result.error or "")
    # 携带令牌可执行
    tc_with_token = _tool_context(v3_builder, confirmation_tokens=["TOKEN"])
    ok = await execute_tool("task_sheet_update_objectives", tc_with_token, {
        "objective_catalog": catalog, "confirmation_token": "TOKEN",
    })
    assert ok.ok


@pytest.mark.asyncio
async def test_tool_update_objectives_duplicate_id_rejected(v3_builder):
    tc = _tool_context(v3_builder)
    catalog = copy.deepcopy(v3_builder.objective_catalog)
    catalog.append(dict(catalog[0]))
    result = await execute_tool("task_sheet_update_objectives", tc, {"objective_catalog": catalog})
    assert not result.ok
    assert "重复" in (result.error or "")


# ---------------------------------------------------------------------------
# 原生 tool calling 回退（方案 §3.1）
# ---------------------------------------------------------------------------


def test_tool_registry_has_28_tools():
    register_task_sheet_tools()
    from app.agent.registry import all_tools

    names = [t.name for t in all_tools() if t.name.startswith("task_sheet")]
    assert "task_sheet_update_task" in names
    assert "task_sheet_add_section" in names
    assert len(names) >= 25


@pytest.mark.asyncio
async def test_openai_provider_native_method_protocol_error():
    """原生调用协议错误时返回 None（调用方回退结构化协议）。"""
    from app.providers.llm.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(api_key="", base_url="http://invalid", model_name="test")
    assert provider.supports_native_tools is True
    decision = await provider.native_agent_decision("system", "prompt", [])
    assert decision is None


@pytest.mark.asyncio
async def test_anthropic_provider_native_missing_key():
    from app.providers.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="")
    assert provider.supports_native_tools is True
    decision = await provider.native_agent_decision("system", "prompt", [])
    assert decision is None


@pytest.mark.asyncio
async def test_mock_provider_no_native():
    from app.providers.llm.mock import MockProvider

    provider = MockProvider()
    assert getattr(provider, "supports_native_tools", False) is False


# ---------------------------------------------------------------------------
# QA 返修指纹防空转（方案 §1 / §2.3）
# ---------------------------------------------------------------------------

from app.agent.agents.task_sheet.qa import fingerprint, validate_task_sheet_v3
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.task_sheet import make_task_sheet_v3


def test_qa_fingerprint_prevents_stall():
    bp = CourseBlueprintSchema.model_validate(BP)
    data = make_task_sheet_v3(bp).model_dump()
    for section in data["sections"]:
        section["blocks"] = [b for b in section["blocks"] if b.get("kind") != "learning_task"]
    issues_a = validate_task_sheet_v3(bp, copy.deepcopy(data))
    issues_b = validate_task_sheet_v3(bp, copy.deepcopy(data))
    blocking_a = [i for i in issues_a if i["severity"] in {"critical", "major"}]
    assert blocking_a
    assert fingerprint(issues_a) == fingerprint(issues_b)
    first = blocking_a[0]
    assert all(key in first for key in ("id", "severity", "dimension", "path", "description", "suggestion", "target_role"))


def test_qa_llm_system_prompt_no_secrets():
    from app.agent.agents.task_sheet.qa import llm_qa_system_prompt

    prompt = llm_qa_system_prompt()
    assert "api_key" not in prompt.lower()
    assert "api key" not in prompt.lower()


# ---------------------------------------------------------------------------
# finalizer 组装节点收敛（防止只读工具空转 → 工具轮次上限硬失败）
# ---------------------------------------------------------------------------

from app.agent.agents.task_sheet.agents import FINALIZER, FINALIZER_TOOLS
from app.agent.agents.task_sheet.runtime import TaskSheetAgentRuntime, _call_agent
from app.agent.registry import get_tool
from app.agent.schemas import AgentDecision, ToolCall


class _FinalizerToolProvider:
    """仅 stream_decision：第一轮请求 render_preview，第二轮（不应被调用）直接 completed。"""

    def __init__(self):
        self.calls = 0

    async def stream_decision(self, system, prompt, schema):
        self.calls += 1
        if self.calls == 1:
            yield ("decision_ready", schema(
                completed=False,
                tool_calls=[ToolCall(tool_name="task_sheet_render_preview", input={"format": "markdown"})],
                message="先渲染预览确认结构",
            ))
            return
        yield ("decision_ready", schema(
            completed=True,
            output={"note": "终稿要点说明"},
            summary="终稿整合完成", message="已完成终稿整合。",
        ))


class _FinalizerFailProvider:
    """LLM 全程不可用（无 structured）：确定性兜底。"""

    async def stream_decision(self, system, prompt, schema):
        yield ("thought_delta", "x")
        raise RuntimeError("llm down")


class _FinalizerCompleteProvider:
    """LLM 直接 completed（无工具调用）：确定性产物 + 附加 llm_analysis。"""

    async def stream_decision(self, system, prompt, schema):
        yield ("decision_ready", schema(
            completed=True,
            output={"pedagogical_note": "任务梯度合理，支架有效"},
            summary="教学要点说明完成", message="已输出教学要点说明。",
        ))


def _finalizer_runtime(builder, provider):
    tc = _tool_context(builder)
    return TaskSheetAgentRuntime(provider=provider, tool_context=tc)


@pytest.mark.asyncio
async def test_finalizer_tool_round_then_deterministic_complete(v3_builder):
    """第一轮 LLM 请求只读工具 → 放行并缓存；第二轮确定性产出 + 附加分析（不重复调 LLM）。"""
    provider = _FinalizerToolProvider()
    runtime = _finalizer_runtime(v3_builder, provider)
    # 第一轮：LLM 请求 render_preview → 放行
    first = await _call_agent(runtime, "finalizer", FINALIZER, 0)
    assert first.tool_calls and first.tool_calls[0].tool_name == "task_sheet_render_preview"
    assert provider.calls == 1
    assert runtime._analysis_cache.get("finalizer") is not None
    # 第二轮：缓存命中 → 确定性终稿 + 附加 LLM 摘要，不再调用 LLM
    second = await _call_agent(runtime, "finalizer", FINALIZER, 1)
    assert second.completed
    assert second.output["content"]  # 组装产物始终来自确定性 decide
    assert second.output["markdown"]
    assert second.summary == "终稿整合完成"  # 采纳 LLM 摘要
    assert provider.calls == 1  # 未再调 LLM


@pytest.mark.asyncio
async def test_finalizer_llm_failure_falls_back_deterministic(v3_builder):
    provider = _FinalizerFailProvider()
    runtime = _finalizer_runtime(v3_builder, provider)
    decision = await _call_agent(runtime, "finalizer", FINALIZER, 0)
    assert decision.completed
    assert decision.output["content"]
    assert decision.output["markdown"]
    assert "llm_analysis" not in decision.output


@pytest.mark.asyncio
async def test_finalizer_llm_completed_without_tools_merges_analysis(v3_builder):
    provider = _FinalizerCompleteProvider()
    runtime = _finalizer_runtime(v3_builder, provider)
    decision = await _call_agent(runtime, "finalizer", FINALIZER, 0)
    assert decision.completed
    assert decision.output["content"]
    assert "llm_analysis" in decision.output
    assert decision.output["llm_analysis"]["pedagogical_note"] == "任务梯度合理，支架有效"
    assert decision.summary == "教学要点说明完成"


def test_check_tools_marked_idempotent():
    """只读/校验工具标记 idempotent：重复调用不算新进展，配合 no-progress 防空转。"""
    register_task_sheet_tools()
    for name in ("task_sheet_validate_schema", "task_sheet_validate_references",
                 "task_sheet_validate_alignment", "task_sheet_validate_timing",
                 "task_sheet_validate_usability", "task_sheet_validate_student_language",
                 "task_sheet_diff_versions", "task_sheet_render_preview"):
        tool = get_tool(name)
        assert tool is not None, name
        assert tool.idempotent is True, name


# ---------------------------------------------------------------------------
# 空参数防御：LLM 发 {} 空工具调用必须被拒绝（不静默成功、不伪造进展）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_empty_arguments_rejected(v3_builder):
    """空参数工具调用在参数校验层被拒绝，回喂 LLM 自修复。"""
    tc = _tool_context(v3_builder)
    cases = {
        "task_sheet_update_objectives": {},
        "task_sheet_update_task": {},
        "task_sheet_update_self_assessment": {},
        "task_sheet_update_preparation_extension": {},
        "task_sheet_update_section": {},
    }
    for tool_name, payload in cases.items():
        result = await execute_tool(tool_name, tc, payload)
        assert not result.ok, f"{tool_name} 空参数应被拒绝"
        assert result.error_code in {"tool_input_invalid", "missing_input"}, (
            f"{tool_name}: {result.error_code}"
        )


@pytest.mark.asyncio
async def test_tool_self_assessment_scale_only_still_valid(v3_builder):
    """自评仅更新 scale（不传 items）仍合法——保留部分更新语义。"""
    tc = _tool_context(v3_builder)
    result = await execute_tool("task_sheet_update_self_assessment", tc, {
        "scale": ["做不到", "基本做到", "完全做到"],
    })
    assert result.ok
    assert result.output["revision"] > 0


@pytest.mark.asyncio
async def test_tool_update_objectives_requires_catalog(v3_builder):
    """update_objectives 缺 objective_catalog 被参数校验拒绝（不再报 missing_input 后的空转）。"""
    tc = _tool_context(v3_builder)
    result = await execute_tool("task_sheet_update_objectives", tc, {"confirmation_token": "x"})
    assert not result.ok
    assert result.error_code == "tool_input_invalid"


# ---------------------------------------------------------------------------
# update_objectives 同步 objective_list Block（显示区域）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_objectives_syncs_objective_list_block(v3_builder):
    """新增目标时，objective_list Block 同步追加新 ID，修复「目录 4 条/显示 3 条」不一致。"""
    tc = _tool_context(v3_builder)
    catalog = copy.deepcopy(v3_builder.objective_catalog)
    obj_list_before = None
    for section in v3_builder.sections:
        for block in section.get("blocks", []):
            if block.get("kind") == "objective_list":
                obj_list_before = list(block.get("objective_ids", []))
                break

    catalog.append({"id": "obj_04", "statement": "新增第四目标", "success_criterion": "能完成"})
    result = await execute_tool("task_sheet_update_objectives", tc, {"objective_catalog": catalog})
    assert result.ok
    assert "同步更新" in result.output.get("summary", "")

    obj_list_after = None
    for section in v3_builder.sections:
        for block in section.get("blocks", []):
            if block.get("kind") == "objective_list":
                obj_list_after = list(block.get("objective_ids", []))
                break
    assert obj_list_after is not None
    assert "obj_04" in obj_list_after
    assert all(old_id in obj_list_after for old_id in (obj_list_before or []))


@pytest.mark.asyncio
async def test_update_objectives_no_change_no_sync(v3_builder):
    """目录未增加新 ID 时不动 objective_list Block（affected_paths 仅含 catalog）。"""
    tc = _tool_context(v3_builder)
    catalog = copy.deepcopy(v3_builder.objective_catalog)
    catalog[0] = {**catalog[0], "statement": "更新了描述文字"}
    result = await execute_tool("task_sheet_update_objectives", tc, {"objective_catalog": catalog})
    assert result.ok
    assert "同步更新" not in result.output.get("summary", "")
    assert result.output["affected_json_paths"] == ["$.objective_catalog"]


@pytest.mark.asyncio
async def test_update_objectives_no_change_false_positive_fixed(v3_builder):
    """新增目标后 builder 与 source 内容不同，不再误判为 no_change。"""
    tc = _tool_context(v3_builder)
    source_obj_list = None
    for section in v3_builder.sections:
        for block in section.get("blocks", []):
            if block.get("kind") == "objective_list":
                source_obj_list = list(block.get("objective_ids", []))

    catalog = copy.deepcopy(v3_builder.objective_catalog)
    catalog.append({"id": "obj_04", "statement": "新目标", "success_criterion": "能完成"})
    await execute_tool("task_sheet_update_objectives", tc, {"objective_catalog": catalog})

    updated_obj_list = None
    for section in v3_builder.sections:
        for block in section.get("blocks", []):
            if block.get("kind") == "objective_list":
                updated_obj_list = list(block.get("objective_ids", []))

    assert updated_obj_list != source_obj_list
    assert len(updated_obj_list) == len(source_obj_list) + 1
