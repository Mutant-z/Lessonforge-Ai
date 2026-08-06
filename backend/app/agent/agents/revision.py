"""修订 Agent：分析 QA 问题，判断归属（内容/布局/媒体/编辑）并调度对应 Agent 重跑。

Mock 路径：按 QA 问题携带的 target_agent 确定性路由；
LLM 路径：可结合问题描述与上下文自由路由。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision


class RevisionAgent(Agent):
    key = "revision"
    name = "修订 Agent"
    role = "分析视觉 QA 问题，路由到对应的内容/布局/媒体/编辑 Agent 重新处理"
    required_artifacts = ["visual_qa"]
    produced_artifacts = ["revision_note"]
    allowed_tools = ["get_qa_report"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        qa = await tc.artifacts.latest("visual_qa") if tc.artifacts else None
        data = (qa or {}).get("data", {})
        issues = data.get("issues") or []
        blocking = [item for item in issues if item.get("severity") in {"critical", "major"}]
        if not blocking:
            return AgentDecision(completed=True, output={"target_agents": [], "reason": "无阻断性问题"}, summary="无需修订")
        target_agents = sorted({item.get("target_agent", "layout") for item in blocking})
        target_agents = [key for key in target_agents if key in {"slide_content", "layout", "media", "ppt_editor"}]
        reason = "；".join(item.get("message", "")[:60] for item in blocking[:3])
        return AgentDecision(
            completed=True,
            output={"target_agents": target_agents, "reason": reason,
                    "issues": [{"severity": i.get("severity"), "slide_id": i.get("slide_id"), "message": i.get("message", "")} for i in blocking[:8]]},
            summary=f"问题归属：{'、'.join(target_agents) or '无'}",
            message="修订 Agent 已分类问题并调度对应 Agent",
        )


REVISION_AGENT = RevisionAgent()
