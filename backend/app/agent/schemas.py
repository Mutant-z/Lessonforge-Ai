"""Agent Loop 结构化协议（工具调用驱动的 AgentDecision）。

所有 LLM 调用都通过 provider.structured() 返回 AgentDecision：
要么列出一批工具调用（工具执行后结果回喂上下文，再次调用 LLM），
要么标记完成（产出 Artifact，交给下一个 Agent）。
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from uuid import uuid4

from app.schemas.artifact import PPTBlock


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


class LayoutElementSpec(BaseModel):
    """LLM 可执行的页面元素几何；坐标单位为英寸。"""

    # Common geometry remains strongly typed, while renderer-owned metadata
    # (asset identity, crop, chart data, editability flags) must round-trip.
    # Dropping those fields is data loss, especially for image_geometry-only
    # candidates that intentionally reuse the exact existing element.
    model_config = ConfigDict(extra="allow")

    kind: Literal["textbox", "shape", "image", "chart"] = "textbox"
    role: str = ""
    text: str = ""
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    style: dict[str, Any] = Field(default_factory=dict)
    shape_type: str = "rect"
    fill: str | None = None
    line: str | None = None
    file_path: str = ""
    content_ref: str = ""
    visual_slot: str = ""


class PageLayoutSpec(BaseModel):
    """一页可直接交给 layout_slide_batch 的布局结果。"""

    slide_id: str
    layout_type: str
    designRationale: str = ""
    elements: list[LayoutElementSpec] = Field(min_length=1)
    visual_region: dict[str, float] | None = None
    visual_type: str | None = None
    render_mode: Literal["semantic", "hybrid", "absolute"] = "absolute"
    compile_status: Literal["applied", "fallback", "preserved"] = "applied"
    requested_style: dict[str, Any] = Field(default_factory=dict)
    effective_style: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    content_allocation: dict[str, list[str]] = Field(default_factory=dict)
    compile_attempts: list[dict[str, Any]] = Field(default_factory=list)
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    final_metrics: dict[str, Any] = Field(default_factory=dict)
    quality_delta: float = 0.0
    objective_results: list[dict[str, Any]] = Field(default_factory=list)
    requested_objectives: list[dict[str, Any]] = Field(default_factory=list)
    candidate_rankings: list[dict[str, Any]] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    material_change: bool = True
    candidate_score_gap: float | None = None
    requires_candidate_confirmation: bool = False


class SlideLayoutArtifact(BaseModel):
    """布局 Agent 的强类型产物，防止模型只返回自然语言建议。"""

    slides: list[PageLayoutSpec] = Field(min_length=1)


class LayoutStyle(BaseModel):
    """Strongly typed layout controls consumed by every deterministic preset."""

    model_config = ConfigDict(extra="forbid")

    font_tier: Literal["default", "compact", "spacious"] = "default"
    font_scale: float = Field(default=1.0, ge=0.8, le=1.25)
    gap_scale: float = Field(default=1.0, ge=0.8, le=1.5)
    highlight: bool = False


class LayoutDirectiveSlide(BaseModel):
    """LLM 输出的语义版式指令：不携带像素坐标，坐标由确定性引擎计算。

    该 schema 必须区别于旧坐标格式（旧格式带 elements），
    以保证 _ensure_executable_layout 能识别出 directive 并走引擎编译路径。
    """

    slide_id: str = Field(min_length=1)
    layout_type: str = "bullet_flow"
    content_allocation: dict[str, list[str]] = Field(default_factory=dict)
    style: LayoutStyle = Field(default_factory=LayoutStyle)
    visual_region: dict[str, float] | None = None
    visual_type: str | None = None
    rationale: str = ""


class LayoutDirectiveArtifact(BaseModel):
    """布局 Agent 的语义产物：每页一条 LayoutDirective，交引擎编译为可执行坐标。"""

    slides: list[LayoutDirectiveSlide] = Field(min_length=1)


class VisualPlacement(BaseModel):
    """A bounded image region in slide inches."""

    x: float = Field(ge=0, le=13.333)
    y: float = Field(ge=0, le=7.5)
    w: float = Field(gt=0, le=13.333)
    h: float = Field(gt=0, le=7.5)

    @model_validator(mode="after")
    def _inside_slide(self) -> "VisualPlacement":
        if self.x + self.w > 13.333 + 0.01 or self.y + self.h > 7.5 + 0.01:
            raise ValueError("视觉素材坐标超出幻灯片画布")
        return self


class VisualRequest(BaseModel):
    """One concrete, executable visual-generation request."""

    slide_id: str = Field(min_length=1)
    asset_name: str = Field(min_length=1)
    visual_type: Literal["ai_image", "image", "diagram", "chart"] = "ai_image"
    prompt: str = Field(min_length=1)
    purpose: str = ""
    placement: VisualPlacement
    aspect_ratio: str = "4:3"
    visual_slot: str = "primary_visual"


class VisualPlanArtifact(BaseModel):
    """Canonical visual-plan boundary consumed by Media and Editor."""

    requests: list[VisualRequest] = Field(min_length=1)


class MutationEvidence(BaseModel):
    """Proof that a requested mutation was really applied to the current run."""

    kind: Literal["slide_content", "layout", "image"]
    slide_id: str
    tool_name: str
    asset_id: str = ""
    element_id: str = ""


class SlideContentPatchItem(BaseModel):
    """Validated page patch returned by the content agent."""

    id: str = Field(min_length=1)
    changed_fields: list[Literal["title", "purpose", "body", "blocks", "speaker_notes"]] = Field(min_length=1)
    title: str | None = None
    purpose: str | None = None
    body: list[str] | None = None
    blocks: list[PPTBlock] | None = None
    speaker_notes: str | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _changed_fields_match_payload(self) -> "SlideContentPatchItem":
        declared = set(self.changed_fields)
        provided = self.model_fields_set & {"title", "purpose", "body", "blocks", "speaker_notes"}
        if declared != provided:
            raise ValueError("changed_fields 必须与实际提供的语义字段完全一致")
        return self


class SlideContentPatch(BaseModel):
    slides: list[SlideContentPatchItem] = Field(min_length=1)


class ToolResult(BaseModel):
    """一次工具调用的执行结果。"""

    ok: bool = True
    output: dict[str, Any] = Field(default_factory=dict)
    artifact_id: str | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False
    events: list[dict[str, Any]] = Field(default_factory=list)


class PPTAgentError(RuntimeError):
    """Stable runtime failure carried from Agent/Tool through the task service."""

    def __init__(self, code: str, message: str, *, retryable: bool = True, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable
        self.details = details or {}


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


class OrchestratorPlanDecision(BaseModel):
    """LLM-selected initial graph plan; invalid/unknown entries are filtered by Runtime."""

    agents: list[str] = Field(default_factory=list)
    skill_capabilities: list[str] = Field(default_factory=list)
    summary: str = ""


class OrchestratorActionDecision(BaseModel):
    """Re-planning decision made after observing an Agent/tool/artifact result."""

    action: Literal["delegate", "finish"] = "delegate"
    next_agent: str | None = None
    discover_capabilities: list[str] = Field(default_factory=list)
    summary: str = ""


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
    qa_level: Literal["geometry", "raster", "vision"] = "geometry"
    geometry_score: float | None = None
    visual_quality_score: float | None = None
    improvement_delta: float = 0.0


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
