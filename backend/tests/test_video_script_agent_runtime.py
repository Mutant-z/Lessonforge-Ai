"""视频脚本 Agent 动态工具化流水线单元测试：工具、意图、QA、Builder 不变量。"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.agent.agents.video_script.builder import VideoScriptBuilder, build_initial_builder
from app.agent.agents.video_script.intents import agent_chain_for_intent, infer_video_script_intent
from app.agent.agents.video_script.qa import blocking_issues, fingerprint, validate_video_script_v4
from app.agent.agents.video_script.tools import register_video_script_tools, video_script_tool_schemas
from app.agent.context import ContextState
from app.agent.registry import ToolContext, execute_tool
from app.agents.generators import make_blueprint, make_lesson_plan, make_seedance_video_script
from app.providers.llm.mock import MockProvider
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.video_script_v4 import upgrade_video_script_v4

from tests.test_video_script_upgrade import sample_course


@pytest.fixture
def bp() -> CourseBlueprintSchema:
    return make_blueprint(sample_course())


@pytest.fixture
def lesson_payload(bp) -> dict:
    return make_lesson_plan(bp).model_dump()


@pytest.fixture
def builder(bp, lesson_payload) -> VideoScriptBuilder:
    v3 = make_seedance_video_script(bp, make_lesson_plan(bp)).model_dump()
    v4 = upgrade_video_script_v4(v3, lesson_payload)
    return VideoScriptBuilder(v4.model_dump())


def _tool_context(builder: VideoScriptBuilder, bp: dict, lesson: dict | None = None) -> ToolContext:
    register_video_script_tools()
    runtime = SimpleNamespace(locks=[], source_artifact=None)
    context = ContextState(blueprint=bp, upstream={"lesson_plan": lesson or {}})
    return ToolContext(
        ctx=context, workspace_root=None, course=None, task=None,
        generation_run_id="", pipeline_run_id="", provider=None,
        artifacts=None, emitter=None, runtime=runtime, extra={"builder": builder},
    )


def test_semantic_lesson_plan_summary_falls_back_to_blueprint_stages(bp):
    builder = build_initial_builder(bp.model_dump(), {
        "semantic_summary": "教学设计摘要，仅用于模型上下文",
        "objectives": [{"statement": "理解核心概念"}],
        "key_points": ["核心概念"],
    })

    assert builder.sections
    assert builder.scenes
    assert builder.validate_content()["ok"]


def test_video_generation_resolution_tool_registered():
    register_video_script_tools()
    names = {item["name"] for item in video_script_tool_schemas()}
    assert "vs_set_video_generation_resolution" in names


def test_tools_registered():
    register_video_script_tools()
    names = {item["name"] for item in video_script_tool_schemas()}
    for required in (
        "vs_get_context", "vs_get_locks", "vs_inspect_outline", "vs_inspect_scene",
        "vs_apply_outline_ops", "vs_apply_scene_ops", "vs_rewrite_spoken_text",
        "vs_update_visual_direction", "vs_update_continuity", "vs_rebalance_timeline",
        "vs_update_production_settings",
        "vs_validate_draft", "vs_compute_diff", "vs_render_preview",
    ):
        assert required in names, f"工具缺失：{required}"


def test_restructure_tool_changes_sections_and_reassigns_scenes(builder, bp, lesson_payload):
    """验收场景：「不要固定导入和总结，改成问题驱动的三章结构」→ 章节与分镜归属真实变化。"""
    tc = _tool_context(builder, bp.model_dump(), lesson_payload)
    section_before = sorted(item["id"] for item in builder.sections)

    async def run():
        # 删除「情境导入」章节并把分镜迁移到「核心讲解」
        result = await execute_tool("vs_apply_outline_ops", tc, {"operations": [
            {"op": "delete_section", "section_id": section_before[0],
             "move_scenes_to": section_before[1], "reason": "改为问题驱动的结构"},
        ]})
        assert result.ok, result.error
        # 新增问题驱动章节并把首镜移入
        added = await execute_tool("vs_apply_outline_ops", tc, {"operations": [
            {"op": "add_section", "title": "问题驱动的讨论",
             "purpose": "以真实问题引导学生建立核心概念"},
        ]})
        assert added.ok, added.error
        new_sec = added.output["patch"][0]["value"]["id"]
        moved = await execute_tool("vs_apply_scene_ops", tc, {"operations": [
            {"op": "move_scene", "scene_id": builder.scenes[0]["id"], "section_id": new_sec},
        ]})
        assert moved.ok, moved.error
        # 删除章节不允许无 reason
        rejected = await execute_tool("vs_apply_outline_ops", tc, {"operations": [
            {"op": "delete_section", "section_id": builder.sections[0]["id"]},
        ]})
        assert not rejected.ok

    asyncio.run(run())
    content = builder.to_content()
    titles = [item["title"] for item in content["outline"]["sections"]]
    assert "问题驱动的讨论" in titles
    assert "情境导入" not in titles
    # 结构不变量：每个分镜属于存在的章节、同章连续、时间轴连续守恒
    assert builder.validate_content()["ok"]
    issues = validate_video_script_v4(bp, content, lesson_payload, [])
    assert not blocking_issues(issues), issues


def test_apply_scene_ops_accepts_shorthand_update_with_flat_fields(builder, bp, lesson_payload):
    """回归：LLM 常用简写 op='update' + 顶层字段，工具必须规范化而不是报参数不符合。"""
    tc = _tool_context(builder, bp.model_dump(), lesson_payload)
    target = builder.scenes[0]["id"]

    async def run():
        result = await execute_tool("vs_apply_scene_ops", tc, {"operations": [
            {"op": "update", "scene_id": target, "spoken_text": "简化的口播内容。"},
        ]})
        assert result.ok, result.error
        assert result.output["affected_scene_ids"] == [target]

    asyncio.run(run())
    updated = next(item for item in builder.scenes if item["id"] == target)
    assert updated["spoken_text"] == "简化的口播内容。"


def test_apply_scene_ops_syncs_fact_baseline_on_spoken_text_update(builder, bp, lesson_payload):
    """回归：update_scene 修改口播后，required_facts 必须与 rewrite_spoken_text 一样
    只保留仍出现在新口播中的条目，避免精简口播后残留旧句导致 QA 误判。"""
    target = builder.scenes[0]["id"]
    original_fact = next(item["required_facts"] for item in builder.scenes if item["id"] == target)
    assert original_fact, "夹具前置：目标分镜必须带有事实基准"
    tc = _tool_context(builder, bp.model_dump(), lesson_payload)

    async def run():
        result = await execute_tool("vs_apply_scene_ops", tc, {"operations": [
            {"op": "update", "scene_id": target, "spoken_text": "精简后的全新口播。"},
        ]})
        assert result.ok, result.error

    asyncio.run(run())
    updated = next(item for item in builder.scenes if item["id"] == target)
    assert updated["required_facts"] == []


def test_narration_simplification_that_keeps_terms_passes_qa(builder, bp, lesson_payload):
    """回归：口播精简必须保留 required_terms / required_numbers，否则产生阻断问题
    导致“修订完成但原版本保持不变”。本测试验证提示所要求的合规改写可通过 QA。"""
    b = builder
    b.configure_renderer_limit(10)
    for scene in b.scenes:
        head = scene["spoken_text"][:10].rstrip("，、；:：")
        terms = "".join(scene.get("required_terms") or [])
        numbers = "".join(scene.get("required_numbers") or [])
        scene["spoken_text"] = f"{head}，掌握{terms}{numbers}。"
    b.rebalance_timeline()
    content = b.to_content()
    from app.schemas.video_script_v4 import SeedanceVideoScriptContentV4

    SeedanceVideoScriptContentV4.model_validate(content)
    issues = validate_video_script_v4(bp, content, lesson_payload, [], max_scene_seconds=10)
    assert not blocking_issues(issues), [item["description"] for item in blocking_issues(issues)]


def test_timeline_editor_prompt_directs_rebalance_for_narration_edit(builder, bp, lesson_payload):
    """回归：NARRATION_EDIT 链中的 timeline_editor 必须在一次重平衡后收尾，
    否则会陷入 vs_inspect_scene 反复读取直到工具轮次耗尽（8 轮上限）。

    不再依赖 per-intent 定制提示；由共享 system prompt 的通用行动准则兜底。"""
    from app.agent.agents.video_script.agents import AGENT_BY_KEY, ensure_video_script_agents
    from app.agent.context import ContextState
    from app.agent.schemas import AgentDecision, ToolCall

    ensure_video_script_agents()

    captured: dict[str, str] = {}

    class StubProvider:
        """捕获 system+prompt，然后按角色返回确定决策（遵循流式 (kind, payload) 协议）。"""

        async def stream_decision(self, system, prompt, schema):
            captured["system"] = system
            captured["prompt"] = prompt
            if "vs_rebalance_timeline" in prompt:
                yield ("decision_ready", AgentDecision(
                    tool_calls=[ToolCall(tool_name="vs_rebalance_timeline", input={})],
                    message="重平衡时间轴",
                ))
            else:
                yield ("decision_ready", AgentDecision(completed=True, output={}, message="done"))

        async def structured(self, system, prompt, schema):
            raise AssertionError("LLM 路径应使用 stream_decision，不应回退 structured")

    runtime = SimpleNamespace(
        provider=StubProvider(),
        emitter=None,
        artifacts=None,
        builder=builder,
        intent_plan=SimpleNamespace(intent="NARRATION_EDIT"),
        selected_section_ids=[],
        selected_scene_ids=[],
        repair_round=0,
        blocking_issues=[],
        token_usage={"tokens": 0, "llm_calls": 0},
        context=ContextState(blueprint=bp.model_dump(), upstream={"lesson_plan": lesson_payload or {}}),
        pipeline_run=None,
        generation_run=None,
        locks=[],
        request_metadata={},
    )
    runtime.tool_context = SimpleNamespace(runtime=runtime, ctx=runtime.context)

    async def _drain_instructions():
        return []

    runtime._drain_instructions = _drain_instructions
    # 模拟 runtime 所需的上下文形状：_call_agent 用到 runtime.context/user_instruction
    runtime.context.user_instruction = "精简目标分镜的口播"

    from app.agent.agents.video_script.runtime import _call_agent

    async def run():
        decision = await _call_agent(runtime, "timeline_editor", AGENT_BY_KEY["timeline_editor"], 0)
        assert decision.tool_calls and decision.tool_calls[0].tool_name == "vs_rebalance_timeline"

    asyncio.run(run())
    # 共享 system prompt 必须包含通用行动准则（替代 per-intent 定制提示）：
    # 读取足够后立即通过 vs_* 编辑工具完成修改，重复只读视为无进展终止。
    system = captured["system"]
    assert "vs_rebalance_timeline" in captured["prompt"]  # 工具 schema 已提供给 agent
    assert "读取到足够信息后必须立即通过 vs_* 编辑工具完成修改" in system
    assert "重复调用只读工具却没有新的修改动作将被视为无进展终止" in system


def test_narration_edit_is_scoped_and_keeps_other_sections(builder, bp, lesson_payload):
    """验收场景：「只压缩第二章口播」不得修改其他章节、事实与视觉设置。"""
    tc = _tool_context(builder, bp.model_dump(), lesson_payload)
    before = builder.to_content()

    async def run():
        # 只重写第二章（core 讲解章节）首个分镜的口播
        target = next(item for item in builder.sections if item["sequence"] == 2)
        scene = next(item for item in builder.scenes if item["section_id"] == target["id"])
        result = await execute_tool("vs_rewrite_spoken_text", tc, {
            "scene_id": scene["id"], "spoken_text": "这一段聚焦核心概念。注意条件、过程和结论之间的关系，并检查结论成立的条件。",
        })
        assert result.ok, result.error

    asyncio.run(run())
    after = builder.to_content()
    other_scenes = [
        scene for scene in after["scenes"]
        if scene["section_id"] != next(item for item in builder.sections if item["sequence"] == 2)["id"]
    ]
    before_other = [
        scene for scene in before["scenes"]
        if scene["section_id"] != next(item for item in before["outline"]["sections"] if item["sequence"] == 2)["id"]
    ]
    # 非目标章节的口播与视觉提示词保持不变
    assert [scene["spoken_text"] for scene in other_scenes] == [scene["spoken_text"] for scene in before_other]
    assert [scene["visual_prompt"] for scene in other_scenes] == [scene["visual_prompt"] for scene in before_other]
    # 事实基准同步（必需术语仍应出现）
    assert builder.validate_content()["ok"]


def test_timeline_rebalance_preserves_fixed_duration_and_constraints(builder, bp, lesson_payload):
    """验收场景：「把两个章节合并并重新分配时间」→ 总时长守恒、每段 4–15 秒。"""
    tc = _tool_context(builder, bp.model_dump(), lesson_payload)

    async def run():
        sections = list(builder.sections)
        merged = await execute_tool("vs_apply_outline_ops", tc, {"operations": [
            {"op": "merge_sections", "section_id": sections[1]["id"],
             "absorbed_section_id": sections[2]["id"]},
        ]})
        assert merged.ok, merged.error
        fixed = builder.scenes[0]["id"]
        rebalanced = await execute_tool("vs_rebalance_timeline", tc, {"durations": {fixed: 6.0}})
        assert rebalanced.ok, rebalanced.error

    asyncio.run(run())
    content = builder.to_content()
    assert builder.validate_content()["ok"]
    scenes = content["scenes"]
    durations = [scene["end_seconds"] - scene["start_seconds"] for scene in scenes]
    assert all(4.0 <= duration <= 15.0 for duration in durations), durations
    assert abs(sum(durations) - content["production_settings"]["target_duration_seconds"]) < 0.01
    # 指定时长保留
    assert abs(durations[0] - 6.0) < 0.01
    assert not blocking_issues(validate_video_script_v4(bp, content, lesson_payload, []))


def test_timeline_rebalance_respects_gemini_ten_second_limit(builder):
    builder.configure_renderer_limit(10)
    # 夹具时长需要足够的分镜容量；超出容量时发布门禁会要求 LLM 先拆镜。
    builder._content["production_settings"]["target_duration_seconds"] = min(  # noqa: SLF001
        builder.target_duration_seconds, len(builder.scenes) * 10,
    )
    builder._content["course_info"]["duration_seconds"] = builder.target_duration_seconds  # noqa: SLF001
    builder.rebalance_timeline()
    durations = [scene["end_seconds"] - scene["start_seconds"] for scene in builder.scenes]
    assert all(4 <= duration <= 10 for duration in durations)


def test_timeline_rebalance_converges_target_when_cap_makes_original_infeasible(builder):
    """回归：渲染器单镜上限使原始目标时长不可达时，目标必须收敛到可达合计，
    不能把残差全部压到末镜（否则出现 SV-75 时长 160 秒这类结构非法草稿）。"""
    builder.configure_renderer_limit(10)
    original_target = builder.target_duration_seconds
    assert original_target > len(builder.scenes) * 10  # 前置：确实不可达
    builder.rebalance_timeline()
    durations = [scene["end_seconds"] - scene["start_seconds"] for scene in builder.scenes]
    assert all(4 <= duration <= 10 for duration in durations), durations
    # 目标时长收敛到可达合计；总时长守恒
    assert abs(sum(durations) - builder.target_duration_seconds) < 0.01
    assert builder.target_duration_seconds <= len(builder.scenes) * 10
    # 结构门禁必须通过
    from app.schemas.video_script_v4 import SeedanceVideoScriptContentV4

    SeedanceVideoScriptContentV4.model_validate(builder.to_content())


def test_recalc_timeline_feasible_case_keeps_original_target(builder):
    """可行场景（默认 15 秒上限）不得收敛目标，保证既有总时长与草稿不变。"""
    original_target = builder.target_duration_seconds
    builder.rebalance_timeline()
    assert builder.target_duration_seconds == original_target
    durations = [scene["end_seconds"] - scene["start_seconds"] for scene in builder.scenes]
    assert all(4 <= duration <= 15 for duration in durations)
    assert abs(sum(durations) - original_target) < 0.01


def test_deliberate_bad_reference_gets_qa_blocking_and_fingerprint(builder, bp, lesson_payload):
    """验收场景：故意制造非法目标引用 → QA 问题、阻断与指纹防空转。"""
    content = builder.to_content()
    content["scenes"][0]["objective_ids"] = ["OBJ-NOPE"]
    issues = validate_video_script_v4(bp, content, lesson_payload, [])
    blocking = blocking_issues(issues)
    assert blocking, "非法目标引用必须产生阻断问题"
    assert any(item["dimension"] == "alignment" for item in blocking)
    assert fingerprint(issues) == fingerprint(issues), "相同问题指纹必须稳定"


def test_resolution_request_is_answer_only():
    async def run():
        decision = await infer_video_script_intent(MockProvider(), "message", "把分辨率调成480")
        assert decision.intent == "VIDEO_GENERATION_SETTINGS_UPDATE"
        assert not decision.mutates_document
        assert decision.rationale == "deterministic-settings-fallback"
        assert decision.resolution_preference == "854x480"

    asyncio.run(run())


@pytest.mark.parametrize("instruction, expected", [
    ("把分辨率调成720", "1280x720"),
    ("设置为 720P", "1280x720"),
    ("改成 1280 × 720", "1280x720"),
    ("把分辨率调成480", "854x480"),
    ("使用 480p", "854x480"),
    ("采用854x480", "854x480"),
])
def test_resolution_aliases_are_normalized_as_pure_settings(instruction, expected):
    async def run():
        decision = await infer_video_script_intent(MockProvider(), "message", instruction)
        assert decision.intent == "VIDEO_GENERATION_SETTINGS_UPDATE"
        assert decision.resolution_requested
        assert decision.resolution_setting_only
        assert decision.resolution_preference == expected
        assert not decision.mutates_document

    asyncio.run(run())


def test_resolution_question_does_not_write_setting():
    async def run():
        decision = await infer_video_script_intent(MockProvider(), "message", "可以把分辨率调成720p吗？")
        assert decision.intent == "VIDEO_GENERATION_SETTINGS_UPDATE"
        assert decision.rationale == "deterministic-settings-fallback"
        assert decision.resolution_preference == "1280x720"
        assert not decision.resolution_setting_only
        assert not decision.mutates_document

    asyncio.run(run())


def test_resolution_and_script_edit_are_two_decision_dimensions():
    async def run():
        decision = await infer_video_script_intent(
            MockProvider(), "message", "把分辨率调成720，并精简第二章口播",
        )
        assert decision.intent == "NARRATION_EDIT"
        assert decision.mutates_document
        assert decision.resolution_preference == "1280x720"
        assert not decision.resolution_setting_only
        assert decision.resolution_error is None

    asyncio.run(run())


def test_resolution_numbers_with_other_units_are_not_treated_as_settings():
    async def run():
        decision = await infer_video_script_intent(MockProvider(), "message", "把口播精简到480字")
        assert decision.intent == "NARRATION_EDIT"
        assert not decision.resolution_requested
        assert decision.resolution_preference is None

    asyncio.run(run())


@pytest.mark.parametrize("instruction", ["改成1080p", "使用 2K", "切换到4k，同时精简口播"])
def test_unsupported_resolution_blocks_the_whole_request(instruction):
    async def run():
        decision = await infer_video_script_intent(MockProvider(), "message", instruction)
        assert decision.intent == "VIDEO_GENERATION_SETTINGS_UPDATE"
        assert not decision.mutates_document
        assert decision.resolution_preference is None
        assert "仅支持" in (decision.resolution_error or "")

    asyncio.run(run())


def test_video_script_runtime_ignores_application_token_limits():
    from app.agent.agents.video_script.runtime import VideoScriptAgentRuntime
    from app.agent.context import ContextState
    from app.agent.core.loop import run_agent_loop
    from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan

    runtime = VideoScriptAgentRuntime(context=ContextState(user_instruction="长上下文" * 100_000))
    runtime.token_usage["tokens"] = 200_000
    called = False

    async def call_agent(*_args):
        nonlocal called
        called = True
        return AgentDecision(completed=True, output={}, summary="已完成")

    async def persist_artifact(*_args):
        return None

    asyncio.run(run_agent_loop(
        runtime,
        PipelinePlan(agents=[AgentSpec(key="budget", role="budget", max_steps=1)]),
        agent_registry={"budget": type("Agent", (), {"allowed_tools": [], "name": "budget"})()},
        call_agent=call_agent,
        persist_artifact=persist_artifact,
    ))

    assert called
    assert runtime.termination_reason != "agent_token_budget_exceeded"
    assert runtime.max_estimated_tokens == 0
    assert runtime.max_context_tokens == 0


def test_compound_resolution_is_committed_only_for_successful_result():
    from app.services.course_task_service import _apply_pending_video_resolution
    from unittest.mock import AsyncMock

    async def run():
        db = SimpleNamespace(flush=AsyncMock())
        course = SimpleNamespace(settings_json={"unrelated": {"keep": True}})
        rejected = SimpleNamespace(pending_video_resolution="854x480", result_status="rejected")
        assert not await _apply_pending_video_resolution(db, course, rejected)
        assert "video_generation" not in course.settings_json

        applied = SimpleNamespace(pending_video_resolution="1280x720", result_status="applied")
        assert await _apply_pending_video_resolution(db, course, applied)
        assert course.settings_json == {
            "unrelated": {"keep": True},
            "video_generation": {"preferred_resolution": "1280x720"},
        }
        assert applied.video_resolution_update.resolution == "1280x720"
        db.flush.assert_awaited_once()

    asyncio.run(run())


def test_intent_fallback_routing():
    async def run():
        provider = MockProvider()
        restructure = await infer_video_script_intent(provider, "message", "不要固定导入和总结，改成问题驱动的三章结构")
        assert restructure.intent == "RESTRUCTURE"
        narration = await infer_video_script_intent(provider, "message", "只压缩第二章的口播")
        assert narration.intent == "NARRATION_EDIT"
        initial = await infer_video_script_intent(provider, "initial", "")
        assert initial.intent == "GENERATE"
        qa = await infer_video_script_intent(provider, "message", "检查一下脚本质量")
        assert qa.intent == "QA_ONLY"
        answer = await infer_video_script_intent(provider, "message", "这个脚本有几个片段")
        assert answer.intent == "ANSWER_ONLY"
        return True

    assert asyncio.run(run())
    assert agent_chain_for_intent("RESTRUCTURE", "message")[-1] == "finalizer"
    assert "outline_architect" in agent_chain_for_intent("RESTRUCTURE", "message")
    assert "script_director" in agent_chain_for_intent("NARRATION_EDIT", "message")
    assert agent_chain_for_intent("QA_ONLY", "message") == ["validation", "answer_finalizer"]


def test_intent_scope_ordinal_unknown_id_and_destructive_confirmation():
    async def run():
        provider = MockProvider()
        scoped = await infer_video_script_intent(
            provider, "message", "把这一章第 2 个分镜口播压缩",
            selected_section_ids=["SEC-02"], mode="narration",
            available_section_ids=["SEC-01", "SEC-02"],
            available_scene_ids=["VS-04", "VS-05", "VS-06"],
        )
        assert scoped.target_section_ids == ["SEC-02"]
        assert scoped.target_scene_ids == ["VS-05"]
        assert scoped.operation == "edit_narration"
        assert "VS-05" in scoped.affected_json_paths[0]

        stale = await infer_video_script_intent(
            provider, "message", "改一下这个分镜", selected_scene_ids=["VS-MISSING"],
            available_section_ids=["SEC-01"], available_scene_ids=["VS-01"],
        )
        assert stale.target_scene_ids == []
        assert stale.requires_confirmation
        assert stale.confidence < 0.65

        destructive = await infer_video_script_intent(
            provider, "message", "合并这两个章节",
            available_section_ids=["SEC-01", "SEC-02"], available_scene_ids=["VS-01"],
        )
        assert destructive.destructive
        assert destructive.requires_confirmation

        preserved = await infer_video_script_intent(
            provider, "message", "压缩口播，画面保持不变",
            available_section_ids=["SEC-01"], available_scene_ids=["VS-01"],
        )
        assert preserved.intent == "NARRATION_EDIT"
        assert "preserve_visual" in preserved.preserve_constraints

    asyncio.run(run())


def test_diff_is_id_stable_and_reports_changes(builder):
    source = builder.to_content()
    assert builder.diff(source)["changed"] is False
    builder.rename_section(builder.sections[0]["id"], "新的章节标题")
    diff = builder.diff(source)
    assert diff["changed"] is True
    assert diff["changed_sections"] == [builder.sections[0]["id"]]
    # 移动只改变 sequence（重排会让两个章节序号都变化），不改变 ID
    builder2 = VideoScriptBuilder(source)
    builder2.move_section(builder2.sections[0]["id"], to_sequence=2)
    diff2 = builder2.diff(source)
    assert diff2["changed_sections"] == sorted([builder2.sections[0]["id"], builder2.sections[1]["id"]])
    assert not diff2["added_sections"] and not diff2["removed_sections"]


def test_locked_whole_file_rejects_all_edits(builder, bp):
    register_video_script_tools()
    locked_runtime = SimpleNamespace(locks=[SimpleNamespace(json_path="$")], source_artifact=None)
    tc = ToolContext(
        ctx=ContextState(blueprint=bp.model_dump()), workspace_root=None,
        generation_run_id="", pipeline_run_id="", provider=None,
        artifacts=None, emitter=None, runtime=locked_runtime, extra={"builder": builder},
    )

    async def run():
        result = await execute_tool("vs_apply_outline_ops", tc, {"operations": [
            {"op": "rename_section", "section_id": builder.sections[0]["id"], "title": "X"},
        ]})
        assert not result.ok
        assert "锁定" in result.error or "锁定" in result.output.get("error", "")
        validate = await execute_tool("vs_validate_draft", tc, {"scope": "all"})
        issues = validate.output["issues"]
        assert any(item["dimension"] == "lock" and item["severity"] == "critical" for item in issues)

    asyncio.run(run())


def test_objective_coverage_is_minor_not_blocking(builder, bp, lesson_payload):
    """回归：目标覆盖缺口只报 minor 提示，不阻断内容编辑（如精简口播）。"""
    content = builder.to_content()
    # 让所有分镜只绑定第一个目标，制造「obj_02/obj_03 未被任何分镜覆盖」缺口（结构仍合法）
    first_objective = bp.objectives[0].id
    for scene in content["scenes"]:
        scene["objective_ids"] = [first_objective]
    issues = validate_video_script_v4(bp, content, lesson_payload, [])
    coverage = [item for item in issues if "未被任何分镜覆盖" in item.get("description", "")]
    assert coverage, "必须仍然报告目标覆盖问题（提示性）"
    assert all(item["severity"] == "minor" for item in coverage)
    assert not blocking_issues(issues), [item["description"] for item in blocking_issues(issues)]


def test_apply_outline_ops_accepts_shorthand_update(builder, bp, lesson_payload):
    """回归：LLM 常用简写 op='update' 更新章节元数据，必须规范化而不是报参数不符合。"""
    tc = _tool_context(builder, bp.model_dump(), lesson_payload)
    section = builder.sections[0]

    async def run():
        result = await execute_tool("vs_apply_outline_ops", tc, {"operations": [
            {"op": "update", "section_id": section["id"], "purpose": "新的章节目的说明"},
        ]})
        assert result.ok, result.error

    asyncio.run(run())
    updated = next(item for item in builder.sections if item["id"] == section["id"])
    assert updated["purpose"] == "新的章节目的说明"


def test_narration_edit_binding_objectives_no_field_scope_violation(builder, bp, lesson_payload):
    """回归：NARRATION_EDIT 轮内修改分镜 objective_ids（如返修目标覆盖）不再被判字段越界，
    发布门禁只保留章节/分镜范围守护。"""
    from app.agent.agents.video_script.runtime import VideoScriptAgentRuntime

    baseline = builder.to_content()
    candidate = copy.deepcopy(baseline)
    # 修改一个分镜的 objective_ids + spoken_text（模拟返修轮行为）
    candidate["scenes"][0]["objective_ids"] = [str(bp.objectives[0].id)]
    candidate["scenes"][0]["spoken_text"] = "精简后的口播内容。"

    runtime = SimpleNamespace(
        trigger_type="message",
        intent_plan=SimpleNamespace(intent="NARRATION_EDIT"),
        baseline_content=baseline,
        selected_section_ids=[],
        selected_scene_ids=[],
        active_intent="NARRATION_EDIT",
    )
    violations = VideoScriptAgentRuntime._scope_violations(runtime, candidate)
    assert violations == [], f"字段绑定不再产生越界：{violations}"


def test_scope_violation_still_guards_explicit_selection(builder, bp, lesson_payload):
    """范围守护仍生效：用户显式选中章节时，越界修改其他章节仍判越界。"""
    from app.agent.agents.video_script.runtime import VideoScriptAgentRuntime

    baseline = builder.to_content()
    candidate = copy.deepcopy(baseline)
    selected = builder.sections[0]["id"]
    other = next(item for item in builder.sections if item["id"] != selected)["id"]
    # 修改未选中章节的分镜口播
    for scene in candidate["scenes"]:
        if scene["section_id"] == other:
            scene["spoken_text"] = "越界修改其他章节的口播。"
            break

    runtime = SimpleNamespace(
        trigger_type="message",
        intent_plan=SimpleNamespace(intent="NARRATION_EDIT"),
        baseline_content=baseline,
        selected_section_ids=[selected],
        selected_scene_ids=[],
        active_intent="NARRATION_EDIT",
    )
    violations = VideoScriptAgentRuntime._scope_violations(runtime, candidate)
    assert "scene_scope_violation" in violations, violations


def test_upgrade_cleans_ppt_dependent_visual_prompt(builder, bp, lesson_payload):
    """回归：V3→V4 升级时，依赖 PPT 的画面提示词必须清洗为真实教学影像描述，
    原生视频模式严禁以 PPT 为主画面。"""
    from app.schemas.video_script_v4 import upgrade_video_script_v4

    v3 = make_seedance_video_script(bp, make_lesson_plan(bp)).model_dump()
    v3["scenes"][0]["visual_prompt"] = "以对应 PPT 为主画面，结合知识点图示展示概念结构。"
    v4 = upgrade_video_script_v4(v3, lesson_payload)
    cleaned = v4.scenes[0].visual_prompt
    assert "ppt" not in cleaned.lower() and "幻灯片" not in cleaned
    assert "真实教学影像" in cleaned


def test_update_scene_ignores_v3_legacy_fields_like_learning_purpose(builder, bp, lesson_payload):
    """回归：LLM 编辑分镜时把 V3 遗留字段（learning_purpose）混入 patch，
    必须被忽略而不是让整批分镜操作失败；受保护字段（id/sequence）仍拒绝。"""
    tc = _tool_context(builder, bp.model_dump(), lesson_payload)
    target = builder.scenes[0]["id"]

    async def run():
        result = await execute_tool("vs_apply_scene_ops", tc, {"operations": [
            {"op": "update", "scene_id": target,
             "spoken_text": "精简后的口播。",
             "learning_purpose": "旧的 V3 字段不应阻塞更新"},
        ]})
        assert result.ok, result.error
        # 受保护字段仍拒绝
        rejected = await execute_tool("vs_apply_scene_ops", tc, {"operations": [
            {"op": "update", "scene_id": target, "id": "VS-999"},
        ]})
        assert not rejected.ok
        assert "不允许修改分镜" in rejected.error

    asyncio.run(run())
    updated = next(item for item in builder.scenes if item["id"] == target)
    assert updated["spoken_text"] == "精简后的口播。"
    assert "learning_purpose" not in updated, "V3 遗留字段不得写入 V4 分镜"
