"""视觉 QA Agent：渲染 PPT 并执行几何/字宽/知识检查（LibreOffice 可用时附加图像检查）。"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall


class VisualQaAgent(Agent):
    key = "visual_qa"
    name = "视觉 QA Agent"
    role = "渲染 PPT 逐页检查文字溢出/重叠/越界/字号，输出问题与目标 Agent"
    required_artifacts = ["presentation_file"]
    produced_artifacts = ["visual_qa"]
    allowed_tools = ["render_preview", "run_qa", "get_qa_report"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        if not tc.ctx.has_tool_result("run_qa"):
            calls = []
            if tc.builder is not None and tc.builder.slides:
                calls.append(ToolCall(tool_name="render_preview", input={}))
            calls.append(ToolCall(tool_name="run_qa", input={}))
            return AgentDecision(
                tool_calls=calls,
                message="正在渲染并执行视觉质量检查",
            )
        qa = await tc.artifacts.latest("visual_qa") if tc.artifacts else None
        data = (qa or {}).get("data", {})
        issues = data.get("issues") or []
        severity = data.get("severity_counts") or {}
        target_agents = sorted({issue.get("target_agent", "ppt_editor") for issue in issues if issue.get("severity") in {"critical", "major"}})
        return AgentDecision(
            completed=True,
            output=data,
            summary=f"QA 评分 {data.get('score', 0)}：{severity.get('critical', 0)} 严重 / {severity.get('major', 0)} 主要问题",
            message=f"视觉 QA 完成，评分 {data.get('score', 0)}",
        )


VISUAL_QA_AGENT = VisualQaAgent()
