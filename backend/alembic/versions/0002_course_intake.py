"""Add conversational course intake sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0002_course_intake"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 uses Base.metadata.create_all(), so a fresh install executed against the
    # current model set already contains these objects. Existing 0001 databases do
    # not, and still need the explicit migration below.
    inspector = sa.inspect(op.get_bind())
    material_columns = {column["name"] for column in inspector.get_columns("materials")}
    if "course_intake_sessions" in inspector.get_table_names() and "intake_session_id" in material_columns:
        return
    op.create_table(
        "course_intake_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="collecting"),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("field_sources_json", sa.JSON(), nullable=False),
        sa.Column("missing_fields_json", sa.JSON(), nullable=False),
        sa.Column("assumptions_json", sa.JSON(), nullable=False),
        sa.Column("conflicts_json", sa.JSON(), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("course_projects.id", ondelete="SET NULL")),
        sa.Column("confirm_key", sa.String(120), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_intake_sessions_owner_id", "course_intake_sessions", ["owner_id"])
    op.create_index("ix_course_intake_sessions_status", "course_intake_sessions", ["status"])
    op.create_table(
        "course_intake_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("course_intake_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("error_json", sa.JSON()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_intake_turns_session_id", "course_intake_turns", ["session_id"])
    op.create_index("ix_course_intake_turns_status", "course_intake_turns", ["status"])
    op.create_table(
        "course_intake_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("course_intake_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("course_intake_turns.id", ondelete="SET NULL")),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_intake_messages_session_id", "course_intake_messages", ["session_id"])
    op.create_table(
        "course_intake_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("course_intake_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("field_sources_json", sa.JSON(), nullable=False),
        sa.Column("missing_fields_json", sa.JSON(), nullable=False),
        sa.Column("assumptions_json", sa.JSON(), nullable=False),
        sa.Column("conflicts_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "version"),
    )
    op.create_index("ix_course_intake_revisions_session_id", "course_intake_revisions", ["session_id"])
    op.create_table(
        "course_intake_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("course_intake_turns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_intake_events_turn_id", "course_intake_events", ["turn_id"])
    with op.batch_alter_table("materials") as batch:
        batch.alter_column("course_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("intake_session_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_material_intake_session", "course_intake_sessions", ["intake_session_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_materials_intake_session_id", ["intake_session_id"])
        batch.create_check_constraint(
            "ck_material_single_owner",
            "(course_id IS NOT NULL AND intake_session_id IS NULL) OR (course_id IS NULL AND intake_session_id IS NOT NULL)",
        )


def downgrade():
    with op.batch_alter_table("materials") as batch:
        batch.drop_constraint("ck_material_single_owner", type_="check")
        batch.drop_index("ix_materials_intake_session_id")
        batch.drop_constraint("fk_material_intake_session", type_="foreignkey")
        batch.drop_column("intake_session_id")
        batch.alter_column("course_id", existing_type=sa.String(36), nullable=False)
    for table in (
        "course_intake_events",
        "course_intake_revisions",
        "course_intake_messages",
        "course_intake_turns",
        "course_intake_sessions",
    ):
        op.drop_table(table)
