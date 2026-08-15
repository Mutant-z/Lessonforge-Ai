"""教师逐字稿工具集：检查与输出类工具。"""

from __future__ import annotations

from pydantic import BaseModel

from app.agent.agents.verbatim.tools._common import _builder, _video_script_raw
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool


class ValidateVerbatimDraftInput(BaseModel):
    pass


async def _vb_validate_draft(tc: ToolContext, _: ValidateVerbatimDraftInput) -> ToolResult:
    """运行逐字稿完整质量门禁（结构/场景对齐/事实保留/时长/可讲性）。"""
    from app.agent.agents.verbatim.qa import blocking_issues, validate_verbatim_v2

    builder = _builder(tc)
    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    bp = blueprint.model_dump() if hasattr(blueprint, "model_dump") else (blueprint or {})
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    locked_paths = [
        getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        for lock in (locks or [])
    ]
    issues = validate_verbatim_v2(bp, builder.to_content(), _video_script_raw(tc), locked_paths)
    return ToolResult(output={
        "issues": issues,
        "blocking_count": len(blocking_issues(issues)),
        "passed": not blocking_issues(issues),
    })


class ComputeVerbatimDiffInput(BaseModel):
    pass


async def _vb_compute_diff(tc: ToolContext, _: ComputeVerbatimDiffInput) -> ToolResult:
    """对比候选稿与正式源版本的章节差异。"""
    builder = _builder(tc)
    source = getattr(tc.runtime, "source_artifact", None)
    source_content = getattr(source, "content_json", None) if source else None
    candidate = builder.to_content()
    if not source_content:
        return ToolResult(output={"is_new": True, "note": "首次生成，无源版本可对比"})
    if source_content.get("schema_version") != "2.0":
        return ToolResult(output={
            "is_new": True, "note": "源版本为 V1，本轮将生成首个 V2 版本", "migration_required": True,
        })
    source_sections = {str(item.get("id")): item for item in source_content.get("sections", [])}
    candidate_sections = {str(item.get("id")): item for item in candidate.get("sections", [])}
    added = sorted(set(candidate_sections) - set(source_sections))
    removed = sorted(set(source_sections) - set(candidate_sections))
    changed = sorted(
        section_id for section_id in set(source_sections) & set(candidate_sections)
        if source_sections[section_id].get("required_text") != candidate_sections[section_id].get("required_text")
        or source_sections[section_id].get("delivery_tone") != candidate_sections[section_id].get("delivery_tone")
        or source_sections[section_id].get("pause_seconds") != candidate_sections[section_id].get("pause_seconds")
    )
    return ToolResult(output={
        "added_sections": added, "removed_sections": removed, "changed_sections": changed,
        "changed": bool(added or removed or changed),
    })


class RenderVerbatimPreviewInput(BaseModel):
    format: str = "markdown"


async def _vb_render_preview(tc: ToolContext, inp: RenderVerbatimPreviewInput) -> ToolResult:
    """渲染候选稿 Markdown/内容预览。"""
    builder = _builder(tc)
    return ToolResult(output={
        "format": inp.format,
        "markdown": builder.to_markdown()[:8000],
        "content": builder.to_content(),
    })


def _register_check_tools() -> None:
    register_tool(Tool("vb_validate_draft", "运行逐字稿完整质量门禁（结构/对齐/事实/时长）",
                       ValidateVerbatimDraftInput, _vb_validate_draft))
    register_tool(Tool("vb_compute_diff", "对比候选稿与正式源版本的章节差异",
                       ComputeVerbatimDiffInput, _vb_compute_diff))
    register_tool(Tool("vb_render_preview", "渲染候选稿 Markdown/内容预览",
                       RenderVerbatimPreviewInput, _vb_render_preview))
