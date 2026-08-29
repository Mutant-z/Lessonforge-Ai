"""Unify native video configs and archive legacy media helpers."""

import json

from alembic import op
import sqlalchemy as sa


revision = "0017_unify_video_model_configs"
down_revision = "0016_model_config_categories"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("model_configs")}
    if "is_archived" not in columns:
        with op.batch_alter_table("model_configs") as batch:
            batch.add_column(sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("model_configs")}
    if "ix_model_configs_is_archived" not in indexes:
        op.create_index("ix_model_configs_is_archived", "model_configs", ["is_archived"])

    rows = bind.execute(sa.text("""
        SELECT id, api_mode, model_name, adapter_config_json
        FROM model_configs WHERE model_category='video'
    """)).mappings().all()
    def positive(value) -> bool:
        try:
            return float(value or 0) > 0
        except (TypeError, ValueError):
            return False

    for row in rows:
        adapter = row["adapter_config_json"] or {}
        if isinstance(adapter, str):
            try:
                adapter = json.loads(adapter)
            except json.JSONDecodeError:
                adapter = {}
        gemini_ready = (
            row["api_mode"] == "gemini_interactions_video"
            and row["model_name"] == "gemini-omni-flash-preview"
        )
        seedance_ready = (
            row["api_mode"] == "volcengine_ark_video"
            and adapter.get("model_family") == "doubao-seedance-2.5"
            and positive(adapter.get("price_per_million_tokens_cny"))
            and positive(adapter.get("tokens_per_second_720p"))
        )
        if gemini_ready or seedance_ready:
            bind.execute(sa.text("""
                UPDATE model_configs
                SET model_purpose='video_generation',
                    capabilities_json=:capabilities,
                    is_archived=false
                WHERE id=:id
            """), {
                "id": row["id"],
                "capabilities": json.dumps(["video_generation", "native_audio_video_generation"]),
            })
        else:
            bind.execute(sa.text("""
                UPDATE model_configs SET is_active=false, is_archived=true WHERE id=:id
            """), {"id": row["id"]})
    tables = set(sa.inspect(bind).get_table_names())
    if "agent_chat_sessions" in tables:
        bind.execute(sa.text("UPDATE agent_chat_sessions SET speech_model_config_id=NULL"))
        bind.execute(sa.text("""
            UPDATE agent_chat_sessions
            SET video_model_config_id=NULL
            WHERE video_model_config_id IN (
                SELECT id FROM model_configs WHERE is_archived=true
            )
        """))

    owners = bind.execute(sa.text("SELECT DISTINCT owner_id FROM model_configs")).scalars().all()
    for owner_id in owners:
        candidate = bind.execute(sa.text("""
            SELECT id FROM model_configs
            WHERE owner_id=:owner_id AND model_category='video'
              AND model_purpose='video_generation' AND is_archived=false
            ORDER BY updated_at DESC LIMIT 1
        """), {"owner_id": owner_id}).scalar()
        bind.execute(sa.text("""
            UPDATE model_configs SET is_active=false
            WHERE owner_id=:owner_id AND model_category='video'
        """), {"owner_id": owner_id})
        if candidate:
            bind.execute(sa.text("UPDATE model_configs SET is_active=true WHERE id=:id"), {"id": candidate})


def downgrade():
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("model_configs")}
    if "ix_model_configs_is_archived" in indexes:
        op.drop_index("ix_model_configs_is_archived", table_name="model_configs")
    with op.batch_alter_table("model_configs") as batch:
        batch.drop_column("is_archived")
