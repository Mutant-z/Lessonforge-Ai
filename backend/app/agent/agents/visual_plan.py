"""视觉规划 Agent：判断哪些页面需要视觉素材（图片/图表/流程图），不为所有页面机械配图。"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall

MAX_VISUAL_SLIDES = 3


class VisualPlanAgent(Agent):
    key = "visual_plan"
    name = "视觉规划 Agent"
    role = "根据页面目标判断视觉素材需求（ai_image/chart/diagram/none）与构图要求"
    required_artifacts = ["slide_content"]
    produced_artifacts = ["visual_plan"]
    allowed_tools = ["get_template_design"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        if not ctx.has_tool_result("get_template_design"):
            return AgentDecision(
                tool_calls=[ToolCall(tool_name="get_template_design", input={})],
                message="正在评估各页视觉素材需求",
            )
        slide_content = await tc.artifacts.latest("slide_content") if tc.artifacts else None
        slides = (slide_content or {}).get("data", {}).get("slides") or []
        plans = []
        picked = 0
        for slide in slides:
            page_type = slide.get("page_type", "concept")
            slide_id = slide.get("id", "")
            if page_type in {"case", "scenario"}:
                visual_type, purpose, aspect = "diagram", "示意应用过程/场景关系", "4:3"
            elif page_type == "concept" and picked < MAX_VISUAL_SLIDES:
                visual_type, purpose, aspect = "ai_image", "辅助理解核心概念，主体置于右/左留白侧", "4:3"
            elif page_type == "comparison":
                visual_type, purpose, aspect = "chart", "对比数据可视化", "4:3"
            else:
                plans.append({"slideId": slide_id, "visualRequired": False,
                              "visualType": "none", "purpose": "", "aspectRatio": "4:3"})
                continue
            if picked >= MAX_VISUAL_SLIDES and visual_type == "ai_image":
                plans.append({"slideId": slide_id, "visualRequired": False, "visualType": "none", "purpose": "", "aspectRatio": "4:3"})
                continue
            picked += 1
            plans.append({"slideId": slide_id, "visualRequired": True, "visualType": visual_type,
                          "purpose": purpose, "aspectRatio": aspect, "dataSourceIds": []})
        return AgentDecision(
            completed=True,
            output={"slides": plans},
            summary=f"已规划视觉素材：{sum(1 for item in plans if item['visualRequired'])} 页需要配图/图表",
            message="视觉规划完成",
        )


VISUAL_PLAN_AGENT = VisualPlanAgent()
