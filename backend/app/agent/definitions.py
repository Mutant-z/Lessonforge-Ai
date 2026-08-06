"""Agent 定义注册表：key → Agent 实例，以及按触发类型生成执行计划。"""
from app.agent.agents.base import Agent
from app.agent.agents.layout import LAYOUT_AGENT
from app.agent.agents.media import MEDIA_AGENT
from app.agent.agents.narrative import NARRATIVE_AGENT
from app.agent.agents.ppt_editor import PPT_EDITOR_AGENT
from app.agent.agents.revision import REVISION_AGENT
from app.agent.agents.slide_content import SLIDE_CONTENT_AGENT
from app.agent.agents.template_analysis import TEMPLATE_ANALYSIS_AGENT
from app.agent.agents.visual_plan import VISUAL_PLAN_AGENT
from app.agent.agents.visual_qa import VISUAL_QA_AGENT

AGENTS: list[Agent] = [
    NARRATIVE_AGENT,
    TEMPLATE_ANALYSIS_AGENT,
    SLIDE_CONTENT_AGENT,
    VISUAL_PLAN_AGENT,
    LAYOUT_AGENT,
    MEDIA_AGENT,
    PPT_EDITOR_AGENT,
    VISUAL_QA_AGENT,
    REVISION_AGENT,
]

AGENT_BY_KEY: dict[str, Agent] = {agent.key: agent for agent in AGENTS}

# 完整初始流水线（各 Agent 职责 / 产物 / 工具 对齐需求 §7）
FULL_TRIGGER_AGENTS = [
    "narrative",
    "template_analysis",
    "slide_content",
    "visual_plan",
    "layout",
    "media",
    "ppt_editor",
    "visual_qa",
]


def agent_specs_for_trigger(trigger: str) -> list[dict]:
    """按触发类型返回 AgentSpec 列表。message 由服务直接驱动修订 Agent。"""
    if trigger in {"message"}:
        return []
    if trigger in {"sync_context"}:
        return ["template_analysis", "slide_content", "layout", "visual_qa"]
    return FULL_TRIGGER_AGENTS


def spec_for(key: str) -> dict:
    agent = AGENT_BY_KEY[key]
    return {
        "key": agent.key, "role": agent.role,
        "description": agent.description or agent.role, "max_steps": 8,
    }
