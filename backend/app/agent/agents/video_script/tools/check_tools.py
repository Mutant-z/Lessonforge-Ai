"""视频脚本工具集：检查与输出类工具。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.agents.video_script.tools.read_tools import _blueprint_data, _builder, _lesson_plan_raw, _locked_paths
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool

VALIDATE_SCOPES = {"all", "structure", "references", "timeline", "pacing", "fact_baseline", "seedance_contract", "locks"}


class ValidateVideoScriptDraftInput(BaseModel):
    scope: str = Field(default="all", pattern="^(all|structure|references|timeline|pacing|fact_baseline|seedance_contract|locks)$")


async def _vs_validate_draft(tc: ToolContext, inp: ValidateVideoScriptDraftInput) -> ToolResult:
    """运行确定性质量门禁，返回问题列表（scope 过滤检查维度）。"""
    from app.agent.agents.video_script.qa import blocking_issues, validate_video_script_v4

    builder = _builder(tc)
    bp_data = _blueprint_data(tc)
    from app.schemas.blueprint import CourseBlueprintSchema

    issues = validate_video_script_v4(
        CourseBlueprintSchema.model_validate(bp_data),
        builder.to_content(),
        _lesson_plan_raw(tc),
        [path for path in _locked_paths(tc) if path],
        max_scene_seconds=float((getattr(tc.runtime, "request_metadata", {}) or {}).get("renderer_max_scene_seconds") or 15),
    )
    if inp.scope != "all":
        dimension_scope = {
            "structure": {"structure", "integrity"},
            "references": {"alignment"},
            "timeline": {"timing"},
            "pacing": {"timing", "integrity"},
            "fact_baseline": {"consistency"},
            "seedance_contract": {"production"},
            "locks": {"lock"},
        }.get(inp.scope, set())
        issues = [item for item in issues if item.get("dimension") in dimension_scope]
    return ToolResult(output={
        "scope": inp.scope,
        "issues": issues,
        "blocking_count": len(blocking_issues(issues)),
        "passed": not blocking_issues(issues),
    })


class ComputeVideoScriptDiffInput(BaseModel):
    pass


async def _vs_compute_diff(tc: ToolContext, _: ComputeVideoScriptDiffInput) -> ToolResult:
    """对比候选稿与正式源版本（ID 感知的章节与分镜差异）。"""
    builder = _builder(tc)
    source = getattr(tc.runtime, "source_artifact", None)
    source_content = getattr(source, "content_json", None) if source else None
    return ToolResult(output=builder.diff(source_content))


class RenderVideoScriptPreviewInput(BaseModel):
    format: str = Field(default="markdown", pattern="^(markdown|json)$")


async def _vs_render_preview(tc: ToolContext, inp: RenderVideoScriptPreviewInput) -> ToolResult:
    """渲染候选稿 Markdown / JSON 预览。"""
    from app.schemas.video_script_v4 import video_script_v4_to_markdown

    builder = _builder(tc)
    content = builder.to_content()
    if inp.format == "json":
        return ToolResult(output={"format": "json", "content": content})
    markdown = video_script_v4_to_markdown(content)
    return ToolResult(output={"format": "markdown", "markdown": markdown[:8000], "content": content})


def _register_check_tools() -> None:
    register_tool(Tool("vs_validate_draft", "运行视频脚本确定性质量门禁（结构/引用/时间/语速/事实/可执行/锁定）",
                       ValidateVideoScriptDraftInput, _vs_validate_draft))
    register_tool(Tool("vs_compute_diff", "对比候选稿与正式源版本的章节与分镜差异",
                       ComputeVideoScriptDiffInput, _vs_compute_diff))
    register_tool(Tool("vs_render_preview", "渲染候选稿 Markdown/JSON 预览",
                       RenderVideoScriptPreviewInput, _vs_render_preview))
