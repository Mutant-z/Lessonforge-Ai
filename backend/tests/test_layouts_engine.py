import pytest
from app.agent.layouts.metrics import estimate_text_height
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


def test_estimate_text_height_multiline_and_min():
    # 单行 10 个 CJK 字符 @18pt 在 3in 宽框内：每行约可放 int(3/(18/72*0.98))=12 字
    assert estimate_text_height("十个中文字符十个中文字符十个中文字符十个中文字符", 3.0, 18) > 0.6
    assert estimate_text_height("短", 3.0, 18) == 0.6  # 最小高度
    multi = estimate_text_height("一二三\n四五六", 3.0, 18)
    single = estimate_text_height("一二三", 3.0, 18)
    assert multi > single  # 换行增加行数


def test_estimate_text_height_aggregate_box_is_sum_not_max():
    # layout 的 >6 条聚合单框回退需要整框高度 = 各条目高度之和，而非单条最大值。
    # 每条约 2 行（24 个 CJK 字符 @18pt / 3in 宽框，每行 12 字）。
    items = ["十个中文字符" * 4] * 7
    joined = "\n".join(items)
    total = sum(estimate_text_height(item, 3.0, 18) for item in items)
    assert estimate_text_height(joined, 3.0, 18) == total
    assert total > estimate_text_height(items[0], 3.0, 18)  # 求和 > 最大单条


from app.agent.layouts.presets import PRESETS


def _slide(body=None, blocks=None, page_type="concept"):
    return {"page_type": page_type, "title": "核心概念", "purpose": "",
            "body": body or ["第一条正文要点，围绕核心概念展开。", "第二条正文要点，说明适用条件。", "第三条正文要点，给出一个教学例子。"],
            "blocks": blocks or []}


def _invariants(elements, require_vertical_fill=True):
    assert all(e["x"] >= 0 and e["y"] >= 0 and e["x"] + e["w"] <= 13.333 + 1e-6 and e["y"] + e["h"] <= 7.5 + 1e-6 for e in elements), "越界"
    boxes = [(e["x"], e["y"], e["w"], e["h"]) for e in elements if e["kind"] in {"textbox", "note"}]
    for i, (ax, ay, aw, ah) in enumerate(boxes):
        for bx, by, bw, bh in boxes[i + 1:]:
            ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            oy = max(0, min(ay + ah, by + bh) - max(ay, by))
            assert ox * oy <= 1e-6, f"重叠 {i}"
    text_items = [e for e in elements if e["kind"] == "textbox"]
    text_y = [e["y"] for e in text_items if e["content_ref"] != "title"]
    text_bottom = [e["y"] + e["h"] for e in text_items if e["content_ref"] != "title"]
    if text_y and require_vertical_fill:
        assert max(text_bottom) - min(text_y) >= (6.8 - 1.7) * 0.45 - 1e-6, "正文纵向未铺满"
    for e in text_items:
        if e.get("text"):
            from app.agent.layouts.metrics import estimate_text_height
            assert estimate_text_height(e["text"], e["w"], (e.get("style") or {}).get("size", 18)) <= e["h"] * 1.15, "溢出"


def test_bullet_flow_invariants():
    _invariants(PRESETS["bullet_flow"](zones_for("lessonforge_deck_academic", "concept"), _slide(), {}))


def test_split_two_column_invariants():
    _invariants(PRESETS["split_two_column"](zones_for("lessonforge_deck_academic", "concept"), _slide(body=[f"要点 {i}" for i in range(6)]), {}))


def test_steps_horizontal_invariants():
    blocks = [{"kind": "steps", "steps": [
        {"title": "第一步", "detail": "建立概念"},
        {"title": "第二步", "detail": "给出示例"},
        {"title": "第三步", "detail": "迁移应用"},
    ]}]
    _invariants(PRESETS["steps_horizontal"](zones_for("lessonforge_deck_academic", "process"), _slide(blocks=blocks, page_type="process"), {}), require_vertical_fill=False)


def test_steps_horizontal_caps_cards_at_four():
    blocks = [{"kind": "steps", "steps": [
        {"title": f"第 {i} 步", "detail": f"要点 {i}"} for i in range(6)
    ]}]
    elements = PRESETS["steps_horizontal"](zones_for("lessonforge_deck_academic", "process"), _slide(blocks=blocks, page_type="process"), {})
    _invariants(elements, require_vertical_fill=False)
    assert max(e["x"] + e["w"] for e in elements) <= 13.333 + 1e-6
    assert sum(1 for e in elements if e["content_ref"].startswith("blocks.0.steps.")) <= 8


def test_compare_columns_invariants():
    blocks = [{"kind": "compare", "left": {"heading": "传统教学", "items": ["讲授为主", "统一进度"]},
               "right": {"heading": "探究教学", "items": ["任务驱动", "个性化"]}}]
    _invariants(PRESETS["compare_columns"](zones_for("lessonforge_deck_academic", "comparison"), _slide(blocks=blocks, page_type="comparison"), {}), require_vertical_fill=False)


def test_left_text_right_visual_invariants():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=True, visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    _invariants(PRESETS["left_text_right_visual"](z, _slide(), {}))


def test_quote_center_invariants():
    blocks = [{"kind": "quote", "text": "教育的本质意味着一棵树摇动另一棵树。", "citation": "雅斯贝尔斯"}]
    _invariants(PRESETS["quote_center"](zones_for("lessonforge_deck_academic", "concept"), _slide(blocks=blocks), {}), require_vertical_fill=False)


def test_agenda_list_invariants():
    _invariants(PRESETS["agenda_list"](zones_for("lessonforge_deck_academic", "agenda"), _slide(page_type="agenda"), {}))


def test_cover_left_invariants():
    z = zones_for("lessonforge_deck_academic", "cover", has_visual=True, visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    slide = {"page_type": "cover", "title": "课程封面", "purpose": "单元导入", "body": ["目标一", "目标二"], "blocks": []}
    _invariants(PRESETS["cover_left"](z, slide, {}), require_vertical_fill=False)


def test_cover_center_invariants():
    z = zones_for("lessonforge_deck_academic", "cover", has_visual=True, visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    slide = {"page_type": "cover", "title": "课程封面", "purpose": "单元导入", "body": ["目标一", "目标二"], "blocks": []}
    _invariants(PRESETS["cover_center"](z, slide, {}), require_vertical_fill=False)


from app.agent.layouts.engine import compile_layout, normalize_layout_params


def test_compile_layout_unknown_type_falls_back_to_bullet():
    slide = _slide()
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "not_a_preset", "style": {}})
    assert out["layout_type"] == "bullet_flow"
    assert out["slide_id"] == "S01"
    assert out["elements"]


def test_compile_layout_aliases_old_names():
    slide = _slide()
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "title_and_body", "style": {}})
    assert out["layout_type"] == "bullet_flow"


def test_normalize_layout_params_bounds():
    assert normalize_layout_params({"gap_scale": 5.0})["gap_scale"] == 1.5
    assert normalize_layout_params({"gap_scale": 0.1})["gap_scale"] == 0.8
    assert normalize_layout_params({})["font_tier"] == "default"
