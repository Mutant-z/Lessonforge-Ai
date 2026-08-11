from typing import Any
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


def normalize_layout_params(style: dict[str, Any] | None) -> dict[str, Any]:
    style = dict(style or {})
    tier = style.get("font_tier")
    if tier not in {"default", "compact", "spacious"}:
        tier = "default"
    try:
        gap = float(style.get("gap_scale") or 1.0)
    except (TypeError, ValueError):
        gap = 1.0
    return {"font_tier": tier, "gap_scale": max(_GAP_LOW, min(_GAP_HIGH, gap))}


def _resolve_preset(layout_type: str) -> str:
    key = str(layout_type or "bullet_flow")
    if key in PRESET_KEYS:
        return key
    return PRESET_ALIASES.get(key, "bullet_flow")


def compile_layout(template_id: str, slide: dict[str, Any], directive: dict[str, Any]) -> dict[str, Any]:
    slide_id = str(directive.get("slide_id") or slide.get("id") or "")
    layout_type = _resolve_preset(directive.get("layout_type"))
    params = normalize_layout_params(directive.get("style"))
    page_type = str(slide.get("page_type") or "concept")
    visual_region = directive.get("visual_region")
    has_visual = bool(visual_region)
    zones = zones_for(template_id, page_type, has_visual=has_visual, visual_region=visual_region)
    elements = PRESETS[layout_type](zones, slide, params)
    out: dict[str, Any] = {
        "slide_id": slide_id,
        "layout_type": layout_type,
        "designRationale": str(directive.get("rationale") or f"预设版式 {layout_type}"),
        "elements": elements,
        "render_mode": "absolute",
    }
    if has_visual and zones.visual_slot is not None:
        vs = zones.visual_slot
        out["visual_region"] = {"x": vs.x, "y": vs.y, "w": vs.w, "h": vs.h}
        out["visual_type"] = str(directive.get("visual_type") or "image")
    return out
