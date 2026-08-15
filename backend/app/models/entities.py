from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="teacher")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CourseProject(Base, TimestampMixin):
    __tablename__ = "course_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(120))
    grade_level: Mapped[str] = mapped_column(String(120), default="")
    audience: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    scenario: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(20), default="中文")
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    current_blueprint_version: Mapped[int] = mapped_column(Integer, default=0)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[User] = relationship()


class CourseRequirement(Base, TimestampMixin):
    __tablename__ = "course_requirements"
    __table_args__ = (UniqueConstraint("course_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    form_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_prompt: Mapped[str] = mapped_column(Text, default="")
    assumptions_json: Mapped[list] = mapped_column(JSON, default=list)
    conflicts_json: Mapped[list] = mapped_column(JSON, default=list)


class CourseIntakeSession(Base, TimestampMixin):
    __tablename__ = "course_intake_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="collecting", index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    draft_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    field_sources_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    missing_fields_json: Mapped[list] = mapped_column(JSON, default=list)
    assumptions_json: Mapped[list] = mapped_column(JSON, default=list)
    conflicts_json: Mapped[list] = mapped_column(JSON, default=list)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("course_projects.id", ondelete="SET NULL"), nullable=True)
    confirm_key: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)


class CourseIntakeMessage(Base, TimestampMixin):
    __tablename__ = "course_intake_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("course_intake_sessions.id", ondelete="CASCADE"), index=True)
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("course_intake_turns.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)


class CourseIntakeRevision(Base, TimestampMixin):
    __tablename__ = "course_intake_revisions"
    __table_args__ = (UniqueConstraint("session_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("course_intake_sessions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    draft_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    field_sources_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    missing_fields_json: Mapped[list] = mapped_column(JSON, default=list)
    assumptions_json: Mapped[list] = mapped_column(JSON, default=list)
    conflicts_json: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(30), default="agent")


class CourseIntakeTurn(Base, TimestampMixin):
    __tablename__ = "course_intake_turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("course_intake_sessions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CourseIntakeEvent(Base):
    __tablename__ = "course_intake_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_id: Mapped[str] = mapped_column(ForeignKey("course_intake_turns.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Material(Base, TimestampMixin):
    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(
            "(course_id IS NOT NULL AND intake_session_id IS NULL) OR "
            "(course_id IS NULL AND intake_session_id IS NOT NULL)",
            name="ck_material_single_owner",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True, nullable=True)
    intake_session_id: Mapped[str | None] = mapped_column(ForeignKey("course_intake_sessions.id", ondelete="CASCADE"), index=True, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_name: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(Integer)
    usage_policy: Mapped[str] = mapped_column(String(50), default="priority_reference")
    parse_status: Mapped[str] = mapped_column(String(30), default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    checksum: Mapped[str] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaterialChunk(Base):
    __tablename__ = "material_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CourseBlueprint(Base, TimestampMixin):
    __tablename__ = "course_blueprints"
    __table_args__ = (UniqueConstraint("course_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_by: Mapped[str] = mapped_column(String(20), default="agent")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("course_id", "artifact_type", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer)
    blueprint_version: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    model_name: Mapped[str] = mapped_column(String(100), default="mock")
    prompt_version: Mapped[str] = mapped_column(String(30), default="v1")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    change_summary: Mapped[str] = mapped_column(String(500), default="首次生成")
    source_versions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    agent_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_task_agent_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 该版本创建时读取的项目记忆版本（用于追溯"产物基于哪一版记忆生成"）。
    memory_revision_created: Mapped[int] = mapped_column(Integer, default=0)


class ArtifactLock(Base, TimestampMixin):
    __tablename__ = "artifact_locks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"), index=True)
    json_path: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class GenerationRun(Base, TimestampMixin):
    __tablename__ = "generation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    course_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_task_agent_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    thread_id: Mapped[str] = mapped_column(String(100), unique=True)
    run_type: Mapped[str] = mapped_column(String(30), default="full")
    trigger_type: Mapped[str] = mapped_column(String(30), default="initial")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    current_node: Mapped[str] = mapped_column(String(60), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 本次运行读取的项目记忆版本与上下文快照（溯源：实际读了哪些 Artifact 版本）。
    memory_revision: Mapped[int] = mapped_column(Integer, default=0)
    context_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_hash: Mapped[str] = mapped_column(String(64), default="")
    #: 并行首稿批次标识：同一批并行启动的内容 Agent 共享同一记忆快照。
    batch_id: Mapped[str] = mapped_column(String(40), default="", index=True)


class GenerationStep(Base, TimestampMixin):
    __tablename__ = "generation_steps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    node_name: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    output_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class VideoSceneJob(Base, TimestampMixin):
    __tablename__ = "video_scene_jobs"
    __table_args__ = (UniqueConstraint("generation_run_id", "scene_id", "attempt"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    generation_run_id: Mapped[str] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("course_projects.id", ondelete="CASCADE"), index=True
    )
    source_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scene_id: Mapped[str] = mapped_column(String(80), index=True)
    operation: Mapped[str] = mapped_column(String(40), default="generate")
    provider_job_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    request_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    provider: Mapped[str] = mapped_column(String(50), default="")
    api_mode: Mapped[str] = mapped_column(String(50), default="")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    provider_file_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    actual_model_name: Mapped[str] = mapped_column(String(120), default="")
    reference_asset_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    actual_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    actual_cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    qa_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_assets.id", ondelete="SET NULL"), nullable=True
    )
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoGenerationQuote(Base, TimestampMixin):
    __tablename__ = "video_generation_quotes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("course_projects.id", ondelete="CASCADE"), index=True
    )
    script_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    model_config_id: Mapped[str] = mapped_column(
        ForeignKey("model_configs.id", ondelete="CASCADE"), index=True
    )
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scenes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    maximum_cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(10), default="CNY")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GenerationEvent(Base):
    __tablename__ = "generation_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PipelineRun(Base, TimestampMixin):
    """多 Agent 流水线运行（PPT 生成）——与 GenerationRun 1:1 子表。

    承载流水线专属状态（计划、checkpoint、token 用量、修订轮数），
    使共享的 GenerationRun 语义保持不变（蓝图/初始化/全部 6 任务共用）。
    """

    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    generation_run_id: Mapped[str] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    pipeline_type: Mapped[str] = mapped_column(String(30), default="ppt_agent_pipeline")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    current_agent: Mapped[str] = mapped_column(String(60), default="")
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    revision_round: Mapped[int] = mapped_column(Integer, default=0)
    max_revision_rounds: Mapped[int] = mapped_column(Integer, default=3)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    token_usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineArtifact(Base, TimestampMixin):
    """流水线内部 Artifact 图（版本化，依赖边 parent_id）。"""

    __tablename__ = "pipeline_artifacts"
    __table_args__ = (UniqueConstraint("pipeline_run_id", "artifact_type", "name", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120), default="default")
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    mime_type: Mapped[str] = mapped_column(String(100), default="application/json")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    producer_agent: Mapped[str] = mapped_column(String(60), default="")
    producer_tool: Mapped[str] = mapped_column(String(80), default="")
    created_by_step_index: Mapped[int] = mapped_column(Integer, default=0)
    dependencies_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PipelineToolCall(Base):
    __tablename__ = "pipeline_tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    # LLM/provider supplied ids are only scoped to one model response and may be
    # reused by later runs. Keep them for diagnostics, never as the row PK.
    model_call_id: Mapped[str] = mapped_column(String(120), default="")
    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    agent_key: Mapped[str] = mapped_column(String(60))
    tool_name: Mapped[str] = mapped_column(String(80), index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="started")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PPTRevision(Base, TimestampMixin):
    """Immutable presentation-level revision linked to the exported Artifact."""

    __tablename__ = "ppt_revisions"
    __table_args__ = (UniqueConstraint("course_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    pipeline_run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("ppt_revisions.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    template_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    change_summary: Mapped[str] = mapped_column(String(500), default="")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PPTSlideArtifact(Base, TimestampMixin):
    """Current state of one slide inside a presentation revision."""

    __tablename__ = "ppt_slide_artifacts"
    __table_args__ = (UniqueConstraint("ppt_revision_id", "slide_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ppt_revision_id: Mapped[str] = mapped_column(ForeignKey("ppt_revisions.id", ondelete="CASCADE"), index=True)
    pipeline_run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    slide_id: Mapped[str] = mapped_column(String(80), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="planned", index=True)
    qa_status: Mapped[str] = mapped_column(String(30), default="pending")
    preview_url: Mapped[str] = mapped_column(String(500), default="")
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PPTSlideRevision(Base, TimestampMixin):
    __tablename__ = "ppt_slide_revisions"
    __table_args__ = (UniqueConstraint("slide_artifact_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    slide_artifact_id: Mapped[str] = mapped_column(ForeignKey("ppt_slide_artifacts.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("ppt_slide_revisions.id", ondelete="SET NULL"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    change_summary: Mapped[str] = mapped_column(String(500), default="")


class PPTAgentInstruction(Base, TimestampMixin):
    __tablename__ = "ppt_agent_instructions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    selected_slide_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    disposition: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PPTHumanRequest(Base, TimestampMixin):
    __tablename__ = "ppt_human_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    request_type: Mapped[str] = mapped_column(String(60))
    prompt: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentHumanRequest(Base, TimestampMixin):
    """通用人工确认请求（教学设计等非 PPT 流水线复用）。

    字段与 ppt_human_requests 完全领域无关；PPT 专用表保持兼容不迁移。
    """

    __tablename__ = "agent_human_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    request_type: Mapped[str] = mapped_column(String(60))
    prompt: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRunInstruction(Base, TimestampMixin):
    """运行中追加的教师指令（方案 §3.2 持久化）。

    client_instruction_id 用于幂等提交；status 为 queued/merged/superseded/cancelled。
    运行在每次工具完成、Agent 完成和 LLM 调用前的安全边界原子消费 queued 指令，
    合并到当前目标并触发意图重识别（plan.revised）。
    """

    __tablename__ = "agent_run_instructions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_instruction_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PPTTemplateProfile(Base, TimestampMixin):
    __tablename__ = "ppt_template_profiles"
    __table_args__ = (UniqueConstraint("template_id", "template_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    template_id: Mapped[str] = mapped_column(String(120), index=True)
    template_hash: Mapped[str] = mapped_column(String(64))
    catalog_version: Mapped[str] = mapped_column(String(40), default="")
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preview_urls_json: Mapped[list] = mapped_column(JSON, default=list)


class QualityReport(Base, TimestampMixin):
    __tablename__ = "quality_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("generation_runs.id"), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")


class QualityIssue(Base, TimestampMixin):
    __tablename__ = "quality_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    report_id: Mapped[str] = mapped_column(ForeignKey("quality_reports.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    location: Mapped[str] = mapped_column(String(300))
    dimension: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    target_agent: Mapped[str] = mapped_column(String(50), default="supervisor")
    required_action: Mapped[str] = mapped_column(String(50), default="revise")
    status: Mapped[str] = mapped_column(String(20), default="open")


class FileRecord(Base, TimestampMixin):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    file_type: Mapped[str] = mapped_column(String(40))
    relative_path: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))


class ArtifactAsset(Base, TimestampMixin):
    __tablename__ = "artifact_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    generation_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    json_path: Mapped[str] = mapped_column(String(500), default="")
    asset_type: Mapped[str] = mapped_column(String(40), default="generated_image")
    relative_path: Mapped[str] = mapped_column(String(500))
    preview_relative_path: Mapped[str] = mapped_column(String(500), default="")
    mime_type: Mapped[str] = mapped_column(String(100), default="image/png")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    source_scene_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(50), default="")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    review_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PromptTemplate(Base, TimestampMixin):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("agent_type", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    agent_type: Mapped[str] = mapped_column(String(50), index=True)
    version: Mapped[str] = mapped_column(String(30))
    system_prompt: Mapped[str] = mapped_column(Text)
    task_template: Mapped[str] = mapped_column(Text)
    output_schema_version: Mapped[str] = mapped_column(String(30), default="v1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ModelConfig(Base, TimestampMixin):
    __tablename__ = "model_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="LLM 配置")
    provider: Mapped[str] = mapped_column(String(50), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=90)
    context_window_tokens: Mapped[int] = mapped_column(Integer, default=1_000_000)
    supports_multimodal: Mapped[bool] = mapped_column(Boolean, default=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    api_mode: Mapped[str] = mapped_column(String(50), default="text_chat")
    adapter_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    preferences_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentChatSession(Base, TimestampMixin):
    __tablename__ = "agent_chat_sessions"
    __table_args__ = (UniqueConstraint("course_id", "module_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("course_projects.id", ondelete="CASCADE"), index=True
    )
    module_type: Mapped[str] = mapped_column(String(40), index=True)
    model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    image_model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vision_model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    video_model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    speech_model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )


class AgentMessage(Base, TimestampMixin):
    __tablename__ = "agent_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("course_projects.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    module_type: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # Scope/modality are execution metadata, not user-authored prose.  Keeping
    # them structured prevents UI labels such as [活动页面] from polluting LLM
    # intent parsing and the visible conversation transcript.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)


class CourseTask(Base, TimestampMixin):
    __tablename__ = "course_tasks"
    __table_args__ = (UniqueConstraint("course_id", "task_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("course_projects.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(40), index=True)
    agent_type: Mapped[str] = mapped_column(String(60))
    display_order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="waiting_dependency", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    dependency_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: 共享项目记忆时代的可选参考来源（不再控制启动顺序，仅影响上下文快照内容）。
    optional_reference_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: 运行输入契约：执行时必须满足的事实条件（如视频生成必须存在 V3/V4 脚本）。
    required_input_contract_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: 该任务最近一次运行实际读取的项目记忆版本。
    last_context_revision: Mapped[int] = mapped_column(Integer, default=0)
    current_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )
    current_agent_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_task_agent_profiles.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    agent_profile_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    agent_profile_error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    active_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CourseTaskAgentProfile(Base, TimestampMixin):
    __tablename__ = "course_task_agent_profiles"
    __table_args__ = (UniqueConstraint("course_task_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("course_projects.id", ondelete="CASCADE"), index=True
    )
    course_task_id: Mapped[str] = mapped_column(
        ForeignKey("course_tasks.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(40), index=True)
    agent_type: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer)
    initialization_run_id: Mapped[str] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True
    )
    prompt_template_id: Mapped[str] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="RESTRICT"), index=True
    )
    template_version: Mapped[str] = mapped_column(String(30))
    requirement_version: Mapped[int] = mapped_column(Integer)
    blueprint_version: Mapped[int] = mapped_column(Integer)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rendered_system_prompt: Mapped[str] = mapped_column(Text)
    rendered_task_template: Mapped[str] = mapped_column(Text)
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="initializing", index=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ProjectMemoryRevision(Base):
    """项目记忆版本流水：单调递增 revision，记录变更原因与来源。"""

    __tablename__ = "project_memory_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("course_projects.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, index=True)
    change_reason: Mapped[str] = mapped_column(String(300), default="")
    source_type: Mapped[str] = mapped_column(String(40), default="")
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(30), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProjectMemoryItem(Base, TimestampMixin):
    """共享项目记忆统一索引：需求/蓝图/材料/Artifact/决策/QA/对话摘要。

    原始文件与完整 Artifact 仍保留在各自表中；这里只存结构化摘要与引用，
    供 Agent 上下文快照、项目记忆面板与检索使用。按 course_id 严格隔离。
    """

    __tablename__ = "project_memory_items"
    __table_args__ = (UniqueConstraint("course_id", "source_type", "source_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("course_projects.id", ondelete="CASCADE"), index=True
    )
    #: requirement | blueprint | material | artifact | decision | qa | dialogue
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    source_version: Mapped[int] = mapped_column(Integer, default=0)
    artifact_type: Mapped[str] = mapped_column(String(40), default="")
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_ref: Mapped[str] = mapped_column(String(300), default="")
    keywords_json: Mapped[list] = mapped_column(JSON, default=list)
    trust_level: Mapped[str] = mapped_column(String(20), default="agent_generated")
    memory_revision: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_by: Mapped[str] = mapped_column(String(30), default="system")
