"""QA 工具：内容安全、几何、真实栅格与可选视觉模型的分层门禁。"""
import base64
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.renderers.presentation_builder import SLIDE_HEIGHT, SLIDE_WIDTH
from app.agent.slide_rendering import (
    infer_render_mode,
    render_coverage,
    runtime_baseline_slides,
    semantic_ref_details,
    semantic_content_changed,
)
from app.agent.agents.layout import MARGIN_Y, MIN_BODY_VERTICAL_USAGE, SAFE_CONTENT_BOTTOM
from app.agent.layouts.metrics import estimate_text_height as _text_height_inches

SEVERITY_WEIGHT = {"critical": 15, "major": 8, "minor": 3}
CONTENT_QA_INTENTS = {"GENERATE", "MODIFY", "LOCAL_REGENERATE", "CONTENT_UPDATE"}
QUALITY_PANEL_ROLES = {
    "step_card", "highlight_panel", "compare_panel", "quote_panel", "visual_panel",
}


def _rectangle_union_area(items: list[dict[str, Any]]) -> float:
    """Exact union area for axis-aligned element rectangles."""
    rectangles = [
        (
            float(item.get("x") or 0), float(item.get("y") or 0),
            float(item.get("x") or 0) + float(item.get("w") or 0),
            float(item.get("y") or 0) + float(item.get("h") or 0),
        )
        for item in items if float(item.get("w") or 0) > 0 and float(item.get("h") or 0) > 0
    ]
    xs = sorted({value for rect in rectangles for value in (rect[0], rect[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (top, bottom) for x1, top, x2, bottom in rectangles
            if x1 < right - 1e-9 and x2 > left + 1e-9
        )
        covered_y = 0.0
        cursor_top = cursor_bottom = None
        for top, bottom in intervals:
            if cursor_top is None:
                cursor_top, cursor_bottom = top, bottom
            elif top <= float(cursor_bottom) + 1e-9:
                cursor_bottom = max(float(cursor_bottom), bottom)
            else:
                covered_y += float(cursor_bottom) - float(cursor_top)
                cursor_top, cursor_bottom = top, bottom
        if cursor_top is not None:
            covered_y += float(cursor_bottom) - float(cursor_top)
        area += (right - left) * covered_y
    return area


def run_geometry_qa(
    report: list[dict[str, Any]], *, enforce_readability: bool = False,
    enforce_quality: bool = True,
) -> list[dict[str, Any]]:
    """越界 / 重叠 / 文字溢出（基于元素几何与字号估算）。"""
    issues: list[dict[str, Any]] = []
    elements_by_slide: dict[str, list[dict[str, Any]]] = {}
    for item in report:
        elements_by_slide.setdefault(item["slide_id"], []).append(item)
    for slide_id, items in elements_by_slide.items():
        for element in items:
            x, y, w, h = element["x"], element["y"], element["w"], element["h"]
            if x < -0.01 or y < -0.01 or x + w > SLIDE_WIDTH + 0.01 or y + h > SLIDE_HEIGHT + 0.01:
                issues.append({
                    "severity": "critical", "slide_id": slide_id, "rule_id": "geometry.out_of_bounds",
                    "message": f"元素 {element['element_id']}({element['kind']}) 超出画布边界 ({x:.2f},{y:.2f},{w:.2f},{h:.2f})",
                    "target_agent": "layout",
                })
            style = element.get("style") or {}
            size = float(style.get("size") or 18)
            text = element.get("text", "")
            if element["kind"] in {"textbox", "note"} and text:
                needed = _text_height_inches(text, w, size)
                if needed > h * 1.15 and h > 0.1:
                    issues.append({
                        "severity": "major", "slide_id": slide_id, "rule_id": "geometry.text_overflow",
                        "message": f"元素 {element['element_id']} 文本预计 {needed:.1f}in 高，超出框高 {h:.1f}in（字号 {size}pt）",
                        "target_agent": "slide_content",
                    })
            content_ref = str(element.get("content_ref") or "")
            is_body_copy = (
                content_ref == "body" or content_ref.startswith("body.")
                or content_ref.startswith("blocks.")
            ) and content_ref != "title"
            role_minimum = 14.0 if content_ref.endswith(".citation") else 16.0
            if enforce_readability and is_body_copy and size < role_minimum:
                issues.append({
                    "severity": "major", "slide_id": slide_id,
                    "rule_id": "geometry.font_role_minimum",
                    "message": (
                        f"元素 {element['element_id']} 正文字号 {size:g}pt"
                        f"，低于润色发布下限 {role_minimum:g}pt"
                    ),
                    "target_agent": "layout",
                })
            elif size < 9:
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "geometry.font_too_small",
                    "message": f"元素 {element['element_id']} 字号过小（{size}pt < 9pt）",
                    "target_agent": "layout",
                })
        # 两两重叠（内容元素）
        boxes = [(e["element_id"], e["x"], e["y"], e["w"], e["h"]) for e in items if e["kind"] != "shape"]
        for i, (id_a, ax, ay, aw, ah) in enumerate(boxes):
            for id_b, bx, by, bw, bh in boxes[i + 1:]:
                ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
                oy = max(0, min(ay + ah, by + bh) - max(ay, by))
                if ox * oy > 0.05 and ox * oy > 0.3 * min(aw * ah, bw * bh):
                    issues.append({
                        "severity": "major", "slide_id": slide_id, "rule_id": "geometry.overlap",
                        "message": f"元素 {id_a} 与 {id_b} 重叠（面积 {ox * oy:.2f}in²）",
                        "target_agent": "layout",
                    })
        # 空间利用率：把全部文字挤在一角、其余大片空白的布局能通过“内容存在”
        # 检查，这里从几何上拦截“挤成一团”类不合格页面。只要存在正文内容引用
        # 就做空间检查（大标题 + 单条窄正文的稀疏页面也拦截）；旧报告无
        # content_ref 时沿用 len>=3 兜底，避免把少量正文的合法页面误判为异常。
        text_items = [item for item in items if item["kind"] in {"textbox", "note"}]
        body_items = [item for item in text_items if item.get("content_ref") and item["content_ref"] != "title"]
        spatial_items = body_items if body_items else text_items
        if enforce_quality and (body_items or len(text_items) >= 3):
            text_x = [float(item["x"]) for item in spatial_items]
            text_y = [float(item["y"]) for item in spatial_items]
            text_right = [float(item["x"]) + float(item["w"]) for item in spatial_items]
            text_bottom = [float(item["y"]) + float(item["h"]) for item in spatial_items]
            span_h = max(text_bottom) - min(text_y)
            span_w = max(text_right) - min(text_x)
            content_h = SAFE_CONTENT_BOTTOM - MARGIN_Y
            full_body_w = SLIDE_WIDTH - 1.3
            # A narrow text column is intentional in a left-copy/right-visual
            # composition.  The former rule looked only at text geometry and
            # therefore rejected a complete cover as "right side blank" even
            # when a real image (or its visual panel) occupied that side.  A
            # visual counts as complementary only when it is materially to the
            # right of the body column and overlaps its vertical reading band;
            # decorative background shapes do not receive this exemption.
            complementary_visuals = [
                item for item in items
                if (
                    item["kind"] in {"image", "chart"}
                    or (
                        item["kind"] == "shape"
                        and str(item.get("role") or "") == "visual_panel"
                    )
                )
                and float(item["x"]) >= max(text_right) + 0.12
                and min(float(item["y"]) + float(item["h"]), max(text_bottom))
                    - max(float(item["y"]), min(text_y)) > 0.25
            ]
            has_complementary_visual = bool(complementary_visuals)
            # Vertical and horizontal utilisation are independent axes.  The
            # former AND condition let a three-column row packed into the top
            # third pass merely because it was wide (the V60 regression).
            if span_h < content_h * MIN_BODY_VERTICAL_USAGE:
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "layout.vertical_underuse",
                    "message": f"正文纵向只占内容区 {span_h:.1f}in（<{content_h * MIN_BODY_VERTICAL_USAGE:.1f}in），页面下方大段空白",
                    "target_agent": "layout",
                })
            if span_w < 4.0:
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "layout.cluster_cramming",
                    "message": f"文字横向只占 {span_w:.1f}in，被压成窄条堆在一侧",
                    "target_agent": "layout",
                })
            # 窄条竖排但占满高度、横向细条 → 右侧大片空白
            if (
                span_h >= content_h * MIN_BODY_VERTICAL_USAGE
                and span_w < full_body_w * 0.45
                and not has_complementary_visual
            ):
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "layout.column_balance",
                    "message": f"文字横向只占 {span_w:.1f}in，右侧大片空白",
                    "target_agent": "layout",
                })
            # Use rectangle union, never a bounding rectangle.  The old metric
            # counted whitespace between columns and the title rail as filled.
            content_items = [
                item for item in items
                if (
                    item["kind"] in {"textbox", "note", "image", "chart"}
                    or (
                        item["kind"] == "shape"
                        and str(item.get("role") or "") in QUALITY_PANEL_ROLES
                    )
                )
                and str(item.get("content_ref") or "") != "title"
                and str(item.get("role") or "") != "title"
            ]
            covered = _rectangle_union_area(content_items)
            canvas_area = SLIDE_WIDTH * SLIDE_HEIGHT
            blank_threshold = canvas_area * 0.18
            # Keep a small numerical tolerance so rounded diagnostics never
            # claim e.g. ``18in² < 18in²`` at the threshold boundary.
            if covered < blank_threshold - 0.05:
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "layout.blank_region",
                    "message": (
                        f"页面内容只覆盖画布 {covered:.1f}in²"
                        f"（<{blank_threshold:.1f}in²），大面积空白"
                    ),
                    "target_agent": "layout",
                })
        # 标题框必须落在标题轨（y 0.35..1.6，注释轨 0.55..1.35）。
        # 封面标题按设计位于 y≈2+（hero 布局），不适用标题轨规则，豁免。
        page_type = str(items[0].get("page_type") or "concept") if items else "concept"
        if page_type != "cover":
            for item in text_items:
                if item.get("content_ref") == "title":
                    ty = float(item["y"])
                    if ty < 0.35 or ty + float(item["h"]) > 1.6:
                        issues.append({
                            "severity": "major", "slide_id": slide_id, "rule_id": "geometry.title_in_rail",
                            "message": f"标题框 y={ty:.2f} 未落在标题轨", "target_agent": "layout",
                        })
        # min_margin：执行 0.5in 安全边距
        for item in items:
            if item["kind"] in {"textbox", "note", "image", "chart"} and (
                float(item["x"]) < 0.5 - 0.01 or float(item["y"]) < 0.5 - 0.01
                or float(item["x"]) + float(item["w"]) > SLIDE_WIDTH - 0.5 + 0.01
                or float(item["y"]) + float(item["h"]) > SLIDE_HEIGHT - 0.5 + 0.01
            ):
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "geometry.min_margin",
                    "message": f"元素 {item['element_id']} 侵入 0.5in 安全边距", "target_agent": "layout",
                })
    return issues


class RunQaInput(BaseModel):
    pass


class RenderedPairVerdict(BaseModel):
    judgement: Literal["better", "same", "worse"] = "same"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    readability: float = Field(default=0.0, ge=0.0, le=100.0)
    balance: float = Field(default=0.0, ge=0.0, le=100.0)
    hierarchy: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: list[str] = Field(default_factory=list)


def _objective_metrics(runtime: Any) -> set[str]:
    params = dict(getattr(runtime, "layout_engine_params", None) or {})
    metrics = {
        str(item.get("metric") or "")
        for item in (params.get("objectives") or []) if isinstance(item, dict)
    }
    dimension = str(params.get("target_dimension") or "")
    aliases = {
        "size": "font_size", "distribution": "vertical_utilization",
        "balance": "whitespace_balance", "overall": "whitespace_balance",
    }
    if dimension:
        metrics.add(aliases.get(dimension, dimension))
    return {value for value in metrics if value and value != "none"}


def _requires_pairwise_vision(runtime: Any) -> bool:
    metrics = _objective_metrics(runtime)
    if not metrics:
        return getattr(runtime, "active_intent", "") in {"LAYOUT_ONLY", "GLOBAL_OPTIMIZE"}
    deterministic_only = {"font_size", "spacing", "alignment", "image_scale"}
    return not metrics.issubset(deterministic_only)


async def _run_rendered_qa(tc: ToolContext, slide_ids: set[str]) -> dict[str, Any]:
    """Render baseline/current decks, compute raster metrics, then review pairs."""
    from app.agent.layouts.zones import zones_for
    from app.agent.tools.vision_tools import provider_supports_vision
    from app.renderers.ppt_visual_qa import PPTVisualQARenderer
    from app.renderers.presentation_builder import PresentationBuilder

    result: dict[str, Any] = {
        "qa_level": "geometry", "degraded": True, "render_paths": {},
        "raster_metrics": {}, "vision_reviews": {}, "rejected_slide_ids": [],
        "rendered_slide_ids": [], "missing_render_slide_ids": sorted(slide_ids),
        "reason": "",
    }
    if tc.builder is None or tc.workspace_root is None or not PPTVisualQARenderer.is_available():
        result["reason"] = "真实渲染器不可用"
        return result

    qa_root = Path(tc.workspace_root) / "qa"
    current_pptx = qa_root / "current.pptx"
    baseline_pptx = qa_root / "baseline.pptx"
    try:
        # Render a staging deck containing only the pages under review.  This
        # preserves real templates/assets while avoiding two full-deck office
        # conversions for a one-page polish request.
        ordered_ids = [
            str(slide.get("id") or "") for slide in tc.builder.slides
            if str(slide.get("id") or "") in slide_ids
        ]
        current_by_id = {
            str(slide.get("id") or ""): deepcopy(slide) for slide in tc.builder.slides
        }
        current_content = {
            "theme": str((tc.builder.template or {}).get("id") or ""),
            "slides": [current_by_id[slide_id] for slide_id in ordered_ids],
        }
        current_builder = PresentationBuilder().from_ppt_content(current_content)
        current_builder.render(current_pptx)
        current_images = PPTVisualQARenderer.convert_pptx_to_images(
            current_pptx, qa_root / "current-images", dpi=120,
        )
        source_content = dict(
            getattr(getattr(tc.runtime, "source_artifact", None), "content_json", {}) or {}
        )
        if not source_content.get("slides"):
            source_content = {
                "theme": str((tc.builder.template or {}).get("id") or ""),
                "slides": deepcopy(runtime_baseline_slides(tc.runtime)),
            }
        source_by_id = {
            str(slide.get("id") or ""): deepcopy(slide)
            for slide in (source_content.get("slides") or [])
        }
        baseline_content = {
            "theme": str(source_content.get("theme") or current_content["theme"]),
            "slides": [source_by_id[slide_id] for slide_id in ordered_ids if slide_id in source_by_id],
        }
        baseline_builder = PresentationBuilder().from_ppt_content(baseline_content)
        baseline_builder.render(baseline_pptx)
        baseline_images = PPTVisualQARenderer.convert_pptx_to_images(
            baseline_pptx, qa_root / "baseline-images", dpi=120,
        )
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"真实渲染失败：{str(exc)[:240]}"
        return result

    current_index = {
        str(slide.get("id") or ""): index for index, slide in enumerate(current_builder.slides)
    }
    baseline_index = {
        str(slide.get("id") or ""): index for index, slide in enumerate(baseline_builder.slides)
    }
    provider = getattr(tc.runtime, "provider", None) or tc.provider
    vision_available = provider_supports_vision(provider)
    result["qa_level"] = "raster"
    result["degraded"] = False
    rendered_slide_ids: set[str] = set()

    for slide_id in sorted(slide_ids):
        ci, bi = current_index.get(slide_id), baseline_index.get(slide_id)
        if ci is None or bi is None or ci >= len(current_images) or bi >= len(baseline_images):
            continue
        rendered_slide_ids.add(slide_id)
        slide = current_builder.slides[ci]
        zones = zones_for(
            str((current_builder.template or {}).get("id") or ""),
            str(slide.get("page_type") or "concept"),
            has_visual=any(item.get("kind") in {"image", "chart"} for item in slide.get("elements") or []),
        )
        body = zones.body_column
        body_box = (body.x, body.y, body.w, body.h)
        before_metrics = PPTVisualQARenderer.raster_metrics(baseline_images[bi], body_box=body_box)
        after_metrics = PPTVisualQARenderer.raster_metrics(current_images[ci], body_box=body_box)
        result["raster_metrics"][slide_id] = {
            "baseline": before_metrics, "final": after_metrics,
            "vertical_delta": round(after_metrics["vertical_utilization"] - before_metrics["vertical_utilization"], 4),
            "blank_delta": round(after_metrics["largest_blank_ratio"] - before_metrics["largest_blank_ratio"], 4),
        }
        result["render_paths"][slide_id] = {
            "baseline": str(baseline_images[bi]), "final": str(current_images[ci]),
        }
        if not vision_available:
            continue
        pair_path = PPTVisualQARenderer.compose_before_after(
            baseline_images[bi], current_images[ci], qa_root / "pairs" / f"{slide_id}.png",
        )
        try:
            verdict = await provider.structured_with_image(
                "你是严谨的 PPT 视觉审稿人。左图是修改前，右图是修改后。只输出结构化 JSON。",
                (
                    "比较可读性、空间利用、留白平衡、层级、对齐、阅读顺序和模板一致性。"
                    "只有右图存在清晰且非微小的整体改善时 judgement 才为 better；"
                    "仅标题增加 1pt 或几何不变必须判为 same。"
                ),
                base64.b64encode(pair_path.read_bytes()).decode("ascii"),
                "image/png", RenderedPairVerdict,
            )
            result["vision_reviews"][slide_id] = verdict.model_dump()
            result["qa_level"] = "vision"
        except Exception as exc:  # noqa: BLE001
            result["vision_reviews"][slide_id] = {"error": str(exc)[:240]}
    missing = sorted(set(slide_ids) - rendered_slide_ids)
    result["rendered_slide_ids"] = sorted(rendered_slide_ids)
    result["missing_render_slide_ids"] = missing
    if missing:
        result["degraded"] = True
        result["reason"] = "目标页缺少真实渲染证据：" + "、".join(missing)
        if not rendered_slide_ids:
            result["qa_level"] = "geometry"
    return result


def _preserve_rejected_layout_pages(
    tc: ToolContext, rejected: dict[str, str], issues: list[dict[str, Any]],
) -> None:
    """Rollback failed staging pages and turn the run into partial/no_change."""
    if not rejected or tc.builder is None or tc.runtime is None:
        return
    baseline_by_id = {
        str(slide.get("id") or ""): slide for slide in runtime_baseline_slides(tc.runtime)
    }
    for index, slide in enumerate(tc.builder.slides):
        slide_id = str(slide.get("id") or "")
        if slide_id in rejected and slide_id in baseline_by_id:
            tc.builder.slides[index] = deepcopy(baseline_by_id[slide_id])
    tc.runtime.affected_slide_ids = [
        value for value in (getattr(tc.runtime, "affected_slide_ids", None) or [])
        if value not in rejected
    ]
    for item in getattr(tc.runtime, "layout_compile_results", None) or []:
        slide_id = str(item.get("slide_id") or "")
        if slide_id in rejected:
            reason_text = rejected[slide_id]
            item["status"] = "preserved"
            item["decision"] = "preserved"
            item["material_change"] = False
            item["rejection_code"] = (
                "render_unavailable"
                if (
                    "不可用" in reason_text or "渲染" in reason_text
                    or "证据" in reason_text or "render." in reason_text
                )
                else "vision_not_better"
                if "视觉审稿" in reason_text
                else "unsafe_geometry"
            )
            item["rejection_reasons"] = list(dict.fromkeys([
                *(item.get("rejection_reasons") or []), rejected[slide_id],
            ]))
            item["warnings"] = list(dict.fromkeys([
                *(item.get("warnings") or []), rejected[slide_id],
            ]))
    # Candidate issues describe a page that is no longer in the Builder. Keep
    # one warning for diagnostics, but do not fail the safely restored result.
    issues[:] = [
        item for item in issues if str(item.get("slide_id") or "") not in rejected
    ]
    issues.extend({
        "severity": "minor", "slide_id": slide_id,
        "rule_id": "layout.candidate_preserved", "message": reason,
        "target_agent": "layout",
    } for slide_id, reason in rejected.items())
    tc.runtime.result_status = "partial" if tc.runtime.affected_slide_ids else "no_change"
    tc.runtime.mutation_applied = True


async def _run_qa(tc: ToolContext, _: RunQaInput) -> ToolResult:
    issues: list[dict[str, Any]] = []
    selected = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
    affected = set(getattr(tc.runtime, "affected_slide_ids", []) or [])
    expected_image_slides: set[str] = set(selected)
    if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE" and tc.artifacts is not None:
        for artifact in await tc.artifacts.list_all():
            data = artifact.get("data") or {}
            if artifact.get("artifact_type") == "visual_asset":
                slide_id = str(data.get("slide_id") or "")
                if slide_id:
                    expected_image_slides.add(slide_id)
                for generated in data.get("generated_assets") or data.get("assets") or []:
                    slide_id = str(generated.get("slide_id") or "")
                    if slide_id:
                        expected_image_slides.add(slide_id)
            elif artifact.get("artifact_type") == "visual_plan":
                for plan in data.get("slides_visual_plan") or data.get("slides") or data.get("visual_plans") or []:
                    slide_id = str(plan.get("slide_id") or plan.get("slideId") or plan.get("id") or "")
                    if slide_id:
                        expected_image_slides.add(slide_id)
    qa_scope = (
        expected_image_slides
        if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE"
        else (affected or selected)
    )
    degraded = False
    content: dict[str, Any] = {}
    if tc.builder is not None:
        report = tc.builder.geometry_report()
        if qa_scope:
            report = [item for item in report if str(item.get("slide_id")) in qa_scope]
        quality_mode = (
            (getattr(tc.runtime, "layout_engine_params", None) or {}).get("quality_mode")
            == "polish_v2"
        )
        qa_operation_domains = {
            str(item.get("domain") or "")
            for item in ((getattr(tc.runtime, "layout_engine_params", None) or {}).get("operations") or [])
            if isinstance(item, dict)
        }
        layout_quality_mode = quality_mode and bool(
            # A template switch changes the design system, not the page's
            # requested content distribution.  Applying the V2 "polish this
            # layout" utilisation thresholds to every legacy page would turn
            # pre-existing whitespace into a new blocking defect.  Template
            # runs still receive the unconditional bounds/overflow/overlap
            # checks below plus real rendered evidence.
            qa_operation_domains & {"layout", "typography", "style", "image_geometry"}
        )
        image_geometry_only = bool(
            (getattr(tc.runtime, "layout_engine_params", None) or {}).get("image_geometry_only")
        )
        deterministic_metrics = _objective_metrics(tc.runtime)
        deterministic_only = bool(deterministic_metrics) and deterministic_metrics.issubset({
            "font_size", "spacing", "alignment", "image_scale",
        })
        issues.extend(run_geometry_qa(
            report,
            enforce_readability=layout_quality_mode and not image_geometry_only,
            enforce_quality=layout_quality_mode and not image_geometry_only and not deterministic_only,
        ))
        if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}:
            for issue in issues:
                if issue.get("target_agent") == "slide_content":
                    issue["target_agent"] = "layout"
        content = tc.builder.to_ppt_content()
        try:
            from app.services.ppt_knowledge_service import check_ppt_against_knowledge
            if (
                getattr(tc.runtime, "active_intent", "GENERATE") in CONTENT_QA_INTENTS
                and getattr(tc.runtime, "content_policy", "edit") == "edit"
            ):
                for violation in check_ppt_against_knowledge(content):
                    if qa_scope and str(violation.slide_id) not in qa_scope:
                        continue
                    issues.append({
                        "severity": "major" if violation.rule_id.startswith("density") else "minor",
                        "slide_id": violation.slide_id, "rule_id": violation.rule_id, "message": violation.message,
                        "target_agent": "slide_content" if violation.rule_id.startswith("density") else "ppt_editor",
                    })
        except Exception:  # noqa: BLE001
            pass
        source_by_id = {
            str(slide.get("id") or ""): slide
            for slide in runtime_baseline_slides(tc.runtime)
        }
        # Coverage/content hashes apply to every requested page; visual QA and
        # geometry scoring apply only to pages that were actually changed.
        coverage_scope = selected or qa_scope or set(source_by_id)
        coverage_by_slide: dict[str, Any] = {}
        for slide in tc.builder.slides:
            slide_id = str(slide.get("id") or "")
            if coverage_scope and slide_id not in coverage_scope:
                continue
            # Preserve/restore must prove coverage against the immutable source.
            # An edit run intentionally changes semantic copy, so its absolute
            # layout must be checked against the newly edited slide instead of
            # stale text from the previous Artifact version.
            baseline = (
                source_by_id.get(slide_id, slide)
                if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
                else slide
            )
            coverage = render_coverage(slide, baseline=baseline)
            coverage_by_slide[slide_id] = coverage
            if coverage["missing_refs"]:
                absolute = infer_render_mode(slide) == "absolute"
                issues.append({
                    "severity": "critical", "slide_id": slide_id,
                    "rule_id": "layout.incomplete_absolute" if absolute else "content.not_rendered",
                    "message": "绝对布局未覆盖页面必要文字" if absolute else "页面语义文字没有进入最终渲染层",
                    "target_agent": "layout",
                    "missing_refs": coverage["missing_refs"],
                    "missing_text": semantic_ref_details(baseline, coverage["missing_refs"]),
                })
            if (
                getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
                and slide_id in source_by_id
                and semantic_content_changed(source_by_id[slide_id], slide)
            ):
                issues.append({
                    "severity": "critical", "slide_id": slide_id,
                    "rule_id": "content.accidentally_removed",
                    "message": "内容锁定任务意外改动了页面语义文字",
                    "target_agent": "layout",
                })
            final_elements = tc.builder.render_elements(slide)
            text_elements = [item for item in final_elements if item.get("kind") in {"textbox", "note"}]
            media_elements = [item for item in final_elements if item.get("kind") in {"image", "chart"}]
            if getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}:
                from app.agent.agents.layout import _content_start_x
                safe_x = _content_start_x(
                    str(tc.builder.template.get("id") or ""),
                    str(slide.get("page_type") or "concept"),
                )
                if any(
                    item.get("content_ref")
                    and float(item.get("x") or 0) < safe_x - 0.01
                    for item in text_elements
                ):
                    issues.append({
                        "severity": "critical", "slide_id": slide_id,
                        "rule_id": "visual.overlaps_template",
                        "message": "页面文字进入模板装饰或侧栏遮挡区域",
                        "target_agent": "layout",
                    })
            for media in media_elements:
                mx, my, mw, mh = (float(media.get(key) or 0) for key in ("x", "y", "w", "h"))
                for text_element in text_elements:
                    tx, ty, tw, th = (float(text_element.get(key) or 0) for key in ("x", "y", "w", "h"))
                    overlap_w = max(0.0, min(mx + mw, tx + tw) - max(mx, tx))
                    overlap_h = max(0.0, min(my + mh, ty + th) - max(my, ty))
                    if overlap_w * overlap_h > 0.05:
                        issues.append({
                            "severity": "critical", "slide_id": slide_id,
                            "rule_id": "visual.overlaps_content",
                            "message": "图片或图表遮挡了页面文字区域",
                            "target_agent": "layout",
                        })
                        break
        if tc.runtime is not None:
            tc.runtime.render_coverage = coverage_by_slide

        if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE":
            expected_slots = {
                str(item.get("slide_id") or ""): str(item.get("visual_slot") or "primary_visual")
                for item in (getattr(tc.runtime, "expected_visual_requests", []) or [])
            }
            scoped_slides = [slide for slide in tc.builder.slides if str(slide.get("id")) in expected_image_slides]
            for slide in scoped_slides:
                images = [element for element in (slide.get("elements") or []) if element.get("kind") == "image"]
                valid_ids = set(getattr(tc.runtime, "generated_asset_ids", []) or [])
                valid_images = []
                for element in images:
                    asset_path = str(element.get("asset_path") or "")
                    asset_id = str(element.get("asset_id") or "")
                    candidate = Path(asset_path)
                    # 新写入的图片应当是绝对路径；同时兼容旧 Run 留下的 workspace
                    # 相对路径。仅当原路径不存在时才拼 workspace_root，避免把
                    # ``storage/.../run/assets/x`` 再拼成 ``storage/.../run/storage/...``。
                    if not candidate.is_file() and tc.workspace_root is not None and not candidate.is_absolute():
                        workspace_candidate = Path(tc.workspace_root) / candidate
                        if workspace_candidate.is_file():
                            candidate = workspace_candidate.resolve()
                    if asset_id in valid_ids and candidate.is_file() and not element.get("degraded"):
                        valid_images.append(element)
                if not valid_images:
                    issues.append({
                        "severity": "critical", "slide_id": str(slide.get("id") or ""),
                        "rule_id": "image.missing", "message": "目标页面尚未插入生成图片",
                        "target_agent": "media",
                    })
                else:
                    expected_slot = expected_slots.get(str(slide.get("id") or ""), "primary_visual")
                    if not any(str(element.get("visual_slot") or "primary_visual") == expected_slot for element in valid_images):
                        issues.append({
                            "severity": "critical", "slide_id": str(slide.get("id") or ""),
                            "rule_id": "visual.slot_missing", "message": "生成图片没有进入规划的视觉槽位",
                            "target_agent": "ppt_editor",
                        })
    else:
        content = tc.ctx.source_artifact.content_json if tc.ctx and tc.ctx.source_artifact is not None else {}

    rendered = await _run_rendered_qa(tc, qa_scope) if qa_scope else {
        "qa_level": "geometry", "degraded": True, "render_paths": {},
        "raster_metrics": {}, "vision_reviews": {}, "rejected_slide_ids": [],
        "rendered_slide_ids": [], "missing_render_slide_ids": [],
        "reason": "没有实际修改页",
    }
    operation_domains = {
        str(item.get("domain") or "")
        for item in ((getattr(tc.runtime, "layout_engine_params", None) or {}).get("operations") or [])
        if isinstance(item, dict)
    }
    requires_render_evidence = (
        getattr(tc.runtime, "active_intent", "")
        in {"LAYOUT_ONLY", "GLOBAL_OPTIMIZE", "STYLE_CHANGE", "TEMPLATE_SWITCH", "IMAGE_UPDATE"}
        or bool(operation_domains & {"layout", "typography", "style", "template", "image_asset", "image_geometry"})
    )
    if requires_render_evidence:
        for slide_id in rendered.get("missing_render_slide_ids") or []:
            issues.append({
                "severity": "critical", "slide_id": str(slide_id),
                "rule_id": "render.evidence_missing",
                "message": "目标页面没有获得本轮真实渲染证据",
                "target_agent": "ppt_editor",
            })
    degraded = bool(rendered.get("degraded"))
    rejected: dict[str, str] = {}
    layout_only = (
        getattr(tc.runtime, "active_intent", "") in {"LAYOUT_ONLY", "GLOBAL_OPTIMIZE"}
        and getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
    )
    if layout_only:
        # Any deterministic hard failure rejects that page locally.  The
        # baseline is restored instead of letting one page fail the whole run.
        for issue in issues:
            slide_id = str(issue.get("slide_id") or "")
            if slide_id in qa_scope and issue.get("severity") in {"critical", "major"}:
                rule_id = str(issue.get("rule_id") or "")
                rejected.setdefault(
                    slide_id,
                    (
                        "候选缺少真实渲染证据，已保留原布局"
                        if rule_id == "render.evidence_missing"
                        else f"候选未通过 {rule_id}，已保留原布局"
                    ),
                )

        pairwise_required = _requires_pairwise_vision(tc.runtime)
        spatial_quality_required = bool(
            pairwise_required
            or _objective_metrics(tc.runtime) & {
                "layout_quality", "vertical_utilization", "horizontal_utilization",
                "whitespace_balance", "density",
            }
        )
        if rendered.get("qa_level") == "geometry" and pairwise_required:
            for slide_id in qa_scope:
                rejected.setdefault(
                    slide_id,
                    f"{rendered.get('reason') or '真实视觉 QA 不可用'}，通用布局润色未发布",
                )
        if spatial_quality_required:
            for slide_id, metrics in (rendered.get("raster_metrics") or {}).items():
                final_metrics = metrics.get("final") or {}
                if (
                    float(final_metrics.get("vertical_utilization") or 0) < 0.50
                    or float(final_metrics.get("largest_blank_ratio") or 1) > 0.50
                ):
                    rejected.setdefault(slide_id, "真实渲染显示页面利用不足，已保留原布局")
        if pairwise_required:
            for slide_id in qa_scope:
                review = (rendered.get("vision_reviews") or {}).get(slide_id) or {}
                if review.get("judgement") != "better" or float(review.get("confidence") or 0) < 0.65:
                    reason = (
                        "视觉审稿未确认页面明显改善，已保留原布局"
                        if review and not review.get("error")
                        else "视觉模型不可用，通用布局润色未发布"
                    )
                    rejected.setdefault(slide_id, reason)
        else:
            # Explicit size/spacing requests may be deterministic, but a
            # confident 'worse' visual verdict still vetoes publication.
            for slide_id, review in (rendered.get("vision_reviews") or {}).items():
                if review.get("judgement") == "worse" and float(review.get("confidence") or 0) >= 0.65:
                    rejected.setdefault(slide_id, "视觉审稿认为结果变差，已保留原布局")

    _preserve_rejected_layout_pages(tc, rejected, issues)
    rendered["rejected_slide_ids"] = sorted(rejected)

    severity_counts: dict[str, int] = {}
    for issue in issues:
        severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1
    geometry_score = max(0, 100 - sum(SEVERITY_WEIGHT.get(item["severity"], 3) for item in issues))
    # A degraded check is not a visual score.  Keep geometry_score explicit and
    # cap the compatibility score so the UI can never claim "视觉 QA 100".
    score = min(90, geometry_score) if degraded else geometry_score
    compile_results = list(getattr(tc.runtime, "layout_compile_results", None) or [])
    deltas = [
        float(item.get("quality_delta") or 0) for item in compile_results
        if item.get("status") != "preserved"
    ]
    baseline_scores = [
        float((item.get("baseline_metrics") or {}).get("quality_score") or 0)
        for item in compile_results if item.get("baseline_metrics")
    ]
    objective_results = [
        {"slide_id": item.get("slide_id"), **objective}
        for item in compile_results for objective in (item.get("objective_results") or [])
    ]
    visual_scores = [
        (float(review.get("readability") or 0) + float(review.get("balance") or 0)
         + float(review.get("hierarchy") or 0)) / 3
        for review in (rendered.get("vision_reviews") or {}).values()
        if isinstance(review, dict) and not review.get("error")
    ]
    result = {
        "score": score,
        "safety_status": "fail" if any(
            issue.get("severity") in {"critical", "major"} for issue in issues
        ) else "pass",
        "qa_level": rendered.get("qa_level", "geometry"),
        "geometry_score": geometry_score,
        "visual_quality_score": round(sum(visual_scores) / len(visual_scores), 1) if visual_scores else None,
        "baseline_score": round(sum(baseline_scores) / len(baseline_scores), 1) if baseline_scores else None,
        "improvement_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        "objective_results": objective_results,
        "issues": issues,
        "severity_counts": severity_counts,
        "degraded": degraded,
        "image_qa": rendered.get("reason") or f"{rendered.get('qa_level', 'geometry')} QA",
        "render_paths": rendered.get("render_paths") or {},
        "raster_metrics": rendered.get("raster_metrics") or {},
        "vision_reviews": rendered.get("vision_reviews") or {},
        "rejected_slide_ids": rendered.get("rejected_slide_ids") or [],
        "rendered_slide_ids": rendered.get("rendered_slide_ids") or [],
        "missing_render_slide_ids": rendered.get("missing_render_slide_ids") or [],
    }

    artifact = None
    if tc.artifacts is not None:
        artifact = await tc.artifacts.create("visual_qa", "default", result,
                                             producer_agent="visual_qa", producer_tool="run_qa")
    if tc.emitter is not None:
        for issue in issues:
            await tc.emitter.qa_issue_found(issue)
        await tc.emitter.qa_completed(score, len(issues), severity_counts,
                                      round_=getattr(tc.ctx, "revision_round", 0), degraded=degraded,
                                      issues=issues, qa_level=str(result["qa_level"]),
                                      geometry_score=geometry_score,
                                      visual_quality_score=result["visual_quality_score"],
                                      improvement_delta=float(result["improvement_delta"]))
    return ToolResult(ok=True, output={"qa_artifact_id": artifact["id"] if artifact else "", **result})


class GetQaReportInput(BaseModel):
    pass


async def _get_qa_report(tc: ToolContext, _: GetQaReportInput) -> ToolResult:
    if tc.artifacts is not None:
        latest = await tc.artifacts.latest("visual_qa")
        if latest:
            return ToolResult(ok=True, output={"qa": latest["data"]})
    return ToolResult(ok=False, error="尚无 QA 报告")


async def _run_content_qa(tc: ToolContext, _: RunQaInput) -> ToolResult:
    if getattr(tc.runtime, "content_policy", "edit") != "edit":
        return ToolResult(ok=True, output={"issues": [], "coverage": {"slides_checked": 0}, "score": 100, "skipped": "content_locked"})
    content = tc.builder.to_ppt_content() if tc.builder is not None else (
        tc.ctx.source_artifact.content_json if tc.ctx and tc.ctx.source_artifact is not None else {}
    )
    issues: list[dict[str, Any]] = []
    selected = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
    seen_titles: dict[str, str] = {}
    checked = 0
    for index, slide in enumerate(content.get("slides") or []):
        slide_id = str(slide.get("id") or f"S{index + 1:02d}")
        title = str(slide.get("title") or "").strip()
        body = [str(item).strip() for item in (slide.get("body") or []) if str(item).strip()]
        in_scope = not selected or slide_id in selected
        if in_scope:
            checked += 1
        if in_scope and title and title in seen_titles:
            issues.append({"severity": "major", "slide_id": slide_id, "rule_id": "content.duplicate_title", "message": f"标题与 {seen_titles[title]} 重复", "target_agent": "slide_content"})
        elif title:
            seen_titles[title] = slide_id
        if in_scope and len(body) > 6:
            issues.append({"severity": "major", "slide_id": slide_id, "rule_id": "content.density", "message": f"页面包含 {len(body)} 条正文，超过 6 条", "target_agent": "slide_content"})
        if in_scope and not title and slide.get("page_type") != "cover":
            issues.append({"severity": "minor", "slide_id": slide_id, "rule_id": "content.missing_title", "message": "页面缺少标题", "target_agent": "slide_content"})
    result = {"issues": issues, "coverage": {"slides_checked": checked}, "score": max(0, 100 - len(issues) * 8)}
    artifact = await tc.artifacts.create("content_qa", "default", result, producer_agent="visual_qa", producer_tool="run_content_qa") if tc.artifacts else None
    if tc.emitter:
        await tc.emitter.emit_domain("qa.completed", message=f"内容 QA 完成，发现 {len(issues)} 个问题", payload={"kind": "content", **result})
    return ToolResult(ok=True, output={"qa_artifact_id": artifact["id"] if artifact else "", **result})


def register_qa_tools():
    register_tool(Tool("run_qa", "运行几何/字宽/知识 QA，返回评分与问题列表", RunQaInput, _run_qa, timeout_seconds=120, max_retries=1, idempotent=True))
    register_tool(Tool("run_content_qa", "检查目标覆盖、重复、缺失标题和内容密度", RunQaInput, _run_content_qa, timeout_seconds=60, idempotent=True))
    register_tool(Tool("get_qa_report", "读取最近一次 QA 报告", GetQaReportInput, _get_qa_report))


register_qa_tools()
