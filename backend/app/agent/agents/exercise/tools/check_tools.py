"""课后练习工具集：检查类工具。

QA 角色（exercise_qa）通过本组工具执行确定性规则校验；结果回喂上下文供
返修路由决策。LLM 语义质询在 exercise_qa 角色 decide 中调用，失败回退
本组确定性门禁。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.agents.exercise.tools._common import _builder, _lock_paths
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool


def _bp_model(tc: ToolContext):
    from app.schemas.blueprint import CourseBlueprintSchema

    bp_data = tc.ctx.blueprint if tc.ctx is not None else None
    bp_content = bp_data.model_dump() if hasattr(bp_data, "model_dump") else (bp_data or {})
    return CourseBlueprintSchema.model_validate(bp_content)


def _task_sheet_raw(tc: ToolContext) -> dict[str, Any] | None:
    knowledge = getattr(tc.runtime, "knowledge_context", None) if tc.runtime else None
    raw = ((knowledge or {}).get("sibling_artifacts", {}).get("task_sheet")
           or (knowledge or {}).get("hard_dependencies", {}).get("task_sheet"))
    if isinstance(raw, dict):
        raw = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    return raw if isinstance(raw, dict) else None


class ValidateRulesInput(BaseModel):
    pass


async def _exercise_validate_rules(tc: ToolContext, _: ValidateRulesInput) -> ToolResult:
    """执行确定性规则门禁：结构/引用/认知层级/总分/任务单复用/用时等。"""
    from app.agent.agents.exercise.qa import (
        blocking_issues as _blocking,
        exercise_validate_rules as _rules,
        fingerprint as _fingerprint,
    )

    builder = _builder(tc)
    content = builder.to_content()
    try:
        bp = _bp_model(tc)
    except Exception:  # noqa: BLE001  蓝图异常视为无问题（与旧行为一致）
        issues: list[dict] = []
        return ToolResult(output={
            "passed": True, "issues": issues, "blocking": [], "fingerprint": "",
        })
    issues = _rules(bp, content, _task_sheet_raw(tc), _lock_paths(tc))
    blocking = _blocking(issues)
    return ToolResult(output={
        "passed": not blocking,
        "issues": issues,
        "blocking": blocking,
        "fingerprint": _fingerprint(issues),
        "score": max(0, 100 - len(blocking) * 15),
        "summary": f"规则校验{'通过' if not blocking else f'发现 {len(blocking)} 个阻断问题'}",
    })


class ValidateReferencesInput(BaseModel):
    pass


async def _exercise_validate_references(tc: ToolContext, _: ValidateReferencesInput) -> ToolResult:
    """校验引用合法性：目标/知识点/教学环节 ID 必须来自已批准蓝图。"""
    from app.agent.agents.exercise.qa import blocking_issues as _blocking, issue as _issue

    builder = _builder(tc)
    content = builder.to_content()
    issues: list[dict] = []
    try:
        bp = _bp_model(tc)
        objective_ids = {item.id for item in bp.objectives}
        knowledge_ids = {item.id for item in bp.knowledge_points}
        stage_ids = {item.segment_id for item in bp.timeline}
    except Exception:  # noqa: BLE001  蓝图异常时跳过引用检查
        return ToolResult(output={"passed": True, "issues": [], "blocking": [], "note": "蓝图不可用，跳过引用校验。"})

    def _check(location: str, objective_refs: list[str], knowledge_refs: list[str], source_refs: list[str]) -> None:
        for ref in objective_refs:
            if ref not in objective_ids:
                issues.append(_issue("critical", f"{location}.objective_ids", "alignment",
                                     f"引用了不存在的目标 {ref}", "改为已批准蓝图中的目标 ID"))
        for ref in knowledge_refs:
            if ref not in knowledge_ids:
                issues.append(_issue("critical", f"{location}.knowledge_point_ids", "alignment",
                                     f"引用了不存在的知识点 {ref}", "改为已批准蓝图中的知识点 ID"))
        for ref in source_refs:
            if ref not in stage_ids and ref not in (bp.source_refs or []):
                issues.append(_issue("major", f"{location}.source_refs", "alignment",
                                     f"引用了不存在的教学环节或材料 {ref}", "使用蓝图环节 ID 或合法材料来源"))

    for section_index, section in enumerate(content.get("sections", [])):
        for block in section.get("blocks", []):
            location = f"$.sections[{section_index}].blocks[{block.get('id')}]"
            if block.get("kind") == "question":
                _check(location, block.get("objective_ids", []), block.get("knowledge_point_ids", []), block.get("source_refs", []))
            elif block.get("kind") == "question_group":
                for question in block.get("sub_questions", []):
                    sub = f"{location}.sub_questions[{question.get('id')}]"
                    _check(sub, question.get("objective_ids", []), question.get("knowledge_point_ids", []), question.get("source_refs", []))
    blocking = _blocking(issues)
    return ToolResult(output={
        "passed": not blocking,
        "issues": issues,
        "blocking": blocking,
        "summary": f"引用校验{'通过' if not blocking else f'发现 {len(blocking)} 个阻断问题'}",
    })


class ValidateScoringInput(BaseModel):
    pass


async def _exercise_validate_scoring(tc: ToolContext, _: ValidateScoringInput) -> ToolResult:
    """校验分值守恒：三分区总分=100、每区题目分值之和=分区分值、主观题评分点之和=题目分值。"""
    from app.agent.agents.exercise.qa import blocking_issues as _blocking, issue as _issue

    builder = _builder(tc)
    content = builder.to_content()
    issues: list[dict] = []
    paper = content.get("paper_settings", {})
    total = int(paper.get("total_score", 0))
    sections = content.get("sections", [])
    if total != 100:
        issues.append(_issue("critical", "$.paper_settings.total_score", "scoring",
                             f"V2 课后练习总分必须为 100 分（当前 {total}）", "重新分配各分区和题目分值"))
    section_total = sum(int(s.get("score", 0)) for s in sections)
    if total == 100 and section_total != 100:
        issues.append(_issue("critical", "$.sections", "scoring",
                             f"三分区分值之和 {section_total} 不等于试卷总分 100", "调整分区分值"))

    def _question_score_sum(block: dict[str, Any]) -> int:
        if block.get("kind") == "question":
            return int(block.get("score", 0))
        if block.get("kind") == "question_group":
            return sum(int(item.get("score", 0)) for item in block.get("sub_questions", []))
        return 0

    for section_index, section in enumerate(sections):
        loc = f"$.sections[{section_index}]"
        question_sum = sum(_question_score_sum(block) for block in section.get("blocks", []))
        section_score = int(section.get("score", 0))
        if question_sum != section_score:
            issues.append(_issue("critical", f"{loc}.blocks", "scoring",
                                 f"分区 {section.get('id')} 题目分值之和 {question_sum} 不等于分区分值 {section_score}",
                                 "调整题目分值或分区分值"))
        for block in section.get("blocks", []):
            questions = block.get("sub_questions", []) if block.get("kind") == "question_group" else [block]
            for question in questions:
                score = int(question.get("score", 0))
                points = sum(int(item.get("points", 0)) for item in question.get("scoring_points", []))
                if question.get("question_type") in {"short_answer", "calculation", "case_analysis", "practical_task"}:
                    if points != score:
                        issues.append(_issue("critical", f"{loc}.blocks", "scoring",
                                             f"题目 {question.get('id')} 评分点分值之和 {points} 不等于题目分值 {score}",
                                             "调整评分点分值"))
    blocking = _blocking(issues)
    # 在返回值里附上当前各分区和题目分值快照，帮助 scoring_guard 直接看到
    # 需要修改哪道题，避免只看到"不守恒"错误后反复 validate 空转。
    sections_snapshot = []
    for section in content.get("sections", []):
        questions_snapshot = []
        for block in section.get("blocks", []):
            if block.get("kind") == "question":
                questions_snapshot.append({
                    "id": block.get("id"),
                    "type": block.get("question_type"),
                    "score": block.get("score"),
                    "scoring_points_sum": sum(int(p.get("points", 0)) for p in block.get("scoring_points", [])),
                })
            elif block.get("kind") == "question_group":
                for q in block.get("sub_questions", []):
                    questions_snapshot.append({
                        "id": q.get("id"),
                        "type": q.get("question_type"),
                        "score": q.get("score"),
                        "group": block.get("id"),
                        "scoring_points_sum": sum(int(p.get("points", 0)) for p in q.get("scoring_points", [])),
                    })
        sections_snapshot.append({
            "id": section.get("id"),
            "score": section.get("score"),
            "question_score_sum": sum(_question_score_sum(b) for b in section.get("blocks", [])),
            "questions": questions_snapshot,
        })
    return ToolResult(output={
        "passed": not blocking,
        "issues": issues,
        "blocking": blocking,
        "summary": f"分值守恒校验{'通过' if not blocking else f'发现 {len(blocking)} 个阻断问题'}",
        "current_scores": {
            "total_score": total,
            "section_total": section_total,
            "sections": sections_snapshot,
        },
    })


def _register_check_tools() -> None:
    register_tool(Tool(
        "exercise_validate_rules", "确定性规则门禁：结构/引用/认知层级/总分/任务单复用/用时",
        ValidateRulesInput, _exercise_validate_rules,
    ))
    register_tool(Tool(
        "exercise_validate_references", "引用合法性校验：目标/知识点/环节 ID 必须来自蓝图",
        ValidateReferencesInput, _exercise_validate_references,
    ))
    register_tool(Tool(
        "exercise_validate_scoring", "分值守恒校验：总分 100 / 分区=题目之和 / 评分点=题目分值",
        ValidateScoringInput, _exercise_validate_scoring,
    ))
