"""Add multi-agent PPT pipeline tables (PipelineRun / Artifact / ToolCall / Event)."""

from alembic import op
import sqlalchemy as sa


revision = "0007_ppt_agent_pipeline"
down_revision = "0006_exercise_v2_assets"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "pipeline_runs" not in existing:
        op.create_table(
            "pipeline_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("generation_run_id", sa.String(36), sa.ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("pipeline_type", sa.String(30), nullable=False, server_default="ppt_agent_pipeline"),
            sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
            sa.Column("current_agent", sa.String(60), nullable=False, server_default=""),
            sa.Column("current_step_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("revision_round", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_revision_rounds", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("plan_json", sa.JSON(), nullable=False),
            sa.Column("checkpoint_json", sa.JSON(), nullable=False),
            sa.Column("token_usage_json", sa.JSON(), nullable=False),
            sa.Column("error_json", sa.JSON(), nullable=True),
            sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_pipeline_runs_generation_run_id", "pipeline_runs", ["generation_run_id"], unique=True)

    if "pipeline_artifacts" not in existing:
        op.create_table(
            "pipeline_artifacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("artifact_type", sa.String(40), nullable=False),
            sa.Column("name", sa.String(120), nullable=False, server_default="default"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("parent_id", sa.String(36), sa.ForeignKey("pipeline_artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("data_json", sa.JSON(), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=False, server_default=""),
            sa.Column("mime_type", sa.String(100), nullable=False, server_default="application/json"),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("producer_agent", sa.String(60), nullable=False, server_default=""),
            sa.Column("producer_tool", sa.String(80), nullable=False, server_default=""),
            sa.Column("created_by_step_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("dependencies_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("pipeline_run_id", "artifact_type", "name", "version", name="uq_pipeline_artifacts_run_type_name_version"),
        )
        for name in ("pipeline_run_id", "artifact_type", "status"):
            op.create_index(f"ix_pipeline_artifacts_{name}", "pipeline_artifacts", [name])

    if "pipeline_tool_calls" not in existing:
        op.create_table(
            "pipeline_tool_calls",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("agent_key", sa.String(60), nullable=False, server_default=""),
            sa.Column("tool_name", sa.String(80), nullable=False),
            sa.Column("input_json", sa.JSON(), nullable=False),
            sa.Column("output_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="started"),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name in ("pipeline_run_id", "tool_name"):
            op.create_index(f"ix_pipeline_tool_calls_{name}", "pipeline_tool_calls", [name])

    if "pipeline_events" not in existing:
        op.create_table(
            "pipeline_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("data_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_pipeline_events_pipeline_run_id", "pipeline_events", ["pipeline_run_id"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table in ("pipeline_events", "pipeline_tool_calls", "pipeline_artifacts", "pipeline_runs"):
        if table in existing:
            op.drop_table(table)
