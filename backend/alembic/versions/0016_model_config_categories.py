"""Split model configurations into text, vision, and video categories."""

import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0016_model_config_categories"
down_revision = "0015_gemini_interactions_video"
branch_labels = None
depends_on = None


def _capabilities(value) -> list[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _purpose(caps: set[str], api_mode: str) -> tuple[str, str, list[str]]:
    if api_mode in {"volcengine_ark_video", "gemini_interactions_video"} and "native_audio_video_generation" in caps:
        return "video", "native_audio_video_generation", ["video_generation", "native_audio_video_generation"]
    if api_mode in {"custom_video_async_http", "volcengine_ark_video", "gemini_interactions_video", "mock_media"} and "video_generation" in caps:
        return "video", "video_generation", ["video_generation"]
    if api_mode in {"openai_images", "google_gemini_image", "custom_image_http", "mock_media"} and "image_generation" in caps:
        return "vision", "image_generation", ["image_generation"]
    if api_mode in {"custom_speech_http", "mock_media"} and "speech_generation" in caps:
        return "video", "speech_generation", ["speech_generation"]
    if api_mode in {"volcengine_asr", "mock_media"} and "speech_recognition" in caps:
        return "video", "speech_recognition", ["speech_recognition"]
    if api_mode in {"local_ffmpeg", "mock_media"} and "media_composition" in caps:
        return "video", "media_composition", ["media_composition"]
    if "vision_review" in caps:
        return "vision", "vision_chat", ["text_generation", "structured_output", "vision_review"]
    return "text", "text_chat", ["text_generation", "structured_output"]


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("model_configs")}
    with op.batch_alter_table("model_configs") as batch:
        if "model_category" not in columns:
            batch.add_column(sa.Column("model_category", sa.String(20), nullable=False, server_default="text"))
        if "model_purpose" not in columns:
            batch.add_column(sa.Column("model_purpose", sa.String(40), nullable=False, server_default="text_chat"))
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("model_configs")}
    for column in ("model_category", "model_purpose"):
        name = f"ix_model_configs_{column}"
        if name not in indexes:
            op.create_index(name, "model_configs", [column])

    rows = bind.execute(sa.text("SELECT * FROM model_configs")).mappings().all()
    duplicates: list[tuple[str, str, str]] = []
    insert_sql = sa.text("""
        INSERT INTO model_configs (
            id, owner_id, name, provider, base_url, model_name, encrypted_api_key,
            timeout_seconds, context_window_tokens, supports_multimodal,
            capabilities_json, api_mode, adapter_config_json, model_category,
            model_purpose, is_active, preferences_json, created_at, updated_at
        ) VALUES (
            :id, :owner_id, :name, :provider, :base_url, :model_name, :encrypted_api_key,
            :timeout_seconds, :context_window_tokens, :supports_multimodal,
            :capabilities_json, :api_mode, :adapter_config_json, :model_category,
            :model_purpose, :is_active, :preferences_json, :created_at, :updated_at
        )
    """)
    for row in rows:
        caps = set(_capabilities(row.get("capabilities_json")))
        has_text = bool(caps & {"text_generation", "structured_output"})
        category, purpose, canonical = _purpose(caps, row.get("api_mode") or "text_chat")
        needs_role_copy = has_text and category != "text"
        if needs_role_copy:
            bind.execute(sa.text("""
                UPDATE model_configs SET model_category='text', model_purpose='text_chat',
                capabilities_json=:caps, api_mode='text_chat', supports_multimodal=0
                WHERE id=:id
            """), {"id": row["id"], "caps": json.dumps(["text_generation", "structured_output"])} )
            copy_id = str(uuid4())
            copy_name = f"{row['name']}（{'视觉' if category == 'vision' else '视频'}）"[:100]
            bind.execute(insert_sql, {
                **dict(row), "id": copy_id, "name": copy_name,
                "capabilities_json": json.dumps(canonical), "model_category": category,
                "model_purpose": purpose, "supports_multimodal": purpose == "vision_chat",
                "is_active": False, "preferences_json": row.get("preferences_json") or "{}",
                "adapter_config_json": row.get("adapter_config_json") or "{}",
            })
            duplicates.append((row["id"], copy_id, purpose))
        else:
            bind.execute(sa.text("""
                UPDATE model_configs SET model_category=:category, model_purpose=:purpose,
                capabilities_json=:caps, supports_multimodal=:multimodal
                WHERE id=:id
            """), {
                "id": row["id"], "category": category, "purpose": purpose,
                "caps": json.dumps(canonical), "multimodal": purpose == "vision_chat",
            })

    tables = set(sa.inspect(bind).get_table_names())
    if "agent_chat_sessions" in tables:
        for source_id, copy_id, purpose in duplicates:
            field = {
                "vision_chat": "vision_model_config_id",
                "image_generation": "image_model_config_id",
                "speech_generation": "speech_model_config_id",
            }.get(purpose, "video_model_config_id")
            bind.execute(sa.text(
                f"UPDATE agent_chat_sessions SET {field}=:copy_id WHERE {field}=:source_id"
            ), {"copy_id": copy_id, "source_id": source_id})

    owners = bind.execute(sa.text("SELECT DISTINCT owner_id FROM model_configs")).scalars().all()
    for owner_id in owners:
        for category, purposes in {
            "vision": ("vision_chat",),
            "video": ("video_generation", "native_audio_video_generation"),
        }.items():
            candidate = bind.execute(sa.text("""
                SELECT id FROM model_configs
                WHERE owner_id=:owner_id AND model_category=:category
                  AND model_purpose IN :purposes
                ORDER BY updated_at DESC LIMIT 1
            """).bindparams(sa.bindparam("purposes", expanding=True)), {
                "owner_id": owner_id, "category": category, "purposes": purposes,
            }).scalar()
            if candidate:
                bind.execute(sa.text("UPDATE model_configs SET is_active=0 WHERE owner_id=:owner_id AND model_category=:category"), {"owner_id": owner_id, "category": category})
                bind.execute(sa.text("UPDATE model_configs SET is_active=1 WHERE id=:id"), {"id": candidate})


def downgrade():
    for name in ("ix_model_configs_model_purpose", "ix_model_configs_model_category"):
        if name in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("model_configs")}:
            op.drop_index(name, table_name="model_configs")
    with op.batch_alter_table("model_configs") as batch:
        batch.drop_column("model_purpose")
        batch.drop_column("model_category")
