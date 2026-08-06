"""图片 / 图表工具：生成图片、图表 PNG、示意流程图。"""
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.mock_asset import generate_placeholder_image
from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.core.database import SessionLocal
from app.models.entities import AgentChatSession, CourseProject, ModelConfig
from app.services.model_config_service import resolve_model_config


def _palette(tc: ToolContext) -> dict[str, str]:
    if tc.builder is not None and tc.builder.design_system:
        return tc.builder.design_system.get("palette", {})
    if tc.ctx and tc.ctx.template:
        return tc.ctx.template.get("palette", {})
    return {}


async def _resolve_image_config(tc: ToolContext) -> ModelConfig | None:
    """优先课程 PPT 会话选择的图片模型，其次课程默认模型（非 mock）。"""
    if tc.course is None or getattr(tc.course, "id", None) is None:
        return None
    async with SessionLocal() as db:
        course = await db.get(CourseProject, tc.course.id)
        if not course:
            return None
        image_config_id = None
        session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course.id, AgentChatSession.module_type == "ppt",
        ))
        if session and session.image_model_config_id:
            image_config_id = session.image_model_config_id
        config = await resolve_model_config(db, course.owner_id, image_config_id or course.model_config_id)
        if config and config.provider != "mock":
            return config
    return None


class GenerateImageInput(BaseModel):
    prompt: str = Field(..., description="图片提示词（页面主题/用途/构图/禁止元素）")
    slide_id: str = ""
    asset_name: str = "slide_visual"
    size: str = Field(default="1024x768", description="宽x高")


async def _generate_image(tc: ToolContext, payload: GenerateImageInput) -> ToolResult:
    try:
        width, height = (int(part) for part in payload.size.lower().split("x"))
    except (ValueError, TypeError):
        width, height = 1024, 768
    palette = _palette(tc)
    assets_dir = (tc.workspace_root / "assets") if tc.workspace_root else Path("/tmp")
    assets_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{payload.asset_name or 'asset'}_{payload.slide_id or 'na'}.png"
    target = assets_dir / filename

    config = await _resolve_image_config(tc)
    provider_name = "mock_placeholder"
    if config is not None:
        try:
            from app.services.exercise_visual_service import generate_image as _real_generate
            raw, mime = await _real_generate(config, payload.prompt, f"{width}x{height}")
            suffix = ".png" if "png" in mime else ".jpg"
            target = target.with_suffix(suffix)
            target.write_bytes(raw)
            provider_name = f"{config.provider}:{config.model_name or config.name}"
        except Exception:  # noqa: BLE001 真实生成失败降级占位图
            provider_name = "mock_fallback"
    if not target.is_file():
        output, width, height = generate_placeholder_image(payload.prompt, palette, (width, height), target)

    artifact = None
    if tc.artifacts is not None:
        artifact = await tc.artifacts.create(
            "visual_asset", f"{payload.slide_id or 'slide'}:{payload.asset_name}",
            {"prompt": payload.prompt, "provider": provider_name, "slide_id": payload.slide_id},
            producer_agent=getattr(tc.ctx, "current_agent", "") if tc.ctx else "",
            producer_tool="generate_image",
        )
    if tc.emitter is not None:
        await tc.emitter.asset_generated("image", str(target.relative_to(tc.workspace_root)) if tc.workspace_root else str(target),
                                         width=width, height=height, prompt=payload.prompt)
    return ToolResult(ok=True, output={
        "asset_id": artifact["id"] if artifact else "",
        "file_path": str(target.relative_to(tc.workspace_root)) if tc.workspace_root else str(target),
        "width": width, "height": height, "provider": provider_name,
    })


class GenerateChartPngInput(BaseModel):
    chart_type: str = Field(default="bar", description="bar/line/pie")
    data: dict[str, Any] = Field(default_factory=dict)
    width: int = 960
    height: int = 540
    asset_name: str = "chart"


async def _generate_chart_png(tc: ToolContext, payload: GenerateChartPngInput) -> ToolResult:
    from app.agent.charting import render_chart_png
    assets_dir = (tc.workspace_root / "assets") if tc.workspace_root else Path("/tmp")
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / f"{payload.asset_name or 'chart'}.png"
    render_chart_png(payload.chart_type, payload.data, _palette(tc), (payload.width, payload.height), target)
    if tc.emitter is not None:
        await tc.emitter.asset_generated("chart", str(target.relative_to(tc.workspace_root)) if tc.workspace_root else str(target),
                                         width=payload.width, height=payload.height)
    return ToolResult(ok=True, output={"file_path": str(target.relative_to(tc.workspace_root)) if tc.workspace_root else str(target)})


class RenderDiagramInput(BaseModel):
    diagram_type: str = Field(default="flow", description="flow/architecture/timeline/matrix")
    spec: dict[str, Any] = Field(default_factory=dict)
    asset_name: str = "diagram"
    width: int = 960
    height: int = 540


async def _render_diagram(tc: ToolContext, payload: RenderDiagramInput) -> ToolResult:
    from app.agent.charting import render_diagram_png
    assets_dir = (tc.workspace_root / "assets") if tc.workspace_root else Path("/tmp")
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / f"{payload.asset_name or 'diagram'}.png"
    render_diagram_png(payload.diagram_type, payload.spec, _palette(tc), (payload.width, payload.height), target)
    if tc.emitter is not None:
        await tc.emitter.asset_generated("diagram", str(target.relative_to(tc.workspace_root)) if tc.workspace_root else str(target),
                                         width=payload.width, height=payload.height)
    return ToolResult(ok=True, output={"file_path": str(target.relative_to(tc.workspace_root)) if tc.workspace_root else str(target)})


def register_asset_tools():
    register_tool(Tool("generate_image", "生成页面配图（提示词含构图/留白/禁止元素；无图片模型时占位图）", GenerateImageInput, _generate_image))
    register_tool(Tool("generate_chart_png", "生成柱/线/饼图 PNG", GenerateChartPngInput, _generate_chart_png))
    register_tool(Tool("render_diagram", "生成流程/架构/时间线示意图 PNG", RenderDiagramInput, _render_diagram))


register_asset_tools()
