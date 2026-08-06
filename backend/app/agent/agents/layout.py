"""页面布局 Agent：为每页动态计算元素位置与几何（坐标英寸，安全边距内）。

Mock 路径：按标准版式策略（标题 + 正文流 / 左文右图）确定性计算；
LLM 路径：可基于内容与设计系统选择任意版式策略并输出元素几何。
"""
import math

from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.renderers.presentation_builder import SLIDE_HEIGHT, SLIDE_WIDTH

MARGIN_X = 0.65
MARGIN_Y = 1.7
BODY_FONT = 18


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

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        if not ctx.has_tool_result("get_template_design"):
            return AgentDecision(
                tool_calls=[ToolCall(tool_name="get_template_design", input={})],
                message="正在读取模板设计系统，计算页面布局",
            )
        slide_content = await tc.artifacts.latest("slide_content") if tc.artifacts else None
        visual_plan = await tc.artifacts.latest("visual_plan") if tc.artifacts else None
        slides = (slide_content or {}).get("data", {}).get("slides") or []
        visual_by_slide = {}
        if visual_plan:
            for item in (visual_plan.get("data", {}).get("slides") or []):
                if item.get("visualRequired"):
                    visual_by_slide[item["slideId"]] = item
        layouts = []
        for index, slide in enumerate(slides):
            layout = self._layout_slide(slide, visual_by_slide.get(slide.get("id", "")))
            layouts.append(layout)
        return AgentDecision(
            completed=True,
            output={"slides": layouts},
            summary=f"已为 {len(layouts)} 页计算元素几何",
            message="页面布局设计完成",
        )

    @staticmethod
    def _layout_slide(slide: dict, visual: dict | None) -> dict:
        slide_id = slide.get("id", "")
        page_type = slide.get("page_type", "concept")
        title = slide.get("title", "")
        body = [str(value) for value in (slide.get("body") or [])]
        if slide.get("blocks"):
            from app.agents.generators import _blocks_flat_text
            body = [str(value) for value in _blocks_flat_text(slide.get("blocks"))] or body
        elements = []
        if page_type == "cover":
            elements.append({"kind": "textbox", "role": "title", "text": title,
                             "x": 1.0, "y": 2.3, "w": 11.3, "h": 1.4,
                             "style": {"size": 40, "color": "primary", "bold": True}})
            if body:
                elements.append({"kind": "textbox", "role": "subtitle", "text": " · ".join(body[:2]),
                                 "x": 1.0, "y": 4.0, "w": 11.3, "h": 0.8,
                                 "style": {"size": 20, "color": "muted"}})
            return {"slide_id": slide_id, "layout_type": "cover",
                    "designRationale": "封面：居中标题 + 副标题留白", "elements": elements}

        has_visual = bool(visual and visual.get("visualType") not in {"none", ""})
        body_w = 6.4 if has_visual else 11.9
        body_x = MARGIN_X
        elements.append({"kind": "textbox", "role": "title", "text": title,
                         "x": MARGIN_X, "y": 0.55, "w": 11.9, "h": 0.8,
                         "style": {"size": 28, "color": "primary", "bold": True}})
        body_h = _estimate_height(body, body_w, BODY_FONT)
        body_h = max(2.0, min(4.4, body_h))
        elements.append({"kind": "textbox", "role": "body", "text": "\n".join(body),
                         "x": body_x, "y": MARGIN_Y, "w": body_w, "h": body_h,
                         "style": {"size": BODY_FONT, "color": "text"}})
        result = {"slide_id": slide_id, "layout_type": "title_and_body",
                  "designRationale": "标题 + 正文流",
                  "elements": elements}
        if has_visual:
            visual_type = visual.get("visualType", "image")
            result["layout_type"] = "left_text_right_visual"
            result["designRationale"] = "左侧正文、右侧视觉区"
            result["visual_region"] = {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}
            result["visual_type"] = visual_type
        return result


LAYOUT_AGENT = LayoutAgent()
