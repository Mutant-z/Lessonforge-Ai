"""PPT 编辑工具（PPT Editing Agent 工具层，基于 PresentationBuilder）。

支持动态创建/移动/缩放/删除元素——不是填占位符。
坐标单位英寸，画布 13.333 × 7.5。
"""
from pathlib import Path
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.agent.layouts.metrics import estimate_text_height
from app.renderers.presentation_builder import PresentationBuilder
from app.agent.slide_rendering import (
    bind_content_refs,
    infer_render_mode,
    render_coverage,
    runtime_baseline_slides,
    semantic_content_changed,
    semantic_content_hash,
    objective_result_passed,
    resolve_content_ref,
    semantic_ref_details,
    semantic_text_refs,
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
            if tc.runtime.mutation_applied:
                # A layout candidate may have been safely preserved before the
                # independently valid image replacement was committed.  That
                # earlier page-local no-op must not suppress final visual QA or
                # mislabel a real media mutation as ``no_change``.
                tc.runtime.result_status = "applied"
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


def _sync_locked_geometry_text(
    before: dict[str, Any], current: dict[str, Any],
) -> None:
    """Project edited semantics into existing textboxes without moving them."""
    old_refs = dict(semantic_text_refs(before))
    new_refs = dict(semantic_text_refs(current))
    old_text_to_refs: dict[str, list[str]] = {}
    for ref, text in old_refs.items():
        old_text_to_refs.setdefault(str(text), []).append(ref)
    for element in current.get("elements") or []:
        if element.get("kind") not in {"textbox", "note"}:
            continue
        ref = str(element.get("content_ref") or "")
        if not ref:
            matches = old_text_to_refs.get(str(element.get("text") or ""), [])
            if len(matches) == 1:
                ref = matches[0]
        if not ref:
            continue
        projected = resolve_content_ref(current, ref)
        if projected is not None:
            element["text"] = projected


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
    unchanged_ids: list[str] = []
    changed_specs: list[dict[str, Any]] = []
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
        before_slide = deepcopy(slide) if slide is not None else None
        before_hash = semantic_content_hash(slide) if slide is not None else None
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
        after_hash = semantic_content_hash(slide)
        if before_hash == after_hash:
            unchanged_ids.append(slide_id)
            continue
        if before_slide is not None and (slide.get("elements") or []):
            _sync_locked_geometry_text(before_slide, slide)
        updated += 1
        changed_specs.append(spec)
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
        } for spec in changed_specs)
    if (
        tc.runtime is not None
        and scoped_slides
        and not updated
        and getattr(tc.runtime, "active_intent", "") != "GENERATE"
    ):
        tc.runtime.result_status = "no_change"
    return ToolResult(ok=True, output={
        "updated": updated,
        "slide_ids": list(tc.runtime.affected_slide_ids if tc.runtime else []),
        "rejected_slide_ids": rejected_ids,
        "unchanged_slide_ids": unchanged_ids,
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


def _apply_layout_to_builder(
    builder: PresentationBuilder, layout: dict[str, Any], *, preserve_visuals: bool,
) -> tuple[int, int]:
    """Apply one already-bound layout to a builder; callers decide staging/commit."""
    slide_id = str(layout.get("slide_id") or "")
    slide = builder.get_slide(slide_id)
    if str(layout.get("layout_type") or "") == "existing_image_geometry":
        # This operation is deliberately not a page rebuild.  Match existing
        # visual elements in stable order and mutate only their four geometry
        # fields, leaving every text box and all image/chart metadata intact.
        existing_visuals = [
            item for item in (slide.get("elements") or [])
            if item.get("kind") in {"image", "chart"}
        ]
        candidate_visuals = [
            item for item in (layout.get("elements") or [])
            if item.get("kind") in {"image", "chart"}
        ]
        if len(existing_visuals) != len(candidate_visuals):
            raise ValueError("image_geometry 候选的视觉元素数量与原页不一致")
        for existing, candidate in zip(existing_visuals, candidate_visuals):
            if str(existing.get("kind") or "") != str(candidate.get("kind") or ""):
                raise ValueError("image_geometry 候选的视觉元素顺序与原页不一致")
            existing.update({
                key: float(candidate.get(key) or 0) for key in ("x", "y", "w", "h")
            })
        return len(candidate_visuals), 0
    visual_resources = _preserved_visual_resources(slide.get("elements") or []) if preserve_visuals else []
    slide["elements"] = []
    placed = 0
    for element in layout.get("elements") or []:
        kind = element.get("kind", "textbox")
        if kind == "shape":
            builder.add_shape(
                slide_id, element.get("shape_type", "rect"), element.get("x", 0), element.get("y", 0),
                element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)),
                fill=element.get("fill"), line=element.get("line"), role=element.get("role", ""),
            )
        elif kind == "image":
            file_path = str(element.get("file_path") or "")
            if not file_path:
                builder.add_shape(
                    slide_id, element.get("shape_type", "rounded"), element.get("x", 0), element.get("y", 0),
                    element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)),
                    fill=element.get("fill") or "surface", line=element.get("line") or "secondary",
                    role=element.get("role") or "visual_panel",
                )
            else:
                builder.add_image(
                    slide_id, file_path, element.get("x", 0), element.get("y", 0),
                    element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)),
                    role=element.get("role", "image"),
                )
        elif kind == "chart":
            builder.add_chart(
                slide_id, element.get("chart_type", "bar"), element.get("data", {}),
                element.get("x", 0), element.get("y", 0),
                element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)),
            )
        else:
            builder.add_textbox(
                slide_id, element.get("text", ""), element.get("x", 0), element.get("y", 0),
                element.get("width", element.get("w", 1)), element.get("height", element.get("h", 1)),
                style=element.get("style", {}), role=element.get("role", ""),
                content_ref=element.get("content_ref", ""),
            )
        placed += 1
    restored = _restore_visual_resources(slide, layout, visual_resources)
    slide["render_mode"] = str(layout.get("render_mode") or "absolute")
    return placed, restored


def _normalized_locked_non_media(element: dict[str, Any]) -> dict[str, Any]:
    """Normalize schema defaults before comparing an image-only candidate."""
    return {
        "id": str(element.get("id") or ""),
        "kind": str(element.get("kind") or "textbox"),
        "role": str(element.get("role") or ""),
        "text": str(element.get("text") or ""),
        "x": round(float(element.get("x") or 0), 4),
        "y": round(float(element.get("y") or 0), 4),
        "w": round(float(element.get("w") or 0), 4),
        "h": round(float(element.get("h") or 0), 4),
        "style": element.get("style") or {},
        "shape_type": str(element.get("shape_type") or "rect"),
        "fill": element.get("fill"),
        "line": element.get("line"),
        "content_ref": str(element.get("content_ref") or ""),
    }


def _media_metadata_matches(source: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Candidate may contain empty schema defaults, but cannot alter source metadata."""
    if str(source.get("kind") or "") != str(candidate.get("kind") or ""):
        return False
    return all(
        candidate.get(key) == value
        for key, value in source.items()
        if key not in {"x", "y", "w", "h"}
    )


def _mark_layout_preserved(runtime: Any, slide_id: str, warning: str) -> None:
    results = list(getattr(runtime, "layout_compile_results", None) or [])
    result = next((item for item in reversed(results) if item.get("slide_id") == slide_id), None)
    if result is None:
        result = {"slide_id": slide_id, "status": "preserved", "warnings": []}
        results.append(result)
    result["status"] = "preserved"
    result["warnings"] = list(dict.fromkeys([*(result.get("warnings") or []), warning]))
    runtime.layout_compile_results = results


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
    failed_pages: list[dict[str, Any]] = []
    for layout in scoped_layouts:
        slide_id = str(layout.get("slide_id") or "")
        if not slide_id:
            continue
        objective_results = list(layout.get("objective_results") or [])
        unmet_objectives = [
            item for item in objective_results
            if not objective_result_passed(item)
            and bool(item.get("hard_requirement", True))
        ]
        if layout.get("material_change") is False or unmet_objectives:
            failed_pages.append({
                "slide_id": slide_id,
                "reason": "no_material_improvement" if layout.get("material_change") is False else "objectives_unmet",
                "objective_results": objective_results,
            })
            continue
        slide = builder.get_slide(slide_id)
        image_geometry_only = str(layout.get("layout_type") or "") == "existing_image_geometry"
        if image_geometry_only:
            bound_elements = deepcopy(list(layout.get("elements") or []))
            unresolved = []
            source_non_media = [
                item for item in (slide.get("elements") or [])
                if item.get("kind") not in {"image", "chart"}
            ]
            candidate_non_media = [
                item for item in bound_elements
                if item.get("kind") not in {"image", "chart"}
            ]
            source_media = [
                item for item in (slide.get("elements") or [])
                if item.get("kind") in {"image", "chart"}
            ]
            candidate_media = [
                item for item in bound_elements
                if item.get("kind") in {"image", "chart"}
            ]
            if (
                [_normalized_locked_non_media(item) for item in source_non_media]
                != [_normalized_locked_non_media(item) for item in candidate_non_media]
                or len(source_media) != len(candidate_media)
            ):
                failed_pages.append({
                    "slide_id": slide_id, "reason": "image_geometry_scope_violation",
                })
                continue
            metadata_mismatch = False
            for source_element, candidate_element in zip(source_media, candidate_media):
                if not _media_metadata_matches(source_element, candidate_element):
                    metadata_mismatch = True
                    break
            if metadata_mismatch:
                failed_pages.append({
                    "slide_id": slide_id, "reason": "image_geometry_metadata_changed",
                })
                continue
        else:
            bound_elements, unresolved = bind_content_refs(slide, list(layout.get("elements") or []))
        if unresolved:
            failed_pages.append({
                "slide_id": slide_id, "reason": "unresolved_content_refs",
                "unresolved_content_refs": unresolved,
            })
            continue
        # Normalize too-short text boxes before staging.  This is a local,
        # deterministic correction (not an LLM retry); if the taller box then
        # collides or leaves the safe canvas, staging will still reject it.
        for element in ([] if image_geometry_only else bound_elements):
            if element.get("kind") not in {"textbox", "note"} or not element.get("text"):
                continue
            try:
                needed = estimate_text_height(
                    str(element.get("text") or ""), float(element.get("w") or 0.01),
                    float((element.get("style") or {}).get("size") or 18),
                )
                current_h = float(element.get("h") or 0)
            except (TypeError, ValueError):
                continue
            if needed > current_h:
                element["h"] = round(needed, 3)
        prepared = {**layout, "elements": bound_elements}
        baseline = (
            baseline_by_id.get(slide_id, slide)
            if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
            else slide
        )
        candidate = {
            **slide,
            "render_mode": str(prepared.get("render_mode") or "absolute"),
            "elements": bound_elements,
        }
        coverage = render_coverage(candidate, baseline=baseline)
        if coverage["missing_refs"]:
            failed_pages.append({
                "slide_id": slide_id, "reason": "missing_refs",
                "missing_refs": coverage["missing_refs"],
                "missing_text": semantic_ref_details(baseline, coverage["missing_refs"]),
            })
            continue
        prepared_layouts.append(prepared)
    scoped_layouts = prepared_layouts
    if tc.runtime is not None and failed_pages:
        for failure in failed_pages:
            quality_rejection = failure.get("reason") in {
                "no_material_improvement", "objectives_unmet",
            }
            _mark_layout_preserved(
                tc.runtime, failure["slide_id"],
                (
                    f"{failure['slide_id']} 未达到用户目标或可感知改善阈值，已保留原布局"
                    if quality_rejection
                    else f"{failure['slide_id']} 写入前覆盖校验未通过，已保留原布局"
                ),
            )
    if failed_pages and not scoped_layouts:
        if all(item.get("reason") in {"no_material_improvement", "objectives_unmet"} for item in failed_pages):
            if tc.runtime is not None:
                tc.runtime.result_status = "no_change"
                tc.runtime.mutation_applied = True
            return ToolResult(ok=True, output={
                "placed": 0,
                "slide_ids": [],
                "preserved_slide_ids": [item["slide_id"] for item in failed_pages],
                "failed_pages": failed_pages,
                "result_status": "no_change",
            })
        first = failed_pages[0]
        return ToolResult(
            ok=False,
            error=(
                "布局包含无法解析的页面内容引用。"
                if first["reason"] == "unresolved_content_refs"
                else "绝对布局未覆盖页面全部必要文字。"
            ),
            error_code="layout_incomplete", retryable=False, output=first,
        )
    placed = 0
    preserved = 0
    # 文字类变更（润色/局部重排/上下文同步等）同样不能丢页面上已有的图片/图表：
    # 本轮没有 visual_plan/visual_asset 时，旧视觉资源必须在重排前捕获并恢复，
    # 否则 layout 重建元素会把图片静默清掉且 QA 无法发现。
    mutation_intents = {
        "MODIFY", "LOCAL_REGENERATE", "LAYOUT_ONLY", "CONTENT_UPDATE", "GLOBAL_OPTIMIZE",
        "STYLE_CHANGE", "TEMPLATE_SWITCH", "IMAGE_UPDATE",
    }
    preserve_visuals = (
        getattr(tc.runtime, "active_intent", "") in mutation_intents
        or getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
    )
    for layout in scoped_layouts:
        slide_id = str(layout.get("slide_id") or "")
        if not slide_id:
            continue
        # Validate on a throw-away builder.  The official Builder is only
        # touched after this page passes coverage and geometry checks.
        staging = PresentationBuilder().from_ppt_content(deepcopy(builder.to_ppt_content()))
        staged_placed, staged_preserved = _apply_layout_to_builder(
            staging, layout, preserve_visuals=preserve_visuals,
        )
        staged_slide = staging.get_slide(slide_id)
        baseline = (
            baseline_by_id.get(slide_id, staged_slide)
            if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
            else staged_slide
        )
        coverage = render_coverage(staged_slide, baseline=baseline)
        from app.agent.tools.qa_tools import run_geometry_qa
        staging_blocking_rules = {
            "geometry.out_of_bounds", "geometry.text_overflow", "geometry.overlap",
            "geometry.font_too_small", "geometry.min_margin", "geometry.title_in_rail",
            "geometry.font_role_minimum", "layout.vertical_underuse",
            "layout.cluster_cramming", "layout.column_balance", "layout.blank_region",
        }
        quality_mode = (
            not image_geometry_only
            and
            (getattr(tc.runtime, "layout_engine_params", None) or {}).get("quality_mode")
            == "polish_v2"
        )
        geometry_issues = [
            issue for issue in run_geometry_qa(
                [
                    item for item in staging.geometry_report()
                    if str(item.get("slide_id") or "") == slide_id
                ],
                enforce_readability=quality_mode,
                enforce_quality=quality_mode,
            )
            if issue.get("severity") in {"critical", "major"}
            and issue.get("rule_id") in staging_blocking_rules
        ]
        if coverage["missing_refs"] or geometry_issues:
            reason_codes = [
                str(item.get("rule_id") or "geometry") for item in geometry_issues
            ]
            if coverage["missing_refs"]:
                reason_codes.append("content.not_rendered")
            reason = "、".join(sorted(set(reason_codes)))
            warning = f"{slide_id} staging 未通过安全校验（{reason}），已保留原布局"
            failed_pages.append({
                "slide_id": slide_id, "reason": reason,
                "missing_refs": coverage["missing_refs"], "geometry_issues": geometry_issues,
            })
            if tc.runtime is not None:
                _mark_layout_preserved(tc.runtime, slide_id, warning)
            continue

        # Re-apply the verified operation to the official Builder.  This keeps
        # its element sequence consistent for later media operations.
        committed_placed, committed_preserved = _apply_layout_to_builder(
            builder, layout, preserve_visuals=preserve_visuals,
        )
        placed += committed_placed
        preserved += committed_preserved
        slide = builder.get_slide(slide_id)
        if tc.runtime is not None:
            affected = list(getattr(tc.runtime, "affected_slide_ids", None) or [])
            if slide_id not in affected:
                affected.append(slide_id)
            tc.runtime.affected_slide_ids = affected
            tc.runtime.mutation_applied = True
        if preserve_visuals and tc.runtime is not None:
            evidence = list(getattr(tc.runtime, "mutation_evidence", []) or [])
            evidence.append({
                "kind": "template_layout", "slide_id": str(slide_id),
                "tool_name": "layout_slide_batch", "asset_id": "", "element_id": "",
                "preserved_visuals": committed_preserved,
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
    if tc.runtime is not None and failed_pages:
        if placed:
            tc.runtime.result_status = "partial"
        else:
            tc.runtime.result_status = "no_change"
            tc.runtime.mutation_applied = True
    return ToolResult(ok=True, output={
        "placed": placed, "preserved_visual_resources": preserved,
        "rejected_slide_ids": rejected_ids,
        "slide_ids": list(getattr(tc.runtime, "affected_slide_ids", None) or []),
        "preserved_slide_ids": [item["slide_id"] for item in failed_pages],
        "failed_pages": failed_pages,
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
