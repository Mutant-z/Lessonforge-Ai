"""Separate persisted tool invocation ids from model supplied call ids."""
from alembic import op
import sqlalchemy as sa


revision = "0009_pipeline_tool_call_identity"
down_revision = "0008_ppt_agentic_runtime"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("pipeline_tool_calls")}
    if "model_call_id" not in columns:
        op.add_column(
            "pipeline_tool_calls",
            sa.Column("model_call_id", sa.String(120), nullable=False, server_default=""),
        )


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("pipeline_tool_calls")}
    if "model_call_id" in columns:
        op.drop_column("pipeline_tool_calls", "model_call_id")
