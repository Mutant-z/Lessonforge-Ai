"""教学设计工具集：读取类工具。

所有工具通过全局注册表（app.agent.registry）注册，使用 lesson_ 前缀避免与
PPT 工具重名冲突。只读，不修改任何状态。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel

from app.agent.agents.lesson_plan.context import build_lesson_plan_context_snapshot
from app.agent.agents.lesson_plan.tools._common import blueprint_schema, builder_for
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool, summarize


def _builder(tc: ToolContext):
    return builder_for(tc)


class GetLessonBlueprintInput(BaseModel):
    pass


async def _get_lesson_blueprint(tc: ToolContext, _: GetLessonBlueprintInput) -> ToolResult:
    try:
        data = blueprint_schema(tc).model_dump()
    except LookupError:
        return ToolResult(ok=False, error="上下文缺少课程蓝图", error_code="blueprint_missing", retryable=False)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=f"课程蓝图结构非法：{str(exc)[:300]}",
            error_code="blueprint_invalid",
            retryable=False,
        )
    return ToolResult(output={
        "blueprint": data,
        "objectives": [item.get("id") for item in data.get("objectives", [])],
        "stages": [item.get("segment_id") for item in data.get("timeline", [])],
    })


class GetLessonSourceInput(BaseModel):
    view: Literal["summary", "outline", "core", "section", "full"] = "summary"
    section_id: str | None = None


async def _get_lesson_source(tc: ToolContext, inp: GetLessonSourceInput) -> ToolResult:
    builder = _builder(tc)
    content = builder.to_content()
    base = {
        "schema_version": content.get("schema_version", "2.0"),
        "section_ids": builder.all_section_ids(),
    }
    if inp.view == "outline":
        return ToolResult(output={**base, "outline": content.get("outline", {})})
    if inp.view == "core":
        return ToolResult(output={**base, "course_info": content.get("course_info", {}), "pedagogical_core": content.get("pedagogical_core", {})})
    if inp.view == "section":
        if not inp.section_id:
            return ToolResult(ok=False, error="view=section 时必须提供 section_id", error_code="section_id_required", retryable=False)
        section = builder.find_section(inp.section_id)
        if section is None:
            return ToolResult(ok=False, error=f"章节不存在：{inp.section_id}", error_code="section_not_found", retryable=False)
        return ToolResult(output={**base, "section": section})
    if inp.view == "full":
        current_agent = getattr(tc.runtime, "current_agent_key", "") if tc.runtime else ""
        if current_agent != "finalizer":
            return ToolResult(ok=False, error="完整候选稿仅终稿角色可读取", error_code="source_view_forbidden", retryable=False)
        return ToolResult(output={**base, "content": content})
    core = content.get("pedagogical_core", {})
    outline = content.get("outline", {}).get("sections", [])
    return ToolResult(output={
        **base,
        "course_info": content.get("course_info", {}),
        "outline_summary": [
            {"id": item.get("id"), "title": item.get("title"), "coverage_refs": item.get("coverage_refs", [])}
            for item in outline
        ],
        "core_summary": {
            "objective_count": len(core.get("objectives", [])),
            "stage_count": len(core.get("stages", [])),
            "assessment_count": len(core.get("assessment_plan", [])),
            "has_homework": bool(core.get("homework")),
            "has_board_design": bool(core.get("board_design")),
            "has_reflection": bool(core.get("reflection")),
        },
    })


class GetLessonContextSnapshotInput(BaseModel):
    pass


async def _get_lesson_context_snapshot(tc: ToolContext, _: GetLessonContextSnapshotInput) -> ToolResult:
    """读取当前教学设计服务端统一生成的全局上下文快照。"""
    try:
        builder = _builder(tc)
        content = builder.to_content()
        runtime = tc.runtime
        bp_data = None
        try:
            bp_data = blueprint_schema(tc)
        except Exception:
            pass
        
        snapshot = build_lesson_plan_context_snapshot(
            content,
            blueprint=bp_data,
            artifact_id=getattr(getattr(runtime, "source_artifact", None), "id", ""),
            snapshot_version=1,
            requested_section_ids=getattr(runtime, "selected_section_ids", []),
            resolved_section_ids=getattr(runtime, "affected_section_ids", []),
            locked_paths=[getattr(lock, "json_path", "") for lock in (getattr(runtime, "locks", None) or [])],
            profile=getattr(getattr(runtime, "profile", None), "context_json", {}) if hasattr(getattr(runtime, "profile", None), "context_json") else getattr(runtime, "profile", {}),
            siblings=getattr(runtime, "knowledge_context", {}).get("sibling_artifacts") or {},
        )
        return ToolResult(output={"snapshot": snapshot.model_dump()})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"生成上下文快照失败：{str(exc)[:300]}", error_code="snapshot_error", retryable=False)


class GetLessonProfileInput(BaseModel):
    pass


async def _get_lesson_profile(tc: ToolContext, _: GetLessonProfileInput) -> ToolResult:
    profile = getattr(tc, "runtime", None)
    profile = getattr(profile, "profile", None) if profile else None
    context_json = getattr(profile, "context_json", None) if profile else None
    return ToolResult(output={"profile": context_json or {}})


class SearchLessonMaterialsInput(BaseModel):
    query: str = ""
    limit: int = 5


async def _search_lesson_materials(tc: ToolContext, inp: SearchLessonMaterialsInput) -> ToolResult:
    """检索当前课程材料摘要（不读取原始文件内容，仅返回摘要与片段）。"""
    materials = (tc.ctx.knowledge or {}).get("materials") if tc.ctx is not None else None
    summaries = materials if isinstance(materials, list) else []
    if not summaries:
        return ToolResult(output={"materials": [], "note": "当前上下文未注入课程材料摘要"})
    items = []
    for material in summaries:
        text = json.dumps(material, ensure_ascii=False, default=str)
        if not inp.query or inp.query in text:
            items.append(material)
        if len(items) >= inp.limit:
            break
    return ToolResult(output={"materials": items})


class GetLessonSiblingsInput(BaseModel):
    pass


async def _get_lesson_siblings(tc: ToolContext, _: GetLessonSiblingsInput) -> ToolResult:
    """读取兄弟产物摘要（下游参考），不读取原始文件。"""
    upstream = tc.ctx.upstream if tc.ctx is not None else {}
    return ToolResult(output={
        "siblings": {kind: summarize(value, 1200) for kind, value in upstream.items()},
        "note": "兄弟产物仅作软参考；与已批准蓝图冲突时以蓝图为准。",
    })


class GetLessonLocksInput(BaseModel):
    pass


async def _get_lesson_locks(tc: ToolContext, _: GetLessonLocksInput) -> ToolResult:
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    paths = [
        getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        for lock in (locks or [])
    ]
    return ToolResult(output={"locked_paths": [p for p in paths if p]})


def _register_read_tools() -> None:
    register_tool(Tool("lesson_get_blueprint", "读取已批准课程蓝图（目标/知识点/环节 ID 权威来源）",
                       GetLessonBlueprintInput, _get_lesson_blueprint, idempotent=True))
    register_tool(Tool("lesson_get_source", "按 summary/outline/core/section/full 投影读取教学设计候选稿",
                       GetLessonSourceInput, _get_lesson_source, idempotent=True))
    register_tool(Tool("lesson_get_context_snapshot", "读取当前教学设计服务端生成的全局上下文快照（章节树/事实映射/范围划分）",
                       GetLessonContextSnapshotInput, _get_lesson_context_snapshot, idempotent=True))
    register_tool(Tool("lesson_get_profile", "读取教学设计 Agent 的项目专属配置",
                       GetLessonProfileInput, _get_lesson_profile, idempotent=True))
    register_tool(Tool("lesson_search_materials", "按关键词检索当前课程材料摘要",
                       SearchLessonMaterialsInput, _search_lesson_materials, idempotent=True))
    register_tool(Tool("lesson_get_siblings", "读取兄弟产物（任务单/PPT/练习/脚本）摘要",
                       GetLessonSiblingsInput, _get_lesson_siblings, idempotent=True))
    register_tool(Tool("lesson_get_locks", "读取当前任务文件的锁定路径", GetLessonLocksInput, _get_lesson_locks, idempotent=True))
