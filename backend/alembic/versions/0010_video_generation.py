"""Add video generation task, media bindings, and persistent scene jobs."""

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0010_video_generation"
down_revision = "0009_pipeline_tool_call_identity"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade():
    chat_columns = _columns("agent_chat_sessions")
    if "video_model_config_id" not in chat_columns:
        op.add_column("agent_chat_sessions", sa.Column("video_model_config_id", sa.String(36), nullable=True))
    if "speech_model_config_id" not in chat_columns:
        op.add_column("agent_chat_sessions", sa.Column("speech_model_config_id", sa.String(36), nullable=True))

    asset_columns = _columns("artifact_assets")
    if "duration_ms" not in asset_columns:
        op.add_column("artifact_assets", sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"))
    if "source_scene_id" not in asset_columns:
        op.add_column("artifact_assets", sa.Column("source_scene_id", sa.String(80), nullable=False, server_default=""))
        op.create_index("ix_artifact_assets_source_scene_id", "artifact_assets", ["source_scene_id"])
    if "metadata_json" not in asset_columns:
        op.add_column("artifact_assets", sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"))

    inspector = sa.inspect(op.get_bind())
    if "video_scene_jobs" not in inspector.get_table_names():
        op.create_table(
            "video_scene_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("generation_run_id", sa.String(36), sa.ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("course_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_artifact_id", sa.String(36), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("scene_id", sa.String(80), nullable=False),
            sa.Column("operation", sa.String(40), nullable=False, server_default="generate"),
            sa.Column("provider_job_id", sa.String(200), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("input_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("output_asset_id", sa.String(36), sa.ForeignKey("artifact_assets.id", ondelete="SET NULL"), nullable=True),
            sa.Column("error_json", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("generation_run_id", "scene_id", "attempt"),
        )
        for column in ("generation_run_id", "course_id", "source_artifact_id", "scene_id", "provider_job_id", "status"):
            op.create_index(f"ix_video_scene_jobs_{column}", "video_scene_jobs", [column])

    if "course_tasks" in inspector.get_table_names():
        op.execute("UPDATE course_tasks SET display_order = 7 WHERE task_type = 'verbatim'")
        bind = op.get_bind()
        metadata = sa.MetaData()
        task_table = sa.Table("course_tasks", metadata, autoload_with=bind)
        existing_course_ids = set(bind.execute(sa.text(
            "SELECT course_id FROM course_tasks WHERE task_type = 'video_generation'"
        )).scalars())
        course_ids = list(bind.execute(sa.text("SELECT id FROM course_projects")).scalars())
        now = datetime.now(timezone.utc)
        rows = []
        for course_id in course_ids:
            if course_id in existing_course_ids:
                continue
            dependency_count = bind.execute(sa.text(
                "SELECT COUNT(DISTINCT artifact_type) FROM artifacts "
                "WHERE course_id = :course_id AND artifact_type IN ('video_script', 'ppt')"
            ), {"course_id": course_id}).scalar_one()
            rows.append({
                "id": str(uuid4()),
                "course_id": course_id,
                "task_type": "video_generation",
                "agent_type": "video_generation_pipeline",
                "display_order": 6,
                "status": "ready_to_generate" if dependency_count == 2 else "waiting_dependency",
                "progress": 0,
                "dependency_types_json": ["video_script", "ppt"],
                "agent_profile_status": "ready",
                "created_at": now,
                "updated_at": now,
            })
        if rows:
            bind.execute(task_table.insert(), rows)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "video_scene_jobs" in inspector.get_table_names():
        op.drop_table("video_scene_jobs")
    asset_columns = _columns("artifact_assets")
    if "metadata_json" in asset_columns:
        op.drop_column("artifact_assets", "metadata_json")
    if "source_scene_id" in asset_columns:
        op.drop_column("artifact_assets", "source_scene_id")
    if "duration_ms" in asset_columns:
        op.drop_column("artifact_assets", "duration_ms")
    chat_columns = _columns("agent_chat_sessions")
    if "speech_model_config_id" in chat_columns:
        op.drop_column("agent_chat_sessions", "speech_model_config_id")
    if "video_model_config_id" in chat_columns:
        op.drop_column("agent_chat_sessions", "video_model_config_id")
    if "course_tasks" in inspector.get_table_names():
        op.execute("DELETE FROM course_tasks WHERE task_type = 'video_generation'")
        op.execute("UPDATE course_tasks SET display_order = 6 WHERE task_type = 'verbatim'")
