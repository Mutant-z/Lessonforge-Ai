import json
import statistics
from copy import deepcopy
from typing import Any
from app.agent.layouts.analysis import (
    analyze_layout, baseline_distribution_is_sound, font_change_metrics,
)
from app.agent.layouts.metrics import estimate_text_height
from app.agent.layouts.presets import PRESETS, PRESET_KEYS
from app.agent.layouts.zones import zones_for

# 旧版式名 → 新预设名（兼容历史 Artifact 与测试）
PRESET_ALIASES = {
    "title_and_body": "bullet_flow",
    "cover": "cover_center",
    "cover_visual": "cover_left",
    "split": "split_two_column",
    "comparison": "compare_columns",
    "steps": "steps_horizontal",
    "process": "steps_horizontal",
    "question": "quote_center",
    "bullet": "bullet_flow",
}

_GAP_LOW, _GAP_HIGH = 0.8, 1.5


class LayoutCompileError(ValueError):
    """Structured deterministic-layout failure for precise task diagnostics."""

    def __init__(
        self, unresolved: list[str], missing_refs: list[str], geometry_safe: bool,
        *, attempts: list[dict[str, Any]] | None = None,
    ):
        self.unresolved = list(unresolved)
        self.missing_refs = list(missing_refs)
        self.geometry_safe = bool(geometry_safe)
        self.attempts = list(attempts or [])
        super().__init__(
            "布局无法安全覆盖页面必要文字: "
            f"unresolved={self.unresolved}, missing={self.missing_refs}, "
            f"geometry_safe={self.geometry_safe}, attempts={self.attempts[-6:]}"
        )


def _geometry_failures(elements: list[dict[str, Any]]) -> list[str]:
    """Compile-time bounds, overflow and overlap checks used for every candidate."""
    failures: list[str] = []
    boxes: list[tuple[int, float, float, float, float]] = []
    for element in elements:
        try:
            x = float(element.get("x") or 0)
            y = float(element.get("y") or 0)
            w = float(element.get("w") or 0)
            h = float(element.get("h") or 0)
        except (TypeError, ValueError):
            failures.append("invalid_geometry")
            continue
        if min(x, y, w, h) < 0 or x + w > 13.333 + 0.01 or y + h > 7.5 + 0.01:
            failures.append("out_of_bounds")
        if element.get("kind") in {"textbox", "note", "image", "chart"} and (
            x < 0.49 or y < 0.49 or x + w > 12.843 or y + h > 7.01
        ):
            failures.append("min_margin")
        if element.get("kind") in {"textbox", "note"}:
            text = str(element.get("text") or "")
            try:
                size = float((element.get("style") or {}).get("size") or 18)
            except (TypeError, ValueError):
                size = 18.0
            if text and h > 0.1 and estimate_text_height(text, max(w, 0.01), size) > h * 1.15:
                failures.append("text_overflow")
        if element.get("kind") != "shape":
            boxes.append((len(boxes), x, y, w, h))
    for index, (_id_a, ax, ay, aw, ah) in enumerate(boxes):
        for _id_b, bx, by, bw, bh in boxes[index + 1:]:
            overlap_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
            overlap_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
            overlap = overlap_w * overlap_h
            if overlap > 0.05 and overlap > 0.3 * min(aw * ah, bw * bh):
                failures.append("overlap")
    return list(dict.fromkeys(failures))


def _fits_safe_canvas(elements: list[dict[str, Any]]) -> bool:
    return not _geometry_failures(elements)


def normalize_layout_params(style: dict[str, Any] | None) -> dict[str, Any]:
    style = dict(style or {})
    tier = style.get("font_tier")
    if tier not in {"default", "compact", "spacious"}:
        tier = "default"
    try:
        gap = float(style.get("gap_scale") or 1.0)
    except (TypeError, ValueError):
        gap = 1.0
    try:
        font_scale = float(style.get("font_scale") or 1.0)
    except (TypeError, ValueError):
        font_scale = 1.0
    return {
        "font_tier": tier,
        "font_scale": max(0.8, min(1.25, font_scale)),
        "gap_scale": max(_GAP_LOW, min(_GAP_HIGH, gap)),
        "highlight": bool(style.get("highlight", False)),
    }


def _resolve_preset(layout_type: str) -> str:
    key = str(layout_type or "bullet_flow")
    if key in PRESET_KEYS:
        return key
    return PRESET_ALIASES.get(key, "bullet_flow")


_OBJECTIVE_ALIASES = {
    "size": "font_size", "typography": "font_size", "font": "font_size",
    "vertical_use": "vertical_utilization", "page_utilization": "vertical_utilization",
    "layout_utilization": "vertical_utilization", "distribution": "vertical_utilization",
    "blank_region": "whitespace_balance", "whitespace": "whitespace_balance",
    "gap": "spacing", "rhythm": "spacing", "column_balance": "whitespace_balance",
    "image_size": "image_scale", "visual_scale": "image_scale", "picture_scale": "image_scale",
}
_LAYOUT_SIGNAL_WORDS = (
    "页面分布", "布局利用", "空间利用", "留白", "空白", "铺满", "挤成", "拥挤",
    "分布不充分", "whitespace", "distribution", "utilization", "balance",
)


def _normalize_image_geometry_action(directive: dict[str, Any]) -> str:
    """Return the deterministic image-geometry operation.

    Historical callers did not send an action and always meant resize, so an
    empty value deliberately retains that behaviour.  Reposition and crop are
    kept distinct because neither operation is allowed to change image size.
    """
    raw = str(directive.get("image_geometry_action") or "").strip().lower()
    aliases = {
        "move": "reposition", "position": "reposition", "align": "reposition",
        "移动": "reposition", "位置": "reposition", "对齐": "reposition",
        "scale": "resize", "size": "resize", "放大": "resize", "缩小": "resize",
        "裁剪": "crop", "裁切": "crop",
        "beautify": "polish", "optimize": "polish", "润色": "polish",
    }
    action = aliases.get(raw, raw)
    return action if action in {"resize", "reposition", "crop", "polish"} else "resize"


def _normalized_objectives(
    directive: dict[str, Any], requested_params: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Normalize V2 objectives while remaining compatible with V1 directives."""
    raw = directive.get("objectives") or directive.get("requested_objectives") or []
    if not raw and isinstance(directive.get("polish_command"), dict):
        raw = directive["polish_command"].get("objectives") or []
    image_geometry_only = bool(directive.get("image_geometry_only"))
    image_geometry_action = _normalize_image_geometry_action(directive)
    objectives: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"metric": item}
        if not isinstance(item, dict):
            continue
        metric = _OBJECTIVE_ALIASES.get(str(item.get("metric") or ""), str(item.get("metric") or ""))
        if not metric:
            continue
        # Image scale is a resize objective.  A stale/upstream scale objective
        # must never turn a reposition or crop request into an implicit resize;
        # polish may resize, but does not claim the explicit resize objective.
        if (
            image_geometry_only
            and metric == "image_scale"
            and image_geometry_action != "resize"
        ):
            continue
        objectives.append({
            "metric": metric,
            "direction": str(item.get("direction") or "optimize"),
            "minimum_delta": item.get("minimum_delta"),
            "priority": item.get("priority", 1),
            "hard_requirement": bool(item.get("hard_requirement", True)),
            "source": str(item.get("source") or "explicit"),
            "adaptive": bool(item.get("adaptive", False)),
        })

    target = str(
        directive.get("target_dimension")
        or directive.get("targetDimension")
        or directive.get("operation")
        or ""
    ).lower()
    rationale = " ".join(str(directive.get(key) or "") for key in ("rationale", "instruction", "raw_text"))
    requested_scale = float(requested_params.get("font_scale") or 1.0)
    if requested_scale != 1.0 or target in {"size", "font_size", "typography"}:
        if not any(item["metric"] == "font_size" for item in objectives):
            objectives.append({
                "metric": "font_size",
                "direction": "increase" if requested_scale >= 1.0 else "decrease",
                "minimum_delta": 0.05,
                "priority": 1,
                "hard_requirement": True,
            })
    # ``gap_scale`` is frequently part of an LLM recipe, not necessarily a
    # user objective.  Only an explicit spacing target turns it into a hard
    # material-change gate.
    if target in {"spacing", "gap"}:
        if not any(item["metric"] == "spacing" for item in objectives):
            objectives.append({
                "metric": "spacing", "direction": "optimize", "minimum_delta": 0.2,
                "priority": 1, "hard_requirement": True,
            })
    layout_signal = target in {"layout", "distribution", "whitespace", "page_distribution"} or any(
        word in rationale.lower() for word in _LAYOUT_SIGNAL_WORDS
    )
    if layout_signal and not any(
        item["metric"] in {"vertical_utilization", "whitespace_balance"} for item in objectives
    ):
        objectives.append({
            "metric": "vertical_utilization", "direction": "increase", "minimum_delta": 0.12,
            "priority": 1, "hard_requirement": True,
        })
    generic_polish = bool(directive.get("polish_mode")) or target in {"polish", "layout_polish"}
    if generic_polish and not objectives and not image_geometry_only:
        objectives.append({
            "metric": "layout_quality", "direction": "increase", "minimum_delta": 0.0,
            "priority": 1, "hard_requirement": True, "source": "runtime_gate",
            "adaptive": True,
        })
    if image_geometry_only and image_geometry_action == "resize" and not any(
        item["metric"] == "image_scale" for item in objectives
    ):
        raw_scale = (
            directive.get("image_scale")
            or directive.get("size_scale")
            or (directive.get("style") or {}).get("image_scale")
        )
        try:
            scale = float(raw_scale or 1.10)
        except (TypeError, ValueError):
            scale = 1.10
        objectives.append({
            "metric": "image_scale",
            "direction": "decrease" if scale < 1.0 else "increase",
            # A slight resize may safely degrade from the requested 1.10 down
            # to 1.02, matching the V2 size-objective contract.
            "minimum_delta": 0.02,
            "priority": 1,
            "hard_requirement": True,
        })
    # De-duplicate while retaining the first (usually explicit) threshold.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in objectives:
        if item["metric"] not in seen:
            seen.add(item["metric"])
            deduped.append(item)
    pure_font = bool(deduped) and {item["metric"] for item in deduped} <= {"font_size"}
    return deduped, pure_font


def _image_change_metrics(
    baseline_elements: list[dict[str, Any]], candidate_elements: list[dict[str, Any]],
) -> dict[str, float]:
    """Measure visual geometry without relying on mutable asset metadata.

    Image/chart elements are matched by their stable list position.  The
    image-geometry compiler never inserts, removes or reorders elements, so a
    positional match is stricter than a best-effort ID match and catches
    accidental resource replacement as an invariant violation.
    """
    ratios: list[float] = []
    moved: list[float] = []
    for before, after in zip(baseline_elements, candidate_elements):
        if before.get("kind") not in {"image", "chart"}:
            continue
        try:
            before_area = float(before.get("w") or 0) * float(before.get("h") or 0)
            after_area = float(after.get("w") or 0) * float(after.get("h") or 0)
            if before_area <= 0 or after_area <= 0:
                continue
            ratios.append((after_area / before_area) ** 0.5)
            before_cx = float(before.get("x") or 0) + float(before.get("w") or 0) / 2
            before_cy = float(before.get("y") or 0) + float(before.get("h") or 0) / 2
            after_cx = float(after.get("x") or 0) + float(after.get("w") or 0) / 2
            after_cy = float(after.get("y") or 0) + float(after.get("h") or 0) / 2
            moved.append(((after_cx - before_cx) ** 2 + (after_cy - before_cy) ** 2) ** 0.5)
        except (TypeError, ValueError):
            continue
    if not ratios:
        return {
            "median_ratio": 1.0, "minimum_ratio": 1.0, "maximum_ratio": 1.0,
            "increased_ratio": 0.0, "decreased_ratio": 0.0,
            "maximum_center_shift": 0.0, "matched_count": 0.0,
        }
    return {
        "median_ratio": round(statistics.median(ratios), 4),
        "minimum_ratio": round(min(ratios), 4),
        "maximum_ratio": round(max(ratios), 4),
        "increased_ratio": round(sum(ratio > 1.001 for ratio in ratios) / len(ratios), 4),
        "decreased_ratio": round(sum(ratio < 0.999 for ratio in ratios) / len(ratios), 4),
        "maximum_center_shift": round(max(moved or [0.0]), 4),
        "matched_count": float(len(ratios)),
    }


def _evaluate_objectives(
    objectives: list[dict[str, Any]], baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any], *, baseline_elements: list[dict[str, Any]],
    candidate_elements: list[dict[str, Any]], zones,
) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    baseline_available = bool(baseline_metrics.get("body_element_count"))
    quality_delta = float(candidate_metrics.get("quality_score") or 0) - float(baseline_metrics.get("quality_score") or 0)
    for objective in objectives:
        metric = objective["metric"]
        direction = objective.get("direction") or "optimize"
        minimum = objective.get("minimum_delta")
        passed = False
        baseline_value: Any = None
        candidate_value: Any = None
        delta: Any = None
        evidence: dict[str, Any] = {}
        reason = ""
        if metric == "font_size":
            changes = font_change_metrics(baseline_elements, candidate_elements, zones)
            evidence = changes
            baseline_value = baseline_metrics.get("font_median", 0)
            candidate_value = candidate_metrics.get("font_median", 0)
            delta = round(float(candidate_value or 0) - float(baseline_value or 0), 3)
            if not baseline_available:
                passed = float(candidate_value or 0) >= 16.0
            elif direction == "decrease":
                passed = (
                    changes["median_ratio"] <= 0.95
                    and changes["shrunk_ratio"] >= 0.70
                )
            else:
                passed = (
                    changes["increased_ratio"] >= 0.70
                    and changes["median_ratio"] >= max(1.05, 1.0 + float(minimum or 0.05))
                    and changes["shrunk_ratio"] == 0.0
                )
            reason = "至少 70% 正文增加 1pt、中位字号增加 5%，且无正文缩小"
        elif metric == "vertical_utilization":
            baseline_value = baseline_metrics.get("body_vertical_utilization", 0)
            candidate_value = candidate_metrics.get("body_vertical_utilization", 0)
            delta = round(float(candidate_value) - float(baseline_value), 4)
            blank_delta = round(
                float(baseline_metrics.get("max_blank_region_ratio") or 0)
                - float(candidate_metrics.get("max_blank_region_ratio") or 0), 4,
            )
            evidence = {"vertical_delta": delta, "blank_region_reduction": blank_delta, "quality_delta": round(quality_delta, 2)}
            passed = (
                delta >= float(minimum or 0.12) or blank_delta >= 0.10
            ) if baseline_available else float(candidate_value) >= 0.60
            reason = "纵向利用率提高 12 个百分点或最大空白区降低 10 个百分点"
        elif metric == "horizontal_utilization":
            baseline_value = baseline_metrics.get("body_horizontal_utilization", 0)
            candidate_value = candidate_metrics.get("body_horizontal_utilization", 0)
            delta = round(float(candidate_value) - float(baseline_value), 4)
            passed = delta >= float(minimum or 0.08) if baseline_available else float(candidate_value) >= 0.68
            reason = "正文横向利用率达到或显著超过原页"
        elif metric == "whitespace_balance":
            baseline_value = baseline_metrics.get("max_blank_region_ratio", 1)
            candidate_value = candidate_metrics.get("max_blank_region_ratio", 1)
            delta = round(float(baseline_value) - float(candidate_value), 4)
            balance_delta = round(
                float(candidate_metrics.get("whitespace_balance") or 0)
                - float(baseline_metrics.get("whitespace_balance") or 0), 4,
            )
            evidence = {"blank_region_reduction": delta, "balance_delta": balance_delta}
            passed = (
                delta >= float(minimum or 0.10) or balance_delta >= 0.10
            ) if baseline_available else float(candidate_value) <= 0.48
            reason = "最大空白区降低或上下左右平衡明显改善"
        elif metric == "spacing":
            baseline_value = baseline_metrics.get("spacing_mean", 0)
            candidate_value = candidate_metrics.get("spacing_mean", 0)
            baseline_cv = float(baseline_metrics.get("spacing_cv") or 0)
            candidate_cv = float(candidate_metrics.get("spacing_cv") or 0)
            delta = round(float(candidate_value) - float(baseline_value), 4)
            if not baseline_available:
                passed = candidate_cv <= 0.45
            elif direction == "increase":
                passed = float(candidate_value) >= float(baseline_value) * 1.10
            else:
                passed = baseline_cv > 0 and candidate_cv <= baseline_cv * (1.0 - float(minimum or 0.20))
                if baseline_cv <= 0.05:
                    passed = float(candidate_value) >= float(baseline_value) * 1.10
            evidence = {"baseline_cv": baseline_cv, "candidate_cv": candidate_cv}
            reason = "目标间距增加 10% 或间距离散系数降低 20%"
        elif metric == "alignment":
            baseline_value = baseline_metrics.get("alignment_error", 1)
            candidate_value = candidate_metrics.get("alignment_error", 1)
            delta = round(float(baseline_value) - float(candidate_value), 4)
            passed = float(candidate_value) <= float(minimum or 0.08)
            reason = "主要锚点偏差不超过 0.08in"
        elif metric == "density":
            baseline_value = baseline_metrics.get("density_chars_per_in2", 0)
            candidate_value = candidate_metrics.get("density_chars_per_in2", 0)
            delta = round(float(baseline_value) - float(candidate_value), 3)
            passed = float(candidate_value) <= float(baseline_value) * 0.9 if baseline_available else float(candidate_value) <= 65
            reason = "文字密度降低且内容完整"
        elif metric == "image_scale":
            changes = _image_change_metrics(baseline_elements, candidate_elements)
            evidence = changes
            baseline_value = 1.0
            candidate_value = changes["median_ratio"]
            delta = round(float(candidate_value) - 1.0, 4)
            try:
                threshold = float(minimum if minimum is not None else 0.05)
            except (TypeError, ValueError):
                threshold = 0.05
            # Accept both delta notation (0.10) and ratio notation (1.10).
            if threshold >= 1.0:
                threshold -= 1.0
            threshold = max(0.01, min(0.50, abs(threshold)))
            matched = bool(changes["matched_count"])
            if direction == "decrease":
                passed = (
                    matched
                    and float(candidate_value) <= 1.0 - threshold + 0.001
                    and changes["increased_ratio"] == 0.0
                )
                reason = f"全部目标图片安全缩小至少 {threshold:.0%}"
            elif direction == "optimize":
                passed = matched and abs(float(candidate_value) - 1.0) >= threshold - 0.001
                reason = f"图片尺寸产生至少 {threshold:.0%} 的安全、可感知变化"
            else:
                passed = (
                    matched
                    and float(candidate_value) >= 1.0 + threshold - 0.001
                    and changes["decreased_ratio"] == 0.0
                )
                reason = f"全部目标图片安全放大至少 {threshold:.0%}"
        elif metric == "layout_quality":
            baseline_value = baseline_metrics.get("quality_score", 0)
            candidate_value = candidate_metrics.get("quality_score", 0)
            delta = round(float(candidate_value) - float(baseline_value), 2)
            threshold = (
                adaptive_quality_delta(float(baseline_value or 0))
                if objective.get("adaptive") else float(minimum if minimum is not None else 8)
            )
            evidence = {"quality_gate_threshold": threshold, "adaptive": bool(objective.get("adaptive"))}
            passed = float(candidate_value) >= 75 and (delta >= threshold if baseline_available else True)
            reason = f"质量达到 75 分且比原页提高至少 {threshold:g} 分"
        elif metric == "contrast":
            baseline_value = float(
                (baseline_metrics.get("quality_components") or {}).get("visual_hierarchy") or 0
            ) / 20.0
            candidate_value = float(
                (candidate_metrics.get("quality_components") or {}).get("visual_hierarchy") or 0
            ) / 20.0
            delta = round(candidate_value - baseline_value, 4)
            baseline_emphasis = sum(
                bool((item.get("style") or {}).get("bold"))
                or (item.get("style") or {}).get("color") == "primary"
                or item.get("role") == "highlight_panel"
                for item in baseline_elements
            )
            candidate_emphasis = sum(
                bool((item.get("style") or {}).get("bold"))
                or (item.get("style") or {}).get("color") == "primary"
                or item.get("role") == "highlight_panel"
                for item in candidate_elements
            )
            evidence = {
                "baseline_emphasis": baseline_emphasis,
                "candidate_emphasis": candidate_emphasis,
            }
            passed = (
                delta >= float(minimum or 0.10)
                or candidate_emphasis >= baseline_emphasis + 2
            )
            reason = "视觉层级或主题内强调处理至少提高 10%"
        else:
            reason = "当前确定性布局器无法验证此目标"
        results.append({
            "metric": metric, "direction": direction, "passed": bool(passed),
            "hard_requirement": bool(objective.get("hard_requirement", True)),
            "source": str(objective.get("source") or "explicit"),
            "baseline_value": baseline_value, "candidate_value": candidate_value,
            "delta": delta, "evidence": evidence, "requirement": reason,
        })
    hard_pass = all(item["passed"] for item in results if item["hard_requirement"])
    objective_metrics = {item["metric"] for item in objectives}
    if objectives and baseline_available and not objective_metrics <= {"image_scale"}:
        hard_pass = hard_pass and float(candidate_metrics.get("quality_score") or 0) >= 75.0
    return results, hard_pass


def adaptive_quality_delta(baseline_score: float) -> float:
    """Return the perceptible-improvement threshold for the baseline tier."""
    if baseline_score < 75.0:
        return 8.0
    if baseline_score < 85.0:
        return 5.0
    return 3.0


def _quality_component_regressions(
    baseline_metrics: dict[str, Any], candidate_metrics: dict[str, Any], *, tolerance: float = 1.5,
) -> list[str]:
    baseline = dict(baseline_metrics.get("quality_components") or {})
    candidate = dict(candidate_metrics.get("quality_components") or {})
    regressions = []
    for key, before in baseline.items():
        try:
            delta = float(candidate.get(key, before)) - float(before)
        except (TypeError, ValueError):
            continue
        if delta < -tolerance:
            regressions.append(str(key))
    try:
        before_font = float(baseline_metrics.get("font_median") or 0)
        after_font = float(candidate_metrics.get("font_median") or 0)
    except (TypeError, ValueError):
        before_font = after_font = 0.0
    if before_font and after_font < before_font * 0.95:
        regressions.append("body_font_size")
    return list(dict.fromkeys(regressions))


def _candidate_signature(elements: list[dict[str, Any]]) -> str:
    rows = sorted(
        (
            str(item.get("kind") or ""), str(item.get("role") or ""),
            str(item.get("content_ref") or ""),
            round(float(item.get("x") or 0), 3), round(float(item.get("y") or 0), 3),
            round(float(item.get("w") or 0), 3), round(float(item.get("h") or 0), 3),
            (item.get("style") or {}).get("size"), (item.get("style") or {}).get("bold"),
            (item.get("style") or {}).get("color"), item.get("fill"), item.get("line"),
        )
        for item in elements
    )
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)


_GEOMETRY_KEYS = {"x", "y", "w", "h"}
_VISUAL_KINDS = {"image", "chart"}


def _image_geometry_invariants(
    baseline_elements: list[dict[str, Any]], candidate_elements: list[dict[str, Any]],
    *, action: str = "resize",
) -> list[str]:
    """Return invariant violations for an image-geometry-only candidate.

    Every non-visual element must be byte-for-byte equivalent.  For images and
    charts, only the four top-level geometry fields may differ; consequently
    asset identity, crop, visual_slot, chart data and styling remain locked.
    """
    if len(baseline_elements) != len(candidate_elements):
        return ["element_count_changed"]
    failures: list[str] = []
    for index, (before, after) in enumerate(zip(baseline_elements, candidate_elements)):
        before_kind = before.get("kind")
        if before_kind != after.get("kind"):
            failures.append(f"element_kind_changed:{index}")
            continue
        if before_kind not in _VISUAL_KINDS:
            if before != after:
                failures.append(f"non_visual_changed:{index}")
            continue
        before_locked = {key: value for key, value in before.items() if key not in _GEOMETRY_KEYS}
        after_locked = {key: value for key, value in after.items() if key not in _GEOMETRY_KEYS}
        if before_locked != after_locked:
            failures.append(f"visual_resource_changed:{index}")
        if action == "reposition" and (
            before.get("w") != after.get("w") or before.get("h") != after.get("h")
        ):
            failures.append(f"visual_size_changed:{index}")
    return failures


def _image_reposition_candidates(
    source_elements: list[dict[str, Any]], visual_indices: list[int], zones,
) -> list[dict[str, Any]]:
    """Return up to five grid-aligned, translation-only visual candidates.

    Multiple visuals move as one group, preserving their relative positions.
    The preferred horizontal lane is the free side of the page opposite the
    text.  Candidate bounds stay inside both the template body rail and the
    renderer's hard safety margin; later geometry checks reject any overlap.
    """
    try:
        group_left = min(float(source_elements[index].get("x") or 0) for index in visual_indices)
        group_top = min(float(source_elements[index].get("y") or 0) for index in visual_indices)
        group_right = max(
            float(source_elements[index].get("x") or 0)
            + float(source_elements[index].get("w") or 0)
            for index in visual_indices
        )
        group_bottom = max(
            float(source_elements[index].get("y") or 0)
            + float(source_elements[index].get("h") or 0)
            for index in visual_indices
        )
    except (TypeError, ValueError):
        return []
    group_w, group_h = group_right - group_left, group_bottom - group_top
    safe_left = max(0.49, float(zones.body_column.x))
    safe_top = max(0.49, float(zones.body_column.y))
    safe_right = min(12.843, float(zones.body_column.right))
    safe_bottom = min(7.01, float(zones.body_column.bottom))
    if group_w <= 0 or group_h <= 0 or group_w > safe_right - safe_left or group_h > safe_bottom - safe_top:
        return []

    non_visual_boxes: list[tuple[float, float, float, float]] = []
    for item in source_elements:
        if item.get("kind") in _VISUAL_KINDS:
            continue
        if item.get("role") == "title" or item.get("content_ref") == "title":
            continue
        if item.get("kind") not in {"textbox", "note", "formula", "table"}:
            continue
        try:
            left, top = float(item.get("x") or 0), float(item.get("y") or 0)
            right = left + float(item.get("w") or 0)
            bottom = top + float(item.get("h") or 0)
        except (TypeError, ValueError):
            continue
        if right > safe_left and left < safe_right and bottom > safe_top and top < safe_bottom:
            non_visual_boxes.append((left, top, right, bottom))

    lane_left, lane_right = safe_left, safe_right
    if non_visual_boxes:
        text_left = min(item[0] for item in non_visual_boxes)
        text_right = max(item[2] for item in non_visual_boxes)
        gap = 0.35
        right_lane = (max(safe_left, text_right + gap), safe_right)
        left_lane = (safe_left, min(safe_right, text_left - gap))
        group_center = (group_left + group_right) / 2
        viable_lanes = [
            lane for lane in (right_lane, left_lane)
            if lane[1] - lane[0] >= group_w
        ]
        if viable_lanes:
            lane_left, lane_right = min(
                viable_lanes,
                key=lambda lane: abs((lane[0] + lane[1]) / 2 - group_center),
            )

    x_anchors = [
        lane_left,
        lane_left + (lane_right - lane_left - group_w) / 2,
        lane_right - group_w,
    ]
    y_anchors = [
        safe_top,
        safe_top + (safe_bottom - safe_top - group_h) / 2,
        safe_bottom - group_h,
    ]
    x_anchors = list(dict.fromkeys(round(value, 4) for value in x_anchors))
    y_anchors = list(dict.fromkeys(round(value, 4) for value in y_anchors))
    nearest_x = min(x_anchors, key=lambda value: abs(value - group_left))
    nearest_y = min(y_anchors, key=lambda value: abs(value - group_top))
    center_x = x_anchors[len(x_anchors) // 2]
    center_y = y_anchors[len(y_anchors) // 2]
    targets = [
        (nearest_x, nearest_y),
        (nearest_x, center_y),
        (center_x, center_y),
        (x_anchors[-1], center_y),
        (x_anchors[0], center_y),
        (nearest_x, y_anchors[0]),
        (nearest_x, y_anchors[-1]),
    ]

    def alignment_error(left: float, top: float) -> float:
        x_error = min(abs(left - value) for value in x_anchors)
        y_error = min(abs(top - value) for value in y_anchors)
        return (x_error + y_error) / 2

    baseline_error = alignment_error(group_left, group_top)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()
    for target_left, target_top in targets:
        dx, dy = round(target_left - group_left, 4), round(target_top - group_top, 4)
        key = (dx, dy)
        if key in seen or abs(dx) + abs(dy) < 0.05:
            continue
        seen.add(key)
        gain = baseline_error - alignment_error(target_left, target_top)
        if gain < 0.01:
            continue
        elements = deepcopy(source_elements)
        for index in visual_indices:
            elements[index]["x"] = round(float(source_elements[index].get("x") or 0) + dx, 4)
            elements[index]["y"] = round(float(source_elements[index].get("y") or 0) + dy, 4)
        candidates.append({
            "elements": elements, "dx": dx, "dy": dy,
            "alignment_gain": round(gain, 4),
        })
        if len(candidates) >= 5:
            break
    return candidates


def _image_scale_ladder(
    directive: dict[str, Any], objectives: list[dict[str, Any]],
) -> tuple[list[float], str]:
    objective = next(
        (item for item in objectives if item.get("metric") == "image_scale"),
        None,
    )
    raw_scale = (
        directive.get("image_scale")
        or directive.get("size_scale")
        or (directive.get("style") or {}).get("image_scale")
    )
    explicit_scale = raw_scale is not None
    try:
        requested = float(raw_scale) if raw_scale is not None else None
    except (TypeError, ValueError):
        requested = None

    # Polish uses the same scale ladder without claiming an explicit resize
    # objective.  Infer the direction from its requested scale so 0.90 can
    # never be accidentally normalized into an enlargement.
    if objective is not None:
        direction = str(objective.get("direction") or "optimize")
    elif requested is not None and requested < 0.999:
        direction = "decrease"
    else:
        direction = "increase"

    if requested is None:
        requested = 0.90 if direction == "decrease" else 1.10
    requested = max(0.50, min(1.50, requested))
    if direction == "increase":
        requested = max(1.02, requested)
        raw = [requested, 1.10, 1.08, 1.06, 1.04, 1.02]
        ladder = [scale for scale in raw if 1.001 < scale <= requested + 0.001]
    elif direction == "decrease":
        requested = min(0.98, requested)
        raw = [requested, 0.90, 0.92, 0.94, 0.96, 0.98]
        ladder = [scale for scale in raw if requested - 0.001 <= scale < 0.999]
    else:
        # Optimize remains deterministic.  Prefer the caller's direction, then
        # compare nearby perceptible alternatives without changing assets.
        if explicit_scale and requested < 0.999:
            raw = [
                requested,
                1.0 - (1.0 - requested) * 0.75,
                1.0 - (1.0 - requested) * 0.50,
                1.0 - (1.0 - requested) * 0.25,
            ]
        elif explicit_scale:
            raw = [
                max(1.02, requested),
                1.0 + (requested - 1.0) * 0.75,
                1.0 + (requested - 1.0) * 0.50,
                1.0 + (requested - 1.0) * 0.25,
            ]
        elif requested < 0.999:
            raw = [requested, 0.92, 0.95, 0.98, 1.05]
        else:
            raw = [max(1.02, requested), 1.15, 1.10, 1.05, 0.95]
        ladder = raw

    unique: list[float] = []
    for scale in ladder:
        rounded = round(max(0.50, min(1.50, float(scale))), 4)
        if abs(rounded - 1.0) > 0.001 and rounded not in unique:
            unique.append(rounded)
    return unique[:5], direction


def _compile_image_geometry(
    *, slide_id: str, slide: dict[str, Any], directive: dict[str, Any],
    zones, source_elements: list[dict[str, Any]], baseline_metrics: dict[str, Any],
    objectives: list[dict[str, Any]], requested_params: dict[str, Any], render_coverage,
) -> dict[str, Any]:
    """Compile a deterministic image/chart-only geometry change.

    This branch deliberately does not invoke a preset, bind text, or
    canonicalize elements.  Its output is a deep copy of the baseline where
    only image/chart x/y/w/h values may change.
    """
    visual_indices = [
        index for index, item in enumerate(source_elements)
        if item.get("kind") in _VISUAL_KINDS
    ]
    action = _normalize_image_geometry_action(directive)
    scales, direction = (
        _image_scale_ladder(directive, objectives)
        if action in {"resize", "polish"} else ([], "optimize")
    )
    attempts: list[dict[str, Any]] = []
    viable: list[dict[str, Any]] = []
    baseline_signature = _candidate_signature(source_elements)

    def objective_results_for(elements: list[dict[str, Any]]):
        metrics = analyze_layout(
            elements, zones, slide=slide,
            layout_type="existing_image_geometry",
        )
        results, passed = _evaluate_objectives(
            objectives, baseline_metrics, metrics,
            baseline_elements=source_elements, candidate_elements=elements, zones=zones,
        )
        return metrics, results, passed

    def preserved(reason: str) -> dict[str, Any]:
        _, results, _ = objective_results_for(source_elements)
        requested_style = {**requested_params, "image_geometry_action": action}
        if action in {"resize", "polish"}:
            requested_style["image_scale"] = scales[0] if scales else 1.0
        return {
            "slide_id": slide_id,
            "layout_type": "preserve_original",
            "designRationale": reason,
            "elements": source_elements,
            "render_mode": str(slide.get("render_mode") or "absolute"),
            "compile_status": "preserved",
            "requested_style": requested_style,
            "effective_style": {},
            "warnings": [reason],
            "content_allocation": directive.get("content_allocation") or {},
            "compile_attempts": attempts,
            "selected_candidate_id": None,
            "requested_objectives": objectives,
            "objective_results": results,
            "baseline_metrics": baseline_metrics,
            "final_metrics": baseline_metrics,
            "quality_delta": 0.0,
            "candidate_rankings": [],
            "material_change": False,
            "candidate_score_gap": None,
            "requires_candidate_confirmation": False,
        }

    if not visual_indices:
        return preserved(f"{slide_id} 没有可调整的图片或图表，已保留原布局")

    if action == "crop":
        return preserved(
            f"{slide_id} 缺少可验证的主体/焦点裁切依据，未自动裁切，已保留原图片"
        )

    candidate_inputs: list[dict[str, Any]] = []
    if action == "reposition":
        candidate_inputs = _image_reposition_candidates(source_elements, visual_indices, zones)
        if not candidate_inputs:
            return preserved(
                f"{slide_id} 的图片已对齐，或没有不缩放且不重叠的安全移动位置，已保留原图片"
            )
    else:
        for scale in scales:
            candidate = deepcopy(source_elements)
            for index in visual_indices:
                element = candidate[index]
                try:
                    x = float(element.get("x") or 0)
                    y = float(element.get("y") or 0)
                    w = float(element.get("w") or 0)
                    h = float(element.get("h") or 0)
                except (TypeError, ValueError):
                    continue
                center_x, center_y = x + w / 2, y + h / 2
                new_w, new_h = w * scale, h * scale
                element.update({
                    "x": round(center_x - new_w / 2, 4),
                    "y": round(center_y - new_h / 2, 4),
                    "w": round(new_w, 4),
                    "h": round(new_h, 4),
                })
            candidate_inputs.append({"elements": candidate, "scale": scale})

    for candidate_input in candidate_inputs:
        candidate = candidate_input["elements"]
        scale = float(candidate_input.get("scale") or 1.0)
        invariant_failures = _image_geometry_invariants(
            source_elements, candidate, action=action,
        )
        for index in visual_indices:
            try:
                if min(
                    float(source_elements[index].get("w") or 0),
                    float(source_elements[index].get("h") or 0),
                    float(candidate[index].get("w") or 0),
                    float(candidate[index].get("h") or 0),
                ) <= 0:
                    invariant_failures.append(f"visual_geometry_invalid:{index}")
            except (TypeError, ValueError):
                invariant_failures.append(f"visual_geometry_invalid:{index}")
        invariant_failures = list(dict.fromkeys(invariant_failures))
        coverage = render_coverage(
            {**slide, "render_mode": "absolute", "elements": candidate}, baseline=slide,
        )
        # Text overflow is a locked baseline property in this mode.  Bounds,
        # margins and overlaps are still checked on the complete candidate.
        geometry_failures = [
            item for item in _geometry_failures(candidate) if item != "text_overflow"
        ]
        metrics, result_objectives, objectives_passed = objective_results_for(candidate)
        image_metrics = _image_change_metrics(source_elements, candidate)
        signature = _candidate_signature(candidate)
        complete_safe = bool(
            not invariant_failures
            and not coverage.get("missing_refs")
            and not geometry_failures
            and signature != baseline_signature
        )
        if action == "reposition":
            direction_score = float(candidate_input.get("alignment_gain") or 0) * 100
        elif direction == "decrease":
            direction_score = (1.0 - float(image_metrics["median_ratio"])) * 100
        elif direction == "optimize":
            direction_score = abs(float(image_metrics["median_ratio"]) - 1.0) * 100
        else:
            direction_score = (float(image_metrics["median_ratio"]) - 1.0) * 100
        candidate_id = f"existing_image_geometry:{action}:{len(attempts) + 1}"
        rank_score = round(
            float(metrics.get("quality_score") or 0)
            + direction_score
            + (2.0 if objectives_passed else 0.0),
            2,
        )
        attempt = {
            "candidate_id": candidate_id,
            "layout_type": "existing_image_geometry",
            "style": {
                **requested_params, "image_geometry_action": action,
                **(
                    {"image_scale": scale}
                    if action in {"resize", "polish"} else
                    {"translate_x": candidate_input.get("dx"), "translate_y": candidate_input.get("dy")}
                ),
            },
            "unresolved": [],
            "missing_refs": list(coverage.get("missing_refs") or []),
            "geometry_safe": not geometry_failures,
            "geometry_failures": geometry_failures,
            "invariant_failures": invariant_failures,
            "max_bottom": round(max(
                (float(item.get("y") or 0) + float(item.get("h") or 0) for item in candidate),
                default=0.0,
            ), 3),
            "metrics": metrics,
            "image_metrics": image_metrics,
            "alignment_gain": candidate_input.get("alignment_gain"),
            "quality_score": metrics.get("quality_score"),
            "quality_delta": round(
                float(metrics.get("quality_score") or 0)
                - float(baseline_metrics.get("quality_score") or 0), 2,
            ),
            "objective_results": result_objectives,
            "objectives_passed": objectives_passed,
            "viable": complete_safe,
            "rank_score": rank_score,
            "fingerprint": json.dumps({
                "slide_id": slide_id,
                "baseline_geometry": baseline_signature,
                "image_geometry_action": action,
                "image_scale": scale if action in {"resize", "polish"} else None,
                "translate_x": candidate_input.get("dx"),
                "translate_y": candidate_input.get("dy"),
                "missing_refs": list(coverage.get("missing_refs") or []),
                "geometry": geometry_failures,
                "invariants": invariant_failures,
                "objectives": result_objectives,
            }, ensure_ascii=False, sort_keys=True, default=str),
        }
        attempts.append(attempt)
        if complete_safe:
            viable.append({
                "candidate_id": candidate_id, "elements": candidate,
                "scale": scale, "metrics": metrics,
                "image_metrics": image_metrics,
                "dx": candidate_input.get("dx"), "dy": candidate_input.get("dy"),
                "alignment_gain": candidate_input.get("alignment_gain"),
                "objective_results": result_objectives,
                "objectives_passed": objectives_passed,
                "rank_score": rank_score, "attempt": attempt,
            })

    ranked = sorted(viable, key=lambda item: item["rank_score"], reverse=True)
    selectable = [item for item in ranked if item["objectives_passed"] or not objectives]
    if not selectable:
        if viable:
            failed = [
                result["metric"] for result in viable[0]["objective_results"]
                if result.get("hard_requirement") and not result.get("passed")
            ]
            return preserved(
                f"{slide_id} 的安全候选未达到图片目标（{'、'.join(failed)}），已保留原布局"
            )
        return preserved(f"{slide_id} 的图片调整会越界或遮挡内容，已保留原布局")

    selected = selectable[0]
    selected["attempt"]["selected"] = True
    selected_index = attempts.index(selected["attempt"])
    attempts.append(attempts.pop(selected_index))
    rankings = [
        {
            "rank": rank,
            "candidate_id": item["candidate_id"],
            "layout_type": "existing_image_geometry",
            "style": {
                **requested_params, "image_geometry_action": action,
                **(
                    {"image_scale": item["scale"]}
                    if action in {"resize", "polish"} else
                    {"translate_x": item.get("dx"), "translate_y": item.get("dy")}
                ),
            },
            "quality_score": item["metrics"].get("quality_score"),
            "quality_delta": round(
                float(item["metrics"].get("quality_score") or 0)
                - float(baseline_metrics.get("quality_score") or 0), 2,
            ),
            "rank_score": item["rank_score"],
            "objective_results": item["objective_results"],
            "elements": item["elements"] if rank <= 3 else [],
        }
        for rank, item in enumerate(ranked, 1)
    ]
    competing = [
        item for item in selectable if item["candidate_id"] != selected["candidate_id"]
    ]
    competing.sort(key=lambda item: item["rank_score"], reverse=True)
    competing_score = competing[0]["rank_score"] if competing else None
    quality_delta = round(
        float(selected["metrics"].get("quality_score") or 0)
        - float(baseline_metrics.get("quality_score") or 0), 2,
    )
    requested_scale = scales[0] if scales else 1.0
    degraded_scale = (
        action in {"resize", "polish"}
        and abs(float(selected["scale"]) - float(requested_scale)) > 0.001
    )
    warnings = []
    if degraded_scale:
        warnings.append(
            f"请求的图片缩放 {requested_scale:.2f}× 不安全，已采用 {selected['scale']:.2f}×"
        )
    requested_style = {**requested_params, "image_geometry_action": action}
    effective_style = {**requested_params, "image_geometry_action": action}
    if action in {"resize", "polish"}:
        requested_style["image_scale"] = requested_scale
        effective_style["image_scale"] = selected["scale"]
        rationale = (
            f"仅调整现有图片/图表几何，实际线性缩放 {selected['image_metrics']['median_ratio']:.2f}×；"
            "文字、资源、裁切与视觉槽保持不变"
        )
    else:
        effective_style.update({
            "translate_x": selected.get("dx"), "translate_y": selected.get("dy"),
        })
        rationale = (
            f"仅移动现有图片/图表（Δx={float(selected.get('dx') or 0):.2f}in，"
            f"Δy={float(selected.get('dy') or 0):.2f}in）；"
            "宽高、文字、资源、裁切与视觉槽保持不变"
        )
    return {
        "slide_id": slide_id,
        "layout_type": "existing_image_geometry",
        "designRationale": rationale,
        "elements": selected["elements"],
        "render_mode": "absolute",
        "compile_status": "fallback" if degraded_scale else "applied",
        "requested_style": requested_style,
        "effective_style": effective_style,
        "warnings": warnings,
        "content_allocation": directive.get("content_allocation") or {},
        "compile_attempts": attempts,
        "selected_candidate_id": selected["candidate_id"],
        "requested_objectives": objectives,
        "objective_results": selected["objective_results"],
        "baseline_metrics": baseline_metrics,
        "final_metrics": selected["metrics"],
        "quality_delta": quality_delta,
        "candidate_rankings": rankings,
        "material_change": True,
        "candidate_score_gap": (
            round(float(selected["rank_score"]) - float(competing_score), 2)
            if competing_score is not None else None
        ),
        "requires_candidate_confirmation": False,
    }


def compile_layout(template_id: str, slide: dict[str, Any], directive: dict[str, Any]) -> dict[str, Any]:
    """Compile and rank a bounded set of safe layout candidates.

    V1 returned the first complete geometry.  V2 deliberately evaluates all
    compatible recipes first and only publishes a candidate that is safe,
    materially meets the requested objective, and scores better than weak
    alternatives.  The return shape remains PageLayoutSpec-compatible.
    """
    slide_id = str(directive.get("slide_id") or slide.get("id") or "")
    requested_layout_type = _resolve_preset(directive.get("layout_type"))
    requested_params = normalize_layout_params(directive.get("style"))
    page_type = str(slide.get("page_type") or "concept")
    visual_region = directive.get("visual_region")
    has_visual = bool(visual_region)
    zones = zones_for(template_id, page_type, has_visual=has_visual, visual_region=visual_region)
    from app.agent.slide_rendering import (
        bind_content_refs, render_coverage, semantic_body_refs, semantic_content_hash,
    )

    source_elements = list(slide.get("elements") or [])
    baseline_metrics = analyze_layout(
        source_elements, zones, slide=slide,
        layout_type=str(slide.get("layout_type") or "baseline"),
    )
    objectives, pure_font_request = _normalized_objectives(directive, requested_params)
    if bool(directive.get("image_geometry_only")):
        return _compile_image_geometry(
            slide_id=slide_id,
            slide=slide,
            directive=directive,
            zones=zones,
            source_elements=source_elements,
            baseline_metrics=baseline_metrics,
            objectives=objectives,
            requested_params=requested_params,
            render_coverage=render_coverage,
        )
    valid_refs = {ref for ref, _ in semantic_body_refs(slide)}
    allocation = directive.get("content_allocation") or {}
    requested_order = [
        str(ref) for refs in allocation.values() if isinstance(refs, list) for ref in refs
    ] if isinstance(allocation, dict) else []
    invalid_allocations = [ref for ref in requested_order if ref not in valid_refs and ref != "title"]
    content_order = [ref for ref in requested_order if ref in valid_refs]

    def evaluate(candidate_elements: list[dict[str, Any]]):
        candidate_bound, candidate_unresolved = bind_content_refs(slide, candidate_elements)
        candidate_coverage = render_coverage(
            {**slide, "render_mode": "absolute", "elements": candidate_bound}, baseline=slide,
        )
        from app.agent.tools.editing_tools import compose_layout_elements
        composed_elements = compose_layout_elements(
            slide,
            {
                "elements": candidate_bound,
                "visual_region": visual_region,
                "visual_type": directive.get("visual_type"),
            },
            preserve_visuals=True,
        )
        max_bottom = max(
            (float(item.get("y") or 0) + float(item.get("h") or 0) for item in composed_elements),
            default=0.0,
        )
        geometry_failures = _geometry_failures(composed_elements)
        if any(
            item.get("kind") in {"textbox", "note"}
            and item.get("content_ref")
            and float(item.get("x") or 0) < zones.content_x - 0.01
            for item in candidate_bound
        ):
            geometry_failures = list(dict.fromkeys([*geometry_failures, "template_rail"]))
        return (
            candidate_bound, candidate_unresolved, candidate_coverage,
            not geometry_failures, max_bottom, geometry_failures, composed_elements,
        )

    preferred = "split_two_column" if len(semantic_body_refs(slide)) > 4 else "bullet_flow"
    block_kinds = {str(block.get("kind") or "") for block in (slide.get("blocks") or [])}
    candidate_types = [requested_layout_type]
    # ``purpose`` is a required visible semantic ref on cover pages.  Generic
    # flow recipes intentionally render only body refs, so a model-selected
    # generic recipe must still compete with a purpose-aware cover recipe.
    if page_type == "cover":
        candidate_types.append("cover_left" if has_visual else "cover_center")
    if {"quote", "compare"} <= block_kinds:
        candidate_types.append("quote_compare")
    elif "compare" in block_kinds:
        candidate_types.append("compare_columns")
    elif "quote" in block_kinds:
        candidate_types.append("quote_center")
    if "steps" in block_kinds and (
        requested_layout_type == "steps_horizontal" or page_type == "process"
    ):
        candidate_types.append("steps_horizontal")
    if has_visual:
        candidate_types.append("left_text_right_visual")
    candidate_types.extend([preferred, "split_two_column", "bullet_flow"])
    candidate_types = list(dict.fromkeys(candidate_types))[:5]

    style_ladder = [requested_params]
    requested_scale = float(requested_params.get("font_scale") or 1.0)
    if requested_scale > 1.02:
        for scale in (1.08, 1.06, 1.04, 1.02):
            if scale < requested_scale - 0.001:
                style_ladder.append({**requested_params, "font_scale": scale})
    elif requested_scale < 0.98:
        for scale in (0.92, 0.96, 0.98):
            if scale > requested_scale + 0.001:
                style_ladder.append({**requested_params, "font_scale": scale})
    style_ladder.extend([
        {"font_tier": "default", "font_scale": 1.0, "gap_scale": 1.0, "highlight": requested_params["highlight"]},
        {"font_tier": "compact", "font_scale": 1.0, "gap_scale": 0.8, "highlight": requested_params["highlight"]},
    ])
    unique_styles: list[dict[str, Any]] = []
    seen_styles: set[str] = set()
    for style in style_ladder:
        key = json.dumps(style, sort_keys=True)
        if key not in seen_styles:
            seen_styles.add(key)
            unique_styles.append(style)

    attempts: list[dict[str, Any]] = []
    failures: list[tuple[list[dict[str, Any]], list[str], dict[str, Any], bool, float, list[str], list[dict[str, Any]]]] = []
    viable: list[dict[str, Any]] = []
    viable_signatures: set[str] = set()

    def record_candidate(candidate_type: str, candidate_style: dict[str, Any], result):
        (
            candidate_bound, candidate_unresolved, candidate_coverage,
            candidate_safe, max_bottom, geometry_failures, composed_elements,
        ) = result
        failures.append(result)
        complete_safe = not candidate_unresolved and not candidate_coverage["missing_refs"] and candidate_safe
        metrics = analyze_layout(composed_elements, zones, slide=slide, layout_type=candidate_type)
        objective_results, objectives_passed = _evaluate_objectives(
            objectives, baseline_metrics, metrics,
            baseline_elements=source_elements, candidate_elements=composed_elements, zones=zones,
        )
        quality_delta = round(
            float(metrics.get("quality_score") or 0)
            - float(baseline_metrics.get("quality_score") or 0), 2,
        )
        regressions = _quality_component_regressions(baseline_metrics, metrics)
        explicit_hard_pass = all(
            item.get("passed")
            for item in objective_results
            if item.get("hard_requirement") and item.get("source") != "runtime_gate"
        )
        publishable = bool(objectives_passed and not regressions)
        preview_eligible = bool(
            complete_safe
            and float(metrics.get("quality_score") or 0) >= 75.0
            and quality_delta >= 2.0
            and explicit_hard_pass
            and not regressions
        )
        candidate_id = f"{candidate_type}:{len(attempts) + 1}"
        fingerprint = json.dumps({
            "slide_id": slide_id,
            "content_hash": semantic_content_hash(slide),
            "layout_type": candidate_type,
            "style": candidate_style,
            "missing_refs": candidate_coverage["missing_refs"],
            "geometry": geometry_failures,
            "objectives": objective_results,
        }, ensure_ascii=False, sort_keys=True)
        rank_score = (
            float(metrics.get("quality_score") or 0)
            + (4.0 if candidate_type == requested_layout_type else 0.0)
            + (1.5 if candidate_style == requested_params else 0.0)
            + min(3.0, max(-3.0, quality_delta * 0.12))
            + sum(1.0 for item in objective_results if item.get("passed"))
        )
        attempt = {
            "candidate_id": candidate_id,
            "layout_type": candidate_type,
            "style": candidate_style,
            "unresolved": candidate_unresolved,
            "missing_refs": candidate_coverage["missing_refs"],
            "geometry_safe": candidate_safe,
            "geometry_failures": geometry_failures,
            "max_bottom": round(max_bottom, 3),
            "metrics": metrics,
            "quality_score": metrics.get("quality_score"),
            "quality_delta": quality_delta,
            "objective_results": objective_results,
            "objectives_passed": objectives_passed,
            "publishable": publishable,
            "preview_eligible": preview_eligible,
            "quality_component_regressions": regressions,
            "viable": complete_safe,
            "rank_score": round(rank_score, 2),
            "fingerprint": fingerprint,
        }
        attempts.append(attempt)
        if not complete_safe:
            return None
        signature = _candidate_signature(composed_elements)
        if signature in viable_signatures:
            attempt["viable"] = False
            attempt["rejection_reason"] = "duplicate_geometry_and_style"
            return None
        viable_signatures.add(signature)
        candidate = {
            "candidate_id": candidate_id,
            "layout_type": candidate_type,
            "style": candidate_style,
            "result": result,
            "metrics": metrics,
            "objective_results": objective_results,
            "objectives_passed": objectives_passed,
            "publishable": publishable,
            "preview_eligible": preview_eligible,
            "quality_component_regressions": regressions,
            "rank_score": rank_score,
            "quality_delta": quality_delta,
            "attempt": attempt,
            "signature": signature,
        }
        viable.append(candidate)
        return candidate

    # In-place scaling is allowed only for a pure font-size request whose
    # baseline composition is already balanced.  It can no longer preserve an
    # underused page merely because its text boxes have spare height.
    if (
        source_elements and requested_scale != 1.0 and pure_font_request
        and baseline_distribution_is_sound(baseline_metrics)
    ):
        for candidate_style in unique_styles:
            scale = float(candidate_style.get("font_scale") or 1.0)
            if (requested_scale > 1.0 and scale <= 1.0) or (requested_scale < 1.0 and scale >= 1.0):
                continue
            existing = deepcopy(source_elements)
            for element in existing:
                if element.get("kind") not in {"textbox", "note"} or str(element.get("content_ref") or "") == "title":
                    continue
                style = dict(element.get("style") or {})
                try:
                    before_size = float(style.get("size") or 0)
                except (TypeError, ValueError):
                    before_size = 0.0
                if before_size > 0:
                    style["size"] = max(9, round(before_size * scale))
                    element["style"] = style
            candidate = record_candidate("existing_absolute_scaled", candidate_style, evaluate(existing))
            if candidate is not None:
                break

    # Evaluate every compatible recipe before ranking.  Style degradation is
    # local and deterministic: the first safe style for each recipe becomes a
    # candidate; it never triggers another model call.
    first_style_by_type: dict[str, int] = {}
    for candidate_type in candidate_types:
        if len(viable) >= 5:
            break
        for style_index, candidate_style in enumerate(unique_styles):
            candidate_params = {**candidate_style, "content_order": content_order}
            candidate = record_candidate(
                candidate_type, candidate_style,
                evaluate(PRESETS[candidate_type](zones, slide, candidate_params)),
            )
            if candidate is not None:
                first_style_by_type[candidate_type] = style_index
                break

    # If there are only two distinct recipes, compare a safe style variant so
    # sparse pages still have three choices whenever possible (never more than
    # five viable choices).
    if len(viable) < 3:
        for candidate_type in candidate_types:
            start = first_style_by_type.get(candidate_type, -1) + 1
            for candidate_style in unique_styles[start:]:
                if len(viable) >= 3:
                    break
                candidate_params = {**candidate_style, "content_order": content_order}
                record_candidate(
                    candidate_type, candidate_style,
                    evaluate(PRESETS[candidate_type](zones, slide, candidate_params)),
                )
            if len(viable) >= 3:
                break

    if not viable:
        best = min(
            failures,
            key=lambda item: (
                len(item[1]) + len(item[2]["missing_refs"]),
                0 if item[3] else 1,
                max(0.0, item[4] - 7.01),
            ),
        )
        _, unresolved, coverage, geometry_safe, _, _, _ = best
        raise LayoutCompileError(
            unresolved, coverage["missing_refs"], geometry_safe, attempts=attempts,
        )

    ranked_viable = sorted(viable, key=lambda candidate: candidate["rank_score"], reverse=True)
    candidate_rankings = [
        {
            "rank": rank,
            "candidate_id": candidate["candidate_id"],
            "layout_type": candidate["layout_type"],
            "style": candidate["style"],
            "quality_score": candidate["metrics"].get("quality_score"),
            "quality_delta": candidate["quality_delta"],
            "rank_score": round(float(candidate["rank_score"]), 2),
            "objective_results": candidate["objective_results"],
            "publishable": bool(candidate.get("publishable")),
            "preview_eligible": bool(candidate.get("preview_eligible")),
            "quality_component_regressions": list(candidate.get("quality_component_regressions") or []),
            # The top three are sufficient for staging previews.  Lower-ranked
            # candidates retain diagnostics without bloating the artifact.
            "elements": candidate["result"][0] if rank <= 3 else [],
        }
        for rank, candidate in enumerate(ranked_viable, 1)
    ]

    baseline_signature = _candidate_signature(source_elements) if source_elements else ""
    selectable = [
        candidate for candidate in viable
        if candidate.get("publishable") or (not objectives and not candidate.get("quality_component_regressions"))
    ]
    if baseline_signature:
        selectable = [candidate for candidate in selectable if candidate["signature"] != baseline_signature]
    previewable = [
        candidate for candidate in viable
        if candidate.get("preview_eligible")
        and (not baseline_signature or candidate["signature"] != baseline_signature)
    ]
    warnings: list[str] = []
    if invalid_allocations:
        warnings.append(
            "content_allocation 含无效引用，已由确定性分配器忽略："
            + "、".join(invalid_allocations[:8])
        )

    # No objective winner is a successful per-page no-change.  Returning a
    # preserved spec lets the existing staging/publish policy keep other pages
    # while avoiding an empty version for this one.
    force_confirmation = False
    if not selectable and previewable:
        selectable = previewable
        force_confirmation = True
    if not selectable and source_elements:
        near = max(viable, key=lambda candidate: candidate["rank_score"])
        failed_metrics = [
            item["metric"] for item in near["objective_results"]
            if item.get("hard_requirement") and not item.get("passed")
        ]
        warning = (
            "候选均未达到明确目标（" + "、".join(failed_metrics) + "），已保留原布局"
            if failed_metrics else "候选与原页没有可感知差异，已保留原布局"
        )
        warnings.append(warning)
        rejection_code = (
            "quality_gate_not_met" if "layout_quality" in failed_metrics
            else "objective_unmet" if failed_metrics
            else "identical_to_baseline"
        )
        rejection_reasons = [
            *(f"未达到目标：{metric}" for metric in failed_metrics),
            *(f"质量分项退化：{metric}" for metric in near.get("quality_component_regressions") or []),
        ] or [warning]
        return {
            "slide_id": slide_id,
            "layout_type": "preserve_original",
            "designRationale": warning,
            "elements": source_elements,
            "render_mode": str(slide.get("render_mode") or "absolute"),
            "compile_status": "preserved",
            "requested_style": requested_params,
            "effective_style": {},
            "warnings": warnings,
            "content_allocation": allocation,
            "compile_attempts": attempts,
            "selected_candidate_id": None,
            "decision": "preserved",
            "best_candidate_id": near["candidate_id"],
            "best_candidate_metrics": near["metrics"],
            "best_candidate_quality_delta": near["quality_delta"],
            "rejection_code": rejection_code,
            "rejection_reasons": rejection_reasons,
            "requested_objectives": objectives,
            "objective_results": near["objective_results"],
            "baseline_metrics": baseline_metrics,
            "final_metrics": baseline_metrics,
            "quality_delta": 0.0,
            "candidate_rankings": candidate_rankings,
            "material_change": False,
            "candidate_score_gap": (
                round(float(ranked_viable[0]["rank_score"] - ranked_viable[1]["rank_score"]), 2)
                if len(ranked_viable) > 1 else None
            ),
            "requires_candidate_confirmation": False,
        }
    if not selectable:
        selectable = viable

    # First generation has no baseline improvement evidence.  Preserve the
    # explicit recipe contract when it is safe; V2 ranking is authoritative
    # for polish runs that actually have a baseline to compare.
    requested_viable = [
        candidate for candidate in selectable
        if candidate["layout_type"] == requested_layout_type
    ] if not source_elements else []
    structural_type = (
        "quote_compare" if {"quote", "compare"} <= block_kinds else
        "steps_horizontal" if "steps" in block_kinds else
        "compare_columns" if "compare" in block_kinds else
        "quote_center" if "quote" in block_kinds else
        ""
    )
    structural_viable = [
        candidate for candidate in selectable
        if candidate["layout_type"] == structural_type
        and float(candidate["metrics"].get("quality_score") or 0) >= 75.0
        and (
            not source_elements
            or (bool(objectives) and bool(candidate.get("objectives_passed")))
            or float(candidate.get("quality_delta") or 0) >= 5.0
        )
    ] if structural_type and not requested_viable else []
    selected = max(
        requested_viable or structural_viable or selectable,
        key=lambda candidate: candidate["rank_score"],
    )
    selected["attempt"]["selected"] = True
    selected_index = attempts.index(selected["attempt"])
    attempts.append(attempts.pop(selected_index))
    layout_type = selected["layout_type"]
    effective_style = selected["style"]
    bound = selected["result"][0]
    selected_ranking = next(
        (item for item in candidate_rankings if item["candidate_id"] == selected["candidate_id"]),
        None,
    )
    # A close but unpublishable candidate must not trigger a user choice.
    # Compare only candidates that passed all hard objectives (``selectable``
    # already applies that gate and removes the unchanged baseline).
    confirmation_pool = list({
        candidate["candidate_id"]: candidate
        for candidate in [*selectable, *previewable]
    }.values())
    competing_candidates = sorted(
        (
            candidate for candidate in confirmation_pool
            if candidate["candidate_id"] != selected["candidate_id"]
        ),
        key=lambda candidate: candidate["rank_score"], reverse=True,
    )
    competing = [
        item for candidate in competing_candidates
        for item in candidate_rankings
        if item["candidate_id"] == candidate["candidate_id"]
    ]
    candidate_score_gap = (
        # Human choice is based on the visible 100-point quality score.  The
        # internal rank score also contains recipe/style preference bonuses;
        # using it here could make two equally good pages look far apart and
        # bypass the required side-by-side preview.
        round(
            float(selected["metrics"].get("quality_score") or 0)
            - float(competing[0].get("quality_score") or 0),
            2,
        )
        if competing else None
    )
    fallback_reason = ""
    if layout_type != requested_layout_type or effective_style != requested_params:
        requested_attempt = next(
            (attempt for attempt in attempts if attempt["layout_type"] == requested_layout_type),
            attempts[0],
        )
        if requested_attempt["unresolved"] or requested_attempt["missing_refs"]:
            fallback_reason = "未覆盖全部文字"
        elif not requested_attempt["geometry_safe"]:
            fallback_reason = "超出页面安全区"
        else:
            fallback_reason = "质量评分较低"
        warnings.append(
            f"{requested_layout_type} {fallback_reason}，已选择 {layout_type} / {effective_style['font_tier']}"
        )
    requires_candidate_confirmation = bool(
        source_elements
        and selected_ranking
        and (
            force_confirmation
            or (competing and abs(float(candidate_score_gap or 0)) < 5.0)
        )
        and any(item["metric"] in {
            "layout_quality", "vertical_utilization", "whitespace_balance",
            "horizontal_utilization", "contrast",
        } for item in objectives)
    )
    out: dict[str, Any] = {
        "slide_id": slide_id,
        "layout_type": layout_type,
        "designRationale": str(directive.get("rationale") or f"预设版式 {requested_layout_type}")
        + (
            f"；全量比较后因{fallback_reason}选择 {layout_type}"
            if fallback_reason else "；已通过候选质量排序与目标门禁"
        ),
        "elements": bound,
        "render_mode": "absolute",
        "compile_status": "fallback" if fallback_reason else "applied",
        "requested_style": requested_params,
        "effective_style": effective_style,
        "warnings": warnings,
        "content_allocation": allocation,
        "compile_attempts": attempts,
        "selected_candidate_id": selected["candidate_id"],
        "decision": "preview_required" if requires_candidate_confirmation else "applied",
        "best_candidate_id": selected["candidate_id"],
        "best_candidate_metrics": selected["metrics"],
        "best_candidate_quality_delta": selected["quality_delta"],
        "requested_objectives": objectives,
        "objective_results": selected["objective_results"],
        "baseline_metrics": baseline_metrics,
        "final_metrics": selected["metrics"],
        "quality_delta": selected["quality_delta"],
        "candidate_rankings": candidate_rankings,
        "material_change": not bool(baseline_signature) or selected["signature"] != baseline_signature,
        "candidate_score_gap": candidate_score_gap,
        "requires_candidate_confirmation": requires_candidate_confirmation,
    }
    if has_visual and zones.visual_slot is not None:
        vs = zones.visual_slot
        out["visual_region"] = {"x": vs.x, "y": vs.y, "w": vs.w, "h": vs.h}
        out["visual_type"] = str(directive.get("visual_type") or "image")
    return out
