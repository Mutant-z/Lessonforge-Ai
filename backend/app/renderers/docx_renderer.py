from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


def _configure(doc: Document, title: str, version: str):
    section = doc.sections[0]
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    header = section.header.paragraphs[0]
    header.text = f"LessonForge AI · {title} · {version}"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("第 ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run._r.addnext(fld)
    footer.add_run(" 页")
    styles = doc.styles
    styles["Normal"].font.name = "Microsoft YaHei"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    styles["Normal"].font.size = Pt(10.5)


def render_markdown_docx(title: str, markdown: str, output: Path, version: str = "V1") -> Path:
    doc = Document()
    _configure(doc, title, version)
    doc.add_heading(title, 0)
    doc.add_paragraph(f"版本：{version}")
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith("- "):
            doc.add_paragraph(stripped[2:], style="List Bullet")
        elif stripped.startswith("> "):
            paragraph = doc.add_paragraph(stripped[2:])
            paragraph.style = "Quote"
        else:
            doc.add_paragraph(stripped.replace("**", ""))
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    Document(output)
    return output


def render_exercise_docx(title: str, content: dict, output: Path, include_answers: bool) -> Path:
    doc = Document()
    _configure(doc, title, "V1")
    doc.add_heading(title, 0)
    for item in content.get("items", []):
        doc.add_heading(f"{item['id']} · {item['stem']}", level=2)
        for option in item.get("options", []):
            doc.add_paragraph(option)
        if include_answers:
            doc.add_paragraph(f"答案：{'、'.join(item.get('correct_answers', []))}")
            doc.add_paragraph(f"解析：{item.get('explanation', '')}")
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    Document(output)
    return output

