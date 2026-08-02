"""Add independent course tasks and task provenance."""

from alembic import op
import sqlalchemy as sa

revision = "0004_course_tasks"
down_revision = "0003_model_selection"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "course_tasks" not in inspector.get_table_names():
        op.create_table(
            "course_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("course_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_type", sa.String(40), nullable=False),
            sa.Column("agent_type", sa.String(60), nullable=False),
            sa.Column("display_order", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="waiting_dependency"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("dependency_types_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("current_artifact_id", sa.String(36), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("active_run_id", sa.String(36), nullable=True),
            sa.Column("error_json", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("course_id", "task_type"),
        )
        op.create_index("ix_course_tasks_course_id", "course_tasks", ["course_id"])
        op.create_index("ix_course_tasks_task_type", "course_tasks", ["task_type"])
        op.create_index("ix_course_tasks_status", "course_tasks", ["status"])

    for table, definitions in {
        "generation_runs": [
            ("course_task_id", sa.Column("course_task_id", sa.String(36), nullable=True)),
            ("trigger_type", sa.Column("trigger_type", sa.String(30), nullable=False, server_default="initial")),
        ],
        "artifacts": [
            ("source_versions_json", sa.Column("source_versions_json", sa.JSON(), nullable=False, server_default="{}")),
        ],
        "agent_messages": [
            ("task_id", sa.Column("task_id", sa.String(36), nullable=True)),
            ("run_id", sa.Column("run_id", sa.String(36), nullable=True)),
            ("status", sa.Column("status", sa.String(20), nullable=False, server_default="completed")),
        ],
    }.items():
        existing = _columns(sa.inspect(bind), table)
        with op.batch_alter_table(table) as batch:
            for name, column in definitions:
                if name not in existing:
                    batch.add_column(column)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, names in {
        "agent_messages": ("status", "run_id", "task_id"),
        "artifacts": ("source_versions_json",),
        "generation_runs": ("trigger_type", "course_task_id"),
    }.items():
        existing = _columns(inspector, table)
        with op.batch_alter_table(table) as batch:
            for name in names:
                if name in existing:
                    batch.drop_column(name)
    if "course_tasks" in inspector.get_table_names():
        op.drop_table("course_tasks")
