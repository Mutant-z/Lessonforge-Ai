from dataclasses import dataclass

SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5
MARGIN_Y = 1.7
SAFE_CONTENT_BOTTOM = 6.8
TITLE_RAIL_Y = 0.55
TITLE_RAIL_H = 0.8
# 模板安全导轨左侧偏移：统一由 TEMPLATE_DECOR 装饰几何推导（与 layout._content_start_x 一致）。
DEFAULT_CONTENT_X = 0.65


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class LayoutZones:
    template_id: str
    page_type: str
    content_x: float
    title_rail: Rect
    body_column: Rect
    visual_slot: Rect | None

    @property
    def canvas(self) -> Rect:
        return Rect(0, 0, SLIDE_WIDTH, SLIDE_HEIGHT)


def _template_content_x(template_id: str, page_type: str) -> float:
    from app.renderers.presentation_builder import template_content_start_x

    return template_content_start_x(template_id, page_type)


def zones_for(
    template_id: str,
    page_type: str = "concept",
    has_visual: bool = False,
    visual_region: dict | None = None,
) -> LayoutZones:
    content_x = _template_content_x(template_id, page_type)
    title_rail = Rect(content_x, TITLE_RAIL_Y, SLIDE_WIDTH - content_x - 0.78, TITLE_RAIL_H)
    visual_slot = None
    body_right = SLIDE_WIDTH - content_x - 0.78
    if has_visual:
        raw = visual_region or {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}
        try:
            vx = max(0.0, float(raw.get("x") or 7.4))
            vy = max(0.0, float(raw.get("y") or 1.7))
            vw = max(0.1, float(raw.get("w") or raw.get("width") or 5.2))
            vh = max(0.1, float(raw.get("h") or raw.get("height") or 4.2))
        except (TypeError, ValueError):
            vx, vy, vw, vh = 7.4, 1.7, 5.2, 4.2
        vx = max(vx, 0.65)
        vy = max(vy, 1.15)
        vw = min(vw, SLIDE_WIDTH - 0.65 - vx)
        vh = min(vh, SLIDE_HEIGHT - 1.15 - vy)
        visual_slot = Rect(vx, vy, max(0.1, vw), max(0.1, vh))
        if visual_slot.x > content_x + 1:
            body_right = visual_slot.x - 0.4
    body_column = Rect(content_x, MARGIN_Y, max(3.2, body_right - content_x), SAFE_CONTENT_BOTTOM - MARGIN_Y)
    return LayoutZones(template_id, page_type, content_x, title_rail, body_column, visual_slot)
