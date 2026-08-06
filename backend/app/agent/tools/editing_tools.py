"""PPT 编辑工具（PPT Editing Agent 工具层，基于 PresentationBuilder）。

支持动态创建/移动/缩放/删除元素——不是填占位符。
坐标单位英寸，画布 13.333 × 7.5。
"""
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.renderers.presentation_builder import PresentationBuilder


def _builder(tc: ToolContext) -> PresentationBuilder:
    if tc.builder is None:
        tc.builder = PresentationBuilder()
    return tc.builder


class CreateSlideInput(BaseModel):
    page_type: str = Field(default="concept", description="cover/scenario/objectives/concept/case/question/exercise/summary/homework 等")
    title: str = ""
    layout: str = "bullet"
    purpose: str = ""


async def _create_slide(tc: ToolContext, payload: CreateSlideInput) -> ToolResult:
    slide_id = _builder(tc).create_slide(payload.page_type, payload.title, payload.layout, payload.purpose)
    return ToolResult(ok=True, output={"slide_id": slide_id, "page_type": payload.page_type})


class SetSlideTitleInput(BaseModel):
    slide_id: str
    title: str


async def _set_slide_title(tc: ToolContext, payload: SetSlideTitleInput) -> ToolResult:
    _builder(tc).set_slide_title(payload.slide_id, payload.title)
    return ToolResult(ok=True, output={"slide_id": payload.slide_id})


class AddTextboxInput(BaseModel):
    slide_id: str
    text: str
    x: float
    y: float
    width: float
    height: float
    style: dict[str, Any] = Field(default_factory=dict)
    role: str = ""


async def _add_textbox(tc: ToolContext, payload: AddTextboxInput) -> ToolResult:
    element_id = _builder(tc).add_textbox(
        payload.slide_id, payload.text, payload.x, payload.y, payload.width, payload.height,
        style=payload.style, role=payload.role,
    )
    return ToolResult(ok=True, output={"element_id": element_id, "kind": "textbox"})


class AddShapeInput(BaseModel):
    slide_id: str
    shape_type: str = Field(default="rect", description="rect/oval/rounded")
    x: float = 0
    y: float = 0
    width: float = 1
    height: float = 1
    fill: str | None = None
    line: str | None = None
    radius: bool = False
    role: str = ""


async def _add_shape(tc: ToolContext, payload: AddShapeInput) -> ToolResult:
    element_id = _builder(tc).add_shape(
        payload.slide_id, payload.shape_type, payload.x, payload.y, payload.width, payload.height,
        fill=payload.fill, line=payload.line, radius=payload.radius, role=payload.role,
    )
    return ToolResult(ok=True, output={"element_id": element_id, "kind": "shape"})


class AddImageInput(BaseModel):
    slide_id: str
    file_path: str = Field(description="图片文件路径（visual_asset 的 file_path）")
    x: float
    y: float
    width: float
    height: float
    role: str = "image"


async def _add_image(tc: ToolContext, payload: AddImageInput) -> ToolResult:
    file_path = payload.file_path
    if tc.workspace_root is not None and not Path(file_path).is_absolute():
        candidate = tc.workspace_root / file_path
        if candidate.is_file():
            file_path = str(candidate)
    element_id = _builder(tc).add_image(payload.slide_id, file_path, payload.x, payload.y, payload.width, payload.height, role=payload.role)
    return ToolResult(ok=True, output={"element_id": element_id, "kind": "image"})


class AddChartInput(BaseModel):
    slide_id: str
    chart_type: str = Field(default="bar", description="bar/line/pie")
    data: dict[str, Any] = Field(default_factory=dict)
    x: float
    y: float
    width: float
    height: float
    role: str = "chart"


async def _add_chart(tc: ToolContext, payload: AddChartInput) -> ToolResult:
    element_id = _builder(tc).add_chart(payload.slide_id, payload.chart_type, payload.data, payload.x, payload.y, payload.width, payload.height, role=payload.role)
    return ToolResult(ok=True, output={"element_id": element_id, "kind": "chart"})


class MoveElementInput(BaseModel):
    slide_id: str
    element_id: str
    x: float
    y: float


async def _move_element(tc: ToolContext, payload: MoveElementInput) -> ToolResult:
    _builder(tc).move_element(payload.slide_id, payload.element_id, payload.x, payload.y)
    return ToolResult(ok=True, output={"element_id": payload.element_id, "x": payload.x, "y": payload.y})


class ResizeElementInput(BaseModel):
    slide_id: str
    element_id: str
    width: float
    height: float


async def _resize_element(tc: ToolContext, payload: ResizeElementInput) -> ToolResult:
    _builder(tc).resize_element(payload.slide_id, payload.element_id, payload.width, payload.height)
    return ToolResult(ok=True, output={"element_id": payload.element_id, "width": payload.width, "height": payload.height})


class DeleteElementInput(BaseModel):
    slide_id: str
    element_id: str


async def _delete_element(tc: ToolContext, payload: DeleteElementInput) -> ToolResult:
    _builder(tc).delete_element(payload.slide_id, payload.element_id)
    return ToolResult(ok=True, output={"element_id": payload.element_id, "deleted": True})


class SetElementStyleInput(BaseModel):
    slide_id: str
    element_id: str
    style: dict[str, Any] = Field(default_factory=dict)


async def _set_element_style(tc: ToolContext, payload: SetElementStyleInput) -> ToolResult:
    _builder(tc).set_element_style(payload.slide_id, payload.element_id, payload.style)
    return ToolResult(ok=True, output={"element_id": payload.element_id, "style": payload.style})


class SetBackgroundInput(BaseModel):
    slide_id: str
    fill: str | None = Field(default=None, description="调色板键或 #RRGGBB")


async def _set_background(tc: ToolContext, payload: SetBackgroundInput) -> ToolResult:
    _builder(tc).set_background(payload.slide_id, payload.fill)
    return ToolResult(ok=True, output={"slide_id": payload.slide_id, "fill": payload.fill})


class AddNotesInput(BaseModel):
    slide_id: str
    notes_text: str


async def _add_notes(tc: ToolContext, payload: AddNotesInput) -> ToolResult:
    _builder(tc).add_notes(payload.slide_id, payload.notes_text)
    return ToolResult(ok=True, output={"slide_id": payload.slide_id})


class WriteSlideBatchInput(BaseModel):
    """批量写入幻灯片（内容层规划 → 编辑层执行）。"""

    slides: list[dict[str, Any]] = Field(default_factory=list)


async def _write_slide_batch(tc: ToolContext, payload: WriteSlideBatchInput) -> ToolResult:
    builder = _builder(tc)
    created = 0
    for spec in payload.slides:
        slide_id = builder.create_slide(
            spec.get("page_type", "concept"), spec.get("title", ""), spec.get("layout", "bullet"), spec.get("purpose", ""),
        )
        slide = builder.get_slide(slide_id)
        slide["body"] = list(spec.get("body") or [])
        slide["blocks"] = list(spec.get("blocks") or [])
        slide["visual_suggestion"] = spec.get("visual_suggestion", "")
        slide["speaker_notes"] = spec.get("speaker_notes", "")
        slide["duration_seconds"] = int(spec.get("duration_seconds") or 0)
        created += 1
    return ToolResult(ok=True, output={"created": created})


class LayoutSlideBatchInput(BaseModel):
    """为幻灯片设置元素几何（布局 Agent → 编辑层执行）。"""

    layouts: list[dict[str, Any]] = Field(default_factory=list)


async def _layout_slide_batch(tc: ToolContext, payload: LayoutSlideBatchInput) -> ToolResult:
    builder = _builder(tc)
    placed = 0
    for layout in payload.layouts:
        slide_id = layout.get("slide_id")
        if not slide_id:
            continue
        for element in layout.get("elements") or []:
            kind = element.get("kind", "textbox")
            if kind == "shape":
                builder.add_shape(slide_id, element.get("shape_type", "rect"), element.get("x", 0), element.get("y", 0),
                                  element.get("width", 1), element.get("height", 1),
                                  fill=element.get("fill"), line=element.get("line"), role=element.get("role", ""))
            elif kind == "image":
                builder.add_image(slide_id, element.get("file_path", ""), element.get("x", 0), element.get("y", 0),
                                  element.get("width", 1), element.get("height", 1), role=element.get("role", "image"))
            elif kind == "chart":
                builder.add_chart(slide_id, element.get("chart_type", "bar"), element.get("data", {}),
                                  element.get("x", 0), element.get("y", 0), element.get("width", 1), element.get("height", 1))
            else:
                builder.add_textbox(slide_id, element.get("text", ""), element.get("x", 0), element.get("y", 0),
                                    element.get("width", 1), element.get("height", 1), style=element.get("style", {}),
                                    role=element.get("role", ""))
            placed += 1
    return ToolResult(ok=True, output={"placed": placed})


def register_editing_tools():
    register_tool(Tool("create_slide", "创建一页幻灯片", CreateSlideInput, _create_slide))
    register_tool(Tool("set_slide_title", "设置幻灯片标题", SetSlideTitleInput, _set_slide_title))
    register_tool(Tool("add_textbox", "添加文本框（指定坐标/尺寸/样式）", AddTextboxInput, _add_textbox))
    register_tool(Tool("add_shape", "添加图形（rect/oval/rounded，可指定填充/描边）", AddShapeInput, _add_shape))
    register_tool(Tool("add_image", "添加图片元素", AddImageInput, _add_image))
    register_tool(Tool("add_chart", "添加图表（bar/line/pie）", AddChartInput, _add_chart))
    register_tool(Tool("move_element", "移动元素", MoveElementInput, _move_element))
    register_tool(Tool("resize_element", "缩放元素", ResizeElementInput, _resize_element))
    register_tool(Tool("delete_element", "删除元素", DeleteElementInput, _delete_element))
    register_tool(Tool("set_element_style", "设置元素样式", SetElementStyleInput, _set_element_style))
    register_tool(Tool("set_background", "设置幻灯片背景", SetBackgroundInput, _set_background))
    register_tool(Tool("add_notes", "设置演讲备注", AddNotesInput, _add_notes))
    register_tool(Tool("write_slide_batch", "批量写入幻灯片内容", WriteSlideBatchInput, _write_slide_batch))
    register_tool(Tool("layout_slide_batch", "批量设置元素几何（布局执行）", LayoutSlideBatchInput, _layout_slide_batch))


register_editing_tools()
