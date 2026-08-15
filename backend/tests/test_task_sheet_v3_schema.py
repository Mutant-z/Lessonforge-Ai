"""学习任务单 V3 数据契约与确定性转换测试。"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.agents.generators import make_task_sheet
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.task_sheet import (
    MAX_TOP_LEVEL_SECTIONS,
    TASK_SHEET_V2,
    TASK_SHEET_V3,
    TaskSheetContentV3,
    make_task_sheet_v3,
    task_sheet_objectives,
    task_sheet_outline_sections,
    task_sheet_to_v3,
    task_sheet_v3_to_markdown,
)

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
def v3(bp) -> TaskSheetContentV3:
    return make_task_sheet_v3(bp)


def test_fresh_v3_has_dynamic_sections_and_semantics(v3):
    data = v3.model_dump()
    assert data["schema_version"] == TASK_SHEET_V3
    assert 2 <= len([s for s in data["sections"] if not s["parent_id"]]) <= MAX_TOP_LEVEL_SECTIONS
    kinds = {block["kind"] for section in data["sections"] for block in section["blocks"]}
    assert {"objective_list", "learning_task", "record_table", "assessment"} <= kinds


def test_v3_requires_semantic_elements(bp):
    v3 = make_task_sheet_v3(bp)
    data = copy.deepcopy(v3.model_dump())
    for section in data["sections"]:
        section["blocks"] = [b for b in section["blocks"] if b.get("kind") != "assessment"]
    with pytest.raises(ValidationError):
        TaskSheetContentV3.model_validate(data)


def test_v3_tree_depth_and_id_rules(bp):
    v3 = make_task_sheet_v3(bp)
    data = copy.deepcopy(v3.model_dump())
    data["sections"].append({"id": "SEC-L1", "parent_id": "", "order": 99, "title": "L1", "blocks": []})
    data["sections"].append({"id": "SEC-L2", "parent_id": "SEC-L1", "order": 0, "title": "L2", "blocks": []})
    data["sections"].append({"id": "SEC-L3", "parent_id": "SEC-L2", "order": 0, "title": "L3", "blocks": []})
    data["sections"].append({"id": "SEC-L4", "parent_id": "SEC-L3", "order": 0, "title": "L4", "blocks": []})
    with pytest.raises(ValidationError):
        TaskSheetContentV3.model_validate(data)


def test_v3_order_conflict_detected(bp):
    v3 = make_task_sheet_v3(bp)
    data = copy.deepcopy(v3.model_dump())
    top = [s for s in data["sections"] if not s["parent_id"]]
    top[1]["order"] = top[0]["order"]
    with pytest.raises(ValidationError):
        TaskSheetContentV3.model_validate(data)


def test_v3_self_parent_rejected(bp):
    v3 = make_task_sheet_v3(bp)
    data = copy.deepcopy(v3.model_dump())
    data["sections"][0]["parent_id"] = data["sections"][0]["id"]
    with pytest.raises(ValidationError):
        TaskSheetContentV3.model_validate(data)


def test_v2_to_v3_is_lossless(bp):
    v2 = make_task_sheet(bp)
    v3 = task_sheet_to_v3(v2.model_dump(), bp)
    assert v3.schema_version == TASK_SHEET_V3
    assert len(v3.objective_catalog) == len(v2.learning_objectives)
    v3_tasks = [b for s in v3.sections for b in s.blocks if b.kind == "learning_task"]
    assert len(v3_tasks) == len(v2.tasks)
    assert sorted(v3_tasks[0].steps) == sorted(v2.tasks[0].steps)
    assert v3_tasks[0].estimated_minutes == v2.tasks[0].estimated_minutes
    assert v3_tasks[0].objective_ids == v2.tasks[0].objective_ids


def test_v2_remains_readable(bp):
    v2 = make_task_sheet(bp)
    assert v2.model_dump()["schema_version"] == TASK_SHEET_V2


def test_unified_projection(bp, v3):
    proj = task_sheet_objectives(v3.model_dump())
    assert {item["id"] for item in proj} == {item.id for item in bp.objectives}
    v2_proj = task_sheet_objectives(make_task_sheet(bp).model_dump())
    assert {item["id"] for item in v2_proj} == {item.id for item in bp.objectives}


def test_outline_projection(v3):
    outline = task_sheet_outline_sections(v3.model_dump())
    assert len(outline) == len(v3.sections)


def test_v3_markdown_recursive(v3):
    md = task_sheet_v3_to_markdown(v3)
    assert "学习任务链" in md
    assert "|" in md
    assert "□" in md
    assert md.count("## ") >= 2
