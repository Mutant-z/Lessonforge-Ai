"""页面内容 Agent：把上游完整内容压缩/重组为适合演示的每页内容。

Mock 路径：直接复用 make_ppt 的 15 页角色内容（保持测试 parity）；
LLM 路径：读取叙事 Artifact 动态决定每页内容（禁止照搬上游长文本）。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.schemas.blueprint import CourseBlueprintSchema

DEFAULT_THEME = "lessonforge_deck_academic"


class SlideContentAgent(Agent):
    key = "slide_content"
    name = "页面内容 Agent"
    role = "将上游内容压缩、重组、提炼核心观点，生成符合密度上限的页面级内容"
    required_artifacts = ["presentation_narrative"]
    produced_artifacts = ["slide_content"]
    allowed_tools = ["get_blueprint", "get_template_design", "get_ppt_source"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        if not ctx.has_tool_result("get_blueprint"):
            return AgentDecision(
                tool_calls=[
                    ToolCall(tool_name="get_blueprint", input={}),
                    ToolCall(tool_name="get_template_design", input={}),
                ],
                message="正在读取蓝图与模板，压缩重组页面内容",
            )
        bp = ctx.blueprint
        bp_model = bp if isinstance(bp, CourseBlueprintSchema) else CourseBlueprintSchema.model_validate(bp)
        theme = (ctx.template or {}).get("id") or DEFAULT_THEME
        from app.agents.generators import make_ppt
        content = make_ppt(bp_model, theme).model_dump()
        slides = content.get("slides") or []
        return AgentDecision(
            completed=True,
            output={"slides": slides},
            summary=f"已将上游内容压缩重组为 {len(slides)} 页页面内容，符合密度上限",
            message="页面内容生成完成",
        )


SLIDE_CONTENT_AGENT = SlideContentAgent()
