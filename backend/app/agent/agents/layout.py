"""页面布局 Agent：为每页动态计算元素位置与几何（坐标英寸，安全边距内）。

Mock 路径：按标准版式策略（标题 + 正文流 / 左文右图）确定性计算；
LLM 路径：可基于内容与设计系统选择任意版式策略并输出元素几何。
"""
import math
from typing import Any

from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.agent.slide_rendering import runtime_baseline_slides, semantic_body_texts
from app.renderers.presentation_builder import SLIDE_HEIGHT, SLIDE_WIDTH

MARGIN_X = 0.65
MARGIN_Y = 1.7
BODY_FONT = 18


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
    if not texts:
        return 0.5
    char_w = font_size / 72.0 * 0.98
    chars_per_line = max(1, int(box_width / char_w))
    lines = sum(max(1, math.ceil(len(item) / chars_per_line)) for item in texts)
    return max(0.6, lines * font_size / 72.0 * 1.28)


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
            "不得让图片覆盖任何 textbox、note 或 visual_caption。"
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
            getattr(tc.runtime, "active_intent", "") in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}
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
        slide_id = slide.get("id", "")
        page_type = slide.get("page_type", "concept")
        title = slide.get("title", "")
        body = semantic_body_texts(slide)
        elements = []
        content_x = _content_start_x(template_id, page_type)
        if page_type == "cover":
            has_visual = bool(visual and visual.get("visualType") not in {"none", ""})
            visual_region = (
                normalize_visual_region(
                    visual.get("placement") or {"x": 7.0, "y": 1.2, "w": 5.3, "h": 4.5},
                    template_id,
                    page_type,
                )
                if has_visual else None
            )
            title_width = (
                max(3.2, float(visual_region.get("x") or 7.0) - content_x - 0.4)
                if visual_region else SLIDE_WIDTH - content_x - 0.9
            )
            elements.append({"kind": "textbox", "role": "title", "text": title,
                             "content_ref": "title",
                             "x": content_x, "y": 2.05 if has_visual else 2.3,
                             "w": title_width, "h": 1.6,
                             "style": {"size": 40, "color": "primary", "bold": True}})
            if body:
                elements.append({"kind": "textbox", "role": "subtitle", "text": " · ".join(body[:2]),
                                 "content_ref": "body",
                                 "x": content_x, "y": 4.0,
                                 "w": title_width, "h": 0.8,
                                 "style": {"size": 20, "color": "muted"}})
            purpose = str(slide.get("purpose") or "").strip()
            if purpose:
                elements.append({"kind": "textbox", "role": "purpose", "text": purpose,
                                 "content_ref": "purpose",
                                 "x": content_x, "y": 5.0,
                                 "w": title_width, "h": 0.65,
                                 "style": {"size": 15, "color": "primary", "bold": True}})
            result = {"slide_id": slide_id, "layout_type": "cover_visual" if has_visual else "cover",
                      "designRationale": "封面：左侧标题 + 右侧保留原视觉资源" if has_visual else "封面：居中标题 + 副标题留白",
                      "elements": elements, "render_mode": "absolute"}
            if has_visual:
                result["visual_region"] = visual_region
                result["visual_type"] = visual.get("visualType", "image")
            return result

        has_visual = bool(visual and visual.get("visualType") not in {"none", ""})
        visual_region = (
            normalize_visual_region(
                visual.get("placement") or {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2},
                template_id,
                page_type,
            )
            if has_visual else None
        )
        body_w = (
            max(3.2, float(visual_region.get("x") or 7.4) - content_x - 0.4)
            if visual_region else SLIDE_WIDTH - content_x - 0.78
        )
        body_x = content_x
        elements.append({"kind": "textbox", "role": "title", "text": title,
                         "content_ref": "title",
                         "x": content_x, "y": 0.55, "w": SLIDE_WIDTH - content_x - 0.78, "h": 0.8,
                         "style": {"size": 28, "color": "primary", "bold": True}})
        body_h = _estimate_height(body, body_w, BODY_FONT)
        body_h = max(2.0, min(4.4, body_h))
        elements.append({"kind": "textbox", "role": "body", "text": "\n".join(body),
                         "content_ref": "body",
                         "x": body_x, "y": MARGIN_Y, "w": body_w, "h": body_h,
                         "style": {"size": BODY_FONT, "color": "text"}})
        result = {"slide_id": slide_id, "layout_type": "title_and_body",
                  "designRationale": "标题 + 正文流",
                  "elements": elements, "render_mode": "absolute"}
        if has_visual:
            visual_type = visual.get("visualType", "image")
            result["layout_type"] = "left_text_right_visual"
            result["designRationale"] = "左侧正文、右侧视觉区"
            result["visual_region"] = visual_region
            result["visual_type"] = visual_type
        return result


LAYOUT_AGENT = LayoutAgent()
