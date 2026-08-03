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


class GenerationEvent(Base):
    __tablename__ = "generation_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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
