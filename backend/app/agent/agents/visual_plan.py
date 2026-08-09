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

    def build_system_prompt(self, tc: ToolContext) -> str:
        targets = list(getattr(tc.runtime, "selected_slide_ids", []) or [])
        scope = "、".join(targets) if targets else "教师指令涉及的页面"
        return super().build_system_prompt(tc) + (
            "\n你必须真实分析当前页面已有标题、正文、视觉面板、图注、留白、模板配色和视觉重心，"
            "为图片生成写出具体可执行的 prompt 与 placement，不能返回整页 slides 内容代替视觉请求。"
            f"\n本轮目标页：{scope}。只允许为这些页面创建请求。"
            "\ncompleted.output 必须严格为 {requests:[{slide_id,asset_name,visual_type:'ai_image',"
            "prompt,purpose,placement:{x,y,w,h},aspect_ratio:'4:3'}]}。坐标单位英寸，画布 13.333×7.5；"
            "普通内容页图片槽位只能放在右侧：x 不得小于 7.0、y 不得小于 1.7，"
            "并与标题、正文、visual_caption 保持至少 0.3 英寸间距；图片必须避开文字区域。"
            "图片本身只表达视觉关系，不要嵌入任何中文、英文、字母、数字、公式、标签、Logo 或水印。"
        )

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
