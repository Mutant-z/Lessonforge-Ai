"""Add agent_run_instructions table for mid-run instruction merging (task sheet runtime)."""
from alembic import op
import sqlalchemy as sa


revision = "0014_agent_run_instructions"
down_revision = "0013_agent_human_requests"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "agent_run_instructions" not in existing:
        op.create_table(
            "agent_run_instructions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("message_id", sa.String(36), sa.ForeignKey("agent_messages.id", ondelete="SET NULL"), nullable=True),
            sa.Column("client_instruction_id", sa.String(120), nullable=False, server_default=""),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("applied_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_run_instructions_run", "agent_run_instructions", ["pipeline_run_id"])
        op.create_index("ix_agent_run_instructions_status", "agent_run_instructions", ["status"])
        op.create_index("ix_agent_run_instructions_client", "agent_run_instructions", ["client_instruction_id"])
        op.create_index("ix_agent_run_instructions_message", "agent_run_instructions", ["message_id"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "agent_run_instructions" in inspector.get_table_names():
        op.drop_table("agent_run_instructions")
