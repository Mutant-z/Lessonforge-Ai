#!/usr/bin/env python3
"""重建 templates/PPT_template 为通用微课模板，并同步 templates/ppt_decks/deck_slots.json。

背景：原 6 套成品模板是按主题预制（学术科研/AI/商务/卡通/国学/智慧课堂），自带英文标签、
研究/公式版式与主题内容，通用中文微课内容填入会溢出且语义错配。
本脚本用统一的"通用微课版式"重建 6 套模板（仅配色不同），槽位宽松并支持文字自动缩放，
任意课程内容填入都能整洁呈现。

用法：在仓库根目录执行  .venv/bin/python scripts/build_generic_decks.py
"""
import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "templates" / "pptx" / "catalog.json"
DECK_DIR = ROOT / "templates" / "PPT_template"
SLOTS_PATH = ROOT / "templates" / "ppt_decks" / "deck_slots.json"

EMU_PER_INCH = 914400
CANVAS_W, CANVAS_H = 13.333, 7.5

ROLE_ORDER = [
    "cover", "intro", "objectives", "knowledge_map", "knowledge_intro",
    "core_1", "core_2", "core_3", "core_4", "case_study",
    "discussion", "summary", "assessment", "assignment", "end",
]

# 每个角色的槽位几何：(x, y, w, h, 字号, 颜色键, 是否加粗, 对齐, 是否斜体)
# 每个槽位的 (x, y) 即模板中文本框的左上角，也是 deck_slots.json 的锚点。
# 颜色键对应 catalog.json 的 palette。
ROLE_GEOMETRY: dict[str, dict] = {
    "cover": {
        "full_bleed": True,
        "title": (1.0, 2.0, 11.3, 1.9, 40, "on_primary", True, "left", False),
        "content": [
            (1.0, 4.1, 11.3, 0.9, 20, "on_primary", False, "left", False),
        ],
    },
    "intro": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (0.65, 1.8, 12.0, 1.05, 18, "primary", True, "left", False),
            (0.65, 3.05, 12.0, 0.62, 16, "text", False, "left", False),
            (0.65, 3.77, 12.0, 0.62, 16, "text", False, "left", False),
            (0.65, 4.49, 12.0, 0.62, 16, "text", False, "left", False),
            (0.65, 5.21, 12.0, 0.62, 16, "text", False, "left", False),
            (0.65, 5.93, 12.0, 0.62, 16, "text", False, "left", False),
        ],
    },
    "objectives": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (0.65, 1.9, 12.0, 0.7, 18, "primary", True, "left", False),
            (0.65, 2.8, 12.0, 0.8, 16, "text", False, "left", False),
            (0.65, 3.75, 12.0, 0.8, 16, "text", False, "left", False),
            (0.65, 4.7, 12.0, 0.8, 16, "text", False, "left", False),
            (0.65, 5.65, 12.0, 0.8, 16, "text", False, "left", False),
        ],
    },
    "knowledge_map": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (0.65, 1.9, 12.0, 0.7, 18, "primary", True, "left", False),
            (0.65, 2.85, 5.9, 0.75, 16, "text", False, "left", False),
            (6.85, 2.85, 5.9, 0.75, 16, "text", False, "left", False),
            (0.65, 3.8, 5.9, 0.75, 16, "text", False, "left", False),
            (6.85, 3.8, 5.9, 0.75, 16, "text", False, "left", False),
        ],
    },
    "knowledge_intro": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (0.65, 1.8, 12.0, 1.0, 18, "primary", True, "left", False),
            (0.65, 3.0, 5.9, 0.65, 16, "text", False, "left", False),
            (6.85, 3.0, 5.9, 0.65, 16, "text", False, "left", False),
            (0.65, 3.8, 5.9, 0.65, 16, "text", False, "left", False),
            (6.85, 3.8, 5.9, 0.65, 16, "text", False, "left", False),
            (0.65, 4.6, 5.9, 0.65, 16, "text", False, "left", False),
            (6.85, 4.6, 5.9, 0.65, 16, "text", False, "left", False),
        ],
    },
    "core_1": {"_core": True, "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False), "content": [
        (0.65, 1.8, 3.5, 0.5, 14, "primary", True, "left", False),
        (0.65, 2.4, 12.0, 0.8, 18, "text", True, "left", False),
        (0.65, 3.4, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.18, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.96, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 5.74, 12.0, 0.65, 16, "text", False, "left", False),
    ]},
    "core_2": {"_core": True, "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False), "content": [
        (0.65, 1.8, 3.5, 0.5, 14, "primary", True, "left", False),
        (0.65, 2.4, 12.0, 0.8, 18, "text", True, "left", False),
        (0.65, 3.4, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.18, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.96, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 5.74, 12.0, 0.65, 16, "text", False, "left", False),
    ]},
    "core_3": {"_core": True, "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False), "content": [
        (0.65, 1.8, 3.5, 0.5, 14, "primary", True, "left", False),
        (0.65, 2.4, 12.0, 0.8, 18, "text", True, "left", False),
        (0.65, 3.4, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.18, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.96, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 5.74, 12.0, 0.65, 16, "text", False, "left", False),
    ]},
    "core_4": {"_core": True, "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False), "content": [
        (0.65, 1.8, 3.5, 0.5, 14, "primary", True, "left", False),
        (0.65, 2.4, 12.0, 0.8, 18, "text", True, "left", False),
        (0.65, 3.4, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.18, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 4.96, 12.0, 0.65, 16, "text", False, "left", False),
        (0.65, 5.74, 12.0, 0.65, 16, "text", False, "left", False),
    ]},
    "case_study": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (0.65, 1.85, 2.85, 1.15, 16, "text", True, "left", False),
            (3.75, 1.85, 2.85, 1.15, 16, "text", True, "left", False),
            (6.85, 1.85, 2.85, 1.15, 16, "text", True, "left", False),
            (9.95, 1.85, 2.85, 1.15, 16, "text", True, "left", False),
            (0.65, 3.4, 3.0, 0.5, 14, "primary", True, "left", False),
            (0.65, 4.0, 12.0, 1.2, 16, "text", False, "left", False),
        ],
    },
    "discussion": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (0.65, 1.95, 12.0, 0.9, 18, "primary", True, "left", False),
            (0.65, 3.15, 12.0, 0.85, 16, "text", False, "left", False),
            (0.65, 4.2, 12.0, 0.85, 16, "text", False, "left", False),
            (0.65, 5.25, 12.0, 0.85, 16, "text", False, "left", False),
        ],
    },
    "summary": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (0.65, 1.8, 12.0, 0.6, 17, "primary", True, "left", False),
            (0.65, 2.55, 5.9, 0.6, 16, "text", False, "left", False),
            (6.85, 2.55, 5.9, 0.6, 16, "text", False, "left", False),
            (0.65, 3.3, 5.9, 0.6, 16, "text", False, "left", False),
            (6.85, 3.3, 5.9, 0.6, 16, "text", False, "left", False),
            (0.65, 4.05, 5.9, 0.6, 16, "text", False, "left", False),
            (6.85, 4.05, 5.9, 0.6, 16, "text", False, "left", False),
            (0.65, 4.8, 5.9, 0.6, 16, "text", False, "left", False),
            (6.85, 4.8, 5.9, 0.6, 16, "text", False, "left", False),
            (0.65, 5.85, 12.0, 0.75, 15, "muted", False, "left", True),
        ],
    },
    "assessment": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (1.0, 1.85, 11.3, 0.5, 15, "text", True, "left", False),
            (1.0, 2.4, 11.3, 0.45, 14, "muted", False, "left", False),
            (1.0, 3.3, 11.3, 0.5, 15, "text", True, "left", False),
            (1.0, 3.85, 11.3, 0.45, 14, "muted", False, "left", False),
            (1.0, 4.75, 11.3, 0.5, 15, "text", True, "left", False),
            (1.0, 5.3, 11.3, 0.45, 14, "muted", False, "left", False),
            (1.0, 6.2, 11.3, 0.4, 12, "muted", False, "left", True),
        ],
    },
    "assignment": {
        "title": (0.6, 0.5, 12.1, 0.85, 28, "primary", True, "left", False),
        "content": [
            (1.0, 1.9, 6.0, 0.5, 14, "primary", True, "left", False),
            (1.0, 2.5, 11.3, 1.0, 17, "text", True, "left", False),
            (1.0, 3.95, 5.5, 0.75, 16, "text", False, "left", False),
            (6.8, 3.95, 5.5, 0.75, 16, "text", False, "left", False),
            (1.0, 4.85, 5.5, 0.75, 16, "text", False, "left", False),
            (6.8, 4.85, 5.5, 0.75, 16, "text", False, "left", False),
        ],
    },
    "end": {
        "full_bleed": True,
        "title": (1.0, 2.2, 11.3, 1.3, 34, "on_primary", True, "left", False),
        "content": [
            (1.0, 3.8, 11.3, 0.9, 20, "on_primary", False, "left", False),
        ],
    },
}


def hex_color(value: str) -> RGBColor:
    return RGBColor.from_string(value.lstrip("#"))


def add_rect(slide, x, y, w, h, color):
    from pptx.enum.shapes import MSO_SHAPE
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def add_oval(slide, x, y, w, h, color):
    from pptx.enum.shapes import MSO_SHAPE
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def add_textbox(slide, spec, colors, fonts, base_size=None, page_number=None):
    x, y, w, h, size, color_key, bold, align, italic = spec
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    tf = box.text_frame
    tf.margin_left = tf.margin_right = Inches(0.02)
    tf.margin_top = tf.margin_bottom = Inches(0.01)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = tf.paragraphs[0]
    paragraph.alignment = {
        "left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT,
    }[align]
    run = paragraph.add_run()
    run.text = ""
    run.font.name = fonts["body"] if "latin" not in color_key else fonts["body"]
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = colors[color_key]
    return box


def add_content_page(prs, blank_layout, role, spec, colors, fonts, index):
    slide = prs.slides.add_slide(blank_layout)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = colors["background"]
    # 左侧品牌色条
    add_rect(slide, 0, 0, 0.13, CANVAS_H, colors["primary"])
    # 底部页脚与页码
    brand = slide.shapes.add_textbox(Inches(0.5), Inches(7.02), Inches(4), Inches(0.3))
    brand.text_frame.paragraphs[0].add_run().text = "LESSONFORGE 微课"
    _style_run(brand, colors["muted"], fonts, 9, False, PP_ALIGN.LEFT)
    page = slide.shapes.add_textbox(Inches(11.6), Inches(7.02), Inches(1.2), Inches(0.3))
    page.text_frame.paragraphs[0].add_run().text = f"{index + 1:02d}"
    _style_run(page, colors["muted"], fonts, 10, True, PP_ALIGN.RIGHT)
    # 标题
    add_textbox(slide, spec["title"], colors, fonts)
    # 标题下强调短条
    add_rect(slide, 0.62, 1.42, 1.35, 0.09, colors["secondary"])
    # 内容槽位
    for content in spec["content"]:
        add_textbox(slide, content, colors, fonts)
    return slide


def add_cover_end_page(prs, blank_layout, role, spec, colors, fonts, index):
    slide = prs.slides.add_slide(blank_layout)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = colors["primary"]
    if role == "cover":
        add_oval(slide, 9.4, -1.6, 5.0, 5.0, colors["secondary"])
        add_rect(slide, 0, 0, 0.16, CANVAS_H, colors["secondary"])
    else:
        add_oval(slide, -1.6, 4.8, 5.0, 5.0, colors["secondary"])
    brand = slide.shapes.add_textbox(Inches(0.95), Inches(6.85), Inches(6), Inches(0.4))
    brand.text_frame.paragraphs[0].add_run().text = "LESSONFORGE 微课"
    _style_run(brand, colors["on_primary"], fonts, 10, False, PP_ALIGN.LEFT)
    add_textbox(slide, spec["title"], colors, fonts)
    for content in spec["content"]:
        add_textbox(slide, content, colors, fonts)
    return slide


def _style_run(shape, color, fonts, size, bold, align):
    paragraph = shape.text_frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.runs[0]
    run.font.name = fonts["body"]
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def build_deck(entry: dict) -> None:
    palette = entry["palette"]
    fonts = entry["typography"]
    colors = {key: hex_color(value) for key, value in palette.items()}
    deck_name = Path(entry["file"]).name

    prs = Presentation()
    prs.slide_width = Emu(int(CANVAS_W * EMU_PER_INCH))
    prs.slide_height = Emu(int(CANVAS_H * EMU_PER_INCH))
    blank_layout = prs.slide_layouts[6]
    for index, role in enumerate(ROLE_ORDER):
        spec = ROLE_GEOMETRY[role]
        if spec.get("full_bleed"):
            add_cover_end_page(prs, blank_layout, role, spec, colors, fonts, index)
        else:
            add_content_page(prs, blank_layout, role, spec, colors, fonts, index)
    out = DECK_DIR / deck_name
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)
    print(f"  rebuilt {deck_name}")


def write_deck_slots() -> None:
    roles = {}
    for role in ROLE_ORDER:
        spec = ROLE_GEOMETRY[role]
        title_x, title_y = spec["title"][0], spec["title"][1]
        roles[role] = {
            "title": {"x": title_x, "y": title_y},
            "content": [{"x": item[0], "y": item[1]} for item in spec["content"]],
        }
    payload = {
        "version": "2.0.0",
        "role_order": ROLE_ORDER,
        "default_tol": 0.35,
        "roles": roles,
    }
    SLOTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {SLOTS_PATH.name} (roles={len(roles)})")


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    print(f"rebuilding generic decks from {CATALOG_PATH.name}")
    for entry in catalog["templates"]:
        build_deck(entry)
    write_deck_slots()


if __name__ == "__main__":
    main()
