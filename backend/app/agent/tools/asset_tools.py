"""图片 / 图表工具：生成图片、图表 PNG、示意流程图。"""
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.mock_asset import generate_placeholder_image
from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AgentChatSession, ArtifactAsset, CourseProject, ModelConfig


def _palette(tc: ToolContext) -> dict[str, str]:
    if tc.builder is not None and tc.builder.design_system:
        return tc.builder.design_system.get("palette", {})
    if tc.ctx and tc.ctx.template:
        return tc.ctx.template.get("palette", {})
    return {}


async def _resolve_image_config(tc: ToolContext) -> ModelConfig | None:
    """Resolve and persist the PPT image model using the canonical precedence."""
    if tc.course is None or getattr(tc.course, "id", None) is None:
        return None
    async with SessionLocal() as db:
        course = await db.get(CourseProject, tc.course.id)
        if not course:
            return None
        session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course.id, AgentChatSession.module_type == "ppt",
        ))

        async def eligible(config_id: str | None) -> ModelConfig | None:
            if not config_id:
                return None
            config = await db.scalar(select(ModelConfig).where(
                ModelConfig.id == config_id, ModelConfig.owner_id == course.owner_id,
            ))
            if config and config.provider != "mock" and "image_generation" in (config.capabilities_json or []):
                return config
            return None

        config = await eligible(session.image_model_config_id if session else None)
        if config:
            return config
        config = await eligible(session.model_config_id if session else course.model_config_id)
        if config:
            if session is None:
                session = AgentChatSession(course_id=course.id, module_type="ppt", model_config_id=course.model_config_id)
                db.add(session)
            session.image_model_config_id = config.id
            await db.commit()
            return config
        candidates = list(await db.scalars(select(ModelConfig).where(
            ModelConfig.owner_id == course.owner_id,
            ModelConfig.provider != "mock",
        ).order_by(ModelConfig.updated_at.desc())))
        candidates = [item for item in candidates if "image_generation" in (item.capabilities_json or [])]
        if len(candidates) == 1:
            config = candidates[0]
            if session is None:
                session = AgentChatSession(course_id=course.id, module_type="ppt", model_config_id=course.model_config_id)
                db.add(session)
            session.image_model_config_id = config.id
            await db.commit()
            return config
    return None


class GenerateImageInput(BaseModel):
    prompt: str = Field(..., description="图片提示词（页面主题/用途/构图/禁止元素）")
    slide_id: str = ""
    asset_name: str = "slide_visual"
    visual_slot: str = "primary_visual"
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
    degraded_reason = "未配置具备 image_generation 能力的图片模型"
    mime = "image/png"
    strict = getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE"
    if config is None and strict:
        return ToolResult(
            ok=False,
            error="当前 PPT 会话未选择可用的图片模型，请先选择具备 image_generation 能力的模型。",
            error_code="image_model_required",
            retryable=False,
            output={"slide_id": payload.slide_id, "asset_name": payload.asset_name},
        )
    if config is not None:
        try:
            from app.services.exercise_visual_service import generate_image as _real_generate
            raw, mime = await _real_generate(config, payload.prompt, f"{width}x{height}")
            from PIL import Image
            with Image.open(BytesIO(raw)) as image:
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
            suffix = ".png" if "png" in mime else ".jpg"
            target = target.with_suffix(suffix)
            target.write_bytes(raw)
            provider_name = f"{config.provider}:{config.model_name or config.name}"
            degraded_reason = ""
        except Exception as exc:  # noqa: BLE001
            if strict:
                invalid = isinstance(exc, (ValueError, KeyError, TypeError))
                return ToolResult(
                    ok=False,
                    error=("图片接口返回了无法识别的图片数据。" if invalid else "图片模型调用失败，请检查模型端点后重试。"),
                    error_code="image_response_invalid" if invalid else "image_generation_failed",
                    retryable=not invalid,
                    output={
                        "slide_id": payload.slide_id, "asset_name": payload.asset_name,
                        "model_config_id": config.id, "detail": str(exc)[:300],
                    },
                )
            provider_name = "mock_fallback"
            degraded_reason = f"图片模型调用失败：{str(exc)[:240]}"
    if not target.is_file():
        output, width, height = generate_placeholder_image(payload.prompt, palette, (width, height), target)

    relative_file_path = str(target.relative_to(tc.workspace_root)) if tc.workspace_root else str(target)
    degraded = provider_name.startswith("mock_")
    browser_asset_id = ""
    if tc.course is not None and getattr(tc.course, "id", None):
        storage_root = get_settings().storage_root.resolve()
        resolved_target = target.resolve()
        if storage_root == resolved_target or storage_root in resolved_target.parents:
            raw = target.read_bytes()
            relative_storage_path = str(resolved_target.relative_to(storage_root))
            async with SessionLocal() as db:
                asset = ArtifactAsset(
                    owner_id=tc.course.owner_id,
                    course_id=tc.course.id,
                    generation_run_id=tc.generation_run_id or None,
                    asset_type="generated_image" if not degraded else "fallback_image",
                    relative_path=relative_storage_path,
                    mime_type=mime,
                    width=width,
                    height=height,
                    size_bytes=len(raw),
                    checksum=hashlib.sha256(raw).hexdigest(),
                    provider=provider_name,
                    model_name=(config.model_name if config is not None else "deterministic_placeholder"),
                    # 替代图同样允许工作台读取，但 review_json 明确标记 degraded，不能伪装成模型图片。
                    status="approved",
                    review_json={"passed": not degraded, "degraded": degraded, "reason": degraded_reason},
                )
                db.add(asset)
                await db.commit()
                await db.refresh(asset)
                browser_asset_id = asset.id

    artifact = None
    if tc.artifacts is not None:
        artifact = await tc.artifacts.create(
            "visual_asset", f"{payload.slide_id or 'slide'}:{payload.asset_name}",
            {
                "prompt": payload.prompt,
                "asset_name": payload.asset_name,
                "provider": provider_name,
                "slide_id": payload.slide_id,
                "file_path": relative_file_path,
                "asset_id": browser_asset_id,
                "visual_slot": payload.visual_slot,
                "width": width,
                "height": height,
                "degraded": degraded,
                "degraded_reason": degraded_reason,
            },
            producer_agent=getattr(tc.ctx, "current_agent", "") if tc.ctx else "",
            producer_tool="generate_image",
        )
    if tc.emitter is not None:
        await tc.emitter.asset_generated("image", relative_file_path,
                                         width=width, height=height, prompt=payload.prompt,
                                         asset_id=browser_asset_id, provider=provider_name, degraded=degraded,
                                         degraded_reason=degraded_reason)
    return ToolResult(ok=True, output={
        "asset_id": browser_asset_id,
        "pipeline_artifact_id": artifact["id"] if artifact else "",
        "file_path": relative_file_path,
        "preview_url": f"/api/v1/artifact-assets/{browser_asset_id}" if browser_asset_id else "",
        "width": width,
        "height": height,
        "provider": provider_name,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "visual_slot": payload.visual_slot,
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
    register_tool(Tool("generate_image", "生成页面配图；显式图片修改必须使用真实图片模型，失败时不生成替代图", GenerateImageInput, _generate_image, timeout_seconds=180))
    register_tool(Tool("generate_chart_png", "生成柱/线/饼图 PNG", GenerateChartPngInput, _generate_chart_png))
    register_tool(Tool("render_diagram", "生成流程/架构/时间线示意图 PNG", RenderDiagramInput, _render_diagram))


register_asset_tools()
