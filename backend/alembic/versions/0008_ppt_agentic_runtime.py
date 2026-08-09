"""Add PPT agentic runtime domain tables."""
from alembic import op
import sqlalchemy as sa


revision = "0008_ppt_agentic_runtime"
down_revision = "0007_ppt_agent_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "ppt_revisions" not in existing:
        op.create_table(
            "ppt_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("course_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL")),
            sa.Column("artifact_id", sa.String(36), sa.ForeignKey("artifacts.id", ondelete="SET NULL")),
            sa.Column("parent_id", sa.String(36), sa.ForeignKey("ppt_revisions.id", ondelete="SET NULL")),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("template_id", sa.String(120), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("change_summary", sa.String(500), nullable=False, server_default=""),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("course_id", "version"),
        )
        op.create_index("ix_ppt_revisions_course_id", "ppt_revisions", ["course_id"])
        op.create_index("ix_ppt_revisions_pipeline_run_id", "ppt_revisions", ["pipeline_run_id"])
    if "ppt_slide_artifacts" not in existing:
        op.create_table(
            "ppt_slide_artifacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("ppt_revision_id", sa.String(36), sa.ForeignKey("ppt_revisions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL")),
            sa.Column("slide_id", sa.String(80), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=False),
            sa.Column("current_revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(30), nullable=False, server_default="planned"),
            sa.Column("qa_status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("preview_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("data_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("ppt_revision_id", "slide_id"),
        )
        op.create_index("ix_ppt_slide_artifacts_revision", "ppt_slide_artifacts", ["ppt_revision_id"])
        op.create_index("ix_ppt_slide_artifacts_slide_id", "ppt_slide_artifacts", ["slide_id"])
    if "ppt_slide_revisions" not in existing:
        op.create_table(
            "ppt_slide_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("slide_artifact_id", sa.String(36), sa.ForeignKey("ppt_slide_artifacts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_id", sa.String(36), sa.ForeignKey("ppt_slide_revisions.id", ondelete="SET NULL")),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("data_json", sa.JSON(), nullable=False),
            sa.Column("diff_json", sa.JSON(), nullable=False),
            sa.Column("change_summary", sa.String(500), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("slide_artifact_id", "revision"),
        )
        op.create_index("ix_ppt_slide_revisions_slide", "ppt_slide_revisions", ["slide_artifact_id"])
    if "ppt_agent_instructions" not in existing:
        op.create_table(
            "ppt_agent_instructions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("pipeline_run_id", sa.String(36), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("selected_slide_ids_json", sa.JSON(), nullable=False),
            sa.Column("disposition", sa.String(30), nullable=False, server_default="queued"),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_ppt_agent_instructions_run", "ppt_agent_instructions", ["pipeline_run_id"])
    if "ppt_human_requests" not in existing:
        op.create_table(
            "ppt_human_requests",
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
        op.create_index("ix_ppt_human_requests_run", "ppt_human_requests", ["pipeline_run_id"])
    if "ppt_template_profiles" not in existing:
        op.create_table(
            "ppt_template_profiles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("template_id", sa.String(120), nullable=False),
            sa.Column("template_hash", sa.String(64), nullable=False),
            sa.Column("catalog_version", sa.String(40), nullable=False, server_default=""),
            sa.Column("profile_json", sa.JSON(), nullable=False),
            sa.Column("preview_urls_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("template_id", "template_hash"),
        )
        op.create_index("ix_ppt_template_profiles_template_id", "ppt_template_profiles", ["template_id"])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("ppt_template_profiles", "ppt_human_requests", "ppt_agent_instructions", "ppt_slide_revisions", "ppt_slide_artifacts", "ppt_revisions"):
        if table in existing:
            op.drop_table(table)
