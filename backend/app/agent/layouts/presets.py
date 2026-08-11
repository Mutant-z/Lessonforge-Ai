from typing import Any, Callable

from app.agent.layouts.metrics import estimate_text_height
from app.agent.layouts.zones import LayoutZones
from app.agent.slide_rendering import semantic_body_refs

BODY_FONT = 18
TITLE_FONT = 28
ITEM_GAP = 0.3
MAX_CARD_COLUMNS = 4

CompileFn = Callable[[LayoutZones, dict[str, Any], dict[str, Any]], list[dict[str, Any]]]


def _title(zones: LayoutZones, content: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "textbox",
        "role": "title",
        "text": str(content.get("title") or ""),
        "content_ref": "title",
        "x": round(zones.title_rail.x, 3),
        "y": round(zones.title_rail.y, 3),
        "w": round(zones.title_rail.w, 3),
        "h": round(zones.title_rail.h, 3),
        "style": {"size": TITLE_FONT, "color": "primary", "bold": True},
    }


def _body_box(ref: str, text: str, x: float, y: float, w: float, h: float) -> dict[str, Any]:
    return {
        "kind": "textbox",
        "role": "body",
        "text": text,
        "content_ref": ref,
        "x": round(x, 3),
        "y": round(y, 3),
        "w": round(w, 3),
        "h": round(h, 3),
        "style": {"size": BODY_FONT, "color": "text"},
    }


def _font_size(params: dict[str, Any]) -> int:
    return {"compact": 16, "spacious": 20}.get(params.get("font_tier"), BODY_FONT)


def bullet_flow(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    refs = semantic_body_refs(content)
    if not refs:
        return elements
    size = _font_size(params)
    gap_scale = float(params.get("gap_scale") or 1.0)
    col = zones.body_column
    col_w = col.w
    items = [(ref, text, max(0.5, estimate_text_height(text, col_w, size))) for ref, text in refs]
    total_h = sum(h for _, _, h in items) + ITEM_GAP * gap_scale * max(0, len(items) - 1)
    target_h = col.h * 0.45
    gap = ITEM_GAP * gap_scale
    if len(items) > 1 and total_h < target_h:
        gap = gap + (target_h - total_h) / (len(items) - 1)
    cursor = col.y
    for ref, text, h in items:
        elements.append(_body_box(ref, text, col.x, cursor, col_w, h))
        cursor += h + gap
    return elements


def split_two_column(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    refs = semantic_body_refs(content)
    if not refs:
        return elements
    size = _font_size(params)
    col = zones.body_column
    half_w = (col.w - ITEM_GAP) / 2
    left, right = refs[: max(1, len(refs) // 2)], refs[max(1, len(refs) // 2):]
    for x, column in ((col.x, left), (col.x + half_w + ITEM_GAP, right)):
        cursor = col.y
        for ref, text in column:
            h = max(0.5, estimate_text_height(text, half_w, size))
            elements.append(_body_box(ref, text, x, cursor, half_w, h))
            cursor += h + ITEM_GAP
    return elements


def left_text_right_visual(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    if zones.visual_slot is None:
        return bullet_flow(zones, content, params)
    elements = [_title(zones, content)]
    refs = semantic_body_refs(content)
    col = zones.body_column
    size = _font_size(params)
    cursor = col.y
    for ref, text in refs:
        h = max(0.5, estimate_text_height(text, col.w, size))
        elements.append(_body_box(ref, text, col.x, cursor, col.w, h))
        cursor += h + ITEM_GAP
    vs = zones.visual_slot
    elements.append(
        {
            "kind": "shape",
            "role": "visual_panel",
            "shape_type": "rounded",
            "x": round(vs.x, 3),
            "y": round(vs.y, 3),
            "w": round(vs.w, 3),
            "h": round(vs.h, 3),
            "fill": "surface",
            "line": "secondary",
        }
    )
    return elements


def steps_horizontal(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    steps = []
    for block in content.get("blocks") or []:
        if block.get("kind") == "steps":
            steps = list(block.get("steps") or [])
            break
    if not steps:
        return bullet_flow(zones, content, params)
    col = zones.body_column
    n = min(MAX_CARD_COLUMNS, len(steps))
    card_w = (col.w - ITEM_GAP * (n - 1)) / n
    for index, step in enumerate(steps[:n]):
        x = col.x + index * (card_w + ITEM_GAP)
        title = str(step.get("title") or f"第 {index + 1} 步")
        detail = str(step.get("detail") or "")
        th = max(0.5, estimate_text_height(title, card_w, 16))
        elements.append(_body_box(f"blocks.0.steps.{index}.title", title, x, col.y, card_w, th))
        if detail:
            dh = max(0.5, estimate_text_height(detail, card_w, 14))
            elements.append(
                {
                    "kind": "textbox",
                    "role": "body",
                    "text": detail,
                    "content_ref": f"blocks.0.steps.{index}.detail",
                    "x": round(x, 3),
                    "y": round(col.y + th + 0.15, 3),
                    "w": round(card_w, 3),
                    "h": round(dh, 3),
                    "style": {"size": 14, "color": "muted"},
                }
            )
    return elements


def compare_columns(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    block = next((b for b in content.get("blocks") or [] if b.get("kind") == "compare"), None)
    if not block:
        return split_two_column(zones, content, params)
    col = zones.body_column
    half_w = (col.w - ITEM_GAP) / 2
    for side, x in (("left", col.x), ("right", col.x + half_w + ITEM_GAP)):
        column = block.get(side) or {}
        heading = str(column.get("heading") or "")
        hh = max(0.5, estimate_text_height(heading, half_w, 16))
        elements.append(
            {
                "kind": "textbox",
                "role": "body",
                "text": heading,
                "content_ref": f"blocks.0.{side}.heading",
                "x": round(x, 3),
                "y": round(col.y, 3),
                "w": round(half_w, 3),
                "h": round(hh, 3),
                "style": {"size": 16, "color": "primary", "bold": True},
            }
        )
        cursor = col.y + hh + 0.15
        for index, item in enumerate(column.get("items") or []):
            h = max(0.5, estimate_text_height(str(item), half_w, 14))
            elements.append(
                {
                    "kind": "textbox",
                    "role": "body",
                    "text": str(item),
                    "content_ref": f"blocks.0.{side}.items.{index}",
                    "x": round(x, 3),
                    "y": round(cursor, 3),
                    "w": round(half_w, 3),
                    "h": round(h, 3),
                    "style": {"size": 14, "color": "text"},
                }
            )
            cursor += h + ITEM_GAP
    return elements


def quote_center(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    block = next((b for b in content.get("blocks") or [] if b.get("kind") == "quote"), None)
    text = str(block.get("text") or "") if block else ""
    if not text:
        return bullet_flow(zones, content, params)
    col = zones.body_column
    w = min(col.w, 9.5)
    x = col.x + (col.w - w) / 2
    h = max(0.8, estimate_text_height(text, w, 22))
    elements.append(
        {
            "kind": "textbox",
            "role": "body",
            "text": text,
            "content_ref": "blocks.0.text",
            "x": round(x, 3),
            "y": round(col.y + (col.h - h) / 2, 3),
            "w": round(w, 3),
            "h": round(h, 3),
            "style": {"size": 22, "color": "primary", "bold": True},
        }
    )
    citation = str(block.get("citation") or "") if block else ""
    if citation:
        ch = max(0.5, estimate_text_height(citation, w, 14))
        elements.append(
            {
                "kind": "textbox",
                "role": "body",
                "text": citation,
                "content_ref": "blocks.0.citation",
                "x": round(x, 3),
                "y": round(col.y + (col.h - h) / 2 + h + 0.2, 3),
                "w": round(w, 3),
                "h": round(ch, 3),
                "style": {"size": 14, "color": "muted"},
            }
        )
    return elements


def agenda_list(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    return bullet_flow(zones, content, params)


def cover_left(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = []
    body = [str(t) for t in (content.get("body") or [])]
    title = str(content.get("title") or "")
    purpose = str(content.get("purpose") or "")
    has_visual = zones.visual_slot is not None
    title_w = (zones.visual_slot.x - zones.content_x - 0.4) if has_visual else zones.canvas.w - zones.content_x - 0.9
    elements.append(
        {
            "kind": "textbox",
            "role": "title",
            "text": title,
            "content_ref": "title",
            "x": round(zones.content_x, 3),
            "y": round(2.05 if has_visual else 2.3, 3),
            "w": round(title_w, 3),
            "h": 1.6,
            "style": {"size": 40, "color": "primary", "bold": True},
        }
    )
    if body:
        elements.append(
            {
                "kind": "textbox",
                "role": "subtitle",
                "text": " · ".join(body[:2]),
                "content_ref": "body",
                "x": round(zones.content_x, 3),
                "y": 4.0,
                "w": round(title_w, 3),
                "h": 0.8,
                "style": {"size": 20, "color": "muted"},
            }
        )
    if purpose:
        elements.append(
            {
                "kind": "textbox",
                "role": "purpose",
                "text": purpose,
                "content_ref": "purpose",
                "x": round(zones.content_x, 3),
                "y": 5.0,
                "w": round(title_w, 3),
                "h": 0.65,
                "style": {"size": 15, "color": "primary", "bold": True},
            }
        )
    if has_visual:
        vs = zones.visual_slot
        elements.append(
            {
                "kind": "shape",
                "role": "visual_panel",
                "shape_type": "rounded",
                "x": round(vs.x, 3),
                "y": round(vs.y, 3),
                "w": round(vs.w, 3),
                "h": round(vs.h, 3),
                "fill": "surface",
                "line": "secondary",
            }
        )
    return elements


def cover_center(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    return cover_left(zones, content, params)


PRESETS: dict[str, CompileFn] = {
    "bullet_flow": bullet_flow,
    "split_two_column": split_two_column,
    "left_text_right_visual": left_text_right_visual,
    "steps_horizontal": steps_horizontal,
    "compare_columns": compare_columns,
    "quote_center": quote_center,
    "agenda_list": agenda_list,
    "cover_left": cover_left,
    "cover_center": cover_center,
}

PRESET_KEYS = frozenset(PRESETS)
