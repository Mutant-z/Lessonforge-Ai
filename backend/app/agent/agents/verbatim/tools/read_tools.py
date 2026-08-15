"""教师逐字稿工具集：读取类工具。

通过全局注册表（app.agent.registry）注册，使用 vb_ 前缀避免与 PPT / task_sheet
工具重名冲突。只读，不修改任何状态。

- vb_get_context：课程身份 / 蓝图目标 / 学习者 / 材料摘要。
- vb_get_source：当前正式 Artifact（源版本，V1/V2 均可）。
- vb_get_scenes：视频脚本场景（含时间轴、必需术语/数字/结论、声音指导）。
- vb_inspect_sections：当前候选稿章节（含确定性时长）。
- vb_get_locks：当前任务文件锁定路径。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.agents.verbatim.tools._common import _builder, _lock_paths, _video_script_raw
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool, summarize


def _blueprint_data(tc: ToolContext) -> dict[str, Any]:
    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    return blueprint.model_dump() if hasattr(blueprint, "model_dump") else (blueprint or {})


def _knowledge(tc: ToolContext) -> dict[str, Any]:
    if tc.runtime is not None and getattr(tc.runtime, "knowledge_context", None):
        return dict(tc.runtime.knowledge_context)
    return dict(tc.ctx.knowledge) if tc.ctx is not None and getattr(tc.ctx, "knowledge", None) else {}


class GetVerbatimContextInput(BaseModel):
    pass


async def _vb_get_context(tc: ToolContext, _: GetVerbatimContextInput) -> ToolResult:
    """读取课程身份、蓝图目标/知识点/教学环节与学习者画像。"""
    bp_data = _blueprint_data(tc)
    course = bp_data.get("course_identity", {})
    knowledge = _knowledge(tc)
    summary = knowledge.get("agent_profile_summary") or {}
    return ToolResult(output={
        "course_identity": course,
        "objectives": [
            {"id": item.get("id"), "statement": item.get("behavior"), "criterion": item.get("criterion")}
            for item in bp_data.get("objectives", [])
        ],
        "knowledge_points": [item.get("name") for item in bp_data.get("knowledge_points", [])],
        "key_points": bp_data.get("key_points", []),
        "learner_profile": summary.get("learner_profile") or course.get("audience", ""),
        "style_guidelines": summary.get("style_guidelines") or [],
        "note": "已批准蓝图是逐字稿事实的权威来源。",
    })


class GetVerbatimSourceInput(BaseModel):
    pass


async def _vb_get_source(tc: ToolContext, _: GetVerbatimSourceInput) -> ToolResult:
    """读取当前正式 Artifact（源版本内容与版本号）。"""
    source = getattr(tc.runtime, "source_artifact", None)
    content = getattr(source, "content_json", None) if source else None
    if content is None:
        return ToolResult(output={
            "has_source": False, "schema_version": None,
            "note": "逐字稿尚未生成，本轮为首次生成。",
        })
    return ToolResult(output={
        "has_source": True,
        "version": getattr(source, "version", 0),
        "schema_version": content.get("schema_version"),
        "content": content,
        "markdown": getattr(source, "content_markdown", "") or "",
    })


class GetVerbatimScenesInput(BaseModel):
    pass


async def _vb_get_scenes(tc: ToolContext, _: GetVerbatimScenesInput) -> ToolResult:
    """读取视频脚本场景：时间轴、口播、必需术语/数字/结论、声音指导。"""
    raw = _video_script_raw(tc)
    scenes = (raw or {}).get("scenes", []) or []
    result = []
    for scene in scenes:
        result.append({
            "id": scene.get("id"),
            "sequence": scene.get("sequence"),
            "title": scene.get("title"),
            "pedagogical_role": scene.get("pedagogical_role"),
            "start_seconds": scene.get("start_seconds"),
            "end_seconds": scene.get("end_seconds"),
            "spoken_text": scene.get("spoken_text"),
            "required_terms": scene.get("required_terms") or [],
            "required_numbers": scene.get("required_numbers") or [],
            "required_facts": scene.get("required_facts") or [],
            "voice_direction": scene.get("voice_direction"),
            "production_notes": scene.get("production_notes") or [],
        })
    return ToolResult(output={
        "scene_count": len(result),
        "scenes": result,
        "note": "逐字稿每段必须对齐一个 scene_id；必需术语/数字/结论在改写口播时不得丢失。",
    })


class InspectVerbatimSectionsInput(BaseModel):
    section_ids: list[str] = Field(default_factory=list, description="要查看的章节 ID；空 = 全部")


async def _vb_inspect_sections(tc: ToolContext, inp: InspectVerbatimSectionsInput) -> ToolResult:
    """读取当前候选稿章节（含确定性字数与口播时长）。"""
    builder = _builder(tc)
    from app.schemas.verbatim_v2 import format_clock

    sections = []
    for section in builder.sections:
        if inp.section_ids and section.get("id") not in inp.section_ids:
            continue
        sections.append({
            "id": section.get("id"),
            "scene_id": section.get("scene_id"),
            "time_range": f"{format_clock(float(section.get('start_seconds', 0)))}—{format_clock(float(section.get('end_seconds', 0)))}",
            "start_seconds": section.get("start_seconds"),
            "end_seconds": section.get("end_seconds"),
            "pedagogical_action": section.get("pedagogical_action"),
            "delivery_tone": section.get("delivery_tone"),
            "required_text": section.get("required_text"),
            "optional_text": section.get("optional_text"),
            "key_emphasis": section.get("key_emphasis"),
            "interaction": section.get("interaction"),
            "pause_seconds": section.get("pause_seconds"),
            "word_count": section.get("word_count"),
            "estimated_duration_seconds": section.get("estimated_duration_seconds"),
        })
    return ToolResult(output={
        "section_count": len(sections),
        "speaking_rate_cps": builder.speaking_rate_cps,
        "total_duration": builder.total_duration(),
        "sections": sections,
    })


class GetVerbatimLocksInput(BaseModel):
    pass


async def _vb_get_locks(tc: ToolContext, _: GetVerbatimLocksInput) -> ToolResult:
    """读取当前任务文件的锁定路径。"""
    return ToolResult(output={"locked_paths": [p for p in _lock_paths(tc) if p]})


def _register_read_tools() -> None:
    register_tool(Tool("vb_get_context", "读取课程身份/蓝图目标/学习者与风格要求",
                       GetVerbatimContextInput, _vb_get_context))
    register_tool(Tool("vb_get_source", "读取当前正式逐字稿 Artifact（源版本）",
                       GetVerbatimSourceInput, _vb_get_source))
    register_tool(Tool("vb_get_scenes", "读取视频脚本场景（时间轴/必需术语/数字/结论）",
                       GetVerbatimScenesInput, _vb_get_scenes))
    register_tool(Tool("vb_inspect_sections", "读取当前候选稿章节（含确定性字数与时长）",
                       InspectVerbatimSectionsInput, _vb_inspect_sections))
    register_tool(Tool("vb_get_locks", "读取当前任务文件锁定路径",
                       GetVerbatimLocksInput, _vb_get_locks))
