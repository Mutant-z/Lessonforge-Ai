"""基于真实 PPT 模板（deck）的槽位填字渲染器。

加载 templates/PPT_template/*.pptx 成品模板，按 templates/ppt_decks/deck_slots.json
的角色+位置锚点，把生成内容填入对应文本形状，保留模板的视觉设计（装饰/图表/配图）。
"""
import json
import math
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu, Pt

SLOTS_PATH = Path(__file__).resolve().parents[3] / "templates" / "ppt_decks" / "deck_slots.json"
DECK_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates" / "PPT_template"
EMU_PER_INCH = 914400


def _load_slots() -> dict:
    return json.loads(SLOTS_PATH.read_text(encoding="utf-8"))


def _find_shape(slide, anchor: dict, tol_inches: float):
    """返回最接近锚点 (x,y) 英寸坐标的文本形状，无则 None。

    只匹配文本框/占位符，跳过色块、圆、图片等装饰形状，避免把内容填进装饰元素。
    """
    tx = anchor["x"] * EMU_PER_INCH
    ty = anchor["y"] * EMU_PER_INCH
    best = None
    best_dist = None
    for shape in slide.shapes:
        if shape.left is None or shape.top is None or not shape.has_text_frame:
            continue
        if shape.shape_type != MSO_SHAPE_TYPE.TEXT_BOX and not shape.is_placeholder:
            continue
        dist = abs(shape.left - tx) + abs(shape.top - ty)
        if best_dist is None or dist < best_dist:
            best, best_dist = shape, dist
    if best is not None and best_dist <= tol_inches * EMU_PER_INCH * 2:
        return best
    return None


def _fit_font_size(shape, text: str, base_size: float) -> float:
    """按文本框尺寸估算并收缩字号，避免长文本溢出。"""
    width_in = (shape.width or Emu(int(6 * EMU_PER_INCH))) / EMU_PER_INCH
    height_in = (shape.height or Emu(int(1 * EMU_PER_INCH))) / EMU_PER_INCH
    size = float(base_size)
    while size > 8:
        # 中文字符宽度约等于字号；按整串字符估算（拉丁字符偏保守）
        char_w = size / 72.0 * 0.98
        chars_per_line = max(1, int(width_in / char_w))
        lines = 0
        for segment in text.split("\n"):
            lines += max(1, math.ceil(len(segment) / chars_per_line))
        needed_height = lines * size / 72.0 * 1.28
        if needed_height <= height_in * 0.98:
            break
        size -= 1
    return size


def _set_shape_text(shape, value: str):
    """写入文本并保留首段首个 run 的字体格式，清除多余 run/段落，并收缩字号防止溢出。"""
    if not shape.has_text_frame:
        return
    frame = shape.text_frame
    paragraph = frame.paragraphs[0]
    base_size = 16.0
    if paragraph.runs:
        first_run = paragraph.runs[0]
        if first_run.font.size:
            base_size = float(first_run.font.size.pt)
        first_run.text = str(value)
        for run in paragraph.runs[1:]:
            run._r.getparent().remove(run._r)
    else:
        paragraph.text = str(value)
    for extra in frame.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    frame.word_wrap = True
    size = _fit_font_size(shape, str(value), base_size)
    if paragraph.runs:
        paragraph.runs[0].font.size = Pt(size)
    else:
        paragraph.font.size = Pt(size)


def render_deck(template_path: Path, slides: list[dict], output: Path) -> Path:
    """把 slides 内容填入模板 deck，输出新 .pptx。

    slides[i] 对应模板第 i+1 页（i 与 role_order 对齐）；每页填 title 槽 +
    content 槽（顺序取自 slides[i]["body"]）。装饰形状（页码/页脚/英文标签/图表）
    不在清单中，保持模板原样。
    """
    slots = _load_slots()
    role_order = slots["role_order"]
    roles = slots["roles"]
    tol = slots.get("default_tol", 0.35)
    presentation = Presentation(str(template_path))
    for index, slide in enumerate(slides[: len(presentation.slides)]):
        if index >= len(role_order):
            break
        role = role_order[index]
        spec = roles.get(role)
        if not spec:
            continue
        template_slide = presentation.slides[index]
        title_shape = _find_shape(template_slide, spec["title"], tol)
        if title_shape is not None:
            _set_shape_text(title_shape, str(slide.get("title") or ""))
        body = [str(value) for value in (slide.get("body") or [])]
        for anchor_index, anchor in enumerate(spec["content"]):
            if anchor_index >= len(body):
                break
            shape = _find_shape(template_slide, anchor, tol)
            if shape is not None:
                _set_shape_text(shape, body[anchor_index])
    output.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(output)
    return output


def deck_template_path(template_id: str) -> Path:
    """把模板 id 解析为 .pptx 路径（如 'academic' -> templates/PPT_template/Academic_Template.pptx）。"""
    candidates = [
        DECK_TEMPLATES_DIR / f"{template_id}.pptx",
        DECK_TEMPLATES_DIR / f"{template_id}_Template.pptx",
        DECK_TEMPLATES_DIR / f"{template_id.capitalize()}_Template.pptx",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # 按文件前缀宽松匹配（忽略大小写/下划线）
    for candidate in DECK_TEMPLATES_DIR.glob("*.pptx"):
        if candidate.stem.lower().replace("_", "") == template_id.lower().replace("_", ""):
            return candidate
    raise FileNotFoundError(f"未找到 deck 模板：{template_id}")
