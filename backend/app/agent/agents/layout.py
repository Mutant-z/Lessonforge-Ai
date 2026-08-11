"""页面布局 Agent：为每页动态计算元素位置与几何（坐标英寸，安全边距内）。

Mock 路径：按标准版式策略（标题 + 正文流 / 左文右图）确定性计算；
LLM 路径：可基于内容与设计系统选择任意版式策略并输出元素几何。
"""
import math
from typing import Any

from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.agent.slide_rendering import runtime_baseline_slides, semantic_body_refs
from app.agent.layouts.engine import compile_layout
from app.renderers.presentation_builder import SLIDE_HEIGHT, SLIDE_WIDTH

MARGIN_X = 0.65
MARGIN_Y = 1.7
BODY_FONT = 18
BODY_ITEM_GAP = 0.3
MAX_BODY_ITEMS = 6
# 正文列必须纵向铺满内容区，禁止把所有文字挤在一角。
MIN_BODY_VERTICAL_USAGE = 0.45
SAFE_CONTENT_BOTTOM = SLIDE_HEIGHT - 0.7  # 6.8


def _is_body_content_ref(ref: Any) -> bool:
    ref = str(ref or "")
    return ref == "body" or ref.startswith("body.") or ref.startswith("blocks.")


def canonicalize_spatial_layout(
    template_id: str, slide: dict[str, Any], layout: dict[str, Any],
) -> dict[str, Any]:
    """确定性重排被“挤成一团”的正文列。

    LLM 输出的绝对布局只要 schema 合法就会被信任，但一个把全部文字堆在
    左上角、其余空白一片的布局能通过内容覆盖检查。这里在发布前把“既没有
    纵向铺满、也没有横向展开”的正文强制重排为逐条独立文本框 + 均匀纵向
    分布。多列/横向卡片等真正利用横向空间的版式（span_w 达标）原样保留。
    """
    page_type = str(slide.get("page_type") or "concept")
    if page_type == "cover":
        return layout
    elements = list(layout.get("elements") or [])
    body_indexes = [
        index for index, element in enumerate(elements)
        if element.get("kind") in {"textbox", "note"} and _is_body_content_ref(element.get("content_ref"))
    ]
    if not body_indexes:
        return layout
    body_refs = semantic_body_refs(slide)
    if not body_refs:
        return layout
    body_elements = [elements[index] for index in body_indexes]
    min_y = min(float(item.get("y") or 0) for item in body_elements)
    max_bottom = max(float(item.get("y") or 0) + float(item.get("h") or 0) for item in body_elements)
    min_x = min(float(item.get("x") or 0) for item in body_elements)
    max_right = max(float(item.get("x") or 0) + float(item.get("w") or 0) for item in body_elements)
    available_h = SAFE_CONTENT_BOTTOM - MARGIN_Y
    content_x = _content_start_x(template_id, page_type)
    visual_region = layout.get("visual_region") or {}
    visual_x = float(visual_region.get("x") or 0) if visual_region else 0.0
    body_w = max(3.2, visual_x - content_x - 0.4) if visual_x > content_x + 1 else SLIDE_WIDTH - content_x - 0.78
    vertical_underused = max_bottom - min_y < available_h * MIN_BODY_VERTICAL_USAGE
    horizontal_clustered = max_right - min_x < body_w * 0.6
    if not (vertical_underused and horizontal_clustered):
        return layout
    items: list[tuple[str, str, float]] = []
    for ref, text in body_refs:
        item_h = max(0.5, _estimate_height([text], body_w, BODY_FONT))
        items.append((ref, text, item_h))
    total_h = sum(item_h for _ref, _text, item_h in items) + BODY_ITEM_GAP * max(0, len(items) - 1)
    gap = BODY_ITEM_GAP
    target_h = available_h * MIN_BODY_VERTICAL_USAGE
    if len(items) > 1 and total_h < target_h:
        gap = BODY_ITEM_GAP + (target_h - total_h) / (len(items) - 1)

    kept = [element for index, element in enumerate(elements) if index not in body_indexes]
    title_index = next((index for index, element in enumerate(kept) if element.get("content_ref") == "title"), None)
    if title_index is not None:
        kept[title_index] = {
            **kept[title_index],
            "x": content_x, "y": 0.55, "w": SLIDE_WIDTH - content_x - 0.78, "h": 0.8,
        }
    cursor_y = MARGIN_Y
    for ref, text, item_h in items:
        kept.append({"kind": "textbox", "role": "body", "text": text, "content_ref": ref,
                     "x": round(content_x, 3), "y": round(cursor_y, 3),
                     "w": round(body_w, 3), "h": round(item_h, 3),
                     "style": {"size": BODY_FONT, "color": "text"}})
        cursor_y += item_h + gap
    return {**layout, "elements": kept}


def _content_start_x(template_id: str, page_type: str = "concept") -> float:
    """Match semantic rendering's safe content rail for asymmetric templates."""
    if template_id == "lessonforge_deck_smart_ai":
        return 2.95 if page_type == "cover" else 2.45
    if template_id == "lessonforge_deck_academic":
        return 2.2
    return MARGIN_X


def normalize_visual_region(
    region: dict[str, Any] | None,
    template_id: str = "",
    page_type: str = "concept",
) -> dict[str, float]:
    """Clamp an image slot away from the title/text rails and slide edges.

    LLM visual plans are useful for composition, but their coordinates are not
    trusted layout primitives.  In particular, a perfectly valid-looking
    ``y=1.2`` placement overlaps the bottom of the standard title box
    (``y=.55..1.35``).  Normalize once at the visual-plan boundary so layout,
    editor and QA all consume the same safe slot, including repair rounds.
    """
    raw = region if isinstance(region, dict) else {}
    canvas_right = SLIDE_WIDTH - 0.65
    canvas_bottom = SLIDE_HEIGHT - 0.7
    try:
        x = float(raw.get("x", raw.get("left", 7.4)))
        y = float(raw.get("y", raw.get("top", 1.7)))
        w = float(raw.get("w", raw.get("width", 5.2)))
        h = float(raw.get("h", raw.get("height", 4.2)))
    except (TypeError, ValueError):
        x, y, w, h = 7.4, 1.7, 5.2, 4.2
    values = (x, y, w, h)
    if not all(math.isfinite(value) for value in values):
        x, y, w, h = 7.4, 1.7, 5.2, 4.2

    # Cover layouts compute title width from the visual slot, so keep their
    # more flexible composition while still keeping the image on-canvas.
    if page_type != "cover":
        content_x = _content_start_x(template_id, page_type)
        # Keep a readable left text column plus a visible inter-column gap.
        min_x = max(7.0, content_x + 4.55 + 0.4)
        max_w = max(3.2, canvas_right - min_x)
        w = min(max(3.2, w), max_w)
        x = max(min_x, min(x, canvas_right - w))
        min_y = 1.7
        max_h = max(2.0, canvas_bottom - min_y)
        h = min(max(2.0, h), max_h)
        y = max(min_y, min(y, canvas_bottom - h))
    else:
        x = max(0.65, x)
        y = max(1.15, y)
        w = min(max(3.2, w), canvas_right - 0.65)
        h = min(max(2.0, h), canvas_bottom - 1.15)
        x = min(x, canvas_right - w)
        y = min(y, canvas_bottom - h)
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def _estimate_height(texts: list[str], box_width: float, font_size: float) -> float:
    from app.agent.layouts.metrics import estimate_item_height
    return estimate_item_height(list(texts), box_width, font_size)


class LayoutAgent(Agent):
    key = "layout"
    name = "页面布局 Agent"
    role = "为每页选择版式策略并计算元素位置（标题/正文/图片区域），避免越界与重叠"
    required_artifacts = ["slide_content", "visual_plan"]
    produced_artifacts = ["slide_layout"]
    allowed_tools = ["get_template_design", "get_knowledge_base"]

    def build_system_prompt(self, tc: ToolContext) -> str:
        targets = list(getattr(tc.runtime, "selected_slide_ids", []) or [])
        scope = "、".join(targets) if targets else "全部页面"
        return super().build_system_prompt(tc) + (
            "\n你必须真实分析当前页面已有元素、文字层级、留白、对齐、模板配色与视觉重心，"
            "并将审美判断转化为可执行坐标，不能只改 visual_suggestion 或返回原始 slide 内容。\n"
            f"本轮唯一允许设计的页面：{scope}。不得输出其他页面。\n"
            "completed.output 必须严格为 {slides:[{slide_id, layout_type, designRationale, "
            "elements:[{kind,role,content_ref,text,x,y,w,h,style}]}]}。"
            "视觉/图片任务只能改变坐标和样式，文字必须逐字来自当前页面内容。坐标单位英寸，画布 13.333×7.5。"
            "普通内容页的图片必须位于右侧安全槽位（x≥7.0、y≥1.7），与标题/正文保持至少 0.3 英寸间距；"
            "不得让图片覆盖任何 textbox、note 或 visual_caption。\n"
            "空间分布硬约束（违反会被判定为不合格布局）：\n"
            "· 正文列必须纵向铺满内容区：标题固定 y=0.55，正文从 y≈1.7 起，至少延伸到 y≈5.0 以上；\n"
            "· 正文条目逐条独立成框，条间距 ≥0.3 英寸，禁止把所有文字叠在一个角落或使用互相重叠的文本框；\n"
            "· 标题与正文必须覆盖内容列宽度（x 从安全边距到右侧视觉槽），禁止把文字压成小窄条；\n"
            "· 每个文字元素必须带 content_ref（title / body / body.N / blocks.* / purpose），"
            "且文字逐字来自页面内容，不得自己改写措辞；引用不存在的 content_ref 会被判定为不合格；\n"
            "· 结构块应按语义排版：steps 用横向编号卡片（2~4 列平铺）、compare 用左右双栏、"
            "bullets/正文用纵向条目流，不要把所有条目压成单条竖排；\n"
            "· 正文条目尽量横向展开（利用整个内容列宽度），只有条目极少时才允许集中在一侧；\n"
            "· 不靠放大装饰图形或空白形状占位，页面空间应由文字与图片真实利用。"
        )

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        if not ctx.has_tool_result("get_template_design"):
            return AgentDecision(
                tool_calls=[ToolCall(tool_name="get_template_design", input={})],
                message="正在读取模板设计系统，计算页面布局",
            )
        slide_content = await tc.artifacts.latest("slide_content") if tc.artifacts else None
        visual_plan = await tc.artifacts.latest("visual_plan") if tc.artifacts else None
        source_slides = runtime_baseline_slides(tc.runtime)
        slides = (slide_content or {}).get("data", {}).get("slides") or source_slides
        visual_by_slide = {}
        if visual_plan:
            visual_data = visual_plan.get("data", {})
            for item in (visual_data.get("requests") or []):
                slide_id = str(item.get("slide_id") or "")
                if slide_id:
                    visual_by_slide[slide_id] = {
                        "visualType": item.get("visual_type") or "ai_image",
                        "placement": item.get("placement"),
                    }
            for item in (visual_data.get("slides") or []):
                if item.get("visualRequired"):
                    visual_by_slide[item["slideId"]] = item
        if (
            getattr(tc.runtime, "active_intent", "") in {
                "MODIFY", "LOCAL_REGENERATE", "CONTENT_UPDATE", "GLOBAL_OPTIMIZE",
                "STYLE_CHANGE", "TEMPLATE_SWITCH",
            }
            or getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
        ):
            for slide in source_slides:
                if any(element.get("kind") in {"image", "chart"} for element in (slide.get("elements") or [])):
                    visual_by_slide.setdefault(str(slide.get("id") or ""), {"visualType": "image"})
        layouts = []
        template_id = str(
            getattr(tc.runtime, "preferred_template", "")
            or (getattr(ctx, "template", {}) or {}).get("id")
            or ""
        )
        for index, slide in enumerate(slides):
            layout = self._layout_slide(slide, visual_by_slide.get(slide.get("id", "")), template_id)
            layouts.append(layout)
        return AgentDecision(
            completed=True,
            output={"slides": layouts},
            summary=f"已为 {len(layouts)} 页计算元素几何",
            message="页面布局设计完成",
        )

    @staticmethod
    def _layout_slide(slide: dict, visual: dict | None, template_id: str = "") -> dict:
        directive = {"slide_id": str(slide.get("id") or ""),
                     "layout_type": LayoutAgent._preset_for_page(slide, visual),
                     "style": {},
                     "rationale": "确定性版式（引擎编译）"}
        page_type = str(slide.get("page_type") or "concept")
        if visual and visual.get("visualType") not in {"none", ""}:
            placement = visual.get("placement") or {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}
            directive["visual_region"] = placement
            directive["visual_type"] = visual.get("visualType", "image")
        return compile_layout(template_id, slide, directive)

    @staticmethod
    def _preset_for_page(slide: dict, visual: dict | None) -> str:
        page_type = str(slide.get("page_type") or "concept")
        if page_type == "cover":
            return "cover_left" if visual and visual.get("visualType") not in {"none", ""} else "cover_center"
        blocks = slide.get("blocks") or []
        if any(b.get("kind") == "steps" for b in blocks):
            return "steps_horizontal"
        if any(b.get("kind") == "compare" for b in blocks):
            return "compare_columns"
        if any(b.get("kind") == "quote" for b in blocks):
            return "quote_center"
        if visual and visual.get("visualType") not in {"none", ""}:
            return "left_text_right_visual"
        body = [t for t in (slide.get("body") or []) if str(t).strip()]
        return "split_two_column" if len(body) >= 6 else "bullet_flow"


LAYOUT_AGENT = LayoutAgent()
