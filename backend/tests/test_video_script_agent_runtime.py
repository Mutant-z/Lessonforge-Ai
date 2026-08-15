"""视频脚本 Agent 动态工具化流水线单元测试：工具、意图、QA、Builder 不变量。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.agents.video_script.builder import VideoScriptBuilder
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


def test_tools_registered():
    register_video_script_tools()
    names = {item["name"] for item in video_script_tool_schemas()}
    for required in (
        "vs_get_context", "vs_get_locks", "vs_inspect_outline", "vs_inspect_scene",
        "vs_apply_outline_ops", "vs_apply_scene_ops", "vs_rewrite_spoken_text",
        "vs_update_visual_direction", "vs_update_continuity", "vs_rebalance_timeline",
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


def test_deliberate_bad_reference_gets_qa_blocking_and_fingerprint(builder, bp, lesson_payload):
    """验收场景：故意制造非法目标引用 → QA 问题、阻断与指纹防空转。"""
    content = builder.to_content()
    content["scenes"][0]["objective_ids"] = ["OBJ-NOPE"]
    issues = validate_video_script_v4(bp, content, lesson_payload, [])
    blocking = blocking_issues(issues)
    assert blocking, "非法目标引用必须产生阻断问题"
    assert any(item["dimension"] == "alignment" for item in blocking)
    assert fingerprint(issues) == fingerprint(issues), "相同问题指纹必须稳定"


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
    assert agent_chain_for_intent("QA_ONLY", "message") == ["production_qa", "finalizer"]


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
