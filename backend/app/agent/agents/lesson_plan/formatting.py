"""章节格式确定性修复：去除正文中的硬编码旧序号。

编号不能依赖模型直接写入正文，章节序号统一由渲染器按章节树层级生成。
``strip_hardcoded_ordinals`` 只清理目标章节正文中的「标题型」硬编码序号
（一、/（一）/【教学评价】等行首前缀），且只作用于标题型行——去掉前缀后
剩余文本必须较短（≤40 字符）且不含句末标点（。！？；），避免误删正常的
编号条目、实验编号、公式或表格内容。

安全边界：
- 数字编号（1. / 2. / ①）一律保留：步骤序号由 steps 渲染器生成，物理公式、
  实验编号、目标 ID、时间值属于正文内容，不得被清理器误删；
- 表格单元格不做任何清理（表格内容保持逐字不变）；
- 只清理目标章节，绝不触碰 pedagogical_core 与其他章节；
- 幂等：第二次执行结果为 no_change。
"""

from __future__ import annotations

import copy
import re
from typing import Any

# 中文序数标题前缀：一、/（一）/
_CN_ORDINAL_PREFIX = re.compile(
    r"^\s*(?:[一二三四五六七八九十百]+|（[一二三四五六七八九十百]+）)\s*[、]\s*"
)
# 【教学评价】式包装前缀（独立标题行）。
_MARKER_TITLE_PREFIX = re.compile(r"^\s*【[^】]{1,20}】\s*")
# 标题型行判定：剩余文本较短且不含句末标点，避免误伤正常编号条目。
_MAX_TITLE_LEN = 40
_SENTENCE_END = "。！？；"


def _is_title_line(rest: str) -> bool:
    """去掉序数前缀后的行是否属于「标题型」。

    标题型 = 文本较短（≤40 字符）且不含句末标点。编号条目（1. 目标达成情况检查。）
    因含句末标点而不视为标题，保留原文。
    """
    if not rest:
        return False
    if len(rest) > _MAX_TITLE_LEN:
        return False
    return not any(ch in rest for ch in _SENTENCE_END)


def _strip_line_prefix(line: str) -> str:
    """去除行首的标题型序数前缀与【】包装前缀（保持幂等）。"""
    text = line
    for _ in range(2):
        changed = False
        match = _CN_ORDINAL_PREFIX.match(text)
        if match and _is_title_line(text[match.end():]):
            text = text[match.end():]
            changed = True
        match = _MARKER_TITLE_PREFIX.match(text)
        if match:
            text = text[match.end():]
            changed = True
        if not changed:
            break
    return text


def _strip_text(value: str) -> str:
    """按行清理标题型前缀；保留数字编号、公式与句末标点行。"""
    if not value:
        return value
    lines = str(value).split("\n")
    fixed = [_strip_line_prefix(line) for line in lines]
    if fixed == lines:
        return str(value)
    return "\n".join(fixed)


def _clean_blocks(blocks: list[dict[str, Any]]) -> bool:
    changed = False
    for block in blocks:
        kind = block.get("kind")
        if kind == "paragraph":
            raw = str(block.get("text") or "")
            fixed = _strip_text(raw)
            if fixed != raw:
                block["text"] = fixed
                changed = True
        elif kind == "bullets":
            items = block.get("items") or []
            for index, item in enumerate(items):
                raw = str(item)
                fixed = _strip_text(raw)
                if fixed != raw:
                    items[index] = fixed
                    changed = True
        elif kind == "steps":
            for step in block.get("steps") or []:
                for key in ("title", "detail"):
                    raw = str(step.get(key) or "")
                    fixed = _strip_text(raw)
                    if fixed != raw:
                        step[key] = fixed
                        changed = True
        elif kind == "note":
            raw = str(block.get("text") or "")
            fixed = _strip_text(raw)
            if fixed != raw:
                block["text"] = fixed
                changed = True
        elif kind == "checklist":
            for item in block.get("items") or []:
                raw = str(item.get("text") or "")
                fixed = _strip_text(raw)
                if fixed != raw:
                    item["text"] = fixed
                    changed = True
        # kind in {"table", "process_table"}：表格内容一律保留，不做清理。
    return changed


def strip_hardcoded_ordinals(
    content: dict[str, Any],
    target_section_ids: list[str] | None = None,
) -> dict[str, Any]:
    """去除目标章节正文中的硬编码序号（幂等，重复调用无二次变化）。

    ``target_section_ids`` 为空时作用于全部章节（供格式校验/全量清理使用）。
    返回清理后的内容副本；未发生任何变化时返回与输入等值的新副本。
    """
    target_set = set(target_section_ids or [])
    result = copy.deepcopy(content)
    changed = False

    def visit(sections: list[dict[str, Any]]) -> None:
        nonlocal changed
        for section in sections:
            if not target_set or section.get("id") in target_set:
                if _clean_blocks(section.get("blocks") or []):
                    changed = True
            visit(section.get("children") or [])

    visit(result.get("outline", {}).get("sections") or [])
    return result


def _block_has_ordinal(block: dict[str, Any]) -> bool:
    """块内是否存在「标题型」硬编码序数（一、/（一））——数字编号不计入。"""
    kind = block.get("kind")
    if kind == "paragraph":
        return any(_line_has_ordinal(line) for line in str(block.get("text") or "").split("\n"))
    if kind == "bullets":
        return any(_line_has_ordinal(str(item)) for item in block.get("items") or [])
    if kind == "steps":
        return any(
            _line_has_ordinal(str(step.get(key) or ""))
            for step in block.get("steps") or []
            for key in ("title", "detail")
        )
    if kind == "note":
        return any(_line_has_ordinal(line) for line in str(block.get("text") or "").split("\n"))
    if kind == "checklist":
        return any(
            _line_has_ordinal(str(item.get("text") or ""))
            for item in block.get("items") or []
        )
    # 表格单元格一律不视为硬编码序号（保持表格内容不变）。
    return False


def _line_has_ordinal(line: str) -> bool:
    match = _CN_ORDINAL_PREFIX.match(line)
    if not match:
        return False
    return _is_title_line(line[match.end():])


def has_hardcoded_ordinals(content: dict[str, Any]) -> bool:
    """检查任何章节正文中是否存在硬编码序号（兼容旧签名：全量扫描）。"""
    return bool(hardcoded_ordinal_section_ids(content))


def hardcoded_ordinal_section_ids(content: dict[str, Any]) -> list[str]:
    """返回正文含标题型硬编码序数的章节 ID 列表（全量）。"""
    result: list[str] = []
    for section in _walk((content.get("outline") or {}).get("sections") or []):
        if any(_block_has_ordinal(block) for block in section.get("blocks") or []):
            result.append(str(section.get("id") or ""))
    return sorted(item for item in result if item)


def hardcoded_ordinal_sections_in(
    content: dict[str, Any],
    section_ids: list[str],
) -> list[str]:
    """只检查指定章节内的硬编码序数（目标范围编号校验使用）。"""
    target = set(section_ids or [])
    result: list[str] = []
    for section in _walk((content.get("outline") or {}).get("sections") or []):
        sid = str(section.get("id") or "")
        if target and sid not in target:
            continue
        if any(_block_has_ordinal(block) for block in section.get("blocks") or []):
            result.append(sid)
    return sorted(item for item in result if item)


def _walk(sections: list[dict[str, Any]]):
    for item in sections or []:
        yield item
        yield from _walk(item.get("children") or [])
