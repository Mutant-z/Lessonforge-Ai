"""教师逐字稿 V2 数据契约 / Builder / 意图 / QA / 运行时测试。"""

from __future__ import annotations

import copy

import pytest

from app.agent.agents.verbatim.builder import (
    VerbatimBuilder,
    build_initial_builder,
    upgrade_builder,
)
from app.agent.agents.verbatim.intents import (
    VerbatimIntentDecision,
    agent_chain_for_intent,
    infer_verbatim_intent,
)
from app.agent.agents.verbatim.qa import (
    blocking_issues,
    fingerprint,
    validate_verbatim_v2,
)
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.verbatim_v2 import (
    VERBATIM_V2,
    make_seedance_verbatim_v2,
    upgrade_verbatim_v2,
    verbatim_v2_to_markdown,
)

BP = {
    "course_identity": {"title": "浮力", "subject": "物理", "grade_level": "八年级",
                        "audience": "初二", "duration_minutes": 10, "scenario": "课堂讲解"},
    "learning_analysis": {"prior_knowledge": [], "learner_characteristics": [], "likely_misconceptions": []},
    "objectives": [
        {"id": "OBJ-01", "domain": "knowledge", "behavior": "解释浮力", "condition": "结合情境",
         "criterion": "说明依据", "knowledge_point_ids": ["KP-01"], "activity_ids": ["S1"], "exercise_ids": []},
    ],
    "knowledge_points": [{"id": "KP-01", "name": "浮力"}],
    "key_points": ["浮力产生条件"], "difficulty_points": ["原理应用"],
    "teaching_strategy": ["情境导入"],
    "timeline": [
        {"segment_id": "S1", "name": "导入", "start_minute": 0, "end_minute": 10,
         "purpose": "p", "teacher_action": "t", "learner_action": "l", "evidence_of_learning": "e"},
    ],
    "assessment_plan": [], "terminology": {}, "source_refs": [],
}

SCRIPT = {
    "schema_version": "3.0",
    "course_info": {"course_title": "浮力", "subject": "物理", "grade_level": "八年级",
                    "audience": "初二", "duration_seconds": 12},
    "production_settings": {"mode": "seedance_native", "aspect_ratio": "16:9",
                            "target_duration_seconds": 12, "target_clip_seconds": 12,
                            "min_clip_seconds": 8, "max_clip_seconds": 15},
    "scenes": [
        {"id": "S-01", "sequence": 1, "title": "导入", "pedagogical_role": "导入", "lesson_stage_id": "S1",
         "objective_ids": ["OBJ-01"], "knowledge_point_ids": ["KP-01"], "start_seconds": 0, "end_seconds": 6,
         "continuity_group": "cg1", "visual_prompt": "教室", "spoken_text": "同学们，今天我们一起研究浮力产生条件。",
         "required_terms": ["浮力"], "required_numbers": [], "required_facts": ["浮力产生条件"],
         "voice_direction": "自然、清晰", "production_notes": ["提问：什么是浮力？"]},
        {"id": "S-02", "sequence": 2, "title": "探究", "pedagogical_role": "概念讲解", "lesson_stage_id": "S1",
         "objective_ids": ["OBJ-01"], "knowledge_point_ids": ["KP-01"], "start_seconds": 6, "end_seconds": 12,
         "continuity_group": "cg1", "visual_prompt": "实验", "spoken_text": "用手按压物体，验证浮力产生条件。",
         "required_terms": ["浮力"], "required_numbers": [], "required_facts": ["浮力产生条件"],
         "voice_direction": "自然、清晰", "production_notes": ["互动：学生尝试按压。"]},
    ],
}


@pytest.fixture
def bp() -> CourseBlueprintSchema:
    return CourseBlueprintSchema.model_validate(BP)


@pytest.fixture
def v2_data(bp) -> dict:
    return make_seedance_verbatim_v2(bp, SCRIPT).model_dump()


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


def test_make_seedance_verbatim_v2(bp, v2_data):
    assert v2_data["schema_version"] == "2.0"
    assert len(v2_data["sections"]) == 2
    first = v2_data["sections"][0]
    assert first["scene_id"] == "S-01"
    assert first["start_seconds"] == 0
    assert first["word_count"] == len(first["required_text"].strip())
    assert first["estimated_duration_seconds"] >= 0
    assert v2_data["course_info"]["duration_seconds"] == 12.0


def test_upgrade_verbatim_v2_from_v1(bp):
    v1 = {
        "sections": [
            {"id": "VB-01", "scene_id": "S-01", "slide_ids": [], "time_range": "00:00—00:06",
             "pedagogical_action": "hook", "required_text": "同学们，今天学习浮力。",
             "optional_text": "", "key_emphasis": ["浮力"], "word_count": 12,
             "estimated_duration_seconds": 3.0, "interaction": ""},
        ],
    }
    v2 = upgrade_verbatim_v2(v1, SCRIPT)
    assert v2.schema_version == "2.0"
    assert v2.sections[0].scene_id == "S-01"
    assert abs(v2.sections[0].start_seconds - 0) < 0.01
    assert abs(v2.sections[0].end_seconds - 6) < 0.01
    assert v2.sections[0].word_count == len("同学们，今天学习浮力。")


def test_upgrade_verbatim_v2_normalizes_legacy_display_ids_and_rate():
    """历史工作台 V1 使用 seg_01/scene_01 与文字语速，必须能进入 V2。"""
    legacy = {
        "speaking_rate": "standard",
        "course_info": {"course_title": "浮力", "duration_seconds": 120},
        "sections": [{
            "id": "seg_01",
            "scene_id": "scene_01",
            "time_range": "00:00-02:00",
            "required_text": "同学们好，今天我们研究浮力。",
            "optional_text": "",
            "key_emphasis": ["浮力"],
            "interaction": "",
        }],
    }
    v2 = upgrade_verbatim_v2(legacy)
    assert v2.sections[0].id == "VB-01"
    assert v2.sections[0].scene_id == "scene_01"
    assert v2.speaking_rate_cps == 4.0
    assert v2.sections[0].start_seconds == 0
    assert v2.sections[0].end_seconds == 120


def test_verbatim_v2_to_markdown(v2_data):
    md = verbatim_v2_to_markdown(v2_data)
    assert "教师逐字稿 V2" in md
    assert "VB-01" in md
    assert "00:00" in md


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def test_builder_update_course_title_preserves_sections(v2_data):
    builder = VerbatimBuilder(v2_data)
    original_sections = copy.deepcopy(builder.to_content()["sections"])
    builder.update_course_title("阿基米德原理与浮力产生的原因")
    assert builder.to_content()["course_info"]["course_title"] == "阿基米德原理与浮力产生的原因"
    assert builder.to_content()["sections"] == original_sections


def test_builder_update_required_text_recomputes(v2_data):
    builder = VerbatimBuilder(v2_data)
    section = builder.update_required_text("VB-01", "同学们，请记住浮力的方向是竖直向上的。")
    assert section["word_count"] == len("同学们，请记住浮力的方向是竖直向上的。")
    assert section["estimated_duration_seconds"] > 0
    builder.bump_revision()
    assert builder.revision == 1


def test_builder_rebalance_timing(v2_data):
    builder = VerbatimBuilder(v2_data)
    result = builder.rebalance_timing()
    assert "speaking_rate_cps" in result
    for section in builder.sections:
        duration = section["end_seconds"] - section["start_seconds"]
        assert section["pause_seconds"] <= duration


def test_builder_set_speaking_rate(v2_data):
    builder = VerbatimBuilder(v2_data)
    builder.set_speaking_rate(3.0)
    assert builder.speaking_rate_cps == 3.0
    for section in builder.sections:
        assert section["estimated_duration_seconds"] > 0


def test_builder_add_delete_section(v2_data):
    builder = VerbatimBuilder(v2_data)
    added = builder.add_section("VB-03", "S-NEW-03", "请同学们总结一下本课收获。")
    assert added["id"] == "VB-03"
    assert builder.count_sections() == 3
    deleted = builder.delete_section("VB-03")
    assert deleted["id"] == "VB-03"
    assert builder.count_sections() == 2
    assert abs(builder.total_duration() - 12.0) < 0.01


def test_builder_validate_content(v2_data):
    builder = VerbatimBuilder(v2_data)
    assert builder.validate_content()["ok"] is True
    bad = VerbatimBuilder(v2_data)
    bad.sections[0]["scene_id"] = bad.sections[1]["scene_id"]  # 场景重复
    assert bad.validate_content()["ok"] is False


# ---------------------------------------------------------------------------
# QA 门禁
# ---------------------------------------------------------------------------


def test_qa_fresh_v2_passes(bp, v2_data):
    assert not blocking_issues(validate_verbatim_v2(bp, v2_data, SCRIPT))


def test_qa_rejects_lost_fact(bp, v2_data):
    data = copy.deepcopy(v2_data)
    data["sections"][0]["required_text"] = "同学们，我们开始上课。"  # 丢掉"浮力"
    data["sections"][0]["key_emphasis"] = []
    issues = validate_verbatim_v2(bp, data, SCRIPT)
    assert any(item["severity"] == "critical" and item["dimension"] == "fact" for item in issues)


def test_qa_rejects_timing_overrun(bp, v2_data):
    data = copy.deepcopy(v2_data)
    data["sections"][0]["required_text"] = "浮力" * 60  # 120 字 / 4 = 30s > 6s
    issues = validate_verbatim_v2(bp, data, SCRIPT)
    assert any(item["severity"] == "major" and item["dimension"] == "timing" for item in issues)


def test_qa_rejects_bad_scene(bp, v2_data):
    data = copy.deepcopy(v2_data)
    data["sections"][0]["scene_id"] = "S-NOT-EXIST"
    issues = validate_verbatim_v2(bp, data, SCRIPT)
    assert any(item["dimension"] == "alignment" for item in issues)


def test_qa_fingerprint_stable(bp, v2_data):
    data = copy.deepcopy(v2_data)
    data["sections"][0]["required_text"] = "同学们，我们开始上课。"
    data["sections"][0]["key_emphasis"] = []
    issues1 = validate_verbatim_v2(bp, data, SCRIPT)
    issues2 = validate_verbatim_v2(bp, copy.deepcopy(data), SCRIPT)
    assert fingerprint(issues1) == fingerprint(issues2)


# ---------------------------------------------------------------------------
# 意图识别
# ---------------------------------------------------------------------------


class _MockIntentProvider:
    __class__ = property(lambda self: type("MockProvider", (), {}))


@pytest.mark.asyncio
async def test_intent_initial_is_generate():
    plan = await infer_verbatim_intent(None, "initial", "")
    assert plan.intent == "GENERATE"
    assert plan.mutates_document


@pytest.mark.asyncio
async def test_intent_timing_by_keyword():
    plan = await infer_verbatim_intent(_MockIntentProvider(), "message", "语速太快，停顿重算一下")
    assert plan.intent == "TIMING_ADJUST"
    assert plan.mutates_document


@pytest.mark.asyncio
async def test_intent_section_by_keyword():
    plan = await infer_verbatim_intent(_MockIntentProvider(), "message", "把第二段口播改得更口语化")
    assert plan.intent == "SECTION_EDIT"
    assert plan.mutates_document


@pytest.mark.asyncio
async def test_intent_paragraph_formatting_by_keyword():
    plan = await infer_verbatim_intent(
        _MockIntentProvider(), "message", "润色一下这部分内容，进行分段，不要堆成一行"
    )
    assert plan.intent == "SECTION_EDIT"
    assert plan.mutates_document


@pytest.mark.asyncio
async def test_intent_course_title_is_metadata_only():
    plan = await infer_verbatim_intent(_MockIntentProvider(), "message", "课程名称修改为阿基米德原理与浮力产生的原因")
    assert plan.intent == "COURSE_METADATA_UPDATE"
    assert plan.mutation_domain == "course_metadata"
    assert plan.course_title == "阿基米德原理与浮力产生的原因"
    assert plan.mutates_document


@pytest.mark.asyncio
async def test_intent_course_title_without_value_clarifies():
    plan = await infer_verbatim_intent(_MockIntentProvider(), "message", "课程名称进行修改")
    assert plan.intent == "CLARIFICATION_REQUIRED"
    assert not plan.mutates_document


@pytest.mark.asyncio
async def test_pending_course_title_answer_is_resolved():
    plan = await infer_verbatim_intent(
        _MockIntentProvider(), "message", "阿基米德原理与浮力产生的原因",
        pending_clarification={"kind": "course_title", "status": "pending"},
    )
    assert plan.intent == "COURSE_METADATA_UPDATE"
    assert plan.course_title == "阿基米德原理与浮力产生的原因"


@pytest.mark.asyncio
async def test_unknown_instruction_fails_closed():
    plan = await infer_verbatim_intent(_MockIntentProvider(), "message", "随便处理一下")
    assert plan.intent == "CLARIFICATION_REQUIRED"
    assert not plan.mutates_document


@pytest.mark.asyncio
async def test_intent_destructive_requires_confirmation():
    plan = await infer_verbatim_intent(_MockIntentProvider(), "message", "删除章节 VB-01")
    assert plan.destructive
    assert plan.requires_confirmation


@pytest.mark.asyncio
async def test_intent_answer_only():
    plan = await infer_verbatim_intent(_MockIntentProvider(), "message", "逐字稿是什么？")
    assert plan.intent == "QA_ONLY"
    assert not plan.mutates_document


@pytest.mark.asyncio
async def test_intent_chain_mapping():
    assert agent_chain_for_intent("QA_ONLY", "message") == ["verbatim_qa", "finalizer"]
    assert agent_chain_for_intent("TIMING_ADJUST", "message")[0] == "intent_planner"
    assert "timing_engine" in agent_chain_for_intent("TIMING_ADJUST", "message")


# ---------------------------------------------------------------------------
# 运行时（Mock Provider 全链）
# ---------------------------------------------------------------------------

_runtime_course_cache: dict[str, str] = {}


@pytest.fixture
async def _runtime_course(client, auth_headers):
    """共享课程（模块级缓存）：只建一次。"""
    from agent_pipeline_helpers import ready_course

    if not _runtime_course_cache:
        _runtime_course_cache["course_id"] = await ready_course(client, auth_headers, title="逐字稿运行时课程")
    return _runtime_course_cache["course_id"]


async def _make_runtime(course_id, *, instruction="", trigger="message", use_source=True):
    """基于共享课程构建一个独立 VerbatimAgentRuntime。"""
    from pathlib import Path
    from uuid import uuid4

    from sqlalchemy import select

    from app.agent.agents.verbatim.runtime import VerbatimAgentRuntime
    from app.agent.artifacts import PipelineArtifactManager
    from app.agent.context import ContextState
    from app.agent.events import PipelineEventEmitter
    from app.agent.registry import ToolContext
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.models.entities import Artifact, CourseBlueprint, CourseProject, CourseTask, GenerationRun, PipelineRun
    from app.services.course_task_service import _profile_provider

    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id, CourseTask.task_type == "verbatim",
        ))
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        profile, provider, config = await _profile_provider(db, course, task)
        source = None
        if use_source:
            source = await db.scalar(select(Artifact).where(
                Artifact.course_id == course_id, Artifact.artifact_type == "verbatim",
            ).order_by(Artifact.version.desc()))
        video_script = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id, Artifact.artifact_type == "video_script",
        ).order_by(Artifact.version.desc()))
        knowledge_context = {}
        if video_script:
            knowledge_context = {"sibling_artifacts": {"video_script": {"content": video_script.content_json}}}
        gen_run = GenerationRun(course_id=course_id, course_task_id=task.id, thread_id=str(uuid4()),
                                run_type="task", trigger_type=trigger, status="running")
        db.add(gen_run)
        await db.flush()
        pr = PipelineRun(generation_run_id=gen_run.id, status="running", pipeline_type="verbatim_agent_pipeline")
        db.add(pr)
        await db.commit()
        await db.refresh(gen_run)
        await db.refresh(pr)
    workspace = Path(get_settings().storage_root) / "generated" / course_id / "verbatim_pipeline" / gen_run.id
    workspace.mkdir(parents=True, exist_ok=True)
    for sub in ("analysis", "content", "plans", "assets", "drafts", "qa", "output"):
        (workspace / sub).mkdir(exist_ok=True)
    context = ContextState(
        blueprint=blueprint.content_json, profile=profile,
        source_artifact=source, user_instruction=instruction, locks=[], upstream={},
    )
    artifacts = PipelineArtifactManager(pr, workspace)
    emitter = await PipelineEventEmitter.for_run(gen_run, pr, task_type="verbatim")
    runtime = VerbatimAgentRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=gen_run, pipeline_run=pr,
        profile=profile, provider=provider, config=config, knowledge_context=knowledge_context,
        source_versions={}, locks=[], source_artifact=source, user_message=None,
        trigger_type=trigger, context=context, artifacts=artifacts, emitter=emitter,
        workspace_root=workspace, request_metadata={},
    )
    runtime.tool_context = ToolContext(
        ctx=context, workspace_root=workspace, course=course, task=task,
        generation_run_id=gen_run.id, pipeline_run_id=pr.id, provider=provider,
        artifacts=artifacts, emitter=emitter, runtime=runtime,
    )
    return runtime


def test_verbatim_qa_treats_model_repairable_feedback_as_non_blocking(v2_data):
    """局部润色的事实/节奏反馈应回馈模型，而不是拒绝发布整份合法候选稿。"""
    data = copy.deepcopy(v2_data)
    data["sections"][0]["required_text"] = "同学们，今天我们开始探究。"
    issues = validate_verbatim_v2(BP, data, SCRIPT)
    assert any(item["dimension"] == "fact" for item in issues)
    assert not blocking_issues(issues)


@pytest.mark.asyncio
async def test_runtime_initial_publishes_v2(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="", trigger="initial", use_source=False)
    await runtime.run()
    assert runtime.result_status == "applied"
    assert runtime.publishable
    assert runtime.max_estimated_tokens == 0
    assert runtime.max_context_tokens == 0
    assert runtime.draft_content["schema_version"] == "2.0"
    assert runtime.draft_markdown


@pytest.mark.asyncio
async def test_runtime_timing_adjust_publishes(client, auth_headers, _runtime_course):
    # 提速（5 字/秒）：口播变短必然贴合段落时长，QA 通过 → applied。
    runtime = await _make_runtime(_runtime_course, instruction="把语速改成 5 字/秒")
    await runtime.run()
    assert runtime.result_status == "applied"
    assert runtime.publishable
    assert abs(float(runtime.draft_content["speaking_rate_cps"]) - 5.0) < 0.01


@pytest.mark.asyncio
async def test_runtime_no_change_when_identical(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="嗯")
    await runtime.run()
    assert runtime.result_status in {"no_change", "applied"}


@pytest.mark.asyncio
async def test_runtime_rejects_paragraph_completion_without_line_break(
    client, auth_headers, _runtime_course,
):
    runtime = await _make_runtime(
        _runtime_course,
        instruction="润色一下这部分内容，进行分段，现在的内容全部堆成一行了",
    )
    await runtime._prepare()
    runtime.selected_section_ids = ["VB-01"]
    from app.agent.schemas import ToolResult
    await runtime.record_tool_mutation(
        "verbatim_director", None, ToolResult(output={"affected_section_ids": ["VB-01"]})
    )
    assert runtime.affected_section_ids == ["VB-01"]
    assert runtime._paragraph_format_completion_issue()
    runtime.builder.sections[0]["required_text"] += "\n\n这是新增的可见段落。"
    assert runtime._paragraph_format_completion_issue() is None


@pytest.mark.asyncio
async def test_runtime_answer_only_does_not_publish(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="逐字稿是什么？")
    await runtime.run()
    assert runtime.result_status == "no_change"
    assert not runtime.publishable


@pytest.mark.asyncio
async def test_runtime_destructive_requires_confirmation(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="删除章节 VB-01")
    await runtime.run()
    assert runtime.result_status == "needs_confirmation"
    assert not runtime.publishable
