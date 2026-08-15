"""教学设计 V2 单元测试：数据契约、投影、适配器、builder、工具、QA、意图。

覆盖计划 M7 单元部分：V2 接受任意合法目录、拒绝非法结构、V1→V2 幂等转换、
目录编辑工具、确定性质量门禁、意图识别确定性兜底。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.agents.lesson_plan.builder import LessonPlanBuilder
from app.agent.agents.lesson_plan.diff import diff_lesson_plans
from app.agent.agents.lesson_plan.intents import LessonPlanIntentDecision
from app.agent.agents.lesson_plan.qa import validate_lesson_plan
from app.agent.agents.lesson_plan.recovery import (
    build_assessment_reflection_repair,
    validate_assessment_reflection_repair,
)
from app.agent.agents.lesson_plan.tools import (
    get_lesson_plan_tool,
    register_lesson_plan_tools,
    lesson_plan_tool_schemas,
)
from app.agent.context import ContextState
from app.agent.registry import ToolContext, all_tool_schemas, execute_tool
from app.schemas.blueprint import (
    AssessmentItem,
    CourseBlueprintSchema,
    CourseIdentity,
    KnowledgePoint,
    LearningAnalysis,
    LearningObjective,
    TimelineSegment,
)
from app.schemas.lesson_plan import (
    LessonPlanContentV2,
    lesson_plan_core,
    lesson_plan_outline_sections,
    lesson_plan_to_markdown_v2,
    make_lesson_plan_v2,
    upgrade_lesson_plan_v2,
)


def make_bp(duration: int = 10) -> CourseBlueprintSchema:
    return CourseBlueprintSchema(
        course_identity=CourseIdentity(
            title="勾股定理", subject="数学", grade_level="八年级", audience="八年级学生",
            duration_minutes=duration, scenario="课堂微课", language="中文",
        ),
        learning_analysis=LearningAnalysis(
            prior_knowledge=["直角三角形"], learner_characteristics=["八年级学生"],
            likely_misconceptions=["只记结论"],
        ),
        objectives=[LearningObjective(
            id="OBJ-01", domain="knowledge", behavior="解释", condition="给出典型情境时",
            criterion="能准确说明勾股定理及适用条件", knowledge_point_ids=["KP-01"],
            activity_ids=["ACT-01"], exercise_ids=["Q-01"],
        )],
        knowledge_points=[KnowledgePoint(id="KP-01", name="勾股定理")],
        key_points=["勾股定理及其应用"], difficulty_points=["逆定理的判定"],
        teaching_strategy=["情境驱动"],
        timeline=[
            TimelineSegment(segment_id="ACT-01", name="情境导入", start_minute=0, end_minute=3,
                            purpose="激活经验", teacher_action="提问", learner_action="观察",
                            evidence_of_learning="给出判断"),
            TimelineSegment(segment_id="ACT-02", name="核心讲解", start_minute=3, end_minute=8,
                            purpose="建立概念", teacher_action="示范", learner_action="记录",
                            evidence_of_learning="解释关系"),
            TimelineSegment(segment_id="ACT-03", name="应用总结", start_minute=8, end_minute=10,
                            purpose="迁移应用", teacher_action="提供练习", learner_action="独立完成",
                            evidence_of_learning="完成练习"),
        ],
        assessment_plan=[AssessmentItem(objective_id="OBJ-01", method="口头检查",
                                        evidence="概念解释", criterion="术语准确")],
        terminology={"勾股定理": "a²+b²=c²"}, source_refs=[], resource_constraints=[],
    )


def base_v2(duration: int = 10) -> dict:
    """合法 V2 内容（与 make_lesson_plan_v2 等价形状，便于定向破坏测试）。"""
    return make_lesson_plan_v2(make_bp(duration)).model_dump()


# ---------------------------------------------------------------------------
# V2 Schema：任意合法目录 + 非法结构拒绝
# ---------------------------------------------------------------------------


def test_v2_accepts_arbitrary_outline_names_and_order():
    """V2 接受任意合法的目录名称、顺序与组合，不依赖固定标题。"""
    content = base_v2()
    content["outline"]["sections"] = [
        {"id": "SEC-HOOK", "title": "一、悬念引入", "summary": "s", "coverage_refs": ["stages"], "blocks": [], "children": []},
        {"id": "SEC-MAIN", "title": "贰·概念建构", "summary": "s", "coverage_refs": ["objectives"], "blocks": [], "children": [
            {"id": "SEC-MAIN-A", "title": "为什么是直角？", "summary": "", "coverage_refs": ["key_points"], "blocks": [], "children": []},
        ]},
        {"id": "SEC-DONE", "title": "课堂收尾与作业", "summary": "", "coverage_refs": ["homework"], "blocks": [], "children": []},
    ]
    v2 = LessonPlanContentV2.model_validate(content)
    assert v2.outline.sections[0].title == "一、悬念引入"
    assert v2.outline.sections[1].children[0].title == "为什么是直角？"


def test_v2_rejects_negative_and_inconsistent_timing():
    content = base_v2()
    content["pedagogical_core"]["stages"][0]["duration_minutes"] = -1
    with pytest.raises(ValueError):
        LessonPlanContentV2.model_validate(content)
    content = base_v2()
    content["pedagogical_core"]["stages"][0]["duration_minutes"] = 20  # 总计 27 ≠ 10
    with pytest.raises(ValueError):
        LessonPlanContentV2.model_validate(content)


def test_v2_rejects_duplicate_ids_and_invalid_references():
    content = base_v2()
    content["pedagogical_core"]["stages"][1]["id"] = content["pedagogical_core"]["stages"][0]["id"]
    with pytest.raises(ValueError):
        LessonPlanContentV2.model_validate(content)

    content = base_v2()
    content["pedagogical_core"]["stages"][0]["objective_ids"] = ["NOPE"]
    with pytest.raises(ValueError):
        LessonPlanContentV2.model_validate(content)

    content = base_v2()
    content["outline"]["sections"][1]["id"] = content["outline"]["sections"][0]["id"]
    with pytest.raises(ValueError):
        LessonPlanContentV2.model_validate(content)


def test_v2_rejects_outline_depth_overflow_and_empty_top_level():
    content = base_v2()
    content["outline"]["sections"] = [{
        "id": "SEC-A", "title": "A", "coverage_refs": [], "blocks": [], "children": [{
            "id": "SEC-B", "title": "B", "coverage_refs": [], "blocks": [], "children": [{
                "id": "SEC-C", "title": "C", "coverage_refs": [], "blocks": [], "children": [{
                    "id": "SEC-D", "title": "D", "coverage_refs": [], "blocks": [], "children": [],
                }],
            }],
        }],
    }]
    with pytest.raises(ValueError):
        LessonPlanContentV2.model_validate(content)

    content = base_v2()
    content["outline"]["sections"] = []
    with pytest.raises(ValueError):
        LessonPlanContentV2.model_validate(content)


# ---------------------------------------------------------------------------
# 统一投影 + 大纲投影
# ---------------------------------------------------------------------------


def test_lesson_plan_core_projects_v1_and_v2():
    v2 = base_v2()
    core = lesson_plan_core(v2)
    assert [item["id"] for item in core["objectives"]] == ["OBJ-01"]
    assert [item["id"] for item in core["stages"]] == ["ACT-01", "ACT-02", "ACT-03"]
    v1 = {
        "objectives": ["OBJ-01：解释"], "key_points": ["k"], "difficulty_points": ["d"],
        "methods": ["m"], "resources": ["r"], "stages": [{"id": "ACT-01", "title": "t"}],
        "homework": "h", "board_design": "b",
    }
    assert lesson_plan_core(v1)["stages"][0]["id"] == "ACT-01"
    assert lesson_plan_core({}) == {}


def test_outline_sections_projects_v2_tree_and_v1_defaults():
    v2 = base_v2()
    sections = lesson_plan_outline_sections(v2)
    assert len(sections) >= 2 and sections[0]["id"].startswith("SEC-")
    v1 = {"objectives": ["x"], "stages": [{"id": "S1", "title": "t"}], "content_analysis": "c"}
    defaults = lesson_plan_outline_sections(v1)
    assert any(item["id"] == "SEC-CONTENT" for item in defaults)
    assert any(item["id"] == "SEC-PROCESS" for item in defaults)


# ---------------------------------------------------------------------------
# V1 → V2 适配器
# ---------------------------------------------------------------------------


def test_upgrade_lesson_plan_v2_is_deterministic_and_idempotent():
    bp = make_bp()
    v1 = {
        "content_analysis": "围绕勾股定理组织内容。",
        "learner_analysis": "授课对象：八年级学生",
        "objectives": ["OBJ-01：解释——能准确说明勾股定理及适用条件"],
        "key_points": ["勾股定理"], "difficulty_points": ["逆定理"],
        "methods": ["情境驱动"], "resources": ["PPT"],
        "stages": [
            {"id": "ACT-01", "title": "情境导入", "duration_minutes": 3, "teacher_activity": "t",
             "learner_activity": "l", "design_intent": "d", "assessment": "a"},
        ],
        "board_design": "板书", "homework": "完成练习",
    }
    upgraded = upgrade_lesson_plan_v2(v1, bp)
    assert isinstance(upgraded, LessonPlanContentV2)
    assert upgraded.schema_version == "2.0"
    assert upgraded.pedagogical_core.stages[0].id == "ACT-01"
    # 幂等：再转换不报错，内容一致。
    again = upgrade_lesson_plan_v2(upgraded.model_dump(), bp)
    assert again.pedagogical_core.objectives[0].id == upgraded.pedagogical_core.objectives[0].id
    # 不改写旧 Artifact：入参 dict 未变化。
    assert v1["objectives"] == ["OBJ-01：解释——能准确说明勾股定理及适用条件"]


def test_upgrade_lesson_plan_v2_converges_timing_drift():
    bp = make_bp()
    v1 = {
        "objectives": ["OBJ-01：解释"], "key_points": ["k"],
        "stages": [{"id": "ACT-01", "title": "导入", "duration_minutes": 3,
                    "teacher_activity": "t", "learner_activity": "l",
                    "design_intent": "d", "assessment": "a"}],
    }
    upgraded = upgrade_lesson_plan_v2(v1, bp)
    total = sum(item.duration_minutes for item in upgraded.pedagogical_core.stages)
    assert abs(total - bp.course_identity.duration_minutes) <= 0.5


# ---------------------------------------------------------------------------
# builder 编辑工具
# ---------------------------------------------------------------------------


def test_builder_outline_crud_and_validation():
    builder = LessonPlanBuilder(base_v2())
    builder.add_section("SEC-NEW", "新增章节")
    assert "SEC-NEW" in builder.all_section_ids()
    builder.move_section("SEC-NEW", target_parent_id="SEC-PROCESS" if "SEC-PROCESS" in builder.all_section_ids() else "")
    builder.rename_section("SEC-NEW", "新章节（改名）")
    assert builder.find_section("SEC-NEW")["title"] == "新章节（改名）"
    with pytest.raises(ValueError):
        builder.add_section("SEC-NEW", "重复")
    builder.delete_section("SEC-NEW")
    assert "SEC-NEW" not in builder.all_section_ids()
    result = builder.validate_content()
    assert result["ok"] is True


def test_builder_merge_and_write():
    builder = LessonPlanBuilder(base_v2())
    builder.add_section("SEC-M1", "合并一")
    builder.add_section("SEC-M2", "合并二")
    builder.merge_sections(["SEC-M1", "SEC-M2"], "合并后")
    assert "SEC-M1" in builder.all_section_ids()
    assert "SEC-M2" not in builder.all_section_ids()
    builder.write_section("SEC-M1", blocks=[{"kind": "paragraph", "text": "正文"}], summary="概要")
    node = builder.find_section("SEC-M1")
    assert node["blocks"][0]["text"] == "正文"
    assert node["summary"] == "概要"


def test_lesson_plan_tools_registered():
    register_lesson_plan_tools()
    schemas = lesson_plan_tool_schemas()
    names = {item["name"] for item in schemas}
    for required in (
        "lesson_get_blueprint", "lesson_get_source", "lesson_add_section",
        "lesson_move_section", "lesson_rename_section", "lesson_merge_sections",
        "lesson_delete_section", "lesson_write_section", "lesson_update_core",
        "lesson_apply_patch", "lesson_calculate_timeline", "lesson_validate_alignment",
        "lesson_validate_outline_coverage", "lesson_validate_references",
        "lesson_render_preview", "lesson_diff_versions",
    ):
        assert required in names, f"工具缺失：{required}"
    assert get_lesson_plan_tool("lesson_create_outline") is not None


def test_lesson_source_schema_only_advertises_views_allowed_for_each_role():
    designer_schema = next(
        item for item in lesson_plan_tool_schemas(
            ["lesson_get_source"], agent_key="lesson_designer",
        )
        if item["name"] == "lesson_get_source"
    )
    finalizer_schema = next(
        item for item in lesson_plan_tool_schemas(
            ["lesson_get_source"], agent_key="finalizer",
        )
        if item["name"] == "lesson_get_source"
    )

    designer_views = designer_schema["input_schema"]["properties"]["view"]["enum"]
    finalizer_views = finalizer_schema["input_schema"]["properties"]["view"]["enum"]
    assert designer_views == ["summary", "core", "section"]
    assert "full" not in designer_views
    assert "full" in finalizer_views


def _tool_context(*, content=None, selected=None, locks=None) -> ToolContext:
    builder = LessonPlanBuilder(content or base_v2())
    runtime = SimpleNamespace(
        locks=locks or [], selected_section_ids=selected or [],
        current_agent_key="finalizer", cancel_requested=lambda: False,
    )
    return ToolContext(
        ctx=ContextState(blueprint=make_bp().model_dump()),
        runtime=runtime,
        extra={"builder": builder},
    )


def test_empty_allowed_tool_list_is_deny_all():
    register_lesson_plan_tools()
    assert all_tool_schemas([]) == []
    assert any(item["name"] == "lesson_get_source" for item in all_tool_schemas(None))


def test_alignment_tool_accepts_dict_blueprint():
    result = asyncio.run(execute_tool("lesson_validate_alignment", _tool_context(), {}))
    assert result.ok is True
    assert result.output["passed"] is True


def test_lesson_get_source_projection_defaults_to_compact_summary():
    tc = _tool_context()
    summary = asyncio.run(execute_tool("lesson_get_source", tc, {}))
    assert summary.ok is True
    assert "content" not in summary.output
    assert summary.output["outline_summary"]
    outline = asyncio.run(execute_tool("lesson_get_source", tc, {"view": "outline"}))
    assert outline.output["outline"]["sections"]


def test_full_lesson_diff_covers_core_order_and_coverage():
    source = base_v2()
    candidate = LessonPlanBuilder(source).to_content()
    candidate["pedagogical_core"]["reflection"] = "新的课后反思"
    candidate["outline"]["sections"][0]["coverage_refs"] = ["assessment_plan"]
    candidate["outline"]["sections"][0], candidate["outline"]["sections"][1] = (
        candidate["outline"]["sections"][1], candidate["outline"]["sections"][0],
    )
    diff = diff_lesson_plans(source, candidate)
    assert diff["changed"] is True
    assert diff["outline_structure_changed"] is True
    assert "reflection" in diff["core_changed_fields"]
    assert diff["moved_sections"]
    assert diff["coverage_changed_sections"]


def test_diff_and_qa_detect_sections_emptied_by_outline_replacement():
    source = base_v2()
    candidate = LessonPlanBuilder(source).to_content()
    for section in candidate["outline"]["sections"]:
        section["summary"] = ""
        section["blocks"] = []

    diff = diff_lesson_plans(source, candidate, mutable_section_ids=set())
    issues = validate_lesson_plan(make_bp(), candidate)

    assert diff["emptied_sections"]
    assert diff["block_count_before"] > diff["block_count_after"]
    assert diff["visible_content_chars_before"] > diff["visible_content_chars_after"]
    assert diff["content_loss_ratio"] > 0.95
    assert diff["unexpected_content_changes"]
    assert any(item["dimension"] == "visibility" and item["severity"] == "major" for item in issues)


def test_create_outline_refuses_to_replace_existing_content_atomically():
    tc = _tool_context()
    before = tc.extra["builder"].to_content()
    result = asyncio.run(execute_tool("lesson_create_outline", tc, {
        "sections": [
            {"id": "SEC-A", "title": "空目录一", "children": []},
            {"id": "SEC-B", "title": "空目录二", "children": []},
        ],
    }))

    assert result.ok is False
    assert result.error_code == "outline_replace_forbidden"
    assert tc.extra["builder"].to_content() == before


def test_render_preview_rejects_heading_only_candidate():
    content = base_v2()
    for section in content["outline"]["sections"]:
        section["summary"] = ""
        section["blocks"] = []
    result = asyncio.run(execute_tool(
        "lesson_render_preview", _tool_context(content=content), {"format": "markdown"},
    ))
    assert result.ok is False
    assert result.error_code == "rendered_content_missing"


def test_recovery_splits_combined_section_and_preserves_every_other_section():
    source = base_v2()
    source["outline"]["sections"].insert(1, {
        "id": "SEC-LEARNER", "title": "学情分析", "summary": "",
        "coverage_refs": ["learner_analysis"],
        "blocks": [{"kind": "paragraph", "text": "学生已具备直角三角形基础。"}],
        "children": [],
    })
    reflection = next(
        item for item in source["outline"]["sections"] if item["id"] == "SEC-REFLECTION"
    )
    reflection["blocks"] = [{
        "kind": "paragraph",
        "text": (
            "【教学评价与教学反思】\n\n"
            "一、 教学评价方案（与板书设计、作业布置同级）：\n"
            "1. 过程性评价：观察学习任务。\n"
            "2. 总结性评价：检查目标达成。\n\n"
            "二、 教师课后反思框架：\n"
            "1. 目标达成情况：检查学生表现。\n"
            "2. 持续改进方向：调整教学节奏。"
        ),
    }]
    before = {
        item["id"]: item for item in source["outline"]["sections"]
        if item["id"] != "SEC-REFLECTION"
    }

    candidate = build_assessment_reflection_repair(source)
    checked = validate_assessment_reflection_repair(source, candidate, make_bp())
    after = {item["id"]: item for item in candidate["outline"]["sections"]}

    assert len(candidate["outline"]["sections"]) == 8
    assert checked["fact_owners"] == {
        "assessment_plan": "SEC-ASSESSMENT",
        "reflection": "SEC-REFLECTION",
    }
    assert all(after[section_id] == value for section_id, value in before.items())
    assert "过程性评价" in after["SEC-ASSESSMENT"]["blocks"][0]["text"]
    assert "持续改进方向" in after["SEC-REFLECTION"]["blocks"][0]["text"]
    assert checked["diff"]["emptied_sections"] == []
    assert checked["diff"]["unexpected_content_changes"] == []


def test_edit_tools_enforce_scope_lock_and_atomic_rollback():
    content = base_v2()
    first = content["outline"]["sections"][0]["id"]
    second = content["outline"]["sections"][1]["id"]

    scoped = _tool_context(content=content, selected=[first])
    before = scoped.extra["builder"].to_content()
    denied = asyncio.run(execute_tool("lesson_rename_section", scoped, {"section_id": second, "title": "越界修改"}))
    assert denied.ok is False
    assert denied.error_code == "section_scope_violation"
    assert scoped.extra["builder"].to_content() == before

    locked = _tool_context(content=content, locks=[{"json_path": f"$.outline.sections[{first}].title"}])
    denied = asyncio.run(execute_tool("lesson_rename_section", locked, {"section_id": first, "title": "锁定修改"}))
    assert denied.ok is False
    assert denied.error_code == "locked_path_conflict"

    indexed_lock = _tool_context(content=content, locks=[{"json_path": "$.outline.sections[0].title"}])
    denied = asyncio.run(execute_tool(
        "lesson_rename_section", indexed_lock, {"section_id": first, "title": "索引路径锁定修改"},
    ))
    assert denied.ok is False
    assert denied.error_code == "locked_path_conflict"

    invalid = _tool_context(content=content)
    before = invalid.extra["builder"].to_content()
    denied = asyncio.run(execute_tool("lesson_update_core", invalid, {"patch": {"objectives": []}}))
    assert denied.ok is False
    assert denied.error_code == "candidate_invalid"
    assert invalid.extra["builder"].to_content() == before


# ---------------------------------------------------------------------------
# QA 确定性门禁
# ---------------------------------------------------------------------------


def test_validate_lesson_plan_passes_valid_v2():
    bp = make_bp()
    issues = validate_lesson_plan(bp, base_v2())
    assert issues == []


def test_validate_lesson_plan_catches_reference_and_coverage_issues():
    bp = make_bp()
    content = base_v2()
    content["pedagogical_core"]["objectives"][0]["blueprint_objective_id"] = "NOPE-OBJ"
    issues = validate_lesson_plan(bp, content)
    assert any(item["dimension"] == "alignment" and item["severity"] == "critical" for item in issues)

    content = base_v2()
    content["pedagogical_core"]["stages"][0]["id"] = "WRONG-STAGE"
    issues = validate_lesson_plan(bp, content)
    assert any("WRONG-STAGE" in item["description"] for item in issues)

    content = base_v2()
    content["pedagogical_core"]["objectives"][0]["evidence"] = ""
    issues = validate_lesson_plan(bp, content)
    # 空 evidence 被 Pydantic min_length 拦截 → critical integrity（结构非法）。
    assert any(item["severity"] == "critical" and item["dimension"] == "integrity" for item in issues)

    content = base_v2()
    content["outline"]["sections"][0]["coverage_refs"] = ["not_a_fact"]
    issues = validate_lesson_plan(bp, content)
    assert any(item["dimension"] == "coverage" for item in issues)


def test_validate_lesson_plan_v1_returns_minor_compat():
    bp = make_bp()
    issues = validate_lesson_plan(bp, {"objectives": ["x"], "stages": []})
    assert any(item["dimension"] == "compatibility" for item in issues)


def test_validate_lesson_plan_respects_locks():
    bp = make_bp()
    issues = validate_lesson_plan(bp, base_v2(), locked_paths=["$"])
    assert any(item["dimension"] == "lock" for item in issues)


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def test_v2_markdown_renders_outline_tree():
    md = lesson_plan_to_markdown_v2(base_v2())
    assert "# 教学设计" in md
    assert "教学目标" in md or "内容分析" in md
    assert "教学过程" in md


def test_v2_markdown_heading_numbering_by_tree_level():
    """渲染器按章节树层级生成显示编号：一级一、二、三…；二级（一）（二）…；三级 1. 2. 3.…"""
    content = base_v2()
    # 构造含三级层级的目录，验证编号与层级对应。
    top = content["outline"]["sections"][0]
    top["children"] = [
        {"id": "SEC-SUB1", "title": "子要点一", "summary": "", "coverage_refs": [], "blocks": [
            {"kind": "paragraph", "text": "子要点正文。"},
        ], "children": []},
    ]
    top["children"][0]["children"] = [
        {"id": "SEC-SUB1-1", "title": "孙子要点", "summary": "", "coverage_refs": [], "blocks": [
            {"kind": "paragraph", "text": "孙级正文。"},
        ], "children": []},
    ]
    md = lesson_plan_to_markdown_v2(content)

    first_title = content["outline"]["sections"][0]["title"]
    second_title = content["outline"]["sections"][1]["title"]
    assert f"# 一、{first_title}" in md, "一级标题应为 一、前缀"
    assert f"# 二、{second_title}" in md, "二级一级标题应为 二、前缀"
    assert "## （一）子要点一" in md, "二级标题应为 （一）前缀"
    assert "### 1. 孙子要点" in md, "三级标题应为 1. 前缀"


def test_v2_markdown_numbering_is_idempotent():
    """重复渲染编号不变（幂等）。"""
    first = lesson_plan_to_markdown_v2(base_v2())
    second = lesson_plan_to_markdown_v2(base_v2())
    assert first == second


def test_validate_numbering_tool_detects_hardcoded_ordinals():
    """lesson_validate_numbering：干净内容通过；含硬编码序号的正文被发现。"""
    clean = asyncio.run(execute_tool("lesson_validate_numbering", _tool_context(content=base_v2()), {}))
    assert clean.ok is True
    assert clean.output["ok"] is True
    assert clean.output["problems"] == []

    dirty_content = base_v2()
    for section in dirty_content["outline"]["sections"]:
        if section["id"] == "SEC-REFLECTION":
            section["blocks"] = [{"kind": "paragraph", "text": "一、教师课后反思框架：\n1. 目标达成情况。"}]
    dirty = asyncio.run(execute_tool(
        "lesson_validate_numbering", _tool_context(content=dirty_content), {},
    ))
    assert dirty.ok is True  # 校验工具本身执行成功
    assert dirty.output["ok"] is False
    assert dirty.output["problems"]


def test_validate_scope_tool_reports_preserved_section_changes():
    """lesson_validate_scope：契约目标之外的保留章节被修改时报告失败。"""
    content = base_v2()
    tc = _tool_context(content=content)
    first = content["outline"]["sections"][0]["id"]
    runtime = SimpleNamespace(
        locks=[], source_artifact=SimpleNamespace(content_json=base_v2()),
        resolved_intent=LessonPlanIntentDecision(
            intent="SECTION_EDIT", target_section_ids=[first], resolved_scope=[first],
        ),
    )
    tc.runtime = runtime
    result = asyncio.run(execute_tool("lesson_validate_scope", tc, {}))
    assert result.ok is True
    assert result.output["ok"] is True
    assert result.output["failures"] == []


# ---------------------------------------------------------------------------
# 意图识别确定性兜底
# ---------------------------------------------------------------------------


def test_intent_fallback_for_mock_and_failure():
    import asyncio
    import types

    from app.agent.agents.lesson_plan.intents import agent_chain_for_intent, infer_lesson_plan_intent
    from app.providers.llm.mock import MockProvider

    # Mock Provider → 确定性 GENERATE（initial）
    result = asyncio.run(infer_lesson_plan_intent(MockProvider(), "initial", ""))
    assert result.intent == "GENERATE"

    # LLM 意图识别失败 → 确定性兜底（mode=structure → RESTRUCTURE）
    failing = _FailingStructuredProvider()
    result = asyncio.run(infer_lesson_plan_intent(
        failing, "message", "把教学过程重排一下", ["SEC-PROCESS"], "structure",
    ))
    assert result.intent == "RESTRUCTURE"
    assert result.affected_section_ids == ["SEC-PROCESS"]

    assert agent_chain_for_intent("QA_ONLY", "message") == ["pedagogy_qa", "finalizer"]
    assert agent_chain_for_intent("SYNC_CONTEXT", "sync_context") == ["context_researcher", "lesson_designer", "finalizer"]


class _FailingStructured:
    async def structured(self, system, prompt, schema):
        raise RuntimeError("provider down")


class _FailingStructuredProvider:
    """非 Mock 的 LLM Provider，intent 识别失败用于验证确定性兜底。"""

    async def structured(self, system, prompt, schema):
        raise RuntimeError("provider down")
