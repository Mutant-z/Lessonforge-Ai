"""几何蓝图图渲染 + 视觉模型自检工具。

- render_geometry_preview：把页面元素按比例画成 PNG（base64），供视觉模型检查
- review_geometry_vision：视觉模型审稿工具；无视觉能力的 provider 直接跳过
"""
import base64
import io
from typing import Any

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from app.agent.layouts.zones import (
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
    LayoutZones,
    zones_for,
)
from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.providers.llm.anthropic import AnthropicProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider

_SCALE = 72
_BG = (255, 255, 255)
_ZONE = (200, 220, 240)
_TEXT = (20, 20, 20)
_VISUAL = (255, 200, 200)


class ReviewIssue(BaseModel):
    """视觉自检发现的一条布局问题。"""

    kind: str = ""
    severity: str = "major"
    description: str = ""
    suggested_preset: str | None = None
    suggested_param: str | None = None


class ReviewVerdict(BaseModel):
    """视觉自检结论：pass=True 表示无需修改（JSON 键为 pass）。"""

    pass_: bool = Field(default=True, alias="pass", description="是否通过")
    issues: list[ReviewIssue] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


def render_geometry_preview(spec: dict[str, Any], zones: LayoutZones) -> str:
    """把页面元素按比例画成 PNG，返回 base64（PNG magic = iVBOR...）。"""
    width, height = int(SLIDE_WIDTH * _SCALE), int(SLIDE_HEIGHT * _SCALE)
    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)

    def rect(r, fill, outline="black"):
        draw.rectangle([int(r.x * _SCALE), int(r.y * _SCALE),
                        int(r.right * _SCALE), int(r.bottom * _SCALE)],
                       fill=fill, outline=outline, width=2)

    rect(zones.title_rail, _ZONE)
    rect(zones.body_column, (230, 245, 235))
    if zones.visual_slot:
        rect(zones.visual_slot, _VISUAL)
    for el in spec.get("elements") or []:
        x, y, w, h = (float(el.get(k) or 0) for k in ("x", "y", "w", "h"))
        if el.get("kind") in {"image", "chart"} or el.get("role") == "visual_panel":
            draw.rectangle([int(x * _SCALE), int(y * _SCALE), int((x + w) * _SCALE), int((y + h) * _SCALE)],
                           fill=(255, 235, 205), outline="orange", width=2)
        else:
            draw.rectangle([int(x * _SCALE), int(y * _SCALE), int((x + w) * _SCALE), int((y + h) * _SCALE)],
                           outline="black", width=2)
            label = str(el.get("text") or el.get("content_ref") or "")[:12]
            if label:
                draw.text((int(x * _SCALE) + 4, int(y * _SCALE) + 4), label, fill=_TEXT)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def provider_supports_vision(provider: Any) -> bool:
    # Chat attachments use a transparent provider facade.  Keep the capability
    # check based on the concrete provider as well as the facade's native method
    # so PPT visual QA is not accidentally skipped for an attached image.
    return isinstance(provider, (AnthropicProvider, OpenAICompatibleProvider)) or (
        callable(getattr(provider, "structured_with_image", None))
        and callable(getattr(provider, "structured_with_attachments", None))
        and getattr(provider, "name", "") in {"anthropic", "openai_compatible"}
    )


class RenderGeometryPreviewInput(BaseModel):
    slide_id: str = Field(min_length=1)


class ReviewGeometryVisionInput(BaseModel):
    slide_id: str = Field(min_length=1)


async def _render_geometry_preview(tc: ToolContext, payload: RenderGeometryPreviewInput) -> ToolResult:
    builder = tc.builder
    slide = builder.get_slide(payload.slide_id)
    template_id = str((builder.template or {}).get("id") or "")
    spec = {"slide_id": slide["id"], "elements": slide.get("elements") or []}
    zones = zones_for(template_id, str(slide.get("page_type") or "concept"))
    png = render_geometry_preview(spec, zones)
    return ToolResult(ok=True, output={"preview_png": png, "mime_type": "image/png"})


async def _review_geometry_vision(tc: ToolContext, payload: ReviewGeometryVisionInput) -> ToolResult:
    provider = getattr(tc.runtime, "provider", None)
    if not provider_supports_vision(provider):
        return ToolResult(ok=True, output={
            "verdict": {"pass": True, "issues": []}, "skipped": "no_vision",
        })
    builder = tc.builder
    slide = builder.get_slide(payload.slide_id)
    template_id = str((builder.template or {}).get("id") or "")
    spec = {"slide_id": slide["id"], "elements": slide.get("elements") or []}
    zones = zones_for(template_id, str(slide.get("page_type") or "concept"))
    png = render_geometry_preview(spec, zones)
    verdict = await provider.structured_with_image(
        "你是 PPT 布局审稿人。看图并指出布局问题，只输出 JSON。",
        "检查：文字是否溢出/重叠/挤成一团/右侧大片空白/未对齐/与内容不一致。",
        png, "image/png", ReviewVerdict)
    return ToolResult(ok=True, output={"verdict": verdict.model_dump(by_alias=True)})


def register_vision_tools():
    register_tool(Tool(
        "render_geometry_preview",
        "把页面元素按几何区域渲染为蓝图 PNG（供人工/视觉模型自检）",
        RenderGeometryPreviewInput, _render_geometry_preview, timeout_seconds=60, idempotent=True,
    ))
    register_tool(Tool(
        "review_geometry_vision",
        "调用视觉模型检查蓝图 PNG 的布局问题（无视觉能力时跳过）",
        ReviewGeometryVisionInput, _review_geometry_vision, timeout_seconds=120,
    ))


register_vision_tools()
