"""Add Seedance native-audio quotes and scene accounting."""

import sqlalchemy as sa
from alembic import op


revision = "0012_seedance_native_video"
down_revision = "0011_ppt_polish_command_metadata"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade():
    columns = _columns("video_scene_jobs")
    additions = {
        "request_hash": sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
        "provider": sa.Column("provider", sa.String(50), nullable=False, server_default=""),
        "model_name": sa.Column("model_name", sa.String(120), nullable=False, server_default=""),
        "reference_asset_ids_json": sa.Column("reference_asset_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        "estimated_tokens": sa.Column("estimated_tokens", sa.Integer(), nullable=False, server_default="0"),
        "actual_tokens": sa.Column("actual_tokens", sa.Integer(), nullable=False, server_default="0"),
        "estimated_cost_fen": sa.Column("estimated_cost_fen", sa.Integer(), nullable=False, server_default="0"),
        "actual_cost_fen": sa.Column("actual_cost_fen", sa.Integer(), nullable=False, server_default="0"),
        "usage_json": sa.Column("usage_json", sa.JSON(), nullable=False, server_default="{}"),
        "qa_json": sa.Column("qa_json", sa.JSON(), nullable=False, server_default="{}"),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("video_scene_jobs", column)
    if "request_hash" not in columns:
        op.create_index("ix_video_scene_jobs_request_hash", "video_scene_jobs", ["request_hash"])

    inspector = sa.inspect(op.get_bind())
    if "video_generation_quotes" not in inspector.get_table_names():
        op.create_table(
            "video_generation_quotes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("course_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("script_artifact_id", sa.String(36), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("model_config_id", sa.String(36), sa.ForeignKey("model_configs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("request_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("scenes_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("estimated_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_cost_fen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("maximum_cost_fen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="CNY"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name in ("owner_id", "course_id", "script_artifact_id", "model_config_id", "status", "expires_at"):
            op.create_index(f"ix_video_generation_quotes_{name}", "video_generation_quotes", [name])

    op.execute("UPDATE course_tasks SET dependency_types_json = '[\"lesson_plan\"]' WHERE task_type = 'video_script'")
    op.execute("UPDATE course_tasks SET dependency_types_json = '[\"video_script\"]' WHERE task_type = 'video_generation'")


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "video_generation_quotes" in inspector.get_table_names():
        op.drop_table("video_generation_quotes")
    for name in (
        "qa_json", "usage_json", "actual_cost_fen", "estimated_cost_fen", "actual_tokens",
        "estimated_tokens", "reference_asset_ids_json", "model_name", "provider", "request_hash",
    ):
        if name in _columns("video_scene_jobs"):
            op.drop_column("video_scene_jobs", name)
    op.execute("UPDATE course_tasks SET dependency_types_json = '[\"lesson_plan\", \"ppt\"]' WHERE task_type = 'video_script'")
    op.execute("UPDATE course_tasks SET dependency_types_json = '[\"video_script\", \"ppt\"]' WHERE task_type = 'video_generation'")
