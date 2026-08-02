from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ModelConfig
from app.providers.llm.base import LLMProvider
from app.providers.llm.router import get_provider_for_config


async def owned_model_config(
    db: AsyncSession,
    owner_id: str,
    config_id: str,
) -> ModelConfig:
    config = await db.scalar(
        select(ModelConfig).where(
            ModelConfig.id == config_id,
            ModelConfig.owner_id == owner_id,
        )
    )
    if not config:
        raise HTTPException(404, "指定的模型配置不存在或无权访问")
    return config


async def resolve_model_config(
    db: AsyncSession,
    owner_id: str,
    preferred_id: str | None = None,
) -> ModelConfig | None:
    if preferred_id:
        config = await db.scalar(
            select(ModelConfig).where(
                ModelConfig.id == preferred_id,
                ModelConfig.owner_id == owner_id,
            )
        )
        if config:
            return config
    config = await db.scalar(
        select(ModelConfig).where(
            ModelConfig.owner_id == owner_id,
            ModelConfig.is_active.is_(True),
        ).order_by(ModelConfig.updated_at.desc())
    )
    if config:
        return config
    return await db.scalar(
        select(ModelConfig).where(ModelConfig.owner_id == owner_id)
        .order_by(ModelConfig.updated_at.desc())
    )


async def resolve_provider(
    db: AsyncSession,
    owner_id: str,
    preferred_id: str | None = None,
) -> tuple[LLMProvider, ModelConfig | None]:
    config = await resolve_model_config(db, owner_id, preferred_id)
    return get_provider_for_config(config), config


def resolved_model_name(provider: LLMProvider, config: ModelConfig | None) -> str:
    if config:
        return config.model_name or config.name
    return getattr(provider, "model_name", provider.name)
