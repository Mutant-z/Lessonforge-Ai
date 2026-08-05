import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.artifact import PPTContent

KNOWLEDGE_PATH = Path(__file__).resolve().parents[3] / "templates" / "ppt_design" / "knowledge.json"
REQUIRED_SECTIONS = {
    "version", "design_principles", "page_type_guidance", "density_limits",
    "layout_library", "visual_suggestion_guidelines", "diagram_guidance", "quality_checklist",
    "ppt_skills",
}
DENSITY_LIMIT_KEYS = ("title_chars", "body_chars", "body_items", "item_chars", "speaker_notes_chars")


@lru_cache(maxsize=1)
def load_ppt_design_knowledge() -> dict[str, Any]:
    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    if not knowledge.get("version") or not REQUIRED_SECTIONS.issubset(knowledge):
        raise RuntimeError("PPT 设计知识库缺少必要区块")
    limits = knowledge["density_limits"]
    if any(not isinstance(limits.get(key), int) or limits[key] <= 0 for key in DENSITY_LIMIT_KEYS):
        raise RuntimeError("PPT 设计知识库密度上限无效")
    if not isinstance(knowledge["layout_library"], dict) or not knowledge["layout_library"]:
        raise RuntimeError("PPT 设计知识库缺少版式库")
    return knowledge


_THEME_HEADING_BLACKLIST = {"学习目标", "核心概念", "本课小结", "应用步骤", "课堂练习", "课堂总结"}
_ANTI_PATTERN_TERMS = {
    "下划线": "标题下划线属于典型 AI 装饰痕迹，请使用空白分隔",
    "装饰条": "边缘装饰条属于 AI 填充痕迹，请使用纯色卡片或底框隔离",
    "侧边线": "侧边彩色线条不推荐，推荐使用背景微调",
    "彩条": "避免使用彩色装饰边框",
    "米黄": "避免默认使用暖色/米黄背景，推荐纯白或品牌色",
}
_MIN_TITLE_CHARS = 4
_MIN_VISUAL_SUGGESTION_CHARS = 10


def _block_text_units(blocks: list[dict]) -> tuple[list[str], int]:
    """将 blocks 展平为文本单元列表与文本块计数，供密度规则校验。"""
    units: list[str] = []
    text_block_count = 0
    for block in blocks:
        kind = block.get("kind")
        contributed: list[str] = []
        if kind == "lead":
            contributed = [str(block.get("text") or ""), str(block.get("sub") or "")]
        elif kind == "bullets":
            contributed = [str(item.get("text") or "") for item in (block.get("items") or [])]
        elif kind == "steps":
            for step in block.get("steps") or []:
                contributed.append(str(step.get("title") or ""))
                detail = step.get("detail")
                if detail:
                    contributed.append(str(detail))
        elif kind == "compare":
            for column in (block.get("left"), block.get("right")):
                if not column:
                    continue
                if column.get("heading"):
                    contributed.append(str(column["heading"]))
                contributed.extend(str(value) for value in (column.get("items") or []))
        elif kind == "quote":
            contributed = [str(block.get("text") or ""), str(block.get("citation") or "")]
        elif kind == "visual":
            if block.get("caption"):
                contributed = [str(block["caption"])]
        elif kind == "note":
            contributed = [str(block.get("text") or "")]
        contributed = [unit for unit in contributed if unit]
        if contributed:
            text_block_count += 1
            units.extend(contributed)
    return units, text_block_count


@dataclass
class RuleViolation:
    slide_id: str
    rule_id: str
    message: str


def check_ppt_against_knowledge(content: dict | PPTContent) -> list[RuleViolation]:
    knowledge = load_ppt_design_knowledge()
    limits = knowledge["density_limits"]
    library = knowledge["layout_library"]
    page_guidance = knowledge["page_type_guidance"]
    slides = content["slides"] if isinstance(content, dict) else content.slides
    violations: list[RuleViolation] = []
    for slide in slides:
        item = slide if isinstance(slide, dict) else slide.model_dump()
        slide_id = str(item["id"])
        page_type = item.get("page_type", "")
        title = str(item.get("title") or "")
        body = [str(value) for value in (item.get("body") or [])]
        layout = str(item.get("layout") or "")
        suggestion = str(item.get("visual_suggestion") or "")
        notes = str(item.get("speaker_notes") or "")
        duration = item.get("duration_seconds") or 0

        if page_type not in page_guidance:
            violations.append(RuleViolation(slide_id, "page_type.unknown", f"未知页面类型：{page_type}"))
            continue
        for term, reason in _ANTI_PATTERN_TERMS.items():
            if term in suggestion:
                violations.append(RuleViolation(
                    slide_id, "visual.anti_pattern",
                    f"visual_suggestion 触发设计反模式黑名单（\"{term}\"）：{reason}"
                ))
        for index, item_text in enumerate(body, 1):
            if item_text.strip().startswith(("•", "-", "*")):
                violations.append(RuleViolation(
                    slide_id, "body.bullet_hardcoded",
                    f"第 {index} 条正文包含硬编码符号 \"{item_text[0]}\"，物理渲染时会导致双重圆点"
                ))
        if page_type != "cover" and (len(title) < _MIN_TITLE_CHARS or title in _THEME_HEADING_BLACKLIST):
            violations.append(RuleViolation(slide_id, "title.conclusion", "标题需为结论式措辞而非主题式措辞"))
        elif len(title) > limits["title_chars"]:
            violations.append(RuleViolation(
                slide_id, "density.title_chars",
                f"标题 {len(title)} 字超过上限 {limits['title_chars']} 字",
            ))
        blocks = item.get("blocks") or []
        if blocks:
            block_units, text_block_count = _block_text_units(blocks)
            if text_block_count > limits["body_items"]:
                violations.append(RuleViolation(
                    slide_id, "density.body_items",
                    f"文本块 {text_block_count} 个超过上限 {limits['body_items']} 个",
                ))
            total_chars = sum(len(unit) for unit in block_units)
            if total_chars > limits["body_chars"]:
                violations.append(RuleViolation(
                    slide_id, "density.body_chars",
                    f"内容块合计 {total_chars} 字超过上限 {limits['body_chars']} 字",
                ))
            for index, unit in enumerate(block_units, 1):
                if len(unit) > limits["item_chars"]:
                    violations.append(RuleViolation(
                        slide_id, "density.item_chars",
                        f"第 {index} 个文本单元 {len(unit)} 字超过单条上限 {limits['item_chars']} 字",
                    ))
            for block in blocks:
                if block.get("kind") == "steps" and len(block.get("steps") or []) > 4:
                    violations.append(RuleViolation(slide_id, "blocks.steps_count", "steps 块最多 4 步"))
                if block.get("kind") == "compare":
                    for column in (block.get("left"), block.get("right")):
                        if column and len(column.get("items") or []) > 4:
                            violations.append(RuleViolation(slide_id, "blocks.compare_items", "compare 每栏最多 4 条"))
        else:
            if len(body) > limits["body_items"]:
                violations.append(RuleViolation(
                    slide_id, "density.body_items",
                    f"正文 {len(body)} 条超过上限 {limits['body_items']} 条",
                ))
            total_chars = sum(len(item) for item in body)
            if total_chars > limits["body_chars"]:
                violations.append(RuleViolation(
                    slide_id, "density.body_chars",
                    f"正文合计 {total_chars} 字超过上限 {limits['body_chars']} 字",
                ))
            for index, item_text in enumerate(body, 1):
                if len(item_text) > limits["item_chars"]:
                    violations.append(RuleViolation(
                        slide_id, "density.item_chars",
                        f"第 {index} 条正文 {len(item_text)} 字超过单条上限 {limits['item_chars']} 字",
                    ))
        if len(notes) < limits["speaker_notes_chars"]:
            violations.append(RuleViolation(
                slide_id, "density.speaker_notes",
                f"speaker_notes 仅 {len(notes)} 字，少于 {limits['speaker_notes_chars']} 字",
            ))
        if layout not in library:
            violations.append(RuleViolation(slide_id, "layout.valid", f"版式 {layout!r} 不在版式库中"))
        elif layout not in page_guidance[page_type]["layouts"]:
            violations.append(RuleViolation(
                slide_id, "layout.page_type_match",
                f"版式 {layout!r} 不适用于页面类型 {page_type}",
            ))
        if len(suggestion) < _MIN_VISUAL_SUGGESTION_CHARS:
            violations.append(RuleViolation(
                slide_id, "visual.suggestion_length",
                f"visual_suggestion 仅 {len(suggestion)} 字，少于 {_MIN_VISUAL_SUGGESTION_CHARS} 字",
            ))
        if duration <= 0:
            violations.append(RuleViolation(slide_id, "duration.positive", "duration_seconds 必须为正数"))
    return violations
