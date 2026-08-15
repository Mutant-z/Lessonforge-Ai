"""学习任务单 V3 确定性门禁 / Builder / 意图 / 工具 / 运行时测试。"""

from __future__ import annotations

import copy

import pytest

from app.agent.agents.task_sheet.builder import (
    TaskSheetBuilder,
    build_initial_builder,
    upgrade_builder,
)
from app.agent.agents.task_sheet.intents import (
    TaskSheetIntentPlan,
    agent_chain_for_intent,
    infer_task_sheet_intent,
)
from app.agent.agents.task_sheet.qa import (
    blocking_issues,
    fingerprint,
    validate_task_sheet_v3,
)
from app.agents.generators import make_task_sheet
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.task_sheet import make_task_sheet_v3

BP = {
    "course_identity": {"title": "浮力", "subject": "物理", "grade_level": "八年级",
                        "audience": "初二", "duration_minutes": 10, "scenario": "课堂讲解"},
    "learning_analysis": {"prior_knowledge": [], "learner_characteristics": [], "likely_misconceptions": []},
    "objectives": [
        {"id": "OBJ-01", "domain": "knowledge", "behavior": "解释浮力", "condition": "结合情境",
         "criterion": "说明依据", "knowledge_point_ids": ["KP-01"], "activity_ids": ["S1"], "exercise_ids": []},
        {"id": "OBJ-02", "domain": "skill", "behavior": "应用原理", "condition": "给定数据",
         "criterion": "结果正确", "knowledge_point_ids": ["KP-01"], "activity_ids": ["S2"], "exercise_ids": []},
    ],
    "knowledge_points": [{"id": "KP-01", "name": "浮力"}],
    "key_points": ["浮力产生条件"], "difficulty_points": ["原理应用"],
    "teaching_strategy": ["情境导入"],
    "timeline": [
        {"segment_id": "S1", "name": "导入", "start_minute": 0, "end_minute": 3,
         "purpose": "p", "teacher_action": "t", "learner_action": "l", "evidence_of_learning": "e"},
        {"segment_id": "S2", "name": "探究", "start_minute": 3, "end_minute": 10,
         "purpose": "p", "teacher_action": "t", "learner_action": "l", "evidence_of_learning": "e"},
    ],
    "assessment_plan": [{"objective_id": "OBJ-01", "method": "m", "evidence": "e", "criterion": "c"}],
    "terminology": {}, "source_refs": [],
}


@pytest.fixture
def bp() -> CourseBlueprintSchema:
    return CourseBlueprintSchema.model_validate(BP)


@pytest.fixture
def v3_data(bp) -> dict:
    return make_task_sheet_v3(bp).model_dump()


# ---------------------------------------------------------------------------
# QA 门禁
# ---------------------------------------------------------------------------


def test_qa_fresh_v3_passes(bp, v3_data):
    assert not blocking_issues(validate_task_sheet_v3(bp, v3_data))


def test_qa_rejects_bad_references(bp, v3_data):
    data = copy.deepcopy(v3_data)
    data["objective_catalog"][0]["id"] = "OBJ-NOT-IN-BLUEPRINT"
    issues = validate_task_sheet_v3(bp, data)
    assert any(item["severity"] == "critical" for item in issues)


def test_qa_rejects_uncovered_objective(bp, v3_data):
    data = copy.deepcopy(v3_data)
    for section in data["sections"]:
        for block in section["blocks"]:
            if block.get("kind") == "learning_task":
                block["objective_ids"] = ["OBJ-01"]
    issues = validate_task_sheet_v3(bp, data)
    assert any("OBJ-02" in item["description"] for item in issues)


def test_qa_catalog_with_non_blueprint_objective_passes_when_covered(bp, v3_data):
    """目录含蓝图外目标且被学习任务覆盖 → 无阻断问题（教师细化指令合法）。"""
    data = copy.deepcopy(v3_data)
    data["objective_catalog"].append({
        "id": "obj_04", "statement": "分析浮力与深度的关系", "success_criterion": "能辨析",
    })
    for section in data["sections"]:
        for block in section.get("blocks", []):
            if block.get("kind") == "learning_task":
                block["objective_ids"] = [*block.get("objective_ids", []), "obj_04"]
    issues = validate_task_sheet_v3(bp, data)
    assert not blocking_issues(issues)


def test_qa_catalog_non_blueprint_objective_uncovered_flagged(bp, v3_data):
    """目录含蓝图外目标但未被任何任务覆盖 → 结构底线拦截（防孤儿）。"""
    data = copy.deepcopy(v3_data)
    data["objective_catalog"].append({
        "id": "obj_04", "statement": "分析浮力与深度的关系", "success_criterion": "能辨析",
    })
    issues = validate_task_sheet_v3(bp, data)
    assert blocking_issues(issues)
    assert any("obj_04" in item["description"] and item["severity"] == "critical" for item in blocking_issues(issues))


def test_alignment_flags_orphan_non_blueprint_objective(bp, v3_data):
    """_alignment_issues_v3 直接调用：目录中蓝图外目标未被覆盖 → coverage 问题。"""
    from app.agent.agents.task_sheet.qa import _alignment_issues_v3

    data = copy.deepcopy(v3_data)
    data["objective_catalog"].append({
        "id": "obj_04", "statement": "分析浮力与深度的关系", "success_criterion": "能辨析",
    })
    issues = _alignment_issues_v3(bp, data)
    assert any(item["dimension"] == "coverage" and "obj_04" in item["description"] for item in issues)


def test_qa_rejects_teacher_content(bp, v3_data):
    data = copy.deepcopy(v3_data)
    data["sections"][0]["blocks"][0]["text"] = "本题参考答案：略"
    issues = validate_task_sheet_v3(bp, data)
    assert any(item["dimension"] == "boundary" for item in issues)


def test_qa_locked_whole_file(bp, v3_data):
    issues = validate_task_sheet_v3(bp, v3_data, None, ["$"])
    assert any(item["dimension"] == "lock" and item["severity"] == "critical" for item in issues)


def test_qa_fingerprint_stable(bp, v3_data):
    data = copy.deepcopy(v3_data)
    data["objective_catalog"][0]["id"] = "OBJ-NOT-IN-BLUEPRINT"
    issues_a = validate_task_sheet_v3(bp, data)
    issues_b = validate_task_sheet_v3(bp, copy.deepcopy(data))
    assert fingerprint(issues_a) == fingerprint(issues_b)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def test_builder_crud(bp, v3_data):
    builder = TaskSheetBuilder(v3_data)
    original_count = builder.count_sections()
    builder.add_section("SEC-NEW", "新章节", parent_id="", index=0)
    builder.move_section("SEC-NEW", target_parent_id="SEC-TASKS")
    assert builder.find_section("SEC-NEW")["parent_id"] == "SEC-TASKS"
    builder.rename_section("SEC-NEW", "改名")
    builder.update_section_metadata("SEC-NEW", purpose="新的目的", objective_ids=["OBJ-01"])
    builder.add_block("SEC-NEW", {"kind": "text", "id": "B-NEW", "text": "内容"})
    builder.update_block("SEC-NEW", "B-NEW", {"text": "新内容"})
    assert builder.find_section("SEC-NEW")["blocks"][0]["text"] == "新内容"
    builder.move_block("SEC-NEW", "B-NEW", "SEC-HOOK")
    builder.delete_block("SEC-HOOK", "B-NEW")
    builder.delete_section("SEC-NEW")
    assert builder.count_sections() == original_count
    assert builder.find_section("SEC-NEW") is None


def test_builder_cycle_guard(bp, v3_data):
    builder = TaskSheetBuilder(v3_data)
    builder.add_section("SEC-PARENT", "父", parent_id="")
    builder.add_section("SEC-CHILD", "子", parent_id="SEC-PARENT")
    with pytest.raises(ValueError):
        builder.move_section("SEC-PARENT", target_parent_id="SEC-CHILD")


def test_builder_depth_limit(bp, v3_data):
    builder = TaskSheetBuilder(v3_data)
    builder.add_section("SEC-L1", "L1", parent_id="")
    builder.add_section("SEC-L2", "L2", parent_id="SEC-L1")
    builder.add_section("SEC-L3", "L3", parent_id="SEC-L2")
    with pytest.raises(ValueError):
        builder.add_section("SEC-L4", "L4", parent_id="SEC-L3")


def test_builder_delete_moves_blocks(bp, v3_data):
    builder = TaskSheetBuilder(v3_data)
    blocks_before = len(builder.find_section("SEC-HOOK")["blocks"])
    deleted = builder.delete_section("SEC-HOOK")
    assert builder.find_section("SEC-HOOK") is None
    assert len(deleted["blocks"]) == blocks_before


def test_builder_upgrade_from_v2(bp):
    v2 = make_task_sheet(bp)
    builder = upgrade_builder(v2.model_dump(), BP)
    assert builder.to_content()["schema_version"] == "3.0"
    assert len(builder.objective_catalog) == len(v2.learning_objectives)


def test_builder_initial(bp):
    builder = build_initial_builder(BP)
    assert builder.count_sections() >= 5
    assert builder.validate_content()["ok"] is True


# ---------------------------------------------------------------------------
# 意图识别
# ---------------------------------------------------------------------------


class _MockIntentProvider:
    __class__ = property(lambda self: type("MockProvider", (), {}))


@pytest.mark.asyncio
async def test_intent_initial_is_generate():
    plan = await infer_task_sheet_intent(None, "initial", "")
    assert plan.intent == "GENERATE"
    assert plan.mutates_document


@pytest.mark.asyncio
async def test_intent_outline_restructure_by_keyword():
    plan = await infer_task_sheet_intent(_MockIntentProvider(), "message", "请重组目录，把任务链移到前面")
    assert plan.intent == "STRUCTURE_EDIT"
    assert plan.structural


@pytest.mark.asyncio
async def test_intent_answer_only():
    plan = await infer_task_sheet_intent(_MockIntentProvider(), "message", "任务单是什么？")
    assert plan.intent == "QA_ONLY"
    assert not plan.mutates_document


@pytest.mark.asyncio
async def test_intent_chain_mapping():
    assert agent_chain_for_intent("QA_ONLY", "message") == ["finalizer"]
    assert agent_chain_for_intent("STRUCTURE_EDIT", "message")[0] == "intent_planner"
    # QA 门禁已移除：普通修改链不再包含 task_sheet_qa
    assert "task_sheet_qa" not in agent_chain_for_intent("TASK_EDIT", "message")


# ---------------------------------------------------------------------------
# 运行时（Mock Provider 全链，DB 行 + 事件发射）
# ---------------------------------------------------------------------------

_runtime_course_cache: dict[str, str] = {}


@pytest.fixture
async def _runtime_course(client, auth_headers):
    """共享课程（模块级缓存）：只建一次，避免多次 ready_course 的后台任务相互干扰。"""
    from agent_pipeline_helpers import ready_course

    if not _runtime_course_cache:
        _runtime_course_cache["course_id"] = await ready_course(client, auth_headers, title="任务单运行时课程")
    return _runtime_course_cache["course_id"]


async def _make_runtime(course_id, *, instruction="", trigger="message", corrupt=None):
    from pathlib import Path

    from sqlalchemy import select

    from app.agent.agents.task_sheet.runtime import TaskSheetAgentRuntime
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
            CourseTask.course_id == course_id, CourseTask.task_type == "task_sheet",
        ))
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        profile, provider, config = await _profile_provider(db, course, task)
        artifact = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id, Artifact.artifact_type == "task_sheet",
        ).order_by(Artifact.version.desc()))
        source_content = dict(artifact.content_json)
        if corrupt:
            corrupt(source_content)
        artifact.content_json = source_content
        await db.commit()
        await db.refresh(artifact)
        gen_run = GenerationRun(course_id=course_id, course_task_id=task.id, thread_id=f"ts-{trigger}-{id(artifact)}",
                                run_type="task", trigger_type=trigger, status="running")
        db.add(gen_run)
        await db.flush()
        pr = PipelineRun(generation_run_id=gen_run.id, status="running", pipeline_type="task_sheet_agent_pipeline")
        db.add(pr)
        await db.commit()
        await db.refresh(gen_run)
        await db.refresh(pr)
    workspace = Path(get_settings().storage_root) / "generated" / course_id / "task_sheet_pipeline" / gen_run.id
    workspace.mkdir(parents=True, exist_ok=True)
    for sub in ("analysis", "content", "plans", "assets", "drafts", "qa", "output"):
        (workspace / sub).mkdir(exist_ok=True)
    context = ContextState(
        blueprint=blueprint.content_json, profile=profile,
        source_artifact=artifact, user_instruction=instruction, locks=[], upstream={},
    )
    artifacts = PipelineArtifactManager(pr, workspace)
    emitter = await PipelineEventEmitter.for_run(gen_run, pr, task_type="task_sheet")
    runtime = TaskSheetAgentRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=gen_run, pipeline_run=pr,
        profile=profile, provider=provider, config=config, knowledge_context={},
        source_versions={}, locks=[], source_artifact=artifact, user_message=None,
        trigger_type=trigger, context=context, artifacts=artifacts, emitter=emitter,
        workspace_root=workspace, request_metadata={},
    )
    runtime.tool_context = ToolContext(
        ctx=context, workspace_root=workspace, course=course, task=task,
        generation_run_id=gen_run.id, pipeline_run_id=pr.id, provider=provider,
        artifacts=artifacts, emitter=emitter, runtime=runtime,
    )
    return runtime


@pytest.mark.asyncio
async def test_runtime_answer_only_does_not_publish(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="任务单是什么？")
    await runtime.run()
    assert runtime.result_status == "no_change"
    assert not runtime.publishable


@pytest.mark.asyncio
async def test_runtime_modify_publishes_v3(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="新增一个复习巩固章节")
    await runtime.run()
    assert runtime.result_status == "applied"
    assert runtime.publishable
    assert runtime.draft_content["schema_version"] == "3.0"
    assert runtime.draft_markdown


@pytest.mark.asyncio
async def test_runtime_no_change_when_identical(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="嗯")
    await runtime.run()
    assert runtime.result_status in {"no_change", "applied"}


@pytest.mark.asyncio
async def test_runtime_no_qa_gate_when_timing_invalid(client, auth_headers, _runtime_course):
    # QA 门禁已移除：任务用时超过课程时长（结构仍合法）不再阻断发布。
    # 结构安全校验（TaskSheetContentV3）仍生效；用时超长只违反旧的 timing 规则、
    # 不违反结构 → 直接发布（applied 或 Mock 未修改时 no_change），不再是 rejected。
    def corrupt(source):
        if source.get("schema_version") != "3.0":
            from app.schemas.task_sheet import task_sheet_to_v3
            upgraded = task_sheet_to_v3(source).model_dump()
            source.clear()
            source.update(upgraded)
        for section in source["sections"]:
            for block in section["blocks"]:
                if block.get("kind") == "learning_task":
                    block["estimated_minutes"] = 9999.0
        return source

    runtime = await _make_runtime(_runtime_course, instruction="调整任务用时", corrupt=corrupt)
    await runtime.run()
    assert runtime.result_status in {"applied", "no_change"}
    if runtime.result_status == "applied":
        assert runtime.publishable
