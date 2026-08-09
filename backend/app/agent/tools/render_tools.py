"""渲染工具：把 builder 渲染为 PPTX（动态）或走 deck 兼容路径。"""
from pathlib import Path

from pydantic import BaseModel

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult


class RenderPreviewInput(BaseModel):
    pass


async def _render_preview(tc: ToolContext, _: RenderPreviewInput) -> ToolResult:
    if tc.builder is None or not tc.builder.slides:
        return ToolResult(ok=False, error="builder 为空，先创建幻灯片")
    if tc.workspace_root is None:
        return ToolResult(ok=False, error="缺少工作目录")
    output = tc.workspace_root / "drafts" / "preview.pptx"
    if tc.emitter is not None:
        for index, slide in enumerate(tc.builder.slides):
            await tc.emitter.emit_domain("slide.rendering", message=f"正在渲染第 {index + 1} 页", slide={"slide_id": slide["id"], "page": index + 1}, progress={"current": index + 1, "total": len(tc.builder.slides)})
    tc.builder.render(output)
    if tc.emitter is not None:
        for index, slide in enumerate(tc.builder.slides):
            await tc.emitter.emit_domain("slide.rendered", message=f"第 {index + 1} 页已渲染", slide={"slide_id": slide["id"], "page": index + 1}, payload={"preview_file": str(output.relative_to(tc.workspace_root))})
    return ToolResult(ok=True, output={"file_path": str(output.relative_to(tc.workspace_root)), "slide_count": len(tc.builder.slides)})


class RenderSlideInput(BaseModel):
    slide_id: str


async def _render_slide(tc: ToolContext, payload: RenderSlideInput) -> ToolResult:
    if tc.builder is None or tc.workspace_root is None:
        return ToolResult(ok=False, error="builder 或工作目录不可用")
    tc.builder.get_slide(payload.slide_id)
    output = tc.workspace_root / "renders" / f"{payload.slide_id}.pptx"
    tc.builder.render(output)
    if tc.emitter is not None:
        await tc.emitter.emit_domain("slide.rendered", message=f"{payload.slide_id} 已刷新预览", slide={"slide_id": payload.slide_id}, payload={"preview_file": str(output.relative_to(tc.workspace_root)), "deck_render": True})
    return ToolResult(ok=True, output={"slide_id": payload.slide_id, "file_path": str(output.relative_to(tc.workspace_root)), "deck_render": True})


class RenderDeckPreviewInput(BaseModel):
    """把 builder 内容映射到真实 deck 模板（15 页角色化时）。"""

    pass


async def _render_deck_preview(tc: ToolContext, _: RenderDeckPreviewInput) -> ToolResult:
    from app.agents.generators import deck_from_artifact
    from app.renderers.deck_renderer import deck_template_path, render_deck, role_order

    if tc.builder is None or not tc.builder.slides:
        return ToolResult(ok=False, error="builder 为空")
    content = tc.builder.to_ppt_content()
    slides = content.get("slides") or []
    if len(slides) != len(role_order()):
        return ToolResult(ok=False, error=f"非 15 页内容无法走 deck 渲染（当前 {len(slides)} 页）")
    blueprint = tc.ctx.blueprint if tc.ctx and tc.ctx.blueprint is not None else {}
    from app.schemas.blueprint import CourseBlueprintSchema
    bp = CourseBlueprintSchema.model_validate(blueprint if isinstance(blueprint, dict) else blueprint.model_dump())
    template_id = content.get("theme") or tc.builder.template["id"]
    deck = deck_from_artifact(bp, content, template_id)
    deck_path = deck_template_path(template_id)
    output = tc.workspace_root / "drafts" / "deck_preview.pptx"
    render_deck(deck_path, deck, output, template_id)
    return ToolResult(ok=True, output={"file_path": str(output.relative_to(tc.workspace_root)), "slide_count": len(slides)})


def register_render_tools():
    register_tool(Tool("render_preview", "把当前 builder 渲染为动态 PPTX（供 QA 检查）", RenderPreviewInput, _render_preview, timeout_seconds=120, idempotent=True))
    register_tool(Tool("render_slide", "仅刷新指定页面的版本化预览（当前实现复用 deck render）", RenderSlideInput, _render_slide, timeout_seconds=120, idempotent=True))
    register_tool(Tool("get_slide_preview", "获取指定页面的最新预览", RenderSlideInput, _render_slide, timeout_seconds=120, idempotent=True))
    register_tool(Tool("render_deck_preview", "把 15 页角色内容映射到真实 deck 模板渲染", RenderDeckPreviewInput, _render_deck_preview))


register_render_tools()
