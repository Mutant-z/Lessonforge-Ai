"""Use protocol-based video model configurations and persist verification state."""

import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0019_protocol_video_models"
down_revision = "0018_general_purpose_video_models"
branch_labels = None
depends_on = None


LEGACY_VIDEO_MODES = (
    "volcengine_ark_video",
    "gemini_interactions_video",
    "custom_video_async_http",
    "custom_speech_http",
    "volcengine_asr",
    "local_ffmpeg",
)


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("model_configs")}
    with op.batch_alter_table("model_configs") as batch:
        if "video_capability_status" not in columns:
            batch.add_column(sa.Column("video_capability_status", sa.String(20), nullable=False, server_default="unverified"))
        if "video_capability_error" not in columns:
            batch.add_column(sa.Column("video_capability_error", sa.Text(), nullable=False, server_default=""))
        if "video_capability_verified_at" not in columns:
            batch.add_column(sa.Column("video_capability_verified_at", sa.DateTime(timezone=True), nullable=True))

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("model_configs")}
    if "ix_model_configs_video_capability_status" not in indexes:
        op.create_index("ix_model_configs_video_capability_status", "model_configs", ["video_capability_status"])

    modes = ",".join(f"'{value}'" for value in LEGACY_VIDEO_MODES)
    bind.execute(sa.text(f"""
        UPDATE model_configs
        SET is_active=false, is_archived=true
        WHERE api_mode IN ({modes})
           OR (api_mode='mock_media' AND model_category='video')
           OR model_purpose IN ('speech_generation', 'speech_recognition', 'media_composition')
    """))
    shared_rows = bind.execute(sa.text("""
        SELECT * FROM model_configs
        WHERE provider IN ('openai_compatible', 'anthropic')
          AND is_archived=false
          AND model_purpose IN ('text_chat', 'vision_chat')
    """)).mappings().all()
    for row in shared_rows:
        raw_caps = row["capabilities_json"] or []
        if isinstance(raw_caps, str):
            try:
                raw_caps = json.loads(raw_caps)
            except ValueError:
                raw_caps = []
        if "video_generation" not in raw_caps:
            continue
        bind.execute(sa.text("""
            INSERT INTO model_configs (
                id, owner_id, name, provider, base_url, model_name, encrypted_api_key,
                timeout_seconds, context_window_tokens, supports_multimodal,
                capabilities_json, api_mode, adapter_config_json, model_category,
                model_purpose, is_archived, is_active, preferences_json,
                video_capability_status, video_capability_error,
                video_capability_verified_at, created_at, updated_at
            ) VALUES (
                :id, :owner_id, :name, :provider, :base_url, :model_name, :encrypted_api_key,
                :timeout_seconds, :context_window_tokens, false,
                :capabilities, 'protocol_video', :adapter, 'video',
                'video_generation', false, false, :preferences,
                'unverified', '', NULL, :created_at, :updated_at
            )
        """), {
            "id": str(uuid4()),
            "owner_id": row["owner_id"],
            "name": f"{row['name']}（视频）"[:100],
            "provider": row["provider"],
            "base_url": row["base_url"],
            "model_name": row["model_name"],
            "encrypted_api_key": row["encrypted_api_key"],
            "timeout_seconds": row["timeout_seconds"],
            "context_window_tokens": row["context_window_tokens"],
            "capabilities": json.dumps(["video_generation", "native_audio_video_generation"]),
            "adapter": json.dumps({}),
            "preferences": json.dumps(row["preferences_json"] or {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
        retained = [item for item in raw_caps if item not in {"video_generation", "native_audio_video_generation"}]
        bind.execute(sa.text("""
            UPDATE model_configs SET capabilities_json=:capabilities, api_mode='text_chat'
            WHERE id=:id
        """), {"id": row["id"], "capabilities": json.dumps(retained)})

    bind.execute(sa.text("""
        UPDATE model_configs
        SET model_category='video', model_purpose='video_generation',
            capabilities_json='["video_generation","native_audio_video_generation"]',
            api_mode='protocol_video', adapter_config_json='{}',
            video_capability_status='unverified', video_capability_error='',
            video_capability_verified_at=NULL
        WHERE provider IN ('openai_compatible', 'anthropic')
          AND is_archived=false
          AND model_purpose IN ('video_generation', 'native_audio_video_generation')
    """))
    bind.execute(sa.text("""
        UPDATE agent_chat_sessions
        SET video_model_config_id=NULL
        WHERE video_model_config_id IN (SELECT id FROM model_configs WHERE is_archived=true)
    """))
    owners = bind.execute(sa.text("SELECT DISTINCT owner_id FROM model_configs")).scalars().all()
    for owner_id in owners:
        candidate = bind.execute(sa.text("""
            SELECT id FROM model_configs
            WHERE owner_id=:owner_id AND model_purpose='video_generation'
              AND provider IN ('openai_compatible', 'anthropic')
              AND is_archived=false
            ORDER BY updated_at DESC LIMIT 1
        """), {"owner_id": owner_id}).scalar()
        bind.execute(sa.text("""
            UPDATE model_configs SET is_active=false
            WHERE owner_id=:owner_id AND model_category='video'
        """), {"owner_id": owner_id})
        if candidate:
            bind.execute(sa.text("UPDATE model_configs SET is_active=true WHERE id=:id"), {"id": candidate})


def downgrade() -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("model_configs")}
    if "ix_model_configs_video_capability_status" in indexes:
        op.drop_index("ix_model_configs_video_capability_status", table_name="model_configs")
    with op.batch_alter_table("model_configs") as batch:
        batch.drop_column("video_capability_verified_at")
        batch.drop_column("video_capability_error")
        batch.drop_column("video_capability_status")
