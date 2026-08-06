"""Agent Loop 结构化协议（工具调用驱动的 AgentDecision）。

所有 LLM 调用都通过 provider.structured() 返回 AgentDecision：
要么列出一批工具调用（工具执行后结果回喂上下文，再次调用 LLM），
要么标记完成（产出 Artifact，交给下一个 Agent）。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from uuid import uuid4


def _uid() -> str:
    return str(uuid4())


class ToolCall(BaseModel):
    """Agent 决策中的一次工具调用。"""

    id: str = Field(default_factory=_uid)
    tool_name: str
    input: dict[str, Any] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """Agent 单次 LLM 决策：思考过程 + 工具调用 或 完成（二选一）。

    thinking 字段用于流式输出：模型先输出思考过程（Markdown 文本，实时增量推送给前端），
    再输出结构化决策（tool_calls 或 completed）。
    """

    thinking: str = Field(default="", description="Agent 的实时思考过程（Markdown 文本，流式输出）")
    tool_calls: list[ToolCall] = Field(default_factory=list)
    completed: bool = False
    completed_artifact_id: str | None = None
    output: dict[str, Any] | None = Field(default=None, description="完成时产出的 Artifact 数据（由 loop 持久化）")
    message: str = Field(default="", description="面向用户的可见状态文案")
    progress: int | None = None
    handoff: str | None = Field(default=None, description="显式指定下一个 Agent key")
    summary: str = Field(default="", description="本 Agent 完成摘要（持久化 + 展示）")

    @model_validator(mode="after")
    def _xor_tools_or_completed(self) -> "AgentDecision":
        if self.tool_calls and self.completed:
            raise ValueError("AgentDecision 不能同时包含 tool_calls 与 completed")
        if not self.tool_calls and not self.completed:
            raise ValueError("AgentDecision 必须包含 tool_calls 或 completed")
        return self


class ToolResult(BaseModel):
    """一次工具调用的执行结果。"""

    ok: bool = True
    output: dict[str, Any] = Field(default_factory=dict)
    artifact_id: str | None = None
    error: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class AgentSpec(BaseModel):
    """执行计划中的一个 Agent 步骤。"""

    key: str
    role: str
    description: str = ""
    max_steps: int = 8


class PipelinePlan(BaseModel):
    """一次流水线运行的计划。"""

    agents: list[AgentSpec] = Field(default_factory=list)
    revision_rounds: int = 3

    def keys(self) -> list[str]:
        return [agent.key for agent in self.agents]


# ---------- 事件负载 ----------

class AgentStartedEvent(BaseModel):
    agent_key: str
    agent_label: str
    step_index: int
    progress: int | None = None


class AgentCompletedEvent(BaseModel):
    agent_key: str
    summary: str
    duration_ms: int = 0
    artifact_id: str | None = None
    progress: int | None = None


class ToolCallStartedEvent(BaseModel):
    tool_name: str
    tool_call_id: str
    input_summary: str = ""


class ToolCallCompletedEvent(BaseModel):
    tool_name: str
    tool_call_id: str
    ok: bool
    output_summary: str = ""
    duration_ms: int = 0
    error: str | None = None


class ArtifactCreatedEvent(BaseModel):
    artifact_type: str
    artifact_id: str
    name: str
    version: int
    producer_agent: str = ""


class QaCompletedEvent(BaseModel):
    score: float
    issues_count: int
    severity_counts: dict[str, int] = Field(default_factory=dict)
    round: int = 0
    degraded: bool = False


class RevisionStartedEvent(BaseModel):
    round: int
    max_rounds: int
    reason: str = ""
    target_agents: list[str] = Field(default_factory=list)


class RevisionCompletedEvent(BaseModel):
    round: int
    applied_changes: list[str] = Field(default_factory=list)


class PipelineCompletedEvent(BaseModel):
    artifact_id: str | None = None
    llm_calls: int = 0
    tokens: int = 0


class PipelineFailedEvent(BaseModel):
    error: str = ""


# ---------- 状态字面量 ----------

PipelineStatus = Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
ToolStatus = Literal["started", "completed", "failed"]
ArtifactStatus = Literal["draft", "validated", "approved", "superseded"]
