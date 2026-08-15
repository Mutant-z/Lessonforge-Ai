"""Add generic agent_human_requests table (non-PPT pipelines like lesson_plan)."""
from alembic import op
import sqlalchemy as sa


revision = "0013_agent_human_requests"
down_revision = "0012_seedance_native_video"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "agent_human_requests" not in existing:
        op.create_table(
            "agent_human_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("request_type", sa.String(60), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("options_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("response_json", sa.JSON(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_human_requests_run", "agent_human_requests", ["pipeline_run_id"])
        op.create_index("ix_agent_human_requests_status", "agent_human_requests", ["status"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "agent_human_requests" in inspector.get_table_names():
        op.drop_table("agent_human_requests")
