"""Deterministic recovery helpers for damaged lesson-plan artifacts."""

from __future__ import annotations

import copy
import re
from typing import Any

from app.agent.agents.lesson_plan.diff import (
    diff_lesson_plans,
    distinct_top_level_fact_sections,
    empty_leaf_section_ids,
)
from app.agent.agents.lesson_plan.qa import blocking_issues, validate_lesson_plan
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.lesson_plan import LessonPlanContentV2, lesson_plan_to_markdown_v2


REPAIR_SUMMARY = "安全修复：从 V16 恢复全部正文并拆分教学评价与教学反思"


def _normalized_payload(text: str) -> str:
    return re.sub(r"\s+", "", text)


def build_assessment_reflection_repair(source: dict[str, Any]) -> dict[str, Any]:
    """Split the known combined V16 paragraph without regenerating any prose."""
    content = copy.deepcopy(source)
    sections = list((content.get("outline") or {}).get("sections") or [])
    reflection_index = next(
        (index for index, item in enumerate(sections) if item.get("id") == "SEC-REFLECTION"),
        None,
    )
    if reflection_index is None:
        raise ValueError("源版本缺少 SEC-REFLECTION")
    if any(item.get("id") == "SEC-ASSESSMENT" for item in sections):
        raise ValueError("源版本已经包含 SEC-ASSESSMENT，拒绝重复修复")
    reflection = copy.deepcopy(sections[reflection_index])
    blocks = list(reflection.get("blocks") or [])
    if len(blocks) != 1 or blocks[0].get("kind") != "paragraph":
        raise ValueError("SEC-REFLECTION 不是预期的单段落合并结构")
    original = str(blocks[0].get("text") or "")
    assessment_marker = "一、 教学评价方案"
    reflection_marker = "二、 教师课后反思框架"
    assessment_start = original.find(assessment_marker)
    reflection_start = original.find(reflection_marker)
    if assessment_start < 0 or reflection_start <= assessment_start:
        raise ValueError("未找到可安全分割的教学评价/教学反思标题")

    assessment_payload = original[assessment_start:reflection_start].strip()
    reflection_payload = original[reflection_start:].strip()
    original_payload = original[assessment_start:].strip()
    if _normalized_payload(assessment_payload + reflection_payload) != _normalized_payload(original_payload):
        raise ValueError("分割后的正文与源正文不一致")

    assessment = {
        "id": "SEC-ASSESSMENT",
        "title": "教学评价",
        "summary": "独立呈现教学评价方案。",
        "coverage_refs": ["assessment_plan"],
        "blocks": [{"kind": "paragraph", "text": f"【教学评价】\n\n{assessment_payload}"}],
        "children": [],
    }
    reflection.update({
        "title": "教学反思",
        "summary": "教师课后反思与持续改进。",
        "coverage_refs": ["reflection"],
        "blocks": [{"kind": "paragraph", "text": f"【教学反思】\n\n{reflection_payload}"}],
    })
    sections[reflection_index:reflection_index + 1] = [assessment, reflection]
    content["outline"]["sections"] = sections
    return LessonPlanContentV2.model_validate(content).model_dump()


def validate_assessment_reflection_repair(
    source: dict[str, Any],
    candidate: dict[str, Any],
    blueprint: CourseBlueprintSchema | dict[str, Any],
) -> dict[str, Any]:
    """Run all recovery invariants and return markdown/diff for persistence."""
    blueprint = CourseBlueprintSchema.model_validate(blueprint)
    validated = LessonPlanContentV2.model_validate(candidate).model_dump()
    source_sections = {
        str(item.get("id") or ""): item
        for item in (source.get("outline") or {}).get("sections") or []
    }
    candidate_sections = {
        str(item.get("id") or ""): item
        for item in (validated.get("outline") or {}).get("sections") or []
    }
    untouched = set(source_sections) - {"SEC-REFLECTION"}
    changed_untouched = sorted(
        section_id for section_id in untouched
        if source_sections[section_id] != candidate_sections.get(section_id)
    )
    if changed_untouched:
        raise ValueError(f"非目标章节发生变化：{changed_untouched}")
    if source.get("course_info") != validated.get("course_info"):
        raise ValueError("课程信息发生变化")
    if source.get("pedagogical_core") != validated.get("pedagogical_core"):
        raise ValueError("pedagogical_core 发生变化")
    if len((validated.get("outline") or {}).get("sections") or []) != 8:
        raise ValueError("修复后必须包含 8 个一级章节")
    empty = empty_leaf_section_ids(validated)
    if empty:
        raise ValueError(f"修复后仍存在空叶子章节：{empty}")
    owners = distinct_top_level_fact_sections(validated, ["assessment_plan", "reflection"])
    if owners != {"assessment_plan": "SEC-ASSESSMENT", "reflection": "SEC-REFLECTION"}:
        raise ValueError(f"评价/反思一级章节归属不正确：{owners}")

    issues = validate_lesson_plan(blueprint, validated)
    blocking = blocking_issues(issues)
    if blocking:
        raise ValueError(f"教学质量门禁未通过：{blocking[0]['description']}")
    diff = diff_lesson_plans(
        source,
        validated,
        mutable_section_ids={"SEC-ASSESSMENT", "SEC-REFLECTION"},
    )
    if diff["emptied_sections"] or diff["unexpected_content_changes"]:
        raise ValueError("内容退化门禁未通过")
    if float(diff["content_loss_ratio"]) > 0.05:
        raise ValueError("可见正文减少超过 5%")
    markdown = lesson_plan_to_markdown_v2(validated)
    source_markdown = lesson_plan_to_markdown_v2(source)
    if len(markdown.strip()) < len(source_markdown.strip()) * 0.95:
        raise ValueError("修复后的 Markdown 较源版本异常缩短")
    return {
        "content": validated,
        "markdown": markdown,
        "diff": diff,
        "issues": issues,
        "fact_owners": owners,
    }
