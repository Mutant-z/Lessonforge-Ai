"""课后练习工具集：读取类工具。

所有读取工具通过全局注册表（app.agent.registry）注册，使用 exercise_ 前缀
避免与其他 Agent 工具重名冲突。只读，不修改任何状态。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agent.registry import Tool, ToolContext, ToolResult, register_tool, summarize


def _blueprint_data(tc: ToolContext) -> dict[str, Any]:
    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    return blueprint.model_dump() if hasattr(blueprint, "model_dump") else (blueprint or {})


def _knowledge(tc: ToolContext) -> dict[str, Any]:
    if tc.runtime is not None and getattr(tc.runtime, "knowledge_context", None):
        return dict(tc.runtime.knowledge_context)
    return dict(tc.ctx.knowledge) if tc.ctx is not None and getattr(tc.ctx, "knowledge", None) else {}


def _sibling_raw(tc: ToolContext, kind: str) -> dict[str, Any]:
    knowledge = _knowledge(tc)
    raw = (
        knowledge.get("sibling_artifacts", {}).get(kind)
        or knowledge.get("hard_dependencies", {}).get(kind)
        or {}
    )
    if isinstance(raw, dict):
        raw = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    return raw if isinstance(raw, dict) else {}


class GetExerciseBlueprintInput(BaseModel):
    pass


async def _exercise_get_blueprint(tc: ToolContext, _: GetExerciseBlueprintInput) -> ToolResult:
    """读取已批准蓝图：目标、知识点、教学环节（含时长）与课程身份。"""
    bp_data = _blueprint_data(tc)
    return ToolResult(output={
        "course_identity": bp_data.get("course_identity", {}),
        "objectives": [
            {"id": item.get("id"), "statement": item.get("behavior"),
             "condition": item.get("condition"), "criterion": item.get("criterion")}
            for item in bp_data.get("objectives", [])
        ],
        "knowledge_points": [
            {"id": item.get("id"), "name": item.get("name")}
            for item in bp_data.get("knowledge_points", [])
        ],
        "stages": [
            {"id": item.get("segment_id"), "name": item.get("name"),
             "start_minute": item.get("start_minute"), "end_minute": item.get("end_minute"),
             "duration_minutes": max(0.0, (item.get("end_minute", 0) or 0) - (item.get("start_minute", 0) or 0))}
            for item in bp_data.get("timeline", [])
        ],
        "key_points": bp_data.get("key_points", []),
        "difficulty_points": bp_data.get("difficulty_points", []),
        "assessment_plan": bp_data.get("assessment_plan", []),
        "note": "已批准蓝图是课后练习的权威事实源。",
    })


class GetExerciseLessonPlanInput(BaseModel):
    pass


async def _exercise_get_lesson_plan(tc: ToolContext, _: GetExerciseLessonPlanInput) -> ToolResult:
    """读取教学设计稳定内核（教学环节/活动/证据，软参考，不阻塞生成）。"""
    raw = _sibling_raw(tc, "lesson_plan")
    if not raw:
        return ToolResult(output={
            "available": False,
            "note": "教学设计不存在或尚未生成；课后练习按已批准蓝图独立生成，不阻塞。",
        })
    from app.schemas.lesson_plan import lesson_plan_core

    try:
        core = lesson_plan_core(raw)
    except Exception:  # noqa: BLE001  结构非法的兄弟产物按缺失处理
        return ToolResult(output={"available": False, "note": "教学设计结构无法解析，按软参考忽略。"})
    return ToolResult(output={
        "available": True,
        "core": core,
        "note": "教学设计仅作软参考；与已批准蓝图冲突时以蓝图为准。",
    })


class GetExerciseTaskSheetInput(BaseModel):
    pass


async def _exercise_get_task_sheet(tc: ToolContext, _: GetExerciseTaskSheetInput) -> ToolResult:
    """读取学习任务单（软参考）。课后练习可借鉴其目标、情境与支架，但不得复用任务步骤或过程性问题。"""
    raw = _sibling_raw(tc, "task_sheet")
    if not raw:
        return ToolResult(output={
            "available": False,
            "note": "学习任务单不存在或尚未生成；课后练习按已批准蓝图独立生成，不阻塞。",
        })
    return ToolResult(output={
        "available": True,
        "schema_version": raw.get("schema_version"),
        "content": raw,
        "note": "不得直接复用任务单的任务步骤、过程性问题或完成标准；保留目标但重新设计独立测评情境。",
    })


class GetExerciseSourceInput(BaseModel):
    pass


async def _exercise_get_source(tc: ToolContext, _: GetExerciseSourceInput) -> ToolResult:
    """读取当前内存候选稿；正式 Artifact 仅提供基准版本号。"""
    source = getattr(tc.runtime, "source_artifact", None)
    builder = tc.extra.get("builder")
    content = builder.to_content() if builder is not None else None
    if content is None:
        return ToolResult(output={
            "has_source": False, "schema_version": None,
            "note": "任务文件尚未生成，本轮为首次生成。",
        })
    return ToolResult(output={
        "has_source": source is not None,
        "version": getattr(source, "version", 0),
        "base_version": getattr(source, "version", 0),
        "builder_revision": builder.revision,
        "schema_version": content.get("schema_version"),
        "content": content,
        "question_type_counts": builder.question_type_counts(),
        "questions": builder.question_snapshot(),
        "section_scores": [
            {"id": item.get("id"), "title": item.get("title"), "score": item.get("score")}
            for item in builder.sections
        ],
        "note": "返回当前候选稿而非正式旧版本；后续规划必须以 builder_revision 为准。",
    })


class GetExerciseProfileInput(BaseModel):
    pass


async def _exercise_get_profile(tc: ToolContext, _: GetExerciseProfileInput) -> ToolResult:
    """读取 Agent Profile 摘要（项目背景/学习者/材料摘要/硬约束）。"""
    profile = getattr(tc.runtime, "profile", None)
    context = getattr(profile, "context_json", None) or {}
    return ToolResult(output={
        "project_background": context.get("project_background"),
        "learner_profile": context.get("learner_profile"),
        "prior_knowledge": context.get("prior_knowledge"),
        "likely_misconceptions": context.get("likely_misconceptions"),
        "content_scope": context.get("content_scope"),
        "material_summaries": context.get("material_summaries", []),
        "hard_constraints": context.get("hard_constraints", []),
        "objective_coverage_requirements": context.get("objective_coverage_requirements", []),
        "review_and_repair_requirements": context.get("review_and_repair_requirements", []),
        "note": "Profile 是项目专属配置；与已批准蓝图冲突时以蓝图为准。",
    })


class GetExerciseSiblingsInput(BaseModel):
    pass


async def _exercise_get_siblings(tc: ToolContext, _: GetExerciseSiblingsInput) -> ToolResult:
    """读取兄弟产物摘要（教学设计/PPT/任务单/视频脚本等，软参考）。"""
    knowledge = _knowledge(tc)
    siblings = knowledge.get("sibling_artifacts", {}) or {}
    summary: dict[str, Any] = {}
    for kind, entry in siblings.items():
        if not isinstance(entry, dict):
            continue
        content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
        summary[kind] = {
            "version": entry.get("version"),
            "status": entry.get("status"),
            "content": content,
        }
    return ToolResult(output={
        "siblings": summary,
        "note": "兄弟产物仅作软参考；课后练习只生成和维护自身任务文件。",
    })


class GetExerciseLocksInput(BaseModel):
    pass


async def _exercise_get_locks(tc: ToolContext, _: GetExerciseLocksInput) -> ToolResult:
    """读取当前任务文件锁定路径。"""
    from app.agent.agents.exercise.tools._common import _lock_paths

    return ToolResult(output={"locked_paths": _lock_paths(tc)})


def _register_read_tools() -> None:
    register_tool(Tool(
        "exercise_get_blueprint", "读取已批准蓝图（目标/知识点/教学环节/课程身份）",
        GetExerciseBlueprintInput, _exercise_get_blueprint,
    ))
    register_tool(Tool(
        "exercise_get_lesson_plan", "读取教学设计稳定内核（软参考）",
        GetExerciseLessonPlanInput, _exercise_get_lesson_plan,
    ))
    register_tool(Tool(
        "exercise_get_task_sheet", "读取学习任务单（软参考，禁止复用任务步骤）",
        GetExerciseTaskSheetInput, _exercise_get_task_sheet,
    ))
    register_tool(Tool(
        "exercise_get_source", "读取当前内存候选稿、基准版本、题型统计与分值摘要",
        GetExerciseSourceInput, _exercise_get_source,
    ))
    register_tool(Tool(
        "exercise_get_profile", "读取项目专属 Agent Profile 摘要",
        GetExerciseProfileInput, _exercise_get_profile,
    ))
    register_tool(Tool(
        "exercise_get_siblings", "读取兄弟产物摘要（教学设计/PPT/任务单等软参考）",
        GetExerciseSiblingsInput, _exercise_get_siblings,
    ))
    register_tool(Tool(
        "exercise_get_locks", "读取当前任务文件锁定路径",
        GetExerciseLocksInput, _exercise_get_locks,
    ))
