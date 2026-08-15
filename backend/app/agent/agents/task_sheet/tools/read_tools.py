"""学习任务单工具集：读取类工具（方案 §2.3）。

所有读取工具通过全局注册表（app.agent.registry）注册，使用 task_sheet_ 前缀
避免与 PPT / lesson_plan 工具重名冲突。只读，不修改任何状态。

- task_sheet_get_blueprint：已批准蓝图（目标/知识点/环节/时长）。
- task_sheet_get_lesson_plan：教学设计稳定内核（软参考）。
- task_sheet_get_source：当前正式 Artifact（源版本，V1/V2/V3 均可）。
- task_sheet_get_profile：Agent Profile 摘要（项目背景/学习者/材料摘要）。
- task_sheet_search_materials：材料摘要搜索（按关键字过滤）。
- task_sheet_get_siblings：兄弟产物摘要（软参考）。
- task_sheet_get_locks：当前任务文件锁定路径。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agent.agents.task_sheet.tools._common import _builder, _lock_paths
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool, summarize


def _blueprint_data(tc: ToolContext) -> dict[str, Any]:
    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    return blueprint.model_dump() if hasattr(blueprint, "model_dump") else (blueprint or {})


def _knowledge(tc: ToolContext) -> dict[str, Any]:
    if tc.runtime is not None and getattr(tc.runtime, "knowledge_context", None):
        return dict(tc.runtime.knowledge_context)
    return dict(tc.ctx.knowledge) if tc.ctx is not None and getattr(tc.ctx, "knowledge", None) else {}


class GetTaskSheetBlueprintInput(BaseModel):
    pass


async def _task_sheet_get_blueprint(tc: ToolContext, _: GetTaskSheetBlueprintInput) -> ToolResult:
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
        "note": "已批准蓝图是任务单的权威事实源。",
    })


class GetTaskSheetLessonPlanInput(BaseModel):
    pass


async def _task_sheet_get_lesson_plan(tc: ToolContext, _: GetTaskSheetLessonPlanInput) -> ToolResult:
    """读取教学设计稳定内核（教学环节/活动/证据，软参考，不阻塞生成）。"""
    knowledge = _knowledge(tc)
    raw = (
        knowledge.get("hard_dependencies", {}).get("lesson_plan")
        or knowledge.get("sibling_artifacts", {}).get("lesson_plan")
        or {}
    )
    content = raw.get("content") if isinstance(raw, dict) else raw
    if not isinstance(content, dict) or not content:
        return ToolResult(output={
            "available": False,
            "note": "教学设计不存在或尚未生成；任务单按已批准蓝图独立生成，不阻塞。",
        })
    from app.schemas.lesson_plan import lesson_plan_core

    try:
        core = lesson_plan_core(content)
    except Exception:  # noqa: BLE001  结构非法的兄弟产物按缺失处理
        return ToolResult(output={"available": False, "note": "教学设计结构无法解析，按软参考忽略。"})
    return ToolResult(output={
        "available": True,
        "version": raw.get("version") if isinstance(raw, dict) else None,
        "core": core,
        "note": "教学设计仅作软参考；与已批准蓝图冲突时以蓝图为准。",
    })


class GetTaskSheetSourceInput(BaseModel):
    pass


async def _task_sheet_get_source(tc: ToolContext, _: GetTaskSheetSourceInput) -> ToolResult:
    """读取当前正式 Artifact（源版本内容与版本号）。"""
    source = getattr(tc.runtime, "source_artifact", None)
    content = getattr(source, "content_json", None) if source else None
    if content is None:
        return ToolResult(output={
            "has_source": False, "schema_version": None,
            "note": "任务文件尚未生成，本轮为首次生成。",
        })
    return ToolResult(output={
        "has_source": True,
        "version": getattr(source, "version", 0),
        "schema_version": content.get("schema_version"),
        "content": content,
        "markdown": getattr(source, "content_markdown", "") or "",
    })


class GetTaskSheetProfileInput(BaseModel):
    pass


async def _task_sheet_get_profile(tc: ToolContext, _: GetTaskSheetProfileInput) -> ToolResult:
    """读取 Agent Profile 摘要（项目背景、学习者画像、材料摘要）。"""
    knowledge = _knowledge(tc)
    summary = knowledge.get("agent_profile_summary") or {}
    profile = getattr(tc.runtime, "profile", None)
    context_json = getattr(profile, "context_json", None) or {}
    merged = {
        key: summary.get(key) or context_json.get(key)
        for key in (
            "project_background", "project_requirement_summary", "learner_profile",
            "content_scope", "required_source_refs", "material_summaries",
        )
    }
    return ToolResult(output={"profile": {k: v for k, v in merged.items() if v is not None}})


class SearchTaskSheetMaterialsInput(BaseModel):
    query: str = ""
    limit: int = 8


async def _task_sheet_search_materials(tc: ToolContext, inp: SearchTaskSheetMaterialsInput) -> ToolResult:
    """搜索课程材料摘要（按关键字过滤，返回截断摘要，不返回材料原始全文）。"""
    knowledge = _knowledge(tc)
    summary = knowledge.get("agent_profile_summary") or {}
    materials = summary.get("material_summaries") or []
    results = []
    query = (inp.query or "").strip()
    for material in materials:
        text = str(material.get("summary") or material.get("content") or "")
        if query and query not in text and query not in str(material.get("filename", "")):
            continue
        results.append({
            "id": material.get("id"),
            "filename": material.get("filename", ""),
            "summary": summarize(text, 600),
        })
        if len(results) >= inp.limit:
            break
    return ToolResult(output={
        "count": len(results), "results": results,
        "note": "材料仅作参考，不替换已批准蓝图与教师指令。",
    })


class GetTaskSheetSiblingsInput(BaseModel):
    kinds: list[str] = []


async def _task_sheet_get_siblings(tc: ToolContext, inp: GetTaskSheetSiblingsInput) -> ToolResult:
    """读取兄弟产物摘要（教学设计/PPT/练习等，软参考）。"""
    knowledge = _knowledge(tc)
    siblings = {
        **knowledge.get("hard_dependencies", {}),
        **knowledge.get("sibling_artifacts", {}),
    }
    if inp.kinds:
        siblings = {kind: value for kind, value in siblings.items() if kind in inp.kinds}
    return ToolResult(output={
        "siblings": {
            kind: summarize(value.get("content") if isinstance(value, dict) else value, 1500)
            for kind, value in siblings.items()
        },
        "note": "兄弟产物仅作软参考；与已批准蓝图冲突时以蓝图为准。",
    })


class GetTaskSheetLocksInput(BaseModel):
    pass


async def _task_sheet_get_locks(tc: ToolContext, _: GetTaskSheetLocksInput) -> ToolResult:
    """读取当前任务文件的锁定路径。"""
    return ToolResult(output={"locked_paths": [p for p in _lock_paths(tc) if p]})


def _register_read_tools() -> None:
    register_tool(Tool("task_sheet_get_blueprint", "读取已批准蓝图（目标/知识点/教学环节/时长）",
                       GetTaskSheetBlueprintInput, _task_sheet_get_blueprint))
    register_tool(Tool("task_sheet_get_lesson_plan", "读取教学设计稳定内核（软参考）",
                       GetTaskSheetLessonPlanInput, _task_sheet_get_lesson_plan))
    register_tool(Tool("task_sheet_get_source", "读取当前正式任务单 Artifact（源版本）",
                       GetTaskSheetSourceInput, _task_sheet_get_source))
    register_tool(Tool("task_sheet_get_profile", "读取 Agent Profile 摘要（项目背景/学习者/材料）",
                       GetTaskSheetProfileInput, _task_sheet_get_profile))
    register_tool(Tool("task_sheet_search_materials", "搜索课程材料摘要（不返回原始全文）",
                       SearchTaskSheetMaterialsInput, _task_sheet_search_materials))
    register_tool(Tool("task_sheet_get_siblings", "读取兄弟产物摘要（教学设计/PPT/练习等软参考）",
                       GetTaskSheetSiblingsInput, _task_sheet_get_siblings))
    register_tool(Tool("task_sheet_get_locks", "读取当前任务文件锁定路径",
                       GetTaskSheetLocksInput, _task_sheet_get_locks))
