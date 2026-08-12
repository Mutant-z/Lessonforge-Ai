"""Deterministic layout analysis used by the preset candidate search.

The compiler must be able to reject a geometrically valid but visibly weak
layout without relying on a vision provider.  The metrics in this module are
deliberately based on the body rail (the title is chrome, not evidence that the
page is well occupied) and are stable enough to persist in compile diagnostics.
They are not a replacement for rendered/vision QA; they are the deterministic
gate that prevents first-fit regressions before a candidate reaches that QA.
"""

from __future__ import annotations

import statistics
from typing import Any

from app.agent.layouts.metrics import estimate_text_height
from app.agent.layouts.zones import LayoutZones
from app.agent.slide_rendering import semantic_body_refs


_MEANINGFUL_KINDS = {"textbox", "note", "image", "chart"}
_VISUAL_SHAPE_ROLES = {
    "step_card", "highlight_panel", "compare_panel", "quote_panel", "visual_panel",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_title(element: dict[str, Any], zones: LayoutZones) -> bool:
    role = str(element.get("role") or "").lower()
    ref = str(element.get("content_ref") or "")
    return role in {"title", "subtitle"} or ref == "title" or (
        _number(element.get("y")) + _number(element.get("h")) <= zones.body_column.y - 0.04
    )


def _clipped_box(element: dict[str, Any], zones: LayoutZones) -> tuple[float, float, float, float] | None:
    col = zones.body_column
    left = max(col.x, _number(element.get("x")))
    top = max(col.y, _number(element.get("y")))
    right = min(col.right, _number(element.get("x")) + _number(element.get("w")))
    bottom = min(col.bottom, _number(element.get("y")) + _number(element.get("h")))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _union_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """Exact axis-aligned union area for the small element sets on one slide."""
    xs = sorted({value for box in boxes for value in (box[0], box[2])})
    if len(xs) < 2:
        return 0.0
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (top, bottom) for x1, top, x2, bottom in boxes
            if x1 < right - 1e-9 and x2 > left + 1e-9
        )
        covered = 0.0
        cursor_top = cursor_bottom = None
        for top, bottom in intervals:
            if cursor_top is None:
                cursor_top, cursor_bottom = top, bottom
            elif top <= float(cursor_bottom) + 1e-9:
                cursor_bottom = max(float(cursor_bottom), bottom)
            else:
                covered += float(cursor_bottom) - float(cursor_top)
                cursor_top, cursor_bottom = top, bottom
        if cursor_top is not None:
            covered += float(cursor_bottom) - float(cursor_top)
        area += (right - left) * covered
    return area


def _max_blank_fraction(
    boxes: list[tuple[float, float, float, float]], zones: LayoutZones,
    *, rows: int = 16, columns: int = 24,
) -> float:
    """Approximate the largest contiguous blank rectangle on the body rail.

    A fixed grid makes the result deterministic and, importantly, catches the
    common failure where three wide columns occupy only the top third.  A wide
    title never participates because callers pass body-only boxes.
    """
    if not boxes:
        return 1.0
    col = zones.body_column
    cell_w, cell_h = col.w / columns, col.h / rows
    occupied = [[False] * columns for _ in range(rows)]
    for row in range(rows):
        cy = col.y + (row + 0.5) * cell_h
        for column in range(columns):
            cx = col.x + (column + 0.5) * cell_w
            occupied[row][column] = any(
                left <= cx <= right and top <= cy <= bottom
                for left, top, right, bottom in boxes
            )

    heights = [0] * columns
    largest_cells = 0
    for row in range(rows):
        for column in range(columns):
            heights[column] = 0 if occupied[row][column] else heights[column] + 1
        stack: list[int] = []
        for column in range(columns + 1):
            height = heights[column] if column < columns else 0
            while stack and heights[stack[-1]] > height:
                index = stack.pop()
                left = stack[-1] + 1 if stack else 0
                largest_cells = max(largest_cells, heights[index] * (column - left))
            stack.append(column)
    return min(1.0, largest_cells / float(rows * columns))


def _quadrant_balance(
    boxes: list[tuple[float, float, float, float]], zones: LayoutZones,
) -> tuple[float, float, float]:
    if not boxes:
        return 0.0, 0.0, 0.0
    col = zones.body_column
    center_x, center_y = col.x + col.w / 2, col.y + col.h / 2
    quadrants = []
    for left, top, right, bottom in (
        (col.x, col.y, center_x, center_y),
        (center_x, col.y, col.right, center_y),
        (col.x, center_y, center_x, col.bottom),
        (center_x, center_y, col.right, col.bottom),
    ):
        clipped = []
        for bx1, by1, bx2, by2 in boxes:
            x1, y1, x2, y2 = max(left, bx1), max(top, by1), min(right, bx2), min(bottom, by2)
            if x2 > x1 and y2 > y1:
                clipped.append((x1, y1, x2, y2))
        quadrants.append(_union_area(clipped))
    total = sum(quadrants)
    if total <= 1e-9:
        return 0.0, 0.0, 0.0
    left_area, right_area = quadrants[0] + quadrants[2], quadrants[1] + quadrants[3]
    top_area, bottom_area = quadrants[0] + quadrants[1], quadrants[2] + quadrants[3]
    horizontal = 1.0 - abs(left_area - right_area) / total
    vertical = 1.0 - abs(top_area - bottom_area) / total
    return max(0.0, horizontal), max(0.0, vertical), max(0.0, (horizontal + vertical) / 2)


def _spacing_metrics(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float]:
    gaps: list[float] = []
    for index, (left, top, right, bottom) in enumerate(boxes):
        for other_left, other_top, other_right, other_bottom in boxes[index + 1:]:
            overlap_x = max(0.0, min(right, other_right) - max(left, other_left))
            overlap_y = max(0.0, min(bottom, other_bottom) - max(top, other_top))
            if overlap_x >= 0.25 * min(right - left, other_right - other_left):
                gap = max(other_top - bottom, top - other_bottom)
                if 0.03 <= gap <= 1.5:
                    gaps.append(gap)
            elif overlap_y >= 0.25 * min(bottom - top, other_bottom - other_top):
                gap = max(other_left - right, left - other_right)
                if 0.03 <= gap <= 1.5:
                    gaps.append(gap)
    if not gaps:
        return 0.0, 0.0
    mean = statistics.fmean(gaps)
    deviation = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    return mean, deviation / mean if mean > 1e-9 else 0.0


def _alignment_error(boxes: list[tuple[float, float, float, float]], zones: LayoutZones) -> float:
    if not boxes:
        return 1.0
    anchors = [zones.body_column.x, zones.body_column.right, zones.body_column.x + zones.body_column.w / 2]
    edges = [value for left, _top, right, _bottom in boxes for value in (left, right)]
    errors: list[float] = []
    for index, edge in enumerate(edges):
        other_edges = edges[:index] + edges[index + 1:]
        errors.append(min(abs(edge - value) for value in [*anchors, *other_edges]))
    return statistics.median(errors) if errors else 1.0


def _reading_order_score(
    elements: list[dict[str, Any]], slide: dict[str, Any] | None,
) -> float:
    if not slide:
        return 0.8
    expected = {ref: index for index, (ref, _text) in enumerate(semantic_body_refs(slide))}
    items = [
        element for element in elements
        if str(element.get("content_ref") or "") in expected and not str(element.get("content_ref")) == "title"
    ]
    if len(items) < 2:
        return 1.0
    x_positions = sorted({_number(item.get("x")) for item in items})
    multi_column = len(x_positions) > 1 and x_positions[-1] - x_positions[0] > 1.0
    ordered = sorted(
        items,
        key=(
            (lambda item: (_number(item.get("x")), _number(item.get("y"))))
            if multi_column else
            (lambda item: (_number(item.get("y")), _number(item.get("x"))))
        ),
    )
    indices = [expected[str(item.get("content_ref"))] for item in ordered]
    inversions = sum(
        1 for index, value in enumerate(indices) for other in indices[index + 1:] if value > other
    )
    maximum = len(indices) * (len(indices) - 1) / 2
    return max(0.0, 1.0 - inversions / maximum) if maximum else 1.0


def _structure_fit(slide: dict[str, Any] | None, layout_type: str) -> float:
    if not slide:
        return 0.8
    kinds = {str(block.get("kind") or "") for block in (slide.get("blocks") or [])}
    if {"quote", "compare"} <= kinds:
        return {"quote_compare": 1.0, "split_two_column": 0.72, "bullet_flow": 0.55}.get(layout_type, 0.45)
    if "steps" in kinds:
        return {"steps_horizontal": 1.0, "split_two_column": 0.72, "bullet_flow": 0.58}.get(layout_type, 0.45)
    if "compare" in kinds:
        return {"compare_columns": 1.0, "split_two_column": 0.78, "bullet_flow": 0.58}.get(layout_type, 0.5)
    if "quote" in kinds:
        return {"quote_center": 1.0, "bullet_flow": 0.72, "split_two_column": 0.6}.get(layout_type, 0.5)
    if any(element.get("kind") in {"image", "chart"} for element in (slide.get("elements") or [])):
        return 1.0 if layout_type == "left_text_right_visual" else 0.68
    return {"bullet_flow": 1.0, "agenda_list": 0.95, "split_two_column": 0.85}.get(layout_type, 0.72)


def analyze_layout(
    elements: list[dict[str, Any]], zones: LayoutZones,
    *, slide: dict[str, Any] | None = None, layout_type: str = "",
) -> dict[str, Any]:
    """Return stable body-rail metrics and the deterministic 100-point score."""
    body_elements = [
        element for element in elements
        if not _is_title(element, zones)
        and (
            element.get("kind") in _MEANINGFUL_KINDS
            or (
                element.get("kind") == "shape"
                and str(element.get("role") or "") in _VISUAL_SHAPE_ROLES
            )
        )
    ]
    meaningful_boxes = [box for item in body_elements if (box := _clipped_box(item, zones))]
    text_elements = [item for item in body_elements if item.get("kind") in {"textbox", "note"}]
    text_boxes = [box for item in text_elements if (box := _clipped_box(item, zones))]
    content_boxes = [
        box for item in body_elements
        if item.get("kind") in _MEANINGFUL_KINDS and (box := _clipped_box(item, zones))
    ]
    col = zones.body_column
    if content_boxes:
        vertical = (max(box[3] for box in content_boxes) - min(box[1] for box in content_boxes)) / col.h
        horizontal = (max(box[2] for box in content_boxes) - min(box[0] for box in content_boxes)) / col.w
    else:
        vertical = horizontal = 0.0
    occupied = _union_area(meaningful_boxes) / max(0.01, col.w * col.h)
    max_blank = _max_blank_fraction(meaningful_boxes, zones)
    horizontal_balance, vertical_balance, whitespace_balance = _quadrant_balance(meaningful_boxes, zones)

    body_font_sizes = [
        _number((item.get("style") or {}).get("size"), 18.0)
        for item in text_elements
        if str(item.get("content_ref") or "") != "title"
        and str(item.get("role") or "") != "step_index"
        and str(item.get("text") or "").strip()
    ]
    title_sizes = [
        _number((item.get("style") or {}).get("size"), 28.0)
        for item in elements if _is_title(item, zones) and item.get("kind") in {"textbox", "note"}
    ]
    median_font = statistics.median(body_font_sizes) if body_font_sizes else 0.0
    min_font = min(body_font_sizes) if body_font_sizes else 0.0
    max_font = max(body_font_sizes) if body_font_sizes else 0.0
    spacing_mean, spacing_cv = _spacing_metrics(text_boxes)
    alignment_error = _alignment_error(content_boxes, zones)
    character_count = sum(len(str(item.get("text") or "")) for item in text_elements)
    density = character_count / max(0.1, _union_area(content_boxes))
    fill_ratios = []
    for item in text_elements:
        width, height = _number(item.get("w")), _number(item.get("h"))
        if width > 0 and height > 0:
            size = _number((item.get("style") or {}).get("size"), 18.0)
            fill_ratios.append(min(1.5, estimate_text_height(str(item.get("text") or ""), width, size) / height))
    text_fill = statistics.fmean(fill_ratios) if fill_ratios else 0.0

    # 25 readability points.
    median_score = min(1.0, median_font / 18.0) if median_font else 0.0
    minimum_score = min(1.0, min_font / 14.0) if min_font else 0.0
    fill_score = max(0.0, 1.0 - abs(min(text_fill, 1.2) - 0.78) / 0.78)
    readability = 25.0 * (0.55 * median_score + 0.30 * minimum_score + 0.15 * fill_score)

    # 25 utilization/balance points.  Vertical use below 60% is the most
    # damaging signal; a full-width title cannot influence any term here.
    vertical_score = min(1.0, vertical / 0.60) if vertical < 0.60 else max(0.75, 1.0 - max(0.0, vertical - 0.92) * 1.5)
    horizontal_score = min(1.0, horizontal / 0.68) if horizontal < 0.68 else 1.0
    blank_score = max(0.0, 1.0 - max_blank / 0.68)
    utilization = 25.0 * (
        0.42 * vertical_score + 0.22 * horizontal_score + 0.20 * blank_score + 0.16 * whitespace_balance
    )

    # 20 hierarchy points.
    title_size = statistics.median(title_sizes) if title_sizes else median_font * 1.45
    ratio = title_size / median_font if median_font else 0.0
    ratio_score = max(0.0, 1.0 - abs(ratio - 1.55) / 1.1) if ratio else 0.0
    emphasized = sum(
        1 for item in text_elements
        if (item.get("style") or {}).get("bold") or (item.get("style") or {}).get("color") == "primary"
    )
    emphasis_score = min(1.0, emphasized / max(1.0, len(text_elements) * 0.25))
    hierarchy = 20.0 * (0.72 * ratio_score + 0.28 * emphasis_score)

    # 15 alignment/rhythm points.
    alignment_score = max(0.0, 1.0 - alignment_error / 0.25)
    rhythm_score = 1.0 if spacing_cv <= 0.2 else max(0.0, 1.0 - (spacing_cv - 0.2) / 1.0)
    alignment_rhythm = 15.0 * (0.62 * alignment_score + 0.38 * rhythm_score)

    order_score = _reading_order_score(elements, slide)
    structure_fit = _structure_fit(slide, layout_type)
    has_structured_group = bool(slide and any(
        str(block.get("kind") or "") in {"steps", "compare", "quote"}
        for block in (slide.get("blocks") or [])
    ))
    semantic_grouping = 10.0 * (
        (0.30 * order_score + 0.70 * structure_fit)
        if has_structured_group else
        (0.55 * order_score + 0.45 * structure_fit)
    )
    template_consistency = 5.0 if meaningful_boxes else 0.0
    quality = min(100.0, readability + utilization + hierarchy + alignment_rhythm + semantic_grouping + template_consistency)

    return {
        "body_vertical_utilization": round(max(0.0, min(1.0, vertical)), 4),
        "body_horizontal_utilization": round(max(0.0, min(1.0, horizontal)), 4),
        "occupied_area_ratio": round(max(0.0, min(1.0, occupied)), 4),
        "max_blank_region_ratio": round(max_blank, 4),
        "whitespace_balance": round(whitespace_balance, 4),
        "horizontal_balance": round(horizontal_balance, 4),
        "vertical_balance": round(vertical_balance, 4),
        "font_min": round(min_font, 2),
        "font_median": round(median_font, 2),
        "font_mean": round(statistics.fmean(body_font_sizes), 2) if body_font_sizes else 0.0,
        "font_max": round(max_font, 2),
        "spacing_mean": round(spacing_mean, 4),
        "spacing_cv": round(spacing_cv, 4),
        "alignment_error": round(alignment_error, 4),
        "density_chars_per_in2": round(density, 3),
        "text_fill_ratio": round(text_fill, 4),
        "quality_components": {
            "readability": round(readability, 2),
            "utilization_balance": round(utilization, 2),
            "visual_hierarchy": round(hierarchy, 2),
            "alignment_rhythm": round(alignment_rhythm, 2),
            "semantic_grouping": round(semantic_grouping, 2),
            "template_consistency": round(template_consistency, 2),
        },
        "quality_score": round(quality, 2),
        "body_element_count": len(content_boxes),
    }


def baseline_distribution_is_sound(metrics: dict[str, Any]) -> bool:
    """Whether in-place font scaling may safely preserve the composition."""
    return (
        float(metrics.get("body_vertical_utilization") or 0) >= 0.55
        and float(metrics.get("body_horizontal_utilization") or 0) >= 0.58
        and float(metrics.get("max_blank_region_ratio") or 1) <= 0.48
        and float(metrics.get("whitespace_balance") or 0) >= 0.45
    )


def font_change_metrics(
    baseline_elements: list[dict[str, Any]], candidate_elements: list[dict[str, Any]],
    zones: LayoutZones,
) -> dict[str, float]:
    """Measure actual body-font changes, preferring stable content refs."""
    def sizes(elements: list[dict[str, Any]]) -> tuple[dict[str, float], list[float]]:
        by_ref: dict[str, float] = {}
        values: list[float] = []
        for item in elements:
            if item.get("kind") not in {"textbox", "note"} or _is_title(item, zones):
                continue
            ref = str(item.get("content_ref") or "")
            if ref.endswith(".citation") or str(item.get("role") or "") == "step_index":
                continue
            size = _number((item.get("style") or {}).get("size"), 18.0)
            if ref:
                by_ref[ref] = size
            values.append(size)
        return by_ref, sorted(values)

    baseline_by_ref, baseline_values = sizes(baseline_elements)
    candidate_by_ref, candidate_values = sizes(candidate_elements)
    matched = sorted(set(baseline_by_ref) & set(candidate_by_ref))
    if matched:
        deltas = [candidate_by_ref[ref] - baseline_by_ref[ref] for ref in matched]
        ratios = [candidate_by_ref[ref] / max(0.01, baseline_by_ref[ref]) for ref in matched]
    else:
        count = min(len(baseline_values), len(candidate_values))
        baseline_values = baseline_values[-count:]
        candidate_values = candidate_values[-count:]
        deltas = [after - before for before, after in zip(baseline_values, candidate_values)]
        ratios = [after / max(0.01, before) for before, after in zip(baseline_values, candidate_values)]
    if not deltas:
        return {"increased_ratio": 0.0, "median_ratio": 0.0, "shrunk_ratio": 1.0, "matched_count": 0.0}
    return {
        "increased_ratio": round(sum(delta >= 0.99 for delta in deltas) / len(deltas), 4),
        "median_ratio": round(statistics.median(ratios), 4),
        "shrunk_ratio": round(sum(delta < -0.01 for delta in deltas) / len(deltas), 4),
        "matched_count": float(len(deltas)),
    }
