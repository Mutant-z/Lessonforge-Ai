"""Target-slide semantic and geometric analysis for polish runs."""
from __future__ import annotations

import math
import re
from statistics import median
from typing import Any

from app.agent.layouts.zones import zones_for
from app.agent.slide_rendering import semantic_body_refs


def _normalized_text(value: str) -> str:
    return re.sub(r"[\s，,。；;：:！？!?（）()]+", "", str(value or "")).lower()


def build_slide_semantic_graph(slide: dict[str, Any]) -> dict[str, Any]:
    """Adapt historical body/blocks/elements into one stable semantic graph."""
    units: list[dict[str, Any]] = []
    if slide.get("title"):
        units.append({
            "semantic_id": "title", "text": str(slide.get("title") or ""),
            "role": "title", "level": 0, "group_id": "title",
            "reading_order": 0, "locked": True,
        })
    step_blocks = {
        index for index, block in enumerate(slide.get("blocks") or [])
        if block.get("kind") == "steps"
    }
    for order, (ref, text) in enumerate(semantic_body_refs(slide), 1):
        group_id = f"content:{order}"
        step_match = re.match(r"blocks\.(\d+)\.steps\.(\d+)\.", ref)
        body_match = re.fullmatch(r"body\.(\d+)", ref)
        if step_match and int(step_match.group(1)) in step_blocks:
            group_id = f"step:{step_match.group(2)}"
        elif body_match and step_blocks:
            group_id = f"step:{body_match.group(1)}"
        role = "body"
        if ref.endswith(".title"):
            role = "group_title"
        elif ref.endswith(".citation"):
            role = "citation"
        elif ".detail" in ref:
            role = "detail"
        units.append({
            "semantic_id": ref, "text": text, "role": role,
            "level": 1 if role == "group_title" else 2,
            "group_id": group_id, "reading_order": order, "locked": True,
        })

    # Alias only exact server-observed textual projections. Fuzzy similarity
    # is intentionally not enough to suppress a protected historical ref.
    by_text: dict[str, list[str]] = {}
    for unit in units:
        normalized = _normalized_text(unit["text"])
        if normalized:
            by_text.setdefault(normalized, []).append(unit["semantic_id"])
    alias_groups = [values for values in by_text.values() if len(values) > 1]
    element_bindings: dict[str, list[str]] = {}
    for element in slide.get("elements") or []:
        ref = str(element.get("content_ref") or "")
        if ref:
            element_bindings.setdefault(ref, []).append(str(element.get("id") or ""))
    return {
        "slide_id": str(slide.get("id") or ""),
        "units": units,
        "groups": list(dict.fromkeys(unit["group_id"] for unit in units)),
        "reading_order": [unit["semantic_id"] for unit in units],
        "semantic_alias_groups": alias_groups,
        "element_bindings": element_bindings,
    }


def _layout_metrics(elements: list[dict[str, Any]], body_zone: Any) -> dict[str, Any]:
    text = [
        item for item in elements
        if item.get("kind") in {"textbox", "note"}
        and str(item.get("content_ref") or "") != "title"
        and str(item.get("role") or "") != "title"
    ]
    if not text:
        return {
            "vertical_utilization": 0.0, "horizontal_utilization": 0.0,
            "median_body_font": 0.0, "weighted_mean_font": 0.0,
            "alignment_error": 1.0, "spacing_cv": 1.0,
        }
    min_x = min(float(item.get("x") or 0) for item in text)
    max_x = max(float(item.get("x") or 0) + float(item.get("w") or 0) for item in text)
    min_y = min(float(item.get("y") or 0) for item in text)
    max_y = max(float(item.get("y") or 0) + float(item.get("h") or 0) for item in text)
    sizes = [float((item.get("style") or {}).get("size") or 0) for item in text]
    weights = [max(1, len(str(item.get("text") or ""))) for item in text]
    lefts = sorted(float(item.get("x") or 0) for item in text)
    anchor = median(lefts)
    alignment_error = sum(abs(value - anchor) for value in lefts) / max(1, len(lefts))
    ordered = sorted(text, key=lambda item: (float(item.get("y") or 0), float(item.get("x") or 0)))
    gaps = [
        max(0.0, float(right.get("y") or 0) - (
            float(left.get("y") or 0) + float(left.get("h") or 0)
        ))
        for left, right in zip(ordered, ordered[1:])
    ]
    gap_mean = sum(gaps) / len(gaps) if gaps else 0.0
    gap_variance = sum((value - gap_mean) ** 2 for value in gaps) / len(gaps) if gaps else 0.0
    spacing_cv = math.sqrt(gap_variance) / gap_mean if gap_mean > 0.01 else 0.0
    return {
        "vertical_utilization": round(min(1.0, (max_y - min_y) / max(0.01, body_zone.h)), 4),
        "horizontal_utilization": round(min(1.0, (max_x - min_x) / max(0.01, body_zone.w)), 4),
        "median_body_font": round(float(median(sizes)), 2),
        "weighted_mean_font": round(sum(size * weight for size, weight in zip(sizes, weights)) / sum(weights), 2),
        "alignment_error": round(alignment_error, 4),
        "spacing_cv": round(spacing_cv, 4),
        "content_bounds": {
            "x": round(min_x, 3), "y": round(min_y, 3),
            "w": round(max_x - min_x, 3), "h": round(max_y - min_y, 3),
        },
    }


def build_slide_analysis(
    slide: dict[str, Any], template_id: str, *, objectives: list[dict[str, Any]] | None = None,
    baseline_png: str = "",
) -> dict[str, Any]:
    has_visual = any(
        item.get("kind") in {"image", "chart"} for item in slide.get("elements") or []
    )
    zones = zones_for(template_id, str(slide.get("page_type") or "concept"), has_visual=has_visual)
    elements = list(slide.get("elements") or [])
    metrics = _layout_metrics(elements, zones.body_column)
    defects: list[str] = []
    if metrics["vertical_utilization"] and metrics["vertical_utilization"] < 0.45:
        defects.append("vertical_underuse")
    if metrics["median_body_font"] and metrics["median_body_font"] < 16:
        defects.append("body_font_small")
    if metrics["alignment_error"] > 0.08:
        defects.append("alignment_drift")
    return {
        "slide_id": str(slide.get("id") or ""),
        "page_type": str(slide.get("page_type") or "concept"),
        "teaching_task": str(slide.get("purpose") or ""),
        "content": {
            "title": str(slide.get("title") or ""),
            "body": list(slide.get("body") or []),
            "blocks": list(slide.get("blocks") or []),
            "speaker_notes": str(slide.get("speaker_notes") or ""),
            "duration_seconds": int(slide.get("duration_seconds") or 0),
        },
        "semantic_graph": build_slide_semantic_graph(slide),
        "elements": elements,
        "template": {
            "template_id": template_id,
            "title_rail": zones.title_rail.__dict__,
            "body_zone": zones.body_column.__dict__,
            "visual_slot": zones.visual_slot.__dict__ if zones.visual_slot else None,
        },
        "baseline_png": baseline_png,
        "baseline_metrics": metrics,
        "detected_defects": defects,
        "objectives": list(objectives or []),
    }


__all__ = ["build_slide_analysis", "build_slide_semantic_graph"]
