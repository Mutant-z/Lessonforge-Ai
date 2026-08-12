"""视觉 QA Agent：渲染 PPT 并执行几何/字宽/知识检查（LibreOffice 可用时附加图像检查）。"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.agent.tools.qa_tools import CONTENT_QA_INTENTS


class VisualQaAgent(Agent):
    key = "visual_qa"
    name = "视觉 QA Agent"
    role = "渲染 PPT 逐页检查文字溢出/重叠/越界/字号，输出问题与目标 Agent"
    required_artifacts = ["presentation_file"]
    produced_artifacts = ["visual_qa"]
    allowed_tools = ["render_preview", "run_qa", "run_content_qa", "get_qa_report"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        output_reader = getattr(tc.ctx, "get_tool_output", None)
        live_qa = output_reader("run_qa") if callable(output_reader) else None
        has_result = bool(getattr(tc.ctx, "has_tool_result", lambda _name: False)("run_qa"))
        if live_qa is None and (callable(output_reader) or not has_result):
            calls = []
            if tc.builder is not None and tc.builder.slides:
                calls.append(ToolCall(tool_name="render_preview", input={}))
            calls.append(ToolCall(tool_name="run_qa", input={}))
            if (
                getattr(tc.runtime, "active_intent", "GENERATE") in CONTENT_QA_INTENTS
                and getattr(tc.runtime, "content_policy", "edit") == "edit"
            ):
                calls.append(ToolCall(tool_name="run_content_qa", input={}))
            return AgentDecision(
                tool_calls=calls,
                message="正在渲染并执行视觉质量检查",
            )
        qa = await tc.artifacts.latest("visual_qa") if tc.artifacts else None
        data = live_qa or (qa or {}).get("data", {})
        issues = data.get("issues") or []
        severity = data.get("severity_counts") or {}
        qa_level = str(data.get("qa_level") or "geometry")
        qa_label = {"geometry": "几何 QA", "raster": "真实渲染 QA", "vision": "视觉 QA"}.get(qa_level, "QA")
        target_agents = sorted({issue.get("target_agent", "ppt_editor") for issue in issues if issue.get("severity") in {"critical", "major"}})
        return AgentDecision(
            completed=True,
            output=None,
            completed_artifact_id=(qa or {}).get("id"),
            summary=(
                f"{qa_label}：几何 {data.get('geometry_score', data.get('score', 0))}，"
                f"{severity.get('critical', 0)} 严重 / {severity.get('major', 0)} 主要问题"
            ),
            message=(
                f"{qa_label} 完成"
                + ("（视觉能力已降级）" if data.get("degraded") else "")
            ),
        )


VISUAL_QA_AGENT = VisualQaAgent()
