"""模板分析 Agent：把模板解析为设计系统 Artifact（调色板/字体/装饰/安全边距/布局库）。

Mock 路径：直接复用 catalog + 装饰几何生成 design_system；
LLM 路径：可在该基础上补充每页推荐版式与设计说明。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.renderers.presentation_builder import design_system_for
from app.services.ppt_template_service import resolve_ppt_template


class TemplateAnalysisAgent(Agent):
    key = "template_analysis"
    name = "模板分析 Agent"
    role = "分析所选 PPT 模板，输出设计系统（风格语言/品牌规范/主题色/字体/装饰/版式参考）"
    required_artifacts = []
    produced_artifacts = ["design_system"]
    allowed_tools = ["get_template_catalog", "get_template_design", "inspect_template"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        if not ctx.has_tool_result("inspect_template"):
            return AgentDecision(
                tool_calls=[
                    ToolCall(tool_name="get_template_catalog", input={}),
                    ToolCall(tool_name="inspect_template", input={}),
                ],
                message="正在分析模板设计系统",
            )
        template = ctx.template or design_system_for(resolve_ppt_template(None))
        design = {
            "template_id": template.get("id"),
            "palette": template.get("palette") or template.get("color_system"),
            "typography": template.get("typography"),
            "decoration": template.get("decoration"),
            "safe_margin": template.get("safe_margin", {"x": 0.6, "y": 0.5, "bottom": 0.7}),
            "canvas": template.get("canvas", {"width": 13.333, "height": 7.5}),
            "layout_strategies": ["cover", "title-and-body", "left-text-right-visual", "two-column", "comparison", "process", "summary", "quote"],
            "masters": template.get("masters", 0),
            "layouts": template.get("layouts", []),
            "shape_language": template.get("shape_language", []),
            "layout_patterns": template.get("layout_patterns", []),
        }
        return AgentDecision(
            completed=True,
            output=design,
            summary=f"已识别模板设计系统：{len((template.get('palette') or {}))} 个色彩、装饰元素与版式策略",
            message="模板分析完成",
        )


TEMPLATE_ANALYSIS_AGENT = TemplateAnalysisAgent()
