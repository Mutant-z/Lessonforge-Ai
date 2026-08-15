from itertools import combinations
from typing import Any, Callable

from app.agent.layouts.metrics import estimate_text_height
from app.agent.layouts.zones import LayoutZones
from app.agent.slide_rendering import semantic_body_refs

BODY_FONT = 18
TITLE_FONT = 28
ITEM_GAP = 0.3
MAX_CARD_COLUMNS = 4

CompileFn = Callable[[LayoutZones, dict[str, Any], dict[str, Any]], list[dict[str, Any]]]


def _title(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "textbox",
        "role": "title",
        "text": str(content.get("title") or ""),
        "content_ref": "title",
        "x": round(zones.title_rail.x, 3),
        "y": round(zones.title_rail.y, 3),
        "w": round(zones.title_rail.w, 3),
        "h": round(zones.title_rail.h, 3),
        "style": {"size": _font_size(params or {}, TITLE_FONT), "color": "primary", "bold": True},
    }


def _body_box(
    ref: str, text: str, x: float, y: float, w: float, h: float,
    *, size: int = BODY_FONT, color: str = "text",
) -> dict[str, Any]:
    return {
        "kind": "textbox",
        "role": "body",
        "text": text,
        "content_ref": ref,
        "x": round(x, 3),
        "y": round(y, 3),
        "w": round(w, 3),
        "h": round(h, 3),
        "style": {"size": size, "color": color},
    }


def _highlight(elements: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply a visible, theme-safe emphasis treatment when requested.

    ``highlight`` used to be accepted by the schema but ignored by every
    preset.  A slim accent marker and real typographic emphasis make it an
    executable layout control without introducing new assets or theme colors.
    """
    if not params.get("highlight"):
        return elements
    target = next((
        item for item in elements
        if item.get("kind") in {"textbox", "note"}
        and item.get("content_ref") not in {"", "title", None}
    ), None)
    if target is None:
        return elements
    style = dict(target.get("style") or {})
    style.update({"bold": True, "color": "primary"})
    target["style"] = style
    accent = {
        "kind": "shape", "role": "highlight_panel", "shape_type": "rounded",
        "content_ref": "",
        "x": round(max(0.49, float(target.get("x") or 0) - 0.1), 3),
        "y": round(float(target.get("y") or 0), 3),
        "w": 0.045,
        "h": round(float(target.get("h") or 0), 3),
        "fill": "primary", "line": "primary",
    }
    return [elements[0], accent, *elements[1:]] if elements else [accent]


def _target_fill_fraction(item_count: int, natural_fraction: float) -> float:
    """Body-flow target: visually occupy 60–85% without stretching overflow."""
    count_target = 0.60 + min(0.20, max(0, item_count - 2) * 0.04)
    return min(0.85, max(0.60, count_target, natural_fraction))


def _balanced_columns(
    refs: list[tuple[str, str]], *, column_count: int, column_w: float,
    size: int, gap: float,
) -> tuple[list[list[tuple[str, str]]], float]:
    """Find contiguous, reading-order-preserving columns with balanced height."""
    if not refs:
        return [], 0.0
    column_count = max(1, min(column_count, len(refs)))
    heights = [max(0.5, estimate_text_height(text, column_w, size)) for _, text in refs]
    if column_count == 1:
        return [refs], sum(heights) + gap * max(0, len(refs) - 1)
    # Exhaustive cut search is tiny for normal slides (<= 20 semantic units)
    # and gives a much better split than the old ceil(n / columns) chunks.
    # Fall back to target-height cuts for pathological historical artifacts.
    if len(refs) <= 24:
        best: tuple[tuple[float, float], tuple[int, ...], list[float]] | None = None
        for cuts in combinations(range(1, len(refs)), column_count - 1):
            bounds = (0, *cuts, len(refs))
            totals = []
            for index in range(column_count):
                start, end = bounds[index], bounds[index + 1]
                totals.append(sum(heights[start:end]) + gap * max(0, end - start - 1))
            average = sum(totals) / len(totals)
            key = (max(totals), sum(abs(value - average) for value in totals))
            if best is None or key < best[0]:
                best = (key, cuts, totals)
        assert best is not None
        bounds = (0, *best[1], len(refs))
        chunks = [refs[bounds[index]:bounds[index + 1]] for index in range(column_count)]
        return chunks, max(best[2])
    target = (sum(heights) + gap * max(0, len(refs) - column_count)) / column_count
    chunks: list[list[tuple[str, str]]] = []
    start = 0
    for column in range(column_count - 1):
        cursor = start
        used = 0.0
        remaining_columns = column_count - column - 1
        while cursor < len(refs) - remaining_columns:
            next_height = heights[cursor] + (gap if cursor > start else 0)
            if cursor > start and used + next_height > target:
                break
            used += next_height
            cursor += 1
        chunks.append(refs[start:cursor])
        start = cursor
    chunks.append(refs[start:])
    tallest = max(
        sum(max(0.5, estimate_text_height(text, column_w, size)) for _, text in chunk)
        + gap * max(0, len(chunk) - 1)
        for chunk in chunks
    )
    return chunks, tallest


def _font_size(params: dict[str, Any], base: int = BODY_FONT) -> int:
    tier_size = {"compact": 16, "spacious": 20}.get(params.get("font_tier"), BODY_FONT)
    try:
        scale = float(params.get("font_scale") or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    return max(10, round(base * tier_size / BODY_FONT * scale))


def _ordered_refs(content: dict[str, Any], params: dict[str, Any]) -> list[tuple[str, str]]:
    refs = semantic_body_refs(content)
    requested = [str(value) for value in (params.get("content_order") or [])]
    if not requested:
        return refs
    by_ref = dict(refs)
    ordered = [(ref, by_ref[ref]) for ref in requested if ref in by_ref]
    seen = {ref for ref, _ in ordered}
    ordered.extend((ref, text) for ref, text in refs if ref not in seen)
    return ordered


def bullet_flow(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content, params)]
    refs = _ordered_refs(content, params)
    if not refs:
        return elements
    size = _font_size(params)
    gap_scale = float(params.get("gap_scale") or 1.0)
    col = zones.body_column
    col_w = col.w
    items = [(ref, text, max(0.5, estimate_text_height(text, col_w, size))) for ref, text in refs]
    total_h = sum(h for _, _, h in items) + ITEM_GAP * gap_scale * max(0, len(items) - 1)
    target_h = col.h * _target_fill_fraction(len(items), total_h / max(0.01, col.h))
    gap = ITEM_GAP * gap_scale
    if len(items) > 1 and total_h < target_h:
        gap = gap + (target_h - total_h) / (len(items) - 1)
    cursor = col.y
    for ref, text, h in items:
        elements.append(_body_box(ref, text, col.x, cursor, col_w, h, size=size))
        cursor += h + gap
    return _highlight(elements, params)


def split_two_column(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content, params)]
    refs = _ordered_refs(content, params)
    if not refs:
        return elements
    if len(refs) < 2:
        return bullet_flow(zones, content, params)
    size = _font_size(params)
    col = zones.body_column
    gap = ITEM_GAP * float(params.get("gap_scale") or 1.0)
    # Pick the fewest columns that fit the content rail.  Columns are balanced
    # by estimated rendered height (not item count) while keeping contiguous
    # reading order.
    column_count = 2
    columns: list[list[tuple[str, str]]] = []
    for candidate in range(2, min(4, len(refs)) + 1):
        candidate_w = (col.w - gap * (candidate - 1)) / candidate
        chunks, tallest = _balanced_columns(
            refs, column_count=candidate, column_w=candidate_w, size=size, gap=gap,
        )
        column_count = candidate
        columns = chunks
        if tallest <= col.h + 0.01:
            break
    column_w = (col.w - gap * (column_count - 1)) / column_count
    for column_index, column in enumerate(columns):
        x = col.x + column_index * (column_w + gap)
        cursor = col.y
        for ref, text in column:
            h = max(0.5, estimate_text_height(text, column_w, size))
            elements.append(_body_box(ref, text, x, cursor, column_w, h, size=size))
            cursor += h + gap
    return _highlight(elements, params)


def left_text_right_visual(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    if zones.visual_slot is None:
        return bullet_flow(zones, content, params)
    elements = [_title(zones, content, params)]
    refs = _ordered_refs(content, params)
    col = zones.body_column
    size = _font_size(params)
    cursor = col.y
    for ref, text in refs:
        h = max(0.5, estimate_text_height(text, col.w, size))
        elements.append(_body_box(ref, text, col.x, cursor, col.w, h, size=size))
        cursor += h + ITEM_GAP * float(params.get("gap_scale") or 1.0)
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
    return _highlight(elements, params)


def steps_horizontal(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content, params)]
    steps = []
    block_index = -1
    for index, block in enumerate(content.get("blocks") or []):
        if block.get("kind") == "steps":
            steps = list(block.get("steps") or [])
            block_index = index
            break
    if not steps:
        return bullet_flow(zones, content, params)
    col = zones.body_column
    n = min(MAX_CARD_COLUMNS, len(steps))
    gap_scale = float(params.get("gap_scale") or 1.0)
    card_gap = ITEM_GAP * gap_scale
    card_w = (col.w - card_gap * (n - 1)) / n
    title_size = _font_size(params)
    body_size = max(11, title_size - 4)
    detail_size = max(10, title_size - 5)
    inner_gap = 0.15 * gap_scale
    body_items = list(content.get("body") or [])
    extra_body = list(enumerate(body_items[n:], start=n)) if len(steps) <= MAX_CARD_COLUMNS else []
    extra_columns = min(MAX_CARD_COLUMNS, len(extra_body)) if extra_body else 0
    extra_w = (
        (col.w - card_gap * (extra_columns - 1)) / extra_columns
        if extra_columns else col.w
    )
    extra_rows = [
        extra_body[index:index + extra_columns]
        for index in range(0, len(extra_body), extra_columns)
    ] if extra_columns else []
    reserved_extra_h = 0.0
    for row in extra_rows:
        reserved_extra_h += max(
            max(0.5, estimate_text_height(str(value), extra_w, body_size))
            for _, value in row
        ) + card_gap
    if reserved_extra_h:
        reserved_extra_h += 0.18
    card_h = min(col.h * 0.84, col.h - reserved_extra_h)
    card_h = max(2.35, card_h)
    card_bottom = col.y + card_h
    for index, step in enumerate(steps[:n]):
        x = col.x + index * (card_w + card_gap)
        inner_w = max(0.4, card_w - 0.24)
        title = str(step.get("title") or f"第 {index + 1} 步")
        detail = str(step.get("detail") or "")
        th = max(0.5, estimate_text_height(title, inner_w, title_size))
        body_text = str(body_items[index]) if index < len(body_items) else ""
        bh = (
            max(0.5, estimate_text_height(body_text, inner_w, body_size))
            if body_text and body_text not in {title, detail} else 0.0
        )
        dh = (
            max(0.5, estimate_text_height(detail, inner_w, detail_size))
            if detail and detail not in {title, body_text} else 0.0
        )
        # A real full-height card gives each learning step a visual group.  The
        # semantic text is distributed inside the card instead of clustering
        # immediately under the title rail.
        elements.append({
            "kind": "shape", "role": "step_card", "shape_type": "rounded",
            "content_ref": "",
            "x": round(x, 3), "y": round(col.y, 3), "w": round(card_w, 3),
            "h": round(card_h, 3), "fill": "surface",
            "line": "primary" if params.get("highlight") and index == 0 else "secondary",
        })
        badge_h = 0.6
        badge_w = min(0.58, card_w * 0.24)
        elements.append({
            "kind": "textbox", "role": "step_index", "text": f"{index + 1:02d}",
            "content_ref": "",
            "x": round(x + 0.16, 3), "y": round(col.y + 0.18, 3),
            "w": round(badge_w, 3), "h": badge_h,
            "style": {"size": max(10, detail_size), "color": "primary", "bold": True},
        })
        entries: list[tuple[str, str, float, int, str]] = [
            (f"blocks.{block_index}.steps.{index}.title", title, th, title_size, "text"),
        ]
        if body_text and body_text not in {title, detail}:
            entries.append((f"body.{index}", body_text, bh, body_size, "muted"))
        if detail and detail not in {title, body_text}:
            entries.append((
                f"blocks.{block_index}.steps.{index}.detail", detail,
                dh, detail_size, "muted",
            ))
        content_top = col.y + 0.9
        content_bottom = col.y + card_h - 0.28
        natural_h = sum(entry[2] for entry in entries)
        spread_gap = (
            max(inner_gap, (content_bottom - content_top - natural_h) / (len(entries) - 1))
            if len(entries) > 1 else 0.0
        )
        cursor = content_top
        for ref, text, height, size, color in entries:
            elements.append(_body_box(ref, text, x + 0.12, cursor, inner_w, height, size=size, color=color))
            cursor += height + spread_gap

    # Some historical/content-agent pages contain more flat body items than
    # step cards (for example four experimental steps plus two calculation
    # conclusions).  The old preset silently stopped at ``body[n]``.  Keep the
    # step cards and place the remaining authoritative body copy in a compact
    # summary row underneath them instead of forcing a generic 14-item flow.
    # Pages with more than four actual steps still fall through the coverage
    # gate, because their tail step title/detail refs need a different preset.
    if extra_body:
        extra_gap = card_gap
        extra_y = card_bottom + max(0.2, extra_gap)
        row_y = extra_y
        for row in extra_rows:
            heights = [
                max(0.5, estimate_text_height(str(value), extra_w, body_size))
                for _, value in row
            ]
            for column, ((body_index, value), h) in enumerate(zip(row, heights, strict=True)):
                elements.append(_body_box(
                    f"body.{body_index}", str(value),
                    col.x + column * (extra_w + extra_gap), row_y, extra_w, h,
                    size=body_size, color="muted",
                ))
            # Compile-time geometry QA rejects genuinely overfull pages; rows
            # still use their tallest item so mixed-length copy never overlaps.
            row_y += max(heights) + extra_gap
    return _highlight(elements, params)


def compare_columns(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content, params)]
    indexed_block = next((
        (index, block) for index, block in enumerate(content.get("blocks") or [])
        if block.get("kind") == "compare"
    ), None)
    block_index, block = indexed_block if indexed_block is not None else (-1, None)
    if not block:
        return split_two_column(zones, content, params)
    col = zones.body_column
    gap = ITEM_GAP * float(params.get("gap_scale") or 1.0)
    half_w = (col.w - gap) / 2
    heading_size = _font_size(params, 16)
    item_size = _font_size(params, 14)
    for side, x in (("left", col.x), ("right", col.x + half_w + gap)):
        column = block.get(side) or {}
        heading = str(column.get("heading") or "")
        hh = max(0.5, estimate_text_height(heading, half_w, heading_size))
        item_values = [str(item) for item in (column.get("items") or [])]
        item_heights = [max(0.5, estimate_text_height(item, half_w, item_size)) for item in item_values]
        natural_h = hh + sum(item_heights) + gap * len(item_values)
        target_fraction = max(0.62, natural_h / max(0.01, col.h))
        target_fraction += max(-0.04, min(0.05, (float(params.get("gap_scale") or 1.0) - 1.0) * 0.10))
        target_h = col.h * min(0.82, target_fraction)
        item_gap = gap
        if item_values and natural_h < target_h:
            item_gap += (target_h - natural_h) / len(item_values)
        panel_h = min(col.h, max(target_h + 0.2, natural_h + 0.2))
        elements.append({
            "kind": "shape", "role": "compare_panel", "shape_type": "rounded",
            "content_ref": "",
            "x": round(x - 0.1, 3), "y": round(col.y - 0.1, 3),
            "w": round(half_w + 0.2, 3), "h": round(panel_h, 3),
            "fill": "surface", "line": "secondary",
        })
        elements.append(
            {
                "kind": "textbox",
                "role": "body",
                "text": heading,
                "content_ref": f"blocks.{block_index}.{side}.heading",
                "x": round(x, 3),
                "y": round(col.y, 3),
                "w": round(half_w, 3),
                "h": round(hh, 3),
                "style": {"size": heading_size, "color": "primary", "bold": True},
            }
        )
        cursor = col.y + hh + item_gap
        for index, (item, h) in enumerate(zip(item_values, item_heights, strict=True)):
            elements.append(
                {
                    "kind": "textbox",
                    "role": "body",
                    "text": item,
                    "content_ref": f"blocks.{block_index}.{side}.items.{index}",
                    "x": round(x, 3),
                    "y": round(cursor, 3),
                    "w": round(half_w, 3),
                    "h": round(h, 3),
                    "style": {"size": item_size, "color": "text"},
                }
            )
            cursor += h + item_gap
    return _highlight(elements, params)


def quote_compare(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    """Compound layout for pages that carry both a quote and comparison data."""
    elements = [_title(zones, content, params)]
    blocks = list(content.get("blocks") or [])
    quote_index = next((i for i, block in enumerate(blocks) if block.get("kind") == "quote"), -1)
    compare_index = next((i for i, block in enumerate(blocks) if block.get("kind") == "compare"), -1)
    if quote_index < 0 or compare_index < 0:
        return split_two_column(zones, content, params)
    quote = blocks[quote_index]
    col = zones.body_column
    quote_size = _font_size(params, 17)
    citation_size = _font_size(params, 12)
    gap = max(0.12, 0.18 * float(params.get("gap_scale") or 1.0))
    quote_text = str(quote.get("text") or "")
    citation = str(quote.get("citation") or "")
    quote_h = max(0.5, estimate_text_height(quote_text, col.w * 0.78, quote_size))
    citation_w = col.w * 0.2
    elements.append(_body_box(
        f"blocks.{quote_index}.text", quote_text, col.x, col.y, col.w * 0.78, quote_h,
        size=quote_size, color="primary",
    ))
    if citation:
        citation_h = max(0.5, estimate_text_height(citation, citation_w, citation_size))
        elements.append(_body_box(
            f"blocks.{quote_index}.citation", citation,
            col.x + col.w - citation_w, col.y, citation_w, citation_h,
            size=citation_size, color="muted",
        ))
    start_y = col.y + max(quote_h, 0.5) + gap
    excluded = {f"blocks.{quote_index}.text", f"blocks.{quote_index}.citation"}
    refs = [(ref, text) for ref, text in _ordered_refs(content, params) if ref not in excluded]
    column_count = min(4, max(2, (len(refs) + 3) // 4))
    column_gap = ITEM_GAP * float(params.get("gap_scale") or 1.0)
    column_w = (col.w - column_gap * (column_count - 1)) / column_count
    chunk_size = max(1, (len(refs) + column_count - 1) // column_count)
    # Comparison copy is primary body text, not auxiliary fine print.  Keeping
    # it at the normal readable tier also prevents a "make text larger"
    # request from shrinking former 18pt body boxes during compound fallback.
    item_size = _font_size(params, 15)
    for column_index, chunk_start in enumerate(range(0, len(refs), chunk_size)):
        cursor = start_y
        x = col.x + column_index * (column_w + column_gap)
        for ref, text in refs[chunk_start:chunk_start + chunk_size]:
            h = max(0.5, estimate_text_height(text, column_w, item_size))
            elements.append(_body_box(ref, text, x, cursor, column_w, h, size=item_size))
            cursor += h + gap
    return _highlight(elements, params)


def quote_center(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content, params)]
    indexed_block = next((
        (index, block) for index, block in enumerate(content.get("blocks") or [])
        if block.get("kind") == "quote"
    ), None)
    block_index, block = indexed_block if indexed_block is not None else (-1, None)
    text = str(block.get("text") or "") if block else ""
    if not text:
        return bullet_flow(zones, content, params)
    col = zones.body_column
    w = min(col.w, 9.5)
    x = col.x + (col.w - w) / 2
    quote_size = _font_size(params, 22)
    citation_size = _font_size(params, 14)
    h = max(0.8, estimate_text_height(text, w, quote_size))
    elements.append(
        {
            "kind": "textbox",
            "role": "body",
            "text": text,
            "content_ref": f"blocks.{block_index}.text",
            "x": round(x, 3),
            "y": round(col.y + (col.h - h) / 2, 3),
            "w": round(w, 3),
            "h": round(h, 3),
            "style": {"size": quote_size, "color": "primary", "bold": True},
        }
    )
    citation = str(block.get("citation") or "") if block else ""
    if citation:
        ch = max(0.5, estimate_text_height(citation, w, citation_size))
        elements.append(
            {
                "kind": "textbox",
                "role": "body",
                "text": citation,
                "content_ref": f"blocks.{block_index}.citation",
                "x": round(x, 3),
                "y": round(col.y + (col.h - h) / 2 + h + 0.2, 3),
                "w": round(w, 3),
                "h": round(ch, 3),
                "style": {"size": citation_size, "color": "muted"},
            }
        )
    return _highlight(elements, params)


def agenda_list(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    return bullet_flow(zones, content, params)


def cover_left(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = []
    body = [str(t) for t in (content.get("body") or [])]
    title = str(content.get("title") or "")
    purpose = str(content.get("purpose") or "")
    has_visual = zones.visual_slot is not None
    title_w = (zones.visual_slot.x - zones.content_x - 0.4) if has_visual else zones.canvas.w - zones.content_x - 0.9
    # Cover copy is rebound to the complete canonical ``body`` after a
    # candidate is generated.  The former fixed 0.8in subtitle box was sized
    # from only ``body[:2]`` and then overflowed as soon as the third canonical
    # line was restored.  Stack the real semantic strings using measured
    # heights so cover candidates remain complete at every style tier.
    gap = max(0.16, 0.22 * float(params.get("gap_scale") or 1.0))
    # A Chinese cover title commonly wraps to two lines.  30pt as the recipe
    # base keeps that hierarchy while leaving enough height for the complete
    # three-line teaching lead.  It also avoids an exaggerated >2× title/body
    # ratio; the requested scale still raises the effective title to 33pt for
    # the current moderate polish request.
    title_size = _font_size(params, 30)
    subtitle_size = _font_size(params, 18)
    purpose_size = _font_size(params, 15)
    title_y = 0.72 if has_visual else 1.25
    title_h = max(1.15, estimate_text_height(title, title_w, title_size))
    subtitle_text = "\n".join(body)
    subtitle_h = max(0.75, estimate_text_height(subtitle_text, title_w, subtitle_size)) if body else 0.0
    subtitle_y = title_y + title_h + gap
    purpose_h = max(0.60, estimate_text_height(purpose, title_w, purpose_size)) if purpose else 0.0
    purpose_y = subtitle_y + subtitle_h + (gap if body else 0.0)
    if purpose and has_visual:
        # Keep the closing teaching purpose as a deliberate lower-page anchor.
        # Shrinking this box to its natural text height previously pulled the
        # whole left column into the upper half even though the locked visual
        # continued lower on the right.  That made the complete candidate lose
        # utilization/balance points and fail the no-regression gate.  The
        # anchor remains inside the safe body rail and never stretches text.
        visual_bottom = zones.visual_slot.bottom
        lower_anchor = min(
            zones.body_column.bottom - purpose_h - 0.18,
            max(visual_bottom + 0.28, zones.body_column.y + zones.body_column.h * 0.73),
        )
        purpose_y = max(purpose_y, lower_anchor)
    elements.append(
        {
            "kind": "textbox",
            "role": "title",
            "text": title,
            "content_ref": "title",
            "x": round(zones.content_x, 3),
            "y": round(title_y, 3),
            "w": round(title_w, 3),
            "h": round(title_h, 3),
            "style": {"size": title_size, "color": "primary", "bold": True},
        }
    )
    if body:
        elements.append(
            {
                "kind": "textbox",
                "role": "subtitle",
                "text": subtitle_text,
                "content_ref": "body",
                "x": round(zones.content_x, 3),
                "y": round(subtitle_y, 3),
                "w": round(title_w, 3),
                "h": round(subtitle_h, 3),
                "style": {"size": subtitle_size, "color": "muted"},
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
                "y": round(purpose_y, 3),
                "w": round(title_w, 3),
                "h": round(purpose_h, 3),
                "style": {"size": purpose_size, "color": "primary", "bold": True},
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
    return _highlight(elements, params)


def cover_center(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    return cover_left(zones, content, params)


PRESETS: dict[str, CompileFn] = {
    "bullet_flow": bullet_flow,
    "split_two_column": split_two_column,
    "left_text_right_visual": left_text_right_visual,
    "steps_horizontal": steps_horizontal,
    "compare_columns": compare_columns,
    "quote_compare": quote_compare,
    "quote_center": quote_center,
    "agenda_list": agenda_list,
    "cover_left": cover_left,
    "cover_center": cover_center,
}

PRESET_KEYS = frozenset(PRESETS)
