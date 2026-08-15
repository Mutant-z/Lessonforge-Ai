"""Add Gemini Interactions resume metadata to video scene jobs."""

import sqlalchemy as sa
from alembic import op


revision = "0015_gemini_interactions_video"
down_revision = "0014_agent_run_instructions"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "video_scene_jobs" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("video_scene_jobs")}


def upgrade():
    columns = _columns()
    additions = {
        "api_mode": sa.Column("api_mode", sa.String(50), nullable=False, server_default=""),
        "provider_file_id": sa.Column("provider_file_id", sa.String(200), nullable=False, server_default=""),
        "actual_model_name": sa.Column("actual_model_name", sa.String(120), nullable=False, server_default=""),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("video_scene_jobs", column)
    if "provider_file_id" not in columns:
        op.create_index("ix_video_scene_jobs_provider_file_id", "video_scene_jobs", ["provider_file_id"])


def downgrade():
    columns = _columns()
    if "provider_file_id" in columns:
        op.drop_index("ix_video_scene_jobs_provider_file_id", table_name="video_scene_jobs")
    for name in ("actual_model_name", "provider_file_id", "api_mode"):
        if name in columns:
            op.drop_column("video_scene_jobs", name)
