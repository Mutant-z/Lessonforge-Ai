"""Add model capabilities and persistent Agent model selection."""

from alembic import op
import sqlalchemy as sa

revision = "0003_model_selection"
down_revision = "0002_course_intake"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    model_columns = _columns(inspector, "model_configs")
    with op.batch_alter_table("model_configs") as batch:
        if "context_window_tokens" not in model_columns:
            batch.add_column(sa.Column(
                "context_window_tokens", sa.Integer(), nullable=False, server_default="1000000"
            ))
        if "supports_multimodal" not in model_columns:
            batch.add_column(sa.Column(
                "supports_multimodal", sa.Boolean(), nullable=False, server_default=sa.false()
            ))

    course_columns = _columns(inspector, "course_projects")
    if "model_config_id" not in course_columns:
        with op.batch_alter_table("course_projects") as batch:
            batch.add_column(sa.Column("model_config_id", sa.String(36), nullable=True))
            batch.create_index("ix_course_projects_model_config_id", ["model_config_id"])

    intake_columns = _columns(inspector, "course_intake_sessions")
    if "model_config_id" not in intake_columns:
        with op.batch_alter_table("course_intake_sessions") as batch:
            batch.add_column(sa.Column("model_config_id", sa.String(36), nullable=True))
            batch.create_index("ix_course_intake_sessions_model_config_id", ["model_config_id"])

    inspector = sa.inspect(bind)
    if "agent_chat_sessions" not in inspector.get_table_names():
        op.create_table(
            "agent_chat_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "course_id", sa.String(36),
                sa.ForeignKey("course_projects.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("module_type", sa.String(40), nullable=False),
            sa.Column(
                "model_config_id", sa.String(36),
                sa.ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("course_id", "module_type"),
        )
        op.create_index("ix_agent_chat_sessions_course_id", "agent_chat_sessions", ["course_id"])
        op.create_index("ix_agent_chat_sessions_module_type", "agent_chat_sessions", ["module_type"])
        op.create_index("ix_agent_chat_sessions_model_config_id", "agent_chat_sessions", ["model_config_id"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "agent_chat_sessions" in inspector.get_table_names():
        op.drop_table("agent_chat_sessions")
    if "model_config_id" in _columns(inspector, "course_intake_sessions"):
        with op.batch_alter_table("course_intake_sessions") as batch:
            batch.drop_index("ix_course_intake_sessions_model_config_id")
            batch.drop_column("model_config_id")
    if "model_config_id" in _columns(inspector, "course_projects"):
        with op.batch_alter_table("course_projects") as batch:
            batch.drop_index("ix_course_projects_model_config_id")
            batch.drop_column("model_config_id")
    model_columns = _columns(inspector, "model_configs")
    with op.batch_alter_table("model_configs") as batch:
        if "supports_multimodal" in model_columns:
            batch.drop_column("supports_multimodal")
        if "context_window_tokens" in model_columns:
            batch.drop_column("context_window_tokens")
