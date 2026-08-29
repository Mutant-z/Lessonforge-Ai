"""Allow a general-purpose model configuration to generate video."""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text


revision = "0018_general_purpose_video_models"
down_revision = "0017_unify_video_model_configs"
branch_labels = None
depends_on = None


def _caps(value) -> list[str]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def upgrade() -> None:
    bind = op.get_bind()
    owners = bind.execute(text("SELECT DISTINCT owner_id FROM model_configs")).fetchall()
    for (owner_id,) in owners:
        selected = bind.execute(text("""
            SELECT id, capabilities_json
            FROM model_configs
            WHERE owner_id=:owner_id
              AND provider IN ('openai_compatible', 'anthropic')
              AND model_purpose IN ('text_chat', 'vision_chat')
              AND is_active=true AND is_archived=false
            ORDER BY CASE WHEN model_name LIKE 'gemini-3.7%' THEN 0 ELSE 1 END,
                     updated_at DESC
            LIMIT 1
        """), {"owner_id": owner_id}).mappings().first()
        if not selected:
            continue
        capabilities = _caps(selected["capabilities_json"])
        for capability in ("video_generation", "native_audio_video_generation"):
            if capability not in capabilities:
                capabilities.append(capability)
        bind.execute(text("""
            UPDATE model_configs
            SET capabilities_json=:capabilities, api_mode='openai_chat_video'
            WHERE id=:config_id
        """), {
            "config_id": selected["id"],
            "capabilities": json.dumps(capabilities, ensure_ascii=False),
        })
        bind.execute(text("""
            UPDATE agent_chat_sessions
            SET video_model_config_id=:config_id
            WHERE course_id IN (SELECT id FROM course_projects WHERE owner_id=:owner_id)
              AND module_type='video_generation'
        """), {"owner_id": owner_id, "config_id": selected["id"]})
        bind.execute(text("""
            UPDATE model_configs
            SET is_active=false, is_archived=true
            WHERE owner_id=:owner_id
              AND api_mode='gemini_interactions_video'
              AND model_name='gemini-omni-flash-preview'
        """), {"owner_id": owner_id})


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(text("""
        SELECT id, capabilities_json FROM model_configs
        WHERE api_mode='openai_chat_video'
          AND model_purpose IN ('text_chat', 'vision_chat')
    """)).mappings().all()
    for row in rows:
        capabilities = [
            item for item in _caps(row["capabilities_json"])
            if item not in {"video_generation", "native_audio_video_generation"}
        ]
        bind.execute(text("""
            UPDATE model_configs
            SET capabilities_json=:capabilities, api_mode='text_chat'
            WHERE id=:config_id
        """), {
            "config_id": row["id"],
            "capabilities": json.dumps(capabilities, ensure_ascii=False),
        })
