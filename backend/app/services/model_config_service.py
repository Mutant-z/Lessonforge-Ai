import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AgentChatSession, CourseProject, CourseTask, ModelConfig
from app.providers.llm.base import LLMProvider
from app.providers.llm.router import get_provider_for_config


DEFAULT_PURPOSES = {
    "text": ("text_chat",),
    "vision": ("vision_chat",),
    "video": ("video_generation",),
}

LEGACY_VIDEO_MODES = {
    "volcengine_ark_video", "gemini_interactions_video", "custom_video_async_http",
    "custom_speech_http", "volcengine_asr", "local_ffmpeg",
}


def normalize_model_preferences(value: Any) -> dict[str, Any]:
    """Return preferences as an object, including legacy double-encoded JSON values."""
    current = value
    for _ in range(2):
        if isinstance(current, dict):
            return current
        if not isinstance(current, str) or not current.strip():
            return {}
        try:
            current = json.loads(current)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return current if isinstance(current, dict) else {}


def model_config_matches_category(config: ModelConfig, model_category: str) -> bool:
    """Reject stale cross-category task bindings before choosing a model."""
    purposes = DEFAULT_PURPOSES.get(model_category, ())
    if config.is_archived or config.model_category != model_category or config.model_purpose not in purposes:
        return False
    if model_category == "video":
        capabilities = set(config.capabilities_json or [])
        return (
            config.provider in {"openai_compatible", "anthropic"}
            and config.api_mode == "protocol_video"
            and {"video_generation", "native_audio_video_generation"} <= capabilities
        )
    return True


async def reconcile_protocol_video_configs(db: AsyncSession) -> dict[str, int]:
    """Idempotently apply the protocol-video migration for deployments without Alembic startup."""
    configs = list(await db.scalars(select(ModelConfig).order_by(ModelConfig.updated_at.desc())))
    archived = created = normalized = cleared = preferences_repaired = recovered_tasks = 0

    for config in configs:
        preferences = normalize_model_preferences(config.preferences_json)
        if config.preferences_json != preferences:
            config.preferences_json = preferences
            preferences_repaired += 1
        if (
            config.api_mode in LEGACY_VIDEO_MODES
            or (config.api_mode == "mock_media" and config.model_category == "video")
            or config.model_purpose in {"speech_generation", "speech_recognition", "media_composition"}
        ):
            if not config.is_archived or config.is_active:
                config.is_archived = True
                config.is_active = False
                archived += 1

    active_configs = [item for item in configs if not item.is_archived]
    for source in active_configs:
        capabilities = list(source.capabilities_json or [])
        if (
            source.provider in {"openai_compatible", "anthropic"}
            and source.model_purpose in {"text_chat", "vision_chat"}
            and "video_generation" in capabilities
        ):
            duplicate = next((item for item in active_configs if (
                item.owner_id == source.owner_id
                and item.provider == source.provider
                and item.base_url == source.base_url
                and item.model_name == source.model_name
                and item.model_purpose == "video_generation"
            )), None)
            if duplicate is None:
                duplicate = ModelConfig(
                    owner_id=source.owner_id,
                    name=f"{source.name}（视频）"[:100],
                    provider=source.provider,
                    base_url=source.base_url,
                    model_name=source.model_name,
                    encrypted_api_key=source.encrypted_api_key,
                    timeout_seconds=source.timeout_seconds,
                    context_window_tokens=source.context_window_tokens,
                    supports_multimodal=False,
                    capabilities_json=["video_generation", "native_audio_video_generation"],
                    api_mode="protocol_video",
                    adapter_config_json={},
                    model_category="video",
                    model_purpose="video_generation",
                    is_archived=False,
                    is_active=False,
                    preferences_json={},
                    video_capability_status="unverified",
                    video_capability_error="",
                )
                db.add(duplicate)
                active_configs.append(duplicate)
                created += 1
            source.capabilities_json = [
                item for item in capabilities
                if item not in {"video_generation", "native_audio_video_generation"}
            ]
            if source.api_mode == "openai_chat_video":
                source.api_mode = "text_chat"
            normalized += 1

    for config in active_configs:
        if (
            config.provider in {"openai_compatible", "anthropic"}
            and config.model_purpose in {"video_generation", "native_audio_video_generation"}
        ):
            changed = (
                config.model_category != "video"
                or config.model_purpose != "video_generation"
                or config.api_mode != "protocol_video"
                or set(config.capabilities_json or []) != {"video_generation", "native_audio_video_generation"}
            )
            config.model_category = "video"
            config.model_purpose = "video_generation"
            config.api_mode = "protocol_video"
            config.capabilities_json = ["video_generation", "native_audio_video_generation"]
            config.adapter_config_json = {}
            if changed:
                config.video_capability_status = "unverified"
                config.video_capability_error = ""
                config.video_capability_verified_at = None
                normalized += 1

    await db.flush()
    sessions = list(await db.scalars(select(AgentChatSession)))
    courses = list(await db.scalars(select(CourseProject)))
    video_tasks = list(await db.scalars(select(CourseTask).where(CourseTask.task_type == "video_generation")))
    owner_by_course = {course.id: course.owner_id for course in courses}
    video_task_by_course = {task.course_id: task for task in video_tasks}
    config_by_id = {item.id: item for item in configs}
    for session in sessions:
        selected = config_by_id.get(session.video_model_config_id) if session.video_model_config_id else None
        if selected is not None and model_config_matches_category(selected, "video"):
            task = video_task_by_course.get(session.course_id) if session.module_type == "video_generation" else None
            if (
                task
                and task.status == "failed"
                and task.updated_at
                and selected.updated_at
                and task.updated_at < selected.updated_at
            ):
                task.status = "ready_to_generate"
                task.progress = 0
                task.active_run_id = None
                task.error_json = None
                recovered_tasks += 1
            continue
        owner_id = owner_by_course.get(session.course_id)
        candidates = [
            item for item in active_configs
            if item.owner_id == owner_id and model_config_matches_category(item, "video")
        ]
        replacement = next((item for item in candidates if item.is_active), candidates[0] if candidates else None)
        if session.video_model_config_id != (replacement.id if replacement else None):
            session.video_model_config_id = replacement.id if replacement else None
            cleared += 1
            task = video_task_by_course.get(session.course_id) if session.module_type == "video_generation" else None
            if task and task.status == "failed":
                task.status = "ready_to_generate"
                task.progress = 0
                task.active_run_id = None
                task.error_json = None
                recovered_tasks += 1

    owner_ids = {item.owner_id for item in active_configs}
    for owner_id in owner_ids:
        videos = [item for item in active_configs if item.owner_id == owner_id and item.model_purpose == "video_generation"]
        if videos and not any(item.is_active for item in videos):
            videos[0].is_active = True

    await db.commit()
    return {
        "archived": archived,
        "created": created,
        "normalized": normalized,
        "cleared": cleared,
        "preferences_repaired": preferences_repaired,
        "recovered_tasks": recovered_tasks,
    }


async def owned_model_config(
    db: AsyncSession,
    owner_id: str,
    config_id: str,
) -> ModelConfig:
    config = await db.scalar(
        select(ModelConfig).where(
            ModelConfig.id == config_id,
            ModelConfig.owner_id == owner_id,
            ModelConfig.is_archived.is_(False),
        )
    )
    if not config:
        raise HTTPException(404, "指定的模型配置不存在或无权访问")
    return config


async def resolve_model_config(
    db: AsyncSession,
    owner_id: str,
    preferred_id: str | None = None,
    model_category: str = "text",
) -> ModelConfig | None:
    if preferred_id:
        config = await db.scalar(
            select(ModelConfig).where(
                ModelConfig.id == preferred_id,
                ModelConfig.owner_id == owner_id,
                ModelConfig.is_archived.is_(False),
            )
        )
        if config and model_config_matches_category(config, model_category):
            return config
    config = await db.scalar(
        select(ModelConfig).where(
            ModelConfig.owner_id == owner_id,
            ModelConfig.model_category == model_category,
            ModelConfig.is_archived.is_(False),
            ModelConfig.is_active.is_(True),
            ModelConfig.model_purpose.in_(DEFAULT_PURPOSES.get(model_category, ())),
        ).order_by(ModelConfig.updated_at.desc())
    )
    if config:
        return config
    return await db.scalar(
        select(ModelConfig).where(
            ModelConfig.owner_id == owner_id,
            ModelConfig.model_category == model_category,
            ModelConfig.is_archived.is_(False),
            ModelConfig.model_purpose.in_(DEFAULT_PURPOSES.get(model_category, ())),
        )
        .order_by(ModelConfig.updated_at.desc())
    )


async def resolve_provider(
    db: AsyncSession,
    owner_id: str,
    preferred_id: str | None = None,
    model_category: str = "text",
) -> tuple[LLMProvider, ModelConfig | None]:
    config = await resolve_model_config(db, owner_id, preferred_id, model_category)
    return get_provider_for_config(config), config


def resolved_model_name(provider: LLMProvider, config: ModelConfig | None) -> str:
    if config:
        return config.model_name or config.name
    return getattr(provider, "model_name", provider.name)
