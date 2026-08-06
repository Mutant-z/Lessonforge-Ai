"""PresentationBuilder 动态渲染器单测：坐标/元素/round-trip/主题应用。"""
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Emu

from app.renderers.presentation_builder import PresentationBuilder, EMU_PER_INCH

TEMPLATE = "lessonforge_deck_academic"


@pytest.mark.asyncio
async def test_builder_creates_slides_and_elements():
    builder = PresentationBuilder(TEMPLATE)
    slide_id = builder.create_slide("objectives", "本课学习目标", "bullet", "目标")
    assert slide_id == "S01"
    element_id = builder.add_textbox(slide_id, "要点一", 0.7, 1.8, 5.0, 1.0, style={"size": 18, "color": "text"})
    assert element_id.startswith("E")
    builder.add_shape(slide_id, "rect", 0.2, 0.2, 1.0, 1.0, fill="primary")
    builder.move_element(slide_id, element_id, 1.0, 2.0)
    builder.resize_element(slide_id, element_id, 6.0, 1.2)
    builder.delete_element(slide_id, element_id)
    assert len(builder.get_slide(slide_id)["elements"]) == 1


@pytest.mark.asyncio
async def test_builder_render_produces_valid_pptx_with_exact_coordinates(tmp_path):
    builder = PresentationBuilder(TEMPLATE)
    slide_id = builder.create_slide("objectives", "本课学习目标", "bullet", "目标")
    builder.add_textbox(slide_id, "要点一", 1.0, 2.0, 5.0, 1.0, style={"size": 18, "color": "text"})
    output = Path(tmp_path) / "deck.pptx"
    builder.render(output)
    prs = Presentation(str(output))
    assert len(prs.slides) == 1
    shapes = list(prs.slides[0].shapes)
    text_shapes = [shape for shape in shapes if shape.has_text_frame and shape.text_frame.text == "要点一"]
    assert text_shapes
    box = text_shapes[0]
    assert box.left == Emu(int(1.0 * EMU_PER_INCH))
    assert box.top == Emu(int(2.0 * EMU_PER_INCH))
    assert box.width == Emu(int(5.0 * EMU_PER_INCH))


@pytest.mark.asyncio
async def test_builder_to_ppt_content_round_trip():
    content = {
        "theme": TEMPLATE,
        "slides": [
            {"id": "S01", "page_type": "cover", "title": "浮力原理", "purpose": "p", "body": ["初中物理"],
             "layout": "cover", "visual_suggestion": "封面留白大标题", "speaker_notes": "开场引入课程主题。",
             "duration_seconds": 30, "blocks": []},
            {"id": "S02", "page_type": "objectives", "title": "本课学习目标", "purpose": "p", "body": ["完成本节后能够说明浮力"],
             "layout": "bullet", "visual_suggestion": "编号列表", "speaker_notes": "逐条说明学习目标。",
             "duration_seconds": 60, "blocks": []},
        ],
    }
    builder = PresentationBuilder().from_ppt_content(content)
    out = builder.to_ppt_content()
    assert out["theme"] == TEMPLATE
    assert len(out["slides"]) == 2
    assert out["slides"][0]["title"] == "浮力原理"
    assert out["slides"][0]["duration_seconds"] == 30
    assert out["slides"][1]["duration_seconds"] == 60


@pytest.mark.asyncio
async def test_apply_template_switches_design_system():
    builder = PresentationBuilder(TEMPLATE)
    before = builder.design_system["id"]
    builder.apply_template("lessonforge_deck_smart_ai")
    assert builder.design_system["id"] == "lessonforge_deck_smart_ai"
    assert builder.design_system["palette"]["primary"] == "#5B3DF5"
    assert before == TEMPLATE


def test_geometry_report_lists_elements():
    builder = PresentationBuilder(TEMPLATE)
    slide_id = builder.create_slide("concept", "标题", "bullet")
    builder.add_textbox(slide_id, "正文", 0.7, 1.8, 5.0, 1.0)
    report = builder.geometry_report()
    assert len(report) == 1
    assert report[0]["slide_id"] == slide_id
    assert report[0]["x"] == 0.7
