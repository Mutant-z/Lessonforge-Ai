"""视频脚本工具集：读取类工具。

所有工具通过全局注册表（app.agent.registry）注册，使用 vs_ 前缀避免与
PPT / lesson_plan / task_sheet 工具重名冲突。只读，不修改任何状态。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agent.registry import Tool, ToolContext, ToolResult, register_tool, summarize


def _builder(tc: ToolContext):
    builder = tc.extra.get("builder")
    if builder is None:
        raise ValueError("候选稿 Builder 未初始化")
    return builder


def _blueprint_data(tc: ToolContext) -> dict[str, Any]:
    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    if hasattr(blueprint, "model_dump"):
        return blueprint.model_dump()
    return blueprint or {}


def _lesson_plan_raw(tc: ToolContext) -> dict[str, Any] | None:
    upstream = tc.ctx.upstream if tc.ctx is not None else {}
    raw = upstream.get("lesson_plan")
    if isinstance(raw, dict):
        raw = raw.get("content") or raw
    return raw if isinstance(raw, dict) else None


def _locked_paths(tc: ToolContext) -> list[str]:
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    return [
        getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        for lock in (locks or [])
    ]


class VideoScriptGetContextInput(BaseModel):
    pass


async def _vs_get_context(tc: ToolContext, _: VideoScriptGetContextInput) -> ToolResult:
    """读取课程、蓝图、教学设计、Profile 摘要与来源版本（不读取原始文件全文）。"""
    bp_data = _blueprint_data(tc)
    return ToolResult(output={
        "course": {
            "title": (bp_data.get("course_identity") or {}).get("title", ""),
            "duration_seconds": int((bp_data.get("course_identity") or {}).get("duration_minutes", 0) * 60),
        },
        "blueprint": {
            "objectives": [
                {"id": item.get("id"), "behavior": item.get("behavior"), "criterion": item.get("criterion")}
                for item in bp_data.get("objectives", [])
            ],
            "knowledge_points": [
                {"id": item.get("id"), "name": item.get("name")}
                for item in bp_data.get("knowledge_points", [])
            ],
            "timeline": [
                {"id": item.get("segment_id"), "name": item.get("name"),
                 "start_minute": item.get("start_minute"), "end_minute": item.get("end_minute"),
                 "purpose": item.get("purpose")}
                for item in bp_data.get("timeline", [])
            ],
        },
        "lesson_plan": summarize(_lesson_plan_raw(tc) or {}, 2000),
        "source_version": (
            getattr(getattr(tc.runtime, "source_artifact", None), "version", None)
            if tc.runtime else None
        ),
        "locked_paths": [path for path in _locked_paths(tc) if path],
        "note": "章节目录是动态的：数量、标题、顺序与分镜归属由 AI 根据课程内容与教师意图决定，没有固定目录。",
    })


class VideoScriptGetLocksInput(BaseModel):
    pass


async def _vs_get_locks(tc: ToolContext, _: VideoScriptGetLocksInput) -> ToolResult:
    """返回当前正式版本的锁定路径（局部锁定必须在编辑工具与最终 Diff 两层校验）。"""
    return ToolResult(output={"locked_paths": [path for path in _locked_paths(tc) if path]})


class InspectVideoScriptOutlineInput(BaseModel):
    pass


async def _vs_inspect_outline(tc: ToolContext, _: InspectVideoScriptOutlineInput) -> ToolResult:
    """返回动态章节大纲、覆盖目标与分镜归属情况。"""
    builder = _builder(tc)
    sections = [dict(item) for item in builder.sections]
    scene_counts: dict[str, int] = {}
    covered: set[str] = set()
    for scene in builder.scenes:
        sid = scene.get("section_id", "")
        scene_counts[sid] = scene_counts.get(sid, 0) + 1
        covered.update(scene.get("objective_ids") or [])
    return ToolResult(output={
        "schema_version": builder.to_content().get("schema_version"),
        "section_count": builder.count_sections(),
        "scene_count": builder.count_scenes(),
        "target_duration_seconds": builder.target_duration_seconds,
        "sections": [
            {"id": item.get("id"), "sequence": item.get("sequence"), "title": item.get("title"),
             "purpose": item.get("purpose"), "objective_ids": item.get("objective_ids", []),
             "knowledge_point_ids": item.get("knowledge_point_ids", []),
             "scene_count": scene_counts.get(item.get("id"), 0)}
            for item in sections
        ],
        "coverage": {
            "covered_objectives": sorted(covered),
            "uncovered_objectives": [],
        },
        "timeline": [
            {"id": scene.get("id"), "section_id": scene.get("section_id"),
             "start_seconds": scene.get("start_seconds"), "end_seconds": scene.get("end_seconds"),
             "duration_seconds": round(float(scene.get("end_seconds", 0)) - float(scene.get("start_seconds", 0)), 3),
             "title": scene.get("title"), "pedagogical_role": scene.get("pedagogical_role"),
             "continuity_group": scene.get("continuity_group")}
            for scene in builder.scenes
        ],
    })


class InspectVideoScriptSceneInput(BaseModel):
    section_id: str = ""
    scene_id: str = ""


async def _vs_inspect_scene(tc: ToolContext, inp: InspectVideoScriptSceneInput) -> ToolResult:
    """按章节 / 分镜查询当前草稿的分镜明细。"""
    builder = _builder(tc)
    scenes = [dict(scene) for scene in builder.scenes]
    if inp.section_id:
        scenes = [item for item in scenes if item.get("section_id") == inp.section_id]
    if inp.scene_id:
        scenes = [item for item in scenes if item.get("id") == inp.scene_id]
        if not scenes:
            return ToolResult(ok=False, error=f"分镜不存在：{inp.scene_id}", error_code="scene_not_found", retryable=False)
    return ToolResult(output={
        "scene_count": len(scenes),
        "scenes": scenes,
    })


def _register_read_tools() -> None:
    register_tool(Tool("vs_get_context", "读取课程、蓝图、教学设计、Profile 摘要与来源版本",
                       VideoScriptGetContextInput, _vs_get_context))
    register_tool(Tool("vs_get_locks", "返回当前正式版本的锁定路径",
                       VideoScriptGetLocksInput, _vs_get_locks))
    register_tool(Tool("vs_inspect_outline", "返回动态章节大纲、覆盖目标与分镜归属情况",
                       InspectVideoScriptOutlineInput, _vs_inspect_outline))
    register_tool(Tool("vs_inspect_scene", "按章节 / 分镜查询当前草稿的分镜明细",
                       InspectVideoScriptSceneInput, _vs_inspect_scene))
