"""Store PPT polish scope and modality outside the visible message text."""

from alembic import op
import sqlalchemy as sa


revision = "0011_ppt_polish_command_metadata"
down_revision = "0010_video_generation"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("agent_messages")}
    if "metadata_json" not in columns:
        op.add_column(
            "agent_messages",
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("agent_messages")}
    if "metadata_json" in columns:
        op.drop_column("agent_messages", "metadata_json")
