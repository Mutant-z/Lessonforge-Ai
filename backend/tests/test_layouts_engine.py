import pytest
from app.agent.layouts.zones import LayoutZones, zones_for


def test_academic_content_page_zones():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=False)
    assert z.content_x == 2.2
    assert z.title_rail.y == 0.55
    assert z.body_column.y == 1.7
    assert z.body_column.bottom == 6.8
    # 无视觉槽时正文列右缘 = 画布宽 - content_x - 0.78
    assert z.body_column.right == pytest.approx(13.333 - 2.2 - 0.78)
    assert z.visual_slot is None


def test_smart_ai_cover_zones_content_x():
    assert zones_for("lessonforge_deck_smart_ai", "cover", has_visual=False).content_x == 2.95
    assert zones_for("lessonforge_deck_smart_ai", "concept", has_visual=False).content_x == 2.45


def test_visual_slot_narrows_body_column():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=True,
                  visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    assert z.visual_slot is not None
    assert z.body_column.right == pytest.approx(7.4 - 0.4)
