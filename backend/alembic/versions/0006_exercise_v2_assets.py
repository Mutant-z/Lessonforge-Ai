"""Add exercise V2 visual model capabilities and immutable artifact assets."""

from alembic import op
import sqlalchemy as sa


revision = "0006_exercise_v2_assets"
down_revision = "0005_agent_profiles"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "artifact_assets" not in inspector.get_table_names():
        op.create_table(
            "artifact_assets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("course_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("generation_run_id", sa.String(36), sa.ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("artifact_id", sa.String(36), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("json_path", sa.String(500), nullable=False, server_default=""),
            sa.Column("asset_type", sa.String(40), nullable=False, server_default="generated_image"),
            sa.Column("relative_path", sa.String(500), nullable=False),
            sa.Column("preview_relative_path", sa.String(500), nullable=False, server_default=""),
            sa.Column("mime_type", sa.String(100), nullable=False, server_default="image/png"),
            sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checksum", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(50), nullable=False, server_default=""),
            sa.Column("model_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("review_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name in ("owner_id", "course_id", "generation_run_id", "artifact_id", "checksum", "status"):
            op.create_index(f"ix_artifact_assets_{name}", "artifact_assets", [name])

    additions = {
        "model_configs": (
            ("capabilities_json", sa.Column("capabilities_json", sa.JSON(), nullable=False, server_default="[]")),
            ("api_mode", sa.Column("api_mode", sa.String(50), nullable=False, server_default="text_chat")),
            ("adapter_config_json", sa.Column("adapter_config_json", sa.JSON(), nullable=False, server_default="{}")),
        ),
        "agent_chat_sessions": (
            ("image_model_config_id", sa.Column(
                "image_model_config_id", sa.String(36),
                sa.ForeignKey(
                    "model_configs.id", ondelete="SET NULL",
                    name="fk_agent_chat_sessions_image_model_config_id_model_configs",
                ), nullable=True,
            )),
            ("vision_model_config_id", sa.Column(
                "vision_model_config_id", sa.String(36),
                sa.ForeignKey(
                    "model_configs.id", ondelete="SET NULL",
                    name="fk_agent_chat_sessions_vision_model_config_id_model_configs",
                ), nullable=True,
            )),
        ),
    }
    for table, definitions in additions.items():
        existing = _columns(bind, table)
        with op.batch_alter_table(table) as batch:
            for name, column in definitions:
                if name not in existing:
                    batch.add_column(column)

    existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("agent_chat_sessions")}
    for name in ("image_model_config_id", "vision_model_config_id"):
        index_name = f"ix_agent_chat_sessions_{name}"
        if index_name not in existing_indexes:
            op.create_index(index_name, "agent_chat_sessions", [name])

    bind.execute(sa.text(
        "UPDATE model_configs SET capabilities_json = "
        "CASE WHEN supports_multimodal = 1 THEN '[\"text_generation\",\"structured_output\",\"vision_review\"]' "
        "ELSE '[\"text_generation\",\"structured_output\"]' END "
        "WHERE capabilities_json IS NULL OR capabilities_json = '[]'"
    ))


def downgrade():
    bind = op.get_bind()
    existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("agent_chat_sessions")}
    for name in ("ix_agent_chat_sessions_vision_model_config_id", "ix_agent_chat_sessions_image_model_config_id"):
        if name in existing_indexes:
            op.drop_index(name, table_name="agent_chat_sessions")
    for table, names in {
        "agent_chat_sessions": ("vision_model_config_id", "image_model_config_id"),
        "model_configs": ("adapter_config_json", "api_mode", "capabilities_json"),
    }.items():
        existing = _columns(bind, table)
        with op.batch_alter_table(table) as batch:
            for name in names:
                if name in existing:
                    batch.drop_column(name)
    if "artifact_assets" in sa.inspect(bind).get_table_names():
        op.drop_table("artifact_assets")
