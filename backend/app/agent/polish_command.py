"""Deterministic, multi-objective command resolution for PPT polishing.

The legacy :class:`PolishIntent` is intentionally small because it is used as
an LLM routing schema.  A polishing run needs more information than one action
and one target dimension, though: scope provenance, all requested operations,
measurable objectives and preservation locks must survive the whole run.

This module provides that canonical command without depending on the runtime
or API layers.  ``resolve_polish_command`` is deliberately deterministic.  An
LLM may enrich a command later, but it must not be allowed to weaken the scope
or preservation decisions made here.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.slide_rendering import canonical_slide_id


TurnRelation: TypeAlias = Literal["new", "refine_previous", "alternative", "undo", "redo"]
ScopeSource: TypeAlias = Literal[
    "explicit_selection", "explicit_text", "active_page", "inherited", "all",
]
OperationDomain: TypeAlias = Literal[
    "layout", "typography", "text", "image_asset", "image_geometry", "style",
    "template", "notes", "timing", "restore", "qa", "export",
]
OperationAction: TypeAlias = Literal[
    "polish", "rearrange", "resize", "align", "adjust_spacing", "rewrite",
    "shorten", "expand", "create", "replace", "remove", "reposition", "crop",
    "recolor", "switch", "restore", "review", "export", "undo", "redo",
]
ObjectTarget: TypeAlias = Literal[
    "title", "body", "cards", "image", "content_refs", "slide", "background",
    "notes", "duration", "theme",
]
Strength: TypeAlias = Literal["subtle", "moderate", "strong"]
ObjectiveMetric: TypeAlias = Literal[
    "font_size", "vertical_utilization", "horizontal_utilization",
    "whitespace_balance", "spacing", "alignment", "density", "image_scale",
    "contrast",
]
ObjectiveDirection: TypeAlias = Literal["increase", "decrease", "preserve", "optimize"]
ObjectiveSource: TypeAlias = Literal["explicit", "inferred", "inherited"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolishScope(_StrictModel):
    target_slide_ids: list[str] = Field(default_factory=list)
    reference_slide_ids: list[str] = Field(default_factory=list)
    source: ScopeSource = "all"

    @field_validator("target_slide_ids", "reference_slide_ids")
    @classmethod
    def _unique_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))


class PolishOperation(_StrictModel):
    domain: OperationDomain
    action: OperationAction
    object_targets: list[ObjectTarget] = Field(default_factory=list)
    strength: Strength = "moderate"
    hard_requirement: bool = True
    execution_order: int = Field(default=10, ge=0, le=100)

    @field_validator("object_targets")
    @classmethod
    def _unique_targets(cls, value: list[ObjectTarget]) -> list[ObjectTarget]:
        return list(dict.fromkeys(value))


class PolishObjective(_StrictModel):
    metric: ObjectiveMetric
    direction: ObjectiveDirection = "optimize"
    minimum_delta: float = Field(default=0.0, ge=0.0, le=2.0)
    priority: int = Field(default=80, ge=1, le=100)
    hard_requirement: bool = True
    source: ObjectiveSource = "explicit"


class PolishPreservation(_StrictModel):
    semantic_text: bool = True
    images_and_assets: bool = True
    notes: bool = True
    duration: bool = True
    theme: bool = True
    page_count: bool = True
    slide_order: bool = True
    template_chrome: bool = True


class ResolvedPolishCommandV2(_StrictModel):
    raw_text: str
    turn_relation: TurnRelation = "new"
    scope: PolishScope = Field(default_factory=PolishScope)
    operations: list[PolishOperation] = Field(default_factory=list)
    objectives: list[PolishObjective] = Field(default_factory=list)
    preservation: PolishPreservation = Field(default_factory=PolishPreservation)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    ambiguities: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False
    summary: str = ""

    @field_validator("ambiguities")
    @classmethod
    def _unique_ambiguities(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in value if item))

    @model_validator(mode="after")
    def _normalize_lists(self) -> "ResolvedPolishCommandV2":
        # Stable order and one operation/objective per semantic key make the
        # command safe to fingerprint and inherit across follow-up turns.
        operations: dict[tuple[str, str, tuple[str, ...]], PolishOperation] = {}
        for operation in self.operations:
            key = (operation.domain, operation.action, tuple(operation.object_targets))
            operations[key] = operation
        self.operations = sorted(
            operations.values(), key=lambda item: (item.execution_order, item.domain, item.action),
        )
        objectives: dict[str, PolishObjective] = {}
        for objective in self.objectives:
            objectives[objective.metric] = objective
        self.objectives = list(objectives.values())
        if self.ambiguities or self.confidence < 0.80:
            self.needs_confirmation = True
        return self


class ParsedPageReferences(_StrictModel):
    """Page numbers parsed from natural language before deck-ID resolution."""

    target_page_numbers: list[int] = Field(default_factory=list)
    reference_page_numbers: list[int] = Field(default_factory=list)
    has_deictic_target: bool = False
    mentions_page_distribution: bool = False


_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_PAGE_EXPR_RE = re.compile(
    r"第\s*([0-9零〇一二两三四五六七八九十百\s、，,和及至到~～—\-]+?)\s*页",
)
_PAGE_RANGE_WITH_SECOND_PREFIX_RE = re.compile(
    r"第\s*([0-9零〇一二两三四五六七八九十百]+)\s*页?\s*"
    r"(至|到|~|～|—|-)\s*第\s*([0-9零〇一二两三四五六七八九十百]+)\s*页",
)
_LEGACY_TARGET_RE = re.compile(r"\[目标页面\s*[:：]\s*([^\]]*)\]", re.I)
_LEGACY_ACTIVE_RE = re.compile(r"\[活动页面\s*[:：]\s*([^\]]*)\]", re.I)
_LEGACY_MODALITY_RE = re.compile(r"\[范围\s*[:：]\s*([^\]]*)\]", re.I)
_LEGACY_NATURAL_TARGET_RE = re.compile(r"\[针对\s*([^\]]*?页)\s*\]", re.I)


def _chinese_number(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return number if number > 0 else None
    if any(char not in {*_CHINESE_DIGITS, "十", "百"} for char in text):
        return None
    total = 0
    current = 0
    for char in text:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
    number = total + current
    return number if number > 0 else None


def _expand_page_expression(expression: str) -> list[int]:
    expression = re.sub(r"\s+", "", expression)
    numbers: list[int] = []
    for part in re.split(r"[、，,和及]", expression):
        if not part:
            continue
        range_parts = re.split(r"(?:至|到|~|～|—|-)", part, maxsplit=1)
        start = _chinese_number(range_parts[0])
        if start is None:
            continue
        if len(range_parts) == 1:
            numbers.append(start)
            continue
        end = _chinese_number(range_parts[1])
        if end is None:
            continue
        step = 1 if end >= start else -1
        numbers.extend(range(start, end + step, step))
    return list(dict.fromkeys(numbers))


def _is_reference_page(text: str, match: re.Match[str]) -> bool:
    before = text[max(0, match.start() - 10):match.start()]
    after = text[match.end():match.end() + 14]
    if re.search(r"(?:参考|参照|仿照|按照|对照|借鉴|以)\s*$", before):
        return True
    if re.match(r"\s*(?:为参考|作为参考)", after):
        return True
    if re.match(r"\s*的\s*(?:风格|版式|布局|配色|样式)", after):
        return True
    if re.search(r"(?:和|与)\s*$", before) and re.match(r"\s*(?:一样|一致|相同)", after):
        return True
    return False


def parse_page_references(raw_text: str) -> ParsedPageReferences:
    """Parse Arabic/Chinese lists and ranges, separating target/reference pages.

    Supported examples include ``第2、4、6页``, ``第4～7页`` and
    ``第3页参考第2页``.  Resolution to real slide IDs happens later because
    page numbers are not guaranteed to be the persisted IDs.
    """
    normalized_text = _PAGE_RANGE_WITH_SECOND_PREFIX_RE.sub(
        lambda match: f"第{match.group(1)}{match.group(2)}{match.group(3)}页",
        raw_text,
    )
    targets: list[int] = []
    references: list[int] = []
    for match in _PAGE_EXPR_RE.finditer(normalized_text):
        destination = references if _is_reference_page(normalized_text, match) else targets
        destination.extend(_expand_page_expression(match.group(1)))
    return ParsedPageReferences(
        target_page_numbers=list(dict.fromkeys(targets)),
        reference_page_numbers=list(dict.fromkeys(references)),
        has_deictic_target=bool(re.search(r"(?:本页|当前页|这一页|这页|该页)", normalized_text)),
        mentions_page_distribution=bool(
            re.search(r"(?:页面|页)\s*(?:分布|分配)", normalized_text)
        ),
    )


def _normalize_modality(value: str | None) -> str:
    normalized = str(value or "auto").strip().lower()
    aliases = {
        "自动": "auto", "布局": "layout", "只改布局": "layout",
        "文字": "text", "文本": "text", "只改文字": "text",
        "图片": "image", "图像": "image", "只改图片": "image",
    }
    return aliases.get(normalized, normalized)


def _extract_legacy_context(
    raw_text: str,
) -> tuple[str, list[str], str | None, str | None, list[int]]:
    selected: list[str] = []
    active: str | None = None
    modality: str | None = None
    natural_pages: list[int] = []
    target_match = _LEGACY_TARGET_RE.search(raw_text)
    if target_match:
        selected = [item.strip() for item in re.split(r"[,，、]", target_match.group(1)) if item.strip()]
    active_match = _LEGACY_ACTIVE_RE.search(raw_text)
    if active_match:
        active = active_match.group(1).strip() or None
    modality_match = _LEGACY_MODALITY_RE.search(raw_text)
    if modality_match:
        modality = _normalize_modality(modality_match.group(1))
    natural_match = _LEGACY_NATURAL_TARGET_RE.search(raw_text)
    if natural_match:
        parsed = parse_page_references(natural_match.group(1))
        natural_pages = parsed.target_page_numbers
    cleaned = _LEGACY_TARGET_RE.sub("", raw_text)
    cleaned = _LEGACY_ACTIVE_RE.sub("", cleaned)
    cleaned = _LEGACY_MODALITY_RE.sub("", cleaned)
    cleaned = _LEGACY_NATURAL_TARGET_RE.sub("", cleaned)
    return cleaned.strip(), selected, active, modality, natural_pages


def _resolve_ids(
    requested: Sequence[str], canonical_ids: Sequence[str], *, allow_position: bool = False,
) -> tuple[list[str], list[str]]:
    canonical = list(dict.fromkeys(str(item) for item in canonical_ids if str(item)))
    resolved: list[str] = []
    invalid: list[str] = []
    for raw in requested:
        value = str(raw or "").strip()
        if not value:
            continue
        candidate = canonical_slide_id(value, canonical) if canonical else None
        if candidate is None and allow_position and value.isdigit() and canonical:
            position = int(value)
            if 1 <= position <= len(canonical):
                candidate = canonical[position - 1]
        if candidate is None:
            invalid.append(value)
        else:
            resolved.append(candidate)
    return list(dict.fromkeys(resolved)), list(dict.fromkeys(invalid))


def _turn_relation(text: str) -> TurnRelation:
    if re.search(r"(?:重做|恢复刚才撤销|重新应用刚才)", text):
        return "redo"
    if re.search(r"(?:撤销|回退到|退回到|恢复到上一|恢复上一个版本)", text):
        return "undo"
    if re.search(r"(?:换一种|换一个|另一种|另一个方案|换个版式|其他方案)", text):
        return "alternative"
    if re.search(r"(?:^|[，,；;。\s])(?:再|还是|继续|稍微|略微|退一点|回一点)", text):
        return "refine_previous"
    return "new"


def _strength(text: str) -> Strength:
    if re.search(r"(?:大幅|显著|明显|彻底|强烈|重新设计|完全重排)", text):
        return "strong"
    if re.search(r"(?:一点|一些|稍微|轻微|略微|小幅)", text):
        return "subtle"
    return "moderate"


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def _object_targets(
    text: str, *, domain: OperationDomain, default: ObjectTarget,
) -> list[ObjectTarget]:
    targets: list[ObjectTarget] = []
    if domain in {"image_asset", "image_geometry"}:
        return ["image"]
    if domain == "template":
        return ["theme"]
    if domain == "notes":
        return ["notes"]
    if domain == "timing":
        return ["duration"]
    if domain in {"restore", "qa", "export"}:
        return ["slide"]
    if domain == "layout":
        if _has(text, r"卡片|步骤|模块"):
            targets.append("cards")
        # Layout instructions normally operate on the semantic groups as a
        # whole.  Merely saying "保留文字/图片" must not misclassify those
        # nouns as the layout's object.
        if _has(text, r"标题.{0,4}(?:位置|对齐|排版|布局)|(?:位置|对齐|排版|布局).{0,4}标题"):
            targets.append("title")
        return list(dict.fromkeys(targets or [default]))
    if domain in {"typography", "text"}:
        if _has(text, r"标题|大标题|小标题"):
            targets.append("title")
        if _has(text, r"正文|文字|文本|内容|文案|要点|段落"):
            targets.append("body")
        return list(dict.fromkeys(targets or [default]))
    if domain == "style":
        if _has(text, r"背景"):
            targets.append("background")
        if _has(text, r"卡片|步骤|模块"):
            targets.append("cards")
        if _has(text, r"标题"):
            targets.append("title")
    return list(dict.fromkeys(targets or [default]))


_NEGATED_ACTION_RE = re.compile(
    r"(?:不|不要|无需|别)(?:再)?(?:将|把)?(?:改写|改变|修改|更换|替换|生成|新增|添加|"
    r"删除|移除|放大|缩小|调大|调小|移动|调整|重排|切换|润色|优化|改|动)"
    r"(?:任何)?[^，,；;。！？!?]{0,8}?"
    r"(?:教学内容|文字|文本|内容|文案|图片|图像|配图|插画|照片|示意图|布局|排版|"
    r"位置|字号|字体|模板|主题)",
)
_NEGATED_OBJECT_FIRST_RE = re.compile(
    r"(?:不|不要|无需|别)(?:再)?(?:将|把)?"
    r"(?:教学内容|文字|文本|内容|文案|图片|图像|配图|插画|照片|示意图|布局|排版|"
    r"位置|字号|字体|模板|主题)[^，,；;。！？!?]{0,6}?"
    r"(?:改变|修改|更换|替换|生成|删除|放大|缩小|移动|调整|重排|切换|改|动)",
)
_PRESERVE_PHRASE_RE = re.compile(
    r"保留(?:原|原有|现有|当前)?(?:的)?"
    r"(?:教学内容|文字|文本|内容|文案|图片|图像|配图|插画|照片|示意图|模板|主题)"
    r"|(?:教学内容|文字|文本|内容|文案|图片|图像|配图|布局|排版|模板|主题)"
    r"(?:保持不变|不动)",
)


def _positive_instruction_text(text: str) -> str:
    """Remove negated action phrases while retaining positive sibling clauses.

    Domain-wide filtering loses valid requests such as ``不要放大图片，只缩小图片``.
    Phrase removal lets resize-decrease survive while the prohibited increase
    never becomes an operation or objective.
    """
    positive = _NEGATED_ACTION_RE.sub("", text)
    positive = _NEGATED_OBJECT_FIRST_RE.sub("", positive)
    positive = _PRESERVE_PHRASE_RE.sub("", positive)
    return re.sub(r"(?:但是|但|不过)", "，", positive).strip(" ，,；;。")


def _operation(
    domain: OperationDomain,
    action: OperationAction,
    text: str,
    *,
    default_target: ObjectTarget,
    hard: bool = True,
    order: int,
) -> PolishOperation:
    return PolishOperation(
        domain=domain,
        action=action,
        object_targets=_object_targets(text, domain=domain, default=default_target),
        strength=_strength(text),
        hard_requirement=hard,
        execution_order=order,
    )


def _parse_operations(text: str, relation: TurnRelation) -> tuple[list[PolishOperation], bool]:
    operations: list[PolishOperation] = []
    generic_polish = False
    if relation in {"undo", "redo"}:
        action: OperationAction = "undo" if relation == "undo" else "redo"
        return [_operation("restore", action, text, default_target="slide", order=0)], False

    if _has(text, r"恢复(?:原|之前|上次|历史)|还原"):
        operations.append(_operation("restore", "restore", text, default_target="slide", order=0))
    if _has(text, r"导出|下载(?:PPT|课件)?"):
        operations.append(_operation("export", "export", text, default_target="slide", order=90))
    if _has(text, r"(?:检查|审查|质检|QA|看看).{0,5}(?:页面|布局|溢出|问题|质量)|视觉检查"):
        operations.append(_operation("qa", "review", text, default_target="slide", order=80))
    if _has(text, r"(?:切换|更换|应用|换).{0,5}(?:模板|主题)|(?:模板|主题).{0,4}(?:换|切换)"):
        operations.append(_operation("template", "switch", text, default_target="theme", order=40))
    if _has(
        text,
        r"(?:修改|改写|润色|补充|精简).{0,5}(?:讲解备注|教师备注|备注)"
        r"|(?:讲解备注|教师备注|备注).{0,5}(?:修改|改写|润色|补充|精简)",
    ):
        operations.append(_operation("notes", "rewrite", text, default_target="notes", order=15))
    if _has(
        text,
        r"(?:调整|修改|增加|减少|延长|缩短).{0,4}(?:时长|时间)"
        r"|(?:时长|时间).{0,4}(?:调整|增加|减少|延长|缩短)",
    ):
        operations.append(_operation("timing", "resize", text, default_target="duration", order=16))

    image_noun = r"(?:图片|图像|配图|插画|照片|示意图|图表)"
    if _has(
        text,
        rf"(?:生成|新增|添加|插入|补充).{{0,5}}{image_noun}"
        rf"|{image_noun}.{{0,5}}(?:生成|新增|添加|插入)",
    ):
        operations.append(_operation("image_asset", "create", text, default_target="image", order=30))
    elif _has(
        text,
        rf"(?:替换|更换|重做|重新生成|换).{{0,5}}{image_noun}"
        rf"|{image_noun}.{{0,4}}(?:替换|更换|重做|重新生成)",
    ):
        operations.append(_operation("image_asset", "replace", text, default_target="image", order=30))
    elif _has(text, rf"(?:删除|移除|去掉).{{0,5}}{image_noun}|{image_noun}.{{0,4}}(?:删除|移除|去掉)"):
        operations.append(_operation("image_asset", "remove", text, default_target="image", order=30))
    if _has(
        text,
        rf"(?:放大|缩小|调大|调小|扩大).{{0,4}}{image_noun}"
        rf"|{image_noun}.{{0,5}}(?:大一点|小一点|放大|缩小|尺寸)",
    ):
        operations.append(_operation("image_geometry", "resize", text, default_target="image", order=25))
    if _has(
        text,
        rf"(?:移动|挪动|调整).{{0,5}}{image_noun}.{{0,4}}(?:位置)?"
        rf"|{image_noun}.{{0,4}}(?:位置|摆放)",
    ):
        operations.append(_operation("image_geometry", "reposition", text, default_target="image", order=25))
    if _has(text, rf"(?:裁剪|裁切|剪裁).{{0,4}}{image_noun}|{image_noun}.{{0,4}}(?:裁剪|裁切|剪裁)"):
        operations.append(_operation("image_geometry", "crop", text, default_target="image", order=25))
    image_layout_specific = _has(
        text,
        rf"{image_noun}[^，,；;。！？!?]{{0,4}}(?:位置|摆放|布局)"
        rf"|(?:调整|优化|润色)[^，,；;。！？!?]{{0,4}}{image_noun}"
        rf"[^，,；;。！？!?]{{0,3}}(?:位置|摆放|布局)",
    )
    if image_layout_specific and not any(item.domain == "image_geometry" for item in operations):
        operations.append(
            _operation("image_geometry", "reposition", text, default_target="image", order=25),
        )
    if (
        _has(
            text,
            rf"(?:润色|优化|美化).{{0,5}}{image_noun}"
            rf"|{image_noun}.{{0,5}}(?:润色|优化|美化)",
        )
        and not any(item.domain in {"image_asset", "image_geometry"} for item in operations)
    ):
        operations.append(
            _operation("image_geometry", "polish", text, default_target="image", order=25),
        )

    text_edit = _has(
        text,
        r"(?:润色|改写|修改|改|优化|调整).{0,6}(?:文字|文本|内容|文案|措辞|表达|标题|正文)"
        r"|(?:文字|文本|内容|文案|措辞|表达|标题|正文).{0,6}(?:润色|改写|修改|优化)"
        r"|精简|扩写|补充(?:文字|文本|内容)|删除(?:文字|文本|内容|段落)",
    )
    if text_edit:
        action: OperationAction = "rewrite"
        if _has(text, r"精简|缩短|压缩"):
            action = "shorten"
        elif _has(text, r"扩写|补充|展开"):
            action = "expand"
        elif _has(text, r"删除(?:文字|文本|内容|段落)"):
            action = "remove"
        operations.append(_operation("text", action, text, default_target="body", order=10))

    typography = _has(
        text,
        r"字体|字号|字太小|字太大|文字偏小|文字偏大|文字太小|文字太大"
        r"|(?:放大|缩小|调大|调小).{0,4}(?:文字|文本|标题|正文|字)"
        r"|(?:文字|文本|标题|正文).{0,4}(?:大一点|小一点|放大|缩小)",
    )
    # A bare "放大一点" means typography unless an image/card object was named.
    if (
        _has(text, r"(?:再)?(?:大|小|放大|缩小)一点")
        and not _has(text, image_noun + r"|卡片|元素")
    ):
        typography = True
    if typography:
        operations.append(_operation("typography", "resize", text, default_target="body", order=20))

    layout_terms = _has(
        text,
        r"布局|排版|版式|页面分布|页内分布|空间利用|利用不充分|留白|空白|视觉重心"
        r"|对齐|间距|太挤|拥挤|堆在|铺开|铺满|分栏|卡片|元素大小|卡片大小"
        r"|重新分布|重排|松一点|紧一点|太散",
    )
    if image_layout_specific and not _has(
        text, r"页面|页内|整体|文字|文本|正文|卡片|排版|空间|留白|分布|对齐|间距",
    ):
        layout_terms = False
    if layout_terms:
        action = "rearrange"
        if _has(text, r"对齐"):
            action = "align"
        elif _has(text, r"间距|松一点|紧一点|太挤|拥挤|太散"):
            action = "adjust_spacing"
        elif _has(text, r"卡片大小|元素大小|(?:放大|缩小|调大|调小).{0,3}(?:卡片|元素)"):
            action = "resize"
        operations.append(_operation("layout", action, text, default_target="content_refs", order=21))

    if _has(text, r"配色|颜色|强调色|对比度|视觉层级|背景色|样式"):
        action = "recolor" if _has(text, r"配色|颜色|强调色|背景色") else "polish"
        operations.append(_operation("style", action, text, default_target="slide", order=22))

    has_content_operation = any(
        item.domain not in {"qa", "export", "restore"} for item in operations
    )
    if not has_content_operation and _has(
        text, r"润色|美化|优化(?:一下)?(?:本页|当前页|页面|PPT|课件)?",
    ):
        generic_polish = True
        operations.extend([
            _operation("layout", "polish", text, default_target="content_refs", hard=False, order=21),
            _operation("typography", "polish", text, default_target="body", hard=False, order=20),
            _operation("style", "polish", text, default_target="slide", hard=False, order=22),
        ])
    return operations, generic_polish


def _objective(
    metric: ObjectiveMetric,
    direction: ObjectiveDirection,
    *,
    minimum_delta: float,
    hard: bool = True,
    priority: int = 90,
    source: ObjectiveSource = "explicit",
) -> PolishObjective:
    return PolishObjective(
        metric=metric,
        direction=direction,
        minimum_delta=minimum_delta,
        priority=priority,
        hard_requirement=hard,
        source=source,
    )


def _parse_objectives(text: str, *, generic_polish: bool) -> list[PolishObjective]:
    objectives: list[PolishObjective] = []
    font_signal = (
        r"字体|字号|字太小|字太大|文字偏小|文字偏大|文字太小|文字太大"
        r"|放大文字|缩小文字|标题.*(?:大|小)|正文.*(?:大|小)"
        r"|(?:^|[，,；;。\s])(?:再)?(?:放大|缩小|大|小)一点"
    )
    if _has(text, font_signal):
        direction: ObjectiveDirection = "optimize"
        if _has(text, r"偏小|太小|放大|调大|大一点"):
            direction = "increase"
        elif _has(text, r"偏大|太大|缩小|调小|小一点"):
            direction = "decrease"
        objectives.append(_objective("font_size", direction, minimum_delta=0.05, priority=100))
    if _has(
        text,
        r"页面分布|页内分布|纵向|上下|空间利用|利用不充分"
        r"|堆在(?:上|下)|铺满|上半页|下半页",
    ):
        objectives.append(_objective("vertical_utilization", "increase", minimum_delta=0.12, priority=100))
    if _has(text, r"横向|左右|左边空|右边空|横向利用|左右分布"):
        objectives.append(_objective("horizontal_utilization", "increase", minimum_delta=0.10, priority=95))
    if _has(text, r"留白|空白|平衡|页面分布|视觉重心|空间利用"):
        objectives.append(_objective("whitespace_balance", "optimize", minimum_delta=0.10, priority=95))
    if _has(text, r"间距|松一点|紧一点|太挤|拥挤|太散"):
        direction = "increase"
        if _has(text, r"紧一点|间距太大|太散"):
            direction = "decrease"
        objectives.append(_objective("spacing", direction, minimum_delta=0.10, priority=95))
    if _has(text, r"对齐|不齐|歪"):
        objectives.append(_objective("alignment", "optimize", minimum_delta=0.08, priority=95))
    if _has(text, r"太挤|拥挤|密度太高|太密"):
        objectives.append(_objective("density", "decrease", minimum_delta=0.10, priority=95))
    elif _has(text, r"太散|密度太低"):
        objectives.append(_objective("density", "increase", minimum_delta=0.10, priority=95))
    if _has(
        text,
        r"(?:放大|调大|扩大).{0,4}(?:图片|图像|配图)"
        r"|(?:图片|图像|配图).{0,4}(?:大一点|放大)",
    ):
        objectives.append(_objective("image_scale", "increase", minimum_delta=0.10, priority=100))
    elif _has(
        text,
        r"(?:缩小|调小).{0,4}(?:图片|图像|配图)"
        r"|(?:图片|图像|配图).{0,4}(?:小一点|缩小)",
    ):
        objectives.append(_objective("image_scale", "decrease", minimum_delta=0.10, priority=100))
    if _has(text, r"对比度|强调|突出|层级|颜色太淡|看不清"):
        objectives.append(_objective("contrast", "increase", minimum_delta=0.10, priority=90))
    if generic_polish and not objectives:
        objectives.extend([
            _objective(
                "whitespace_balance", "optimize", minimum_delta=0.08,
                hard=False, priority=70, source="inferred",
            ),
            _objective(
                "alignment", "optimize", minimum_delta=0.08,
                hard=False, priority=65, source="inferred",
            ),
        ])
    return objectives


def _allowed_domains(modality: str) -> set[OperationDomain] | None:
    if modality == "layout":
        return {"layout", "typography", "style", "qa", "restore", "export"}
    if modality == "text":
        return {"text", "qa", "restore", "export"}
    if modality == "image":
        return {"image_asset", "image_geometry", "qa", "restore", "export"}
    return None


def _text_only_modality(text: str) -> str | None:
    if _has(text, r"(?:只|仅)(?:改|修改|调整|润色)?(?:文字|文本|内容|文案)"):
        return "text"
    if _has(text, r"(?:只|仅)(?:改|修改|调整)?(?:布局|排版)"):
        return "layout"
    if _has(text, r"(?:只|仅)(?:改|修改|调整|处理)?(?:图片|图像|配图)"):
        return "image"
    return None


def _preservation_for(operations: Sequence[PolishOperation]) -> PolishPreservation:
    domains = {item.domain for item in operations}
    return PolishPreservation(
        semantic_text="text" not in domains,
        images_and_assets="image_asset" not in domains,
        notes="notes" not in domains,
        duration="timing" not in domains,
        theme="template" not in domains,
        page_count=True,
        slide_order=True,
        template_chrome="template" not in domains,
    )


def _inverse_direction(direction: ObjectiveDirection) -> ObjectiveDirection:
    if direction == "increase":
        return "decrease"
    if direction == "decrease":
        return "increase"
    return direction


def _coerce_previous(
    previous: ResolvedPolishCommandV2 | Mapping[str, Any] | None,
) -> ResolvedPolishCommandV2 | None:
    if previous is None:
        return None
    if isinstance(previous, ResolvedPolishCommandV2):
        return previous
    try:
        return ResolvedPolishCommandV2.model_validate(previous)
    except Exception:
        return None


def _scope_label(scope: PolishScope, canonical_ids: Sequence[str]) -> str:
    if scope.source == "all":
        return "整套 PPT"
    if not scope.target_slide_ids:
        return "待确认页面"
    positions = {value: index + 1 for index, value in enumerate(canonical_ids)}
    labels = [f"第 {positions[item]} 页" if item in positions else item for item in scope.target_slide_ids]
    return "、".join(labels)


def _summary(command: ResolvedPolishCommandV2, canonical_ids: Sequence[str]) -> str:
    labels = {
        "layout": "布局", "typography": "字号与字体", "text": "文字表达",
        "image_asset": "图片素材", "image_geometry": "图片尺寸与位置",
        "style": "视觉样式", "template": "模板", "notes": "讲解备注",
        "timing": "时长", "restore": "版本恢复", "qa": "质量检查", "export": "导出",
    }
    operation_labels = list(dict.fromkeys(labels[item.domain] for item in command.operations))
    scope = _scope_label(command.scope, canonical_ids)
    action = "、".join(operation_labels) if operation_labels else "未识别的修改"
    preserved: list[str] = []
    preservation_labels = {
        "semantic_text": "文字", "images_and_assets": "图片素材", "notes": "备注",
        "duration": "时长", "theme": "主题", "page_count": "页数",
        "slide_order": "页面顺序", "template_chrome": "模板框架",
    }
    for field, label in preservation_labels.items():
        if getattr(command.preservation, field):
            preserved.append(label)
    result = f"将修改{scope}的{action}"
    if preserved:
        result += f"；保留{'、'.join(preserved)}"
    if command.needs_confirmation:
        result += "；执行前需要确认"
    return result + "。"


def resolve_polish_command(
    raw_text: str,
    *,
    target_slide_ids: Sequence[str] | None = None,
    active_slide_id: str | None = None,
    modality: str = "auto",
    canonical_ids: Sequence[str] = (),
    previous_command: ResolvedPolishCommandV2 | Mapping[str, Any] | None = None,
) -> ResolvedPolishCommandV2:
    """Resolve a user turn into a safe, multi-objective polishing command.

    Scope precedence is explicit UI selection, explicit page text, active-page
    deixis, inherited follow-up scope, then the whole deck.  Invalid or
    conflicting explicit scope never falls through to the whole deck.
    """
    original = str(raw_text or "").strip()
    text, legacy_targets, legacy_active, legacy_modality, legacy_pages = _extract_legacy_context(original)
    canonical = list(dict.fromkeys(str(item) for item in canonical_ids if str(item)))
    previous = _coerce_previous(previous_command)
    relation = _turn_relation(text)
    ambiguities: list[str] = []

    supplied_targets = list(target_slide_ids or legacy_targets)
    supplied_active = active_slide_id or legacy_active
    effective_modality = _normalize_modality(modality)
    if effective_modality == "auto" and legacy_modality:
        effective_modality = legacy_modality
    elif legacy_modality and effective_modality != legacy_modality:
        ambiguities.append("modality.parameter_legacy_conflict")
    if effective_modality not in {"auto", "layout", "text", "image"}:
        ambiguities.append(f"modality.invalid:{effective_modality}")
        effective_modality = "auto"

    parsed_pages = parse_page_references(text)
    if legacy_pages and not parsed_pages.target_page_numbers:
        parsed_pages.target_page_numbers = legacy_pages
    text_targets, invalid_text_targets = _resolve_ids(
        [str(number) for number in parsed_pages.target_page_numbers], canonical, allow_position=True,
    )
    references, invalid_references = _resolve_ids(
        [str(number) for number in parsed_pages.reference_page_numbers], canonical, allow_position=True,
    )
    selected_targets, invalid_selected = _resolve_ids(supplied_targets, canonical)
    active_targets, invalid_active = _resolve_ids([supplied_active] if supplied_active else [], canonical)

    active_scope_required = parsed_pages.has_deictic_target or (
        bool(references) and not supplied_targets and not parsed_pages.target_page_numbers
    )
    if not canonical and (
        supplied_targets or parsed_pages.target_page_numbers
        or (supplied_active and active_scope_required)
    ):
        ambiguities.append("scope.canonical_ids_unavailable")
    ambiguities.extend(f"scope.invalid_selection:{item}" for item in invalid_selected)
    ambiguities.extend(f"scope.invalid_page:{item}" for item in invalid_text_targets)
    ambiguities.extend(f"scope.invalid_reference:{item}" for item in invalid_references)
    if active_scope_required:
        ambiguities.extend(f"scope.invalid_active_page:{item}" for item in invalid_active)

    if supplied_targets:
        scope = PolishScope(
            target_slide_ids=selected_targets,
            reference_slide_ids=references,
            source="explicit_selection",
        )
        if parsed_pages.target_page_numbers and set(text_targets) != set(selected_targets):
            ambiguities.append("scope.selection_text_conflict")
    elif parsed_pages.target_page_numbers:
        scope = PolishScope(
            target_slide_ids=text_targets,
            reference_slide_ids=references,
            source="explicit_text",
        )
    elif parsed_pages.has_deictic_target:
        scope = PolishScope(
            target_slide_ids=active_targets,
            reference_slide_ids=references,
            source="active_page",
        )
        if not supplied_active:
            ambiguities.append("scope.active_slide_missing")
    elif references and active_targets:
        scope = PolishScope(
            target_slide_ids=active_targets,
            reference_slide_ids=references,
            source="active_page",
        )
    elif relation in {"refine_previous", "alternative", "undo", "redo"} and previous:
        inherited_targets, invalid_inherited_targets = _resolve_ids(
            previous.scope.target_slide_ids, canonical,
        )
        inherited_references, invalid_inherited_references = _resolve_ids(
            previous.scope.reference_slide_ids, canonical,
        )
        if not canonical and (
            previous.scope.target_slide_ids or previous.scope.reference_slide_ids
        ):
            ambiguities.append("scope.canonical_ids_unavailable")
        ambiguities.extend(
            f"scope.invalid_inherited_target:{item}" for item in invalid_inherited_targets
        )
        ambiguities.extend(
            f"scope.invalid_inherited_reference:{item}"
            for item in invalid_inherited_references
        )
        scope = PolishScope(
            target_slide_ids=inherited_targets,
            reference_slide_ids=inherited_references,
            source="inherited",
        )
        if references:
            scope.reference_slide_ids = references
    elif relation in {"refine_previous", "alternative"} and not previous:
        scope = PolishScope(reference_slide_ids=references, source="inherited")
        ambiguities.append("scope.previous_command_missing")
    elif references:
        scope = PolishScope(reference_slide_ids=references, source="active_page")
        ambiguities.append("scope.reference_without_target")
    else:
        scope = PolishScope(source="all")

    if set(scope.target_slide_ids) & set(scope.reference_slide_ids):
        ambiguities.append("scope.reference_equals_target")
    if parsed_pages.mentions_page_distribution and scope.source == "all":
        ambiguities.append("scope.page_distribution_ambiguous")

    positive_text = _positive_instruction_text(text)
    operations, generic_polish = _parse_operations(positive_text, relation)
    objectives = _parse_objectives(positive_text, generic_polish=generic_polish)

    text_modality = _text_only_modality(text)
    if text_modality and effective_modality != "auto" and text_modality != effective_modality:
        ambiguities.append(f"modality.text_conflict:{effective_modality}:{text_modality}")
    boundary = effective_modality if effective_modality != "auto" else text_modality
    # The verb "润色" is intentionally domain-neutral.  A user-selected
    # modality supplies the missing object without turning it into a conflict.
    if generic_polish and boundary == "text":
        operations = [
            _operation("text", "polish", positive_text, default_target="body", order=10),
        ]
        objectives = []
    elif generic_polish and boundary == "image":
        operations = [
            _operation(
                "image_geometry", "polish", positive_text, default_target="image", order=25,
            ),
        ]
        objectives = []
    if (
        any(item.domain == "typography" for item in operations)
        and not any(item.metric == "font_size" for item in objectives)
        and _has(positive_text, r"(?:再)?(?:大|放大|小|缩小)一点")
    ):
        direction: ObjectiveDirection = (
            "decrease" if _has(positive_text, r"(?:小|缩小)一点") else "increase"
        )
        objectives.append(_objective("font_size", direction, minimum_delta=0.05, priority=100))

    # A bare alternative inherits the previous design intent.  A concrete
    # follow-up such as "再松一点" keeps its new objective but inherits scope.
    only_alternative_words = bool(re.fullmatch(
        r"[\s，,。！？!?]*(?:换一种|换一个|另一种|另一个方案|换个版式|其他方案)"
        r"(?:试试|看看)?[\s，,。！？!?]*",
        text,
    ))
    if previous and relation == "alternative":
        if only_alternative_words or not operations:
            operations = [item.model_copy(deep=True) for item in previous.operations]
        else:
            current_domains = {item.domain for item in operations}
            operations = [
                item.model_copy(deep=True)
                for item in previous.operations
                if item.domain not in current_domains
            ] + operations
        current_metrics = {item.metric for item in objectives}
        objectives = [
            item.model_copy(update={"source": "inherited"}, deep=True)
            for item in previous.objectives
            if item.metric not in current_metrics
        ] + objectives
    elif previous and relation == "refine_previous" and not operations:
        operations = [item.model_copy(deep=True) for item in previous.operations]
        objectives = [
            item.model_copy(update={"source": "inherited"}, deep=True)
            for item in previous.objectives
        ]
    if previous and relation == "refine_previous" and _has(text, r"(?:退|回)一点"):
        if not operations:
            operations = [item.model_copy(deep=True) for item in previous.operations]
        objectives = [
            item.model_copy(
                update={"direction": _inverse_direction(item.direction), "source": "inherited"},
                deep=True,
            )
            for item in previous.objectives
        ]

    requested_domains = {item.domain for item in operations}

    allowed = _allowed_domains(boundary or "auto")
    if allowed is not None:
        disallowed = requested_domains - allowed
        if disallowed:
            ambiguities.append("modality.disallowed_request:" + ",".join(sorted(disallowed)))
        operations = [item for item in operations if item.domain in allowed]
        allowed_metrics: dict[str, set[ObjectiveMetric]] = {
            "layout": {
                "font_size", "vertical_utilization", "horizontal_utilization",
                "whitespace_balance", "spacing", "alignment", "density", "contrast",
            },
            "text": set(),
            "image": {"image_scale"},
        }
        objectives = [item for item in objectives if item.metric in allowed_metrics[boundary or "layout"]]

    if not operations:
        ambiguities.append("intent.no_executable_operation")
    if not text:
        ambiguities.append("intent.empty_instruction")

    preservation = _preservation_for(operations)
    confidence = 0.93
    if generic_polish:
        confidence = min(confidence, 0.86)
    if scope.source == "inherited":
        confidence = min(confidence, 0.90)
    if ambiguities:
        confidence = min(confidence, 0.69)
    if not operations:
        confidence = min(confidence, 0.45)

    command = ResolvedPolishCommandV2(
        raw_text=text,
        turn_relation=relation,
        scope=scope,
        operations=operations,
        objectives=objectives,
        preservation=preservation,
        confidence=confidence,
        ambiguities=ambiguities,
        needs_confirmation=bool(ambiguities) or confidence < 0.80,
    )
    command.summary = _summary(command, canonical)
    return command


def apply_polish_options(
    command: ResolvedPolishCommandV2,
    options: Mapping[str, Any] | None,
    *, canonical_ids: Sequence[str] = (),
) -> ResolvedPolishCommandV2:
    """Apply structured strength/preservation controls to a resolved command.

    These controls may narrow mutation permissions, but never invent or expand
    slide scope.  Confirmation tokens are persisted by the API and validated
    by the human-request layer rather than trusted by this pure resolver.
    """
    data = dict(options or {})
    resolved = command.model_copy(deep=True)
    strength = str(data.get("strength") or "")
    if strength in {"subtle", "moderate", "strong"}:
        resolved.operations = [
            item.model_copy(update={"strength": strength})
            for item in resolved.operations
        ]
    preservation_updates = {
        "semantic_text": (
            data["preserve_text"] if "preserve_text" in data
            else str(data["content_policy"]) != "edit" if data.get("content_policy")
            else resolved.preservation.semantic_text
        ),
        "images_and_assets": (
            data["preserve_images"] if "preserve_images" in data
            else str(data["image_policy"]) == "preserve" if data.get("image_policy")
            else resolved.preservation.images_and_assets
        ),
        "notes": data.get("preserve_notes", resolved.preservation.notes),
        "page_count": (
            data["preserve_page_count"] if "preserve_page_count" in data
            else str(data["page_count_policy"]) == "preserve" if data.get("page_count_policy")
            else resolved.preservation.page_count
        ),
    }
    resolved.preservation = resolved.preservation.model_copy(update={
        key: bool(value) for key, value in preservation_updates.items()
        if value is not None
    })
    resolved.summary = _summary(resolved, canonical_ids)
    return resolved


__all__ = [
    "apply_polish_options",
    "ParsedPageReferences",
    "PolishObjective",
    "PolishOperation",
    "PolishPreservation",
    "PolishScope",
    "ResolvedPolishCommandV2",
    "parse_page_references",
    "resolve_polish_command",
]
