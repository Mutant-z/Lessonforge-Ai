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
from app.agent.slide_rendering import (
    bind_content_refs,
    infer_render_mode,
    render_coverage,
    runtime_baseline_slides,
    semantic_content_changed,
)


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
    content_ref: str = ""


async def _add_textbox(tc: ToolContext, payload: AddTextboxInput) -> ToolResult:
    element_id = _builder(tc).add_textbox(
        payload.slide_id, payload.text, payload.x, payload.y, payload.width, payload.height,
        style=payload.style, role=payload.role, content_ref=payload.content_ref,
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
    asset_id: str = Field(default="", description="可由工作台读取的 ArtifactAsset ID")
    provider: str = ""
    degraded: bool = False
    visual_slot: str = "primary_visual"


async def _add_image(tc: ToolContext, payload: AddImageInput) -> ToolResult:
    # visual_asset 对外保存的是 workspace 相对路径；Builder/QA 内部统一保存绝对路径。
    # 生产环境的 workspace_root 本身也可能是相对路径，如果在这里保留
    # ``workspace_root/file_path`` 这种相对值，QA 再解析时会二次拼接 workspace_root。
    # 优先接受已经可读取的路径，再回退到 workspace 相对解析，最终 canonicalize。
    if not payload.file_path:
        candidate_path = Path(payload.file_path)
    else:
        candidate_path = Path(payload.file_path)
        if candidate_path.is_file():
            candidate_path = candidate_path.resolve()
        elif tc.workspace_root is not None and not candidate_path.is_absolute():
            workspace_candidate = Path(tc.workspace_root) / candidate_path
            if workspace_candidate.is_file():
                candidate_path = workspace_candidate.resolve()
    if not payload.file_path or not candidate_path.is_file():
        return ToolResult(
            ok=False, error="图片文件不存在或不可读取。", error_code="image_not_applied", retryable=True,
            output={"slide_id": payload.slide_id, "asset_id": payload.asset_id},
        )
    if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE" and (
        not payload.asset_id or payload.asset_id not in set(getattr(tc.runtime, "generated_asset_ids", []) or []) or payload.degraded
    ):
        return ToolResult(
            ok=False, error="图片不是本轮真实图片模型生成的有效素材。",
            error_code="image_not_applied", retryable=False,
            output={"slide_id": payload.slide_id, "asset_id": payload.asset_id},
        )
    builder = _builder(tc)
    # 只替换同一视觉槽位。历史图片没有 visual_slot 时，visual/image 角色
    # 兼容映射为 primary_visual；其他图片不能被误删。
    slide = builder.get_slide(payload.slide_id)
    original_elements = [dict(element) for element in (slide.get("elements") or [])]
    original_render_mode = slide.get("render_mode")
    slide["elements"] = [
        element for element in (slide.get("elements") or [])
        if not (
            element.get("kind") == "image"
            and (
                str(element.get("visual_slot") or "") == payload.visual_slot
                or (payload.visual_slot == "primary_visual" and not element.get("visual_slot") and element.get("role") in {"visual", "image"})
            )
        )
    ]
    element_id = builder.add_image(
        payload.slide_id, str(candidate_path), payload.x, payload.y, payload.width, payload.height,
        role=payload.role, asset_id=payload.asset_id, provider=payload.provider, degraded=payload.degraded,
        visual_slot=payload.visual_slot,
    )
    slide = builder.get_slide(payload.slide_id)
    if infer_render_mode(slide) != "absolute":
        slide["render_mode"] = "hybrid"
    slide_index = next((index for index, item in enumerate(builder.slides) if item.get("id") == payload.slide_id), None)
    baseline_by_id = {
        str(item.get("id") or ""): item
        for item in runtime_baseline_slides(tc.runtime)
    } if tc.runtime is not None else {}
    baseline = baseline_by_id.get(payload.slide_id, slide)
    coverage = render_coverage(slide, baseline=baseline)
    content_changed = (
        tc.runtime is not None
        and getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
        and semantic_content_changed(baseline, slide)
    )
    if coverage["missing_refs"] or content_changed:
        # The page replacement is atomic: restore the Builder copy before any
        # Patch/event can expose a media-only or content-altered intermediate.
        slide["elements"] = original_elements
        if original_render_mode is None:
            slide.pop("render_mode", None)
        else:
            slide["render_mode"] = original_render_mode
        return ToolResult(
            ok=False,
            error=("图片写入会导致页面文字不可见。" if coverage["missing_refs"] else "图片写入意外修改了页面语义内容。"),
            error_code=("content_not_rendered" if coverage["missing_refs"] else "content_accidentally_removed"),
            retryable=True,
            output={"slide_id": payload.slide_id, "missing_refs": coverage["missing_refs"]},
        )
    if tc.runtime is not None:
        coverage_map = dict(getattr(tc.runtime, "render_coverage", {}) or {})
        coverage_map[payload.slide_id] = coverage
        tc.runtime.render_coverage = coverage_map
    if tc.emitter is not None and slide_index is not None and not coverage["missing_refs"]:
        draft_artifact_id = (
            getattr(tc.runtime, "draft_artifact_id", None) or f"draft-{tc.generation_run_id}"
        )
        await tc.emitter.artifact_patch(
            draft_artifact_id,
            "presentation_draft",
            [{"op": "replace", "path": f"/slides/{slide_index}", "value": slide}],
            summary=("已插入替代配图（未配置图片模型）" if payload.degraded else "已插入生成图片"),
            slide_index=slide_index,
        )
    if tc.runtime is not None:
        evidence = list(getattr(tc.runtime, "mutation_evidence", []) or [])
        evidence.append({
            "kind": "image", "slide_id": payload.slide_id, "tool_name": "add_image",
            "asset_id": payload.asset_id, "element_id": element_id,
        })
        tc.runtime.mutation_evidence = evidence
        affected = list(getattr(tc.runtime, "affected_slide_ids", []) or [])
        if payload.slide_id not in affected:
            affected.append(payload.slide_id)
        tc.runtime.affected_slide_ids = affected
        if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE":
            expected = {str(item.get("slide_id") or "") for item in (getattr(tc.runtime, "expected_visual_requests", []) or [])}
            applied = {
                str(item.get("slide_id") or "") for item in tc.runtime.mutation_evidence
                if item.get("kind") == "image" and item.get("asset_id") in set(getattr(tc.runtime, "generated_asset_ids", []) or [])
            }
            tc.runtime.mutation_applied = bool(expected) and expected <= applied
    return ToolResult(ok=True, output={
        "element_id": element_id, "kind": "image", "asset_id": payload.asset_id,
        "degraded": payload.degraded, "visual_slot": payload.visual_slot,
    })


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
    allowed_ids = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
    requested_slides = list(payload.slides)
    scoped_slides = [
        spec for spec in requested_slides
        if not allowed_ids or str(spec.get("id") or "") in allowed_ids
    ]
    rejected_ids = [
        str(spec.get("id") or "") for spec in requested_slides
        if allowed_ids and str(spec.get("id") or "") not in allowed_ids
    ]
    if allowed_ids and not scoped_slides:
        return ToolResult(ok=False, error="写入被拒绝：工具输入未包含本轮选中的目标页面")
    updated = 0
    draft_id = f"draft-{tc.generation_run_id}"
    if tc.runtime is not None:
        tc.runtime.draft_artifact_id = draft_id
    if tc.emitter is not None:
        await tc.emitter.artifact_started("presentation_draft", draft_id, producer_agent="ppt_editor")
    for index, spec in enumerate(scoped_slides):
        requested_id = str(spec.get("id") or "")
        try:
            slide = builder.get_slide(requested_id) if requested_id else None
        except KeyError:
            slide = None
        if slide is None:
            slide_id = builder.create_slide(
                spec.get("page_type", "concept"), spec.get("title", ""), spec.get("layout", "bullet"), spec.get("purpose", ""),
            )
            slide = builder.get_slide(slide_id)
            if requested_id:
                slide["id"] = requested_id
                slide_id = requested_id
        else:
            slide_id = requested_id
            slide["page_type"] = spec.get("page_type", slide.get("page_type", "concept"))
            slide["title"] = spec.get("title", slide.get("title", ""))
            slide["layout"] = spec.get("layout", slide.get("layout", "bullet"))
            slide["purpose"] = spec.get("purpose", slide.get("purpose", ""))
        # SlideContentPatch is a field-level patch. Missing optional fields
        # mean "leave untouched", never "erase the current page".
        if "body" in spec:
            slide["body"] = list(spec.get("body") or [])
        if "blocks" in spec:
            slide["blocks"] = list(spec.get("blocks") or [])
        if "visual_suggestion" in spec:
            slide["visual_suggestion"] = spec.get("visual_suggestion", "")
        if "speaker_notes" in spec:
            slide["speaker_notes"] = spec.get("speaker_notes", "")
        if "duration_seconds" in spec:
            slide["duration_seconds"] = int(spec.get("duration_seconds") or 0)
        updated += 1
        if tc.runtime is not None and slide_id not in tc.runtime.affected_slide_ids:
            tc.runtime.affected_slide_ids.append(slide_id)
        slide_index = next((position for position, item in enumerate(builder.slides) if item.get("id") == slide_id), index)
        if tc.emitter is not None:
            await tc.emitter.emit_domain(
                "slide.content.updated", message=f"第 {index + 1} 页内容已生成",
                agent={"id": "ppt_editor", "name": "PPT 编辑 Agent"},
                progress={"current": index + 1, "total": len(scoped_slides)},
                slide={"slide_id": slide_id, "page": slide_index + 1},
                payload={"status": "content_generating", "title": slide.get("title", "")},
            )
            await tc.emitter.artifact_patch(
                draft_id,
                "presentation_draft",
                [{"op": "replace", "path": f"/slides/{slide_index}", "value": slide}],
                summary=f"已完成第 {slide_index + 1} 页：{slide.get('title', '')}",
                slide_index=slide_index,
            )
    if tc.runtime is not None and updated and getattr(tc.runtime, "active_intent", "") != "IMAGE_UPDATE":
        tc.runtime.mutation_applied = True
        tc.runtime.mutation_evidence.extend({
            "kind": "slide_content", "slide_id": str(spec.get("id") or ""),
            "tool_name": "write_slide_batch", "asset_id": "", "element_id": "",
        } for spec in scoped_slides)
    return ToolResult(ok=True, output={
        "updated": updated,
        "slide_ids": list(tc.runtime.affected_slide_ids if tc.runtime else []),
        "rejected_slide_ids": rejected_ids,
    })


class LayoutSlideBatchInput(BaseModel):
    """为幻灯片设置元素几何（布局 Agent → 编辑层执行）。"""

    layouts: list[dict[str, Any]] = Field(default_factory=list)


def _preserved_visual_resources(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回模板重排时必须保留的真实视觉资源，而不是装饰底板。"""
    return [
        dict(element) for element in elements
        if element.get("kind") in {"image", "chart"}
        and (element.get("kind") != "image" or element.get("asset_path"))
    ]


def _visual_target_region(slide: dict[str, Any], layout: dict[str, Any]) -> dict[str, float] | None:
    region = layout.get("visual_region")
    if isinstance(region, dict):
        return {
            "x": float(region.get("x") or 0), "y": float(region.get("y") or 0),
            "w": float(region.get("w", region.get("width")) or 0),
            "h": float(region.get("h", region.get("height")) or 0),
        }
    panel = next((
        element for element in (slide.get("elements") or [])
        if element.get("role") == "visual_panel"
    ), None)
    if not panel:
        return None
    return {
        "x": float(panel.get("x") or 0) + 0.18,
        "y": float(panel.get("y") or 0) + 0.18,
        "w": max(0.4, float(panel.get("w") or 0) - 0.36),
        "h": max(0.4, float(panel.get("h") or 0) - 0.36),
    }


def _restore_visual_resources(slide: dict[str, Any], layout: dict[str, Any], resources: list[dict[str, Any]]) -> int:
    """把旧图片/图表映射到新模板的视觉区，并保持素材身份与可编辑数据。"""
    if not resources:
        return 0
    target = _visual_target_region(slide, layout)
    caption = next((
        element for element in (slide.get("elements") or [])
        if element.get("role") == "visual_caption"
    ), None)
    if target and caption and caption.get("y") is not None:
        target["h"] = max(0.4, min(target["h"], float(caption["y"]) - 0.15 - target["y"]))

    old_x = min(float(item.get("x") or 0) for item in resources)
    old_y = min(float(item.get("y") or 0) for item in resources)
    old_right = max(float(item.get("x") or 0) + float(item.get("w") or 0) for item in resources)
    old_bottom = max(float(item.get("y") or 0) + float(item.get("h") or 0) for item in resources)
    old_w, old_h = max(0.01, old_right - old_x), max(0.01, old_bottom - old_y)
    next_z = max((int(item.get("z") or 0) for item in (slide.get("elements") or [])), default=0) + 1
    existing_keys = {
        (str(item.get("asset_id") or ""), str(item.get("asset_path") or ""))
        for item in (slide.get("elements") or []) if item.get("kind") == "image"
    }
    restored = 0
    for offset, resource in enumerate(resources):
        identity = (str(resource.get("asset_id") or ""), str(resource.get("asset_path") or ""))
        if resource.get("kind") == "image" and identity in existing_keys:
            continue
        item = dict(resource)
        if target and target["w"] > 0 and target["h"] > 0:
            scale = min(target["w"] / old_w, target["h"] / old_h)
            mapped_w, mapped_h = float(item.get("w") or 0) * scale, float(item.get("h") or 0) * scale
            item["x"] = target["x"] + (float(item.get("x") or 0) - old_x) * scale + (target["w"] - old_w * scale) / 2
            item["y"] = target["y"] + (float(item.get("y") or 0) - old_y) * scale + (target["h"] - old_h * scale) / 2
            item["w"], item["h"] = mapped_w, mapped_h
        item["z"] = next_z + offset
        slide["elements"].append(item)
        restored += 1
    return restored


async def _layout_slide_batch(tc: ToolContext, payload: LayoutSlideBatchInput) -> ToolResult:
    builder = _builder(tc)
    allowed_ids = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
    requested_layouts = list(payload.layouts)
    scoped_layouts = [
        layout for layout in requested_layouts
        if not allowed_ids or str(layout.get("slide_id") or "") in allowed_ids
    ]
    rejected_ids = [
        str(layout.get("slide_id") or "") for layout in requested_layouts
        if allowed_ids and str(layout.get("slide_id") or "") not in allowed_ids
    ]
    if allowed_ids and not scoped_layouts:
        return ToolResult(ok=False, error="布局写入被拒绝：工具输入未包含本轮选中的目标页面")
    baseline_by_id = {
        str(item.get("id") or ""): item
        for item in runtime_baseline_slides(tc.runtime)
    } if tc.runtime is not None else {}
    prepared_layouts: list[dict[str, Any]] = []
    for layout in scoped_layouts:
        slide_id = str(layout.get("slide_id") or "")
        if not slide_id:
            continue
        slide = builder.get_slide(slide_id)
        bound_elements, unresolved = bind_content_refs(slide, list(layout.get("elements") or []))
        if unresolved:
            return ToolResult(
                ok=False, error="布局包含无法解析的页面内容引用。",
                error_code="layout_incomplete", retryable=True,
                output={"slide_id": slide_id, "unresolved_content_refs": unresolved},
            )
        prepared = {**layout, "elements": bound_elements}
        if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}:
            baseline = baseline_by_id.get(slide_id, slide)
            candidate = {
                **slide,
                "render_mode": str(prepared.get("render_mode") or "absolute"),
                "elements": bound_elements,
            }
            coverage = render_coverage(candidate, baseline=baseline)
            if coverage["missing_refs"]:
                return ToolResult(
                    ok=False, error="绝对布局未覆盖页面全部必要文字。",
                    error_code="layout_incomplete", retryable=True,
                    output={"slide_id": slide_id, "missing_refs": coverage["missing_refs"]},
                )
        prepared_layouts.append(prepared)
    scoped_layouts = prepared_layouts
    placed = 0
    preserved = 0
    preserve_visuals = (
        getattr(tc.runtime, "active_intent", "") in {"TEMPLATE_SWITCH", "STYLE_CHANGE", "IMAGE_UPDATE"}
        or getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
    )
    for layout in scoped_layouts:
        slide_id = layout.get("slide_id")
        if not slide_id:
            continue
        slide = builder.get_slide(slide_id)
        visual_resources = _preserved_visual_resources(slide.get("elements") or []) if preserve_visuals else []
        slide["elements"] = []
        for element in layout.get("elements") or []:
            kind = element.get("kind", "textbox")
            if kind == "shape":
                builder.add_shape(slide_id, element.get("shape_type", "rect"), element.get("x", 0), element.get("y", 0),
                                  element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)),
                                  fill=element.get("fill"), line=element.get("line"), role=element.get("role", ""))
            elif kind == "image":
                file_path = str(element.get("file_path") or "")
                if not file_path:
                    # A semantic visual slot is not an image. Preserve it as a
                    # panel so the UI never displays a fake "preparing" image.
                    builder.add_shape(
                        slide_id, element.get("shape_type", "rounded"), element.get("x", 0), element.get("y", 0),
                        element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)),
                        fill=element.get("fill") or "surface", line=element.get("line") or "secondary",
                        role=element.get("role") or "visual_panel",
                    )
                else:
                    builder.add_image(slide_id, file_path, element.get("x", 0), element.get("y", 0),
                                      element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)), role=element.get("role", "image"))
            elif kind == "chart":
                builder.add_chart(slide_id, element.get("chart_type", "bar"), element.get("data", {}),
                                  element.get("x", 0), element.get("y", 0), element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)))
            else:
                builder.add_textbox(slide_id, element.get("text", ""), element.get("x", 0), element.get("y", 0),
                                    element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)), style=element.get("style", {}),
                                    role=element.get("role", ""), content_ref=element.get("content_ref", ""))
            placed += 1
        preserved += _restore_visual_resources(slide, layout, visual_resources)
        slide["render_mode"] = str(layout.get("render_mode") or "absolute")
        if preserve_visuals and tc.runtime is not None:
            evidence = list(getattr(tc.runtime, "mutation_evidence", []) or [])
            evidence.append({
                "kind": "template_layout", "slide_id": str(slide_id),
                "tool_name": "layout_slide_batch", "asset_id": "", "element_id": "",
                "preserved_visuals": len(visual_resources),
            })
            tc.runtime.mutation_evidence = evidence
        if tc.emitter is not None:
            await tc.emitter.emit_domain(
                "slide.layout.updated", message=f"第 {slide_id.removeprefix('S')} 页布局已更新",
                agent={"id": "layout", "name": "页面布局 Agent"},
                slide={"slide_id": slide_id}, payload={"status": "layout_generating", "elements": len(slide.get("elements") or [])},
            )
            slide_index = next((index for index, item in enumerate(builder.slides) if item.get("id") == slide_id), None)
            if slide_index is not None and getattr(tc.runtime, "active_intent", "") != "IMAGE_UPDATE":
                await tc.emitter.artifact_patch(
                    tc.runtime.draft_artifact_id or f"draft-{tc.generation_run_id}",
                    "presentation_draft",
                    [{"op": "replace", "path": f"/slides/{slide_index}", "value": slide}],
                    summary=f"第 {slide_index + 1} 页布局已更新",
                    slide_index=slide_index,
                )
    return ToolResult(ok=True, output={
        "placed": placed, "preserved_visual_resources": preserved,
        "rejected_slide_ids": rejected_ids,
    })


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
