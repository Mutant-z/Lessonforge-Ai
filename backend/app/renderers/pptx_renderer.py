from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

BLUE = RGBColor(0x00, 0x2F, 0xA7)
INK = RGBColor(0x16, 0x1A, 0x22)
GRAY = RGBColor(0x64, 0x6B, 0x78)


def render_pptx(title: str, content: dict, output: Path) -> Path:
    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    for index, item in enumerate(content.get("slides", []), 1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        background = slide.background.fill
        background.solid()
        background.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        rail = slide.shapes.add_shape(1, Inches(.55), Inches(.55), Inches(.08), Inches(6.4))
        rail.fill.solid(); rail.fill.fore_color.rgb = BLUE; rail.line.fill.background()
        num = slide.shapes.add_textbox(Inches(.82), Inches(.55), Inches(1.0), Inches(.5))
        run = num.text_frame.paragraphs[0].add_run(); run.text = f"{index:02d}"; run.font.name = "Arial"; run.font.size = Pt(18); run.font.bold = True; run.font.color.rgb = BLUE
        title_box = slide.shapes.add_textbox(Inches(1.85), Inches(.75), Inches(10.5), Inches(1.0))
        p = title_box.text_frame.paragraphs[0]; p.text = item.get("title", ""); p.font.name = "Microsoft YaHei"; p.font.size = Pt(34); p.font.bold = True; p.font.color.rgb = INK
        body_box = slide.shapes.add_textbox(Inches(1.9), Inches(2.0), Inches(9.7), Inches(4.5))
        frame = body_box.text_frame; frame.word_wrap = True
        for body_index, text in enumerate(item.get("body", [])):
            p = frame.paragraphs[0] if body_index == 0 else frame.add_paragraph()
            p.text = text; p.font.name = "Microsoft YaHei"; p.font.size = Pt(22); p.font.color.rgb = INK; p.space_after = Pt(18)
        footer = slide.shapes.add_textbox(Inches(10.7), Inches(6.85), Inches(1.7), Inches(.3))
        p = footer.text_frame.paragraphs[0]; p.text = item.get("id", f"S{index:02d}"); p.alignment = PP_ALIGN.RIGHT; p.font.name = "Arial"; p.font.size = Pt(10); p.font.color.rgb = GRAY
        notes = slide.notes_slide.notes_text_frame
        notes.text = item.get("speaker_notes", "")
    output.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(output)
    Presentation(output)
    return output

