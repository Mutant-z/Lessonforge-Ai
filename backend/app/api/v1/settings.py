from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models.entities import AgentChatSession, CourseIntakeSession, CourseProject, ModelConfig, User
from app.providers.llm.anthropic import AnthropicProvider
from app.providers.llm.mock import MockProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider

router = APIRouter(prefix="/settings", tags=["设置"])


class ModelConfigItem(BaseModel):
    id: str
    name: str | None = None
    provider: str
    base_url: str
    model_name: str
    timeout_seconds: int
    context_window_tokens: int
    supports_multimodal: bool
    api_key_configured: bool
    api_key_masked: str
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class ModelConfigCreate(BaseModel):
    name: str | None = None
    provider: str = "openai_compatible"
    base_url: str
    model_name: str
    api_key: str = Field(default="", max_length=1000)
    timeout_seconds: int = Field(default=90, ge=10, le=600)
    context_window_tokens: int = Field(default=1_000_000, gt=0)
    supports_multimodal: bool = False
    is_active: bool = True


class ModelConfigUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = Field(default=None, max_length=1000)
    timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    context_window_tokens: int | None = Field(default=None, gt=0)
    supports_multimodal: bool | None = None
    is_active: bool | None = None


class TestConnectionRequest(BaseModel):
    config_id: str | None = None
    provider: str = "openai_compatible"
    base_url: str = ""
    model_name: str = ""
    api_key: str = ""
    timeout_seconds: int = 15


class UserPreferencesUpdate(BaseModel):
    default_language: str = "zh-CN"
    default_grade_level: str = ""
    default_ppt_template: str = "lessonforge_swiss_blue"


class FullSettingsResponse(BaseModel):
    configs: list[ModelConfigItem]
    active_config_id: str | None
    preferences: dict[str, Any]
    # 兼容旧单配置字段
    provider: str
    base_url: str
    model_name: str
    api_key_configured: bool
    api_key_masked: str
    timeout_seconds: int
    default_language: str
    default_grade_level: str
    default_ppt_template: str


def _mask_key(secret: str | None) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••••••"
    return secret[:3] + "••••••••" + secret[-4:]


def _format_config(c: ModelConfig) -> ModelConfigItem:
    has_key = bool(c.encrypted_api_key)
    raw_key = decrypt_secret(c.encrypted_api_key) if has_key else ""
    return ModelConfigItem(
        id=c.id,
        name=c.name or f"{c.provider.upper()} - {c.model_name}",
        provider=c.provider,
        base_url=c.base_url,
        model_name=c.model_name,
        timeout_seconds=c.timeout_seconds,
        context_window_tokens=c.context_window_tokens,
        supports_multimodal=c.supports_multimodal,
        api_key_configured=has_key,
        api_key_masked=_mask_key(raw_key),
        is_active=c.is_active,
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
    )


@router.get("", response_model=FullSettingsResponse)
async def get_user_settings(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    configs_query = await db.scalars(
        select(ModelConfig).where(ModelConfig.owner_id == user.id).order_by(ModelConfig.is_active.desc(), ModelConfig.updated_at.desc())
    )
    raw_configs = list(configs_query.all())

    items = [_format_config(c) for c in raw_configs]
    active_c = next((c for c in raw_configs if c.is_active), raw_configs[0] if raw_configs else None)
    active_id = active_c.id if active_c else None

    # 获取偏好设置
    prefs = active_c.preferences_json if (active_c and active_c.preferences_json) else {}
    if not prefs and raw_configs:
        for c in raw_configs:
            if c.preferences_json:
                prefs = c.preferences_json
                break

    default_lang = prefs.get("default_language", settings.default_language)
    default_grade = prefs.get("default_grade_level", "")
    default_ppt = prefs.get("default_ppt_template", "lessonforge_swiss_blue")

    # 兜底旧字段兼容
    prov = active_c.provider if active_c else settings.llm_provider
    b_url = active_c.base_url if active_c else settings.openai_base_url
    m_name = active_c.model_name if active_c else settings.openai_model
    configured = bool(active_c.encrypted_api_key) if active_c else bool(settings.openai_api_key)
    timeout = active_c.timeout_seconds if active_c else settings.llm_timeout_seconds
    raw_key = decrypt_secret(active_c.encrypted_api_key) if (active_c and active_c.encrypted_api_key) else settings.openai_api_key

    return FullSettingsResponse(
        configs=items,
        active_config_id=active_id,
        preferences={
            "default_language": default_lang,
            "default_grade_level": default_grade,
            "default_ppt_template": default_ppt,
        },
        provider=prov,
        base_url=b_url,
        model_name=m_name,
        api_key_configured=configured,
        api_key_masked=_mask_key(raw_key),
        timeout_seconds=timeout,
        default_language=default_lang,
        default_grade_level=default_grade,
        default_ppt_template=default_ppt,
    )


@router.post("/models", response_model=ModelConfigItem)
async def create_model_config(payload: ModelConfigCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if payload.is_active:
        # 如果新设为激活，则取消其他配置的激活
        existing = await db.scalars(select(ModelConfig).where(ModelConfig.owner_id == user.id, ModelConfig.is_active.is_(True)))
        for item in existing:
            item.is_active = False

    name = payload.name.strip() if payload.name else f"{payload.provider.upper()} - {payload.model_name}"
    config = ModelConfig(
        owner_id=user.id,
        name=name,
        provider=payload.provider,
        base_url=payload.base_url,
        model_name=payload.model_name,
        timeout_seconds=payload.timeout_seconds,
        context_window_tokens=payload.context_window_tokens,
        supports_multimodal=payload.supports_multimodal,
        is_active=payload.is_active,
    )
    if payload.api_key:
        config.encrypted_api_key = encrypt_secret(payload.api_key)

    db.add(config)
    await db.commit()
    await db.refresh(config)
    return _format_config(config)


@router.patch("/models/{config_id}", response_model=ModelConfigItem)
async def update_model_config(
    config_id: str,
    payload: ModelConfigUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    config = await db.scalar(select(ModelConfig).where(ModelConfig.id == config_id, ModelConfig.owner_id == user.id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定的模型配置不存在")

    if payload.name is not None:
        config.name = payload.name
    if payload.provider is not None:
        config.provider = payload.provider
    if payload.base_url is not None:
        config.base_url = payload.base_url
    if payload.model_name is not None:
        config.model_name = payload.model_name
    if payload.timeout_seconds is not None:
        config.timeout_seconds = payload.timeout_seconds
    if payload.context_window_tokens is not None:
        config.context_window_tokens = payload.context_window_tokens
    if payload.supports_multimodal is not None:
        config.supports_multimodal = payload.supports_multimodal
    if payload.api_key is not None and payload.api_key != "":
        config.encrypted_api_key = encrypt_secret(payload.api_key)

    if payload.is_active is True:
        existing = await db.scalars(select(ModelConfig).where(ModelConfig.owner_id == user.id, ModelConfig.id != config_id, ModelConfig.is_active == True))
        for item in existing:
            item.is_active = False
        config.is_active = True
    elif payload.is_active is False:
        config.is_active = False

    await db.commit()
    await db.refresh(config)
    return _format_config(config)


@router.post("/models/{config_id}/activate", response_model=ModelConfigItem)
async def activate_model_config(config_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    config = await db.scalar(select(ModelConfig).where(ModelConfig.id == config_id, ModelConfig.owner_id == user.id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定的模型配置不存在")

    all_configs = await db.scalars(select(ModelConfig).where(ModelConfig.owner_id == user.id))
    for c in all_configs:
        c.is_active = (c.id == config_id)

    await db.commit()
    await db.refresh(config)
    return _format_config(config)


@router.delete("/models/{config_id}")
async def delete_model_config(config_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    config = await db.scalar(select(ModelConfig).where(ModelConfig.id == config_id, ModelConfig.owner_id == user.id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定的模型配置不存在")

    was_active = config.is_active
    for model in (CourseIntakeSession, CourseProject, AgentChatSession):
        references = await db.scalars(select(model).where(model.model_config_id == config_id))
        for reference in references:
            reference.model_config_id = None
    await db.delete(config)

    if was_active:
        remaining = await db.scalar(
            select(ModelConfig).where(ModelConfig.owner_id == user.id).order_by(ModelConfig.updated_at.desc())
        )
        if remaining:
            remaining.is_active = True

    await db.commit()
    return {"message": "模型配置已删除"}


@router.post("/test-connection")
async def test_llm_connection(payload: TestConnectionRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    provider_type = payload.provider
    base_url = payload.base_url
    model_name = payload.model_name
    api_key = payload.api_key
    timeout = payload.timeout_seconds

    # 如果指定了 config_id，且 api_key 为空，从数据库读取解密的 key
    if payload.config_id and not api_key:
        config = await db.scalar(select(ModelConfig).where(ModelConfig.id == payload.config_id, ModelConfig.owner_id == user.id))
        if config:
            provider_type = config.provider
            base_url = base_url or config.base_url
            model_name = model_name or config.model_name
            if config.encrypted_api_key:
                api_key = decrypt_secret(config.encrypted_api_key)

    # 兜底全空情况：使用系统默认环境变量 Key
    settings = get_settings()
    if not api_key:
        api_key = settings.openai_api_key

    if provider_type == "mock":
        instance = MockProvider()
    elif provider_type == "anthropic":
        instance = AnthropicProvider(api_key=api_key, base_url=base_url, model_name=model_name, timeout_seconds=timeout)
    else:
        instance = OpenAICompatibleProvider(api_key=api_key, base_url=base_url, model_name=model_name, timeout_seconds=timeout)

    success, message = await instance.test_connection()
    return {"success": success, "message": message, "provider": provider_type, "model_name": model_name}


@router.patch("/preferences")
async def update_preferences(payload: UserPreferencesUpdate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    active_c = await db.scalar(select(ModelConfig).where(ModelConfig.owner_id == user.id, ModelConfig.is_active.is_(True)))
    if not active_c:
        active_c = await db.scalar(select(ModelConfig).where(ModelConfig.owner_id == user.id).order_by(ModelConfig.updated_at.desc()))

    if not active_c:
        settings = get_settings()
        active_c = ModelConfig(
            owner_id=user.id,
            name="默认配置",
            provider=settings.llm_provider,
            base_url=settings.openai_base_url,
            model_name=settings.openai_model,
            timeout_seconds=settings.llm_timeout_seconds,
            is_active=True,
        )
        db.add(active_c)

    active_c.preferences_json = {
        "default_language": payload.default_language,
        "default_grade_level": payload.default_grade_level,
        "default_ppt_template": payload.default_ppt_template,
    }
    await db.commit()
    return {"message": "个人偏好设置已更新", "preferences": active_c.preferences_json}


# 兼容旧接口 PATCH /api/v1/settings
@router.patch("")
async def save_settings_legacy(payload: dict[str, Any], user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    saved = await db.scalar(select(ModelConfig).where(ModelConfig.owner_id == user.id, ModelConfig.is_active.is_(True)))
    if not saved:
        saved = await db.scalar(select(ModelConfig).where(ModelConfig.owner_id == user.id).order_by(ModelConfig.updated_at.desc()))
    if not saved:
        saved = ModelConfig(owner_id=user.id, is_active=True)
        db.add(saved)

    if "provider" in payload and payload["provider"]:
        saved.provider = payload["provider"]
    if "base_url" in payload:
        saved.base_url = payload["base_url"] or ""
    if "model_name" in payload:
        saved.model_name = payload["model_name"] or ""
    if "timeout_seconds" in payload:
        saved.timeout_seconds = int(payload["timeout_seconds"])
    if "context_window_tokens" in payload:
        context_window = int(payload["context_window_tokens"])
        if context_window <= 0:
            raise HTTPException(422, "上下文窗口必须为正整数")
        saved.context_window_tokens = context_window
    if "supports_multimodal" in payload:
        saved.supports_multimodal = bool(payload["supports_multimodal"])
    if "api_key" in payload:
        if payload["api_key"]:
            saved.encrypted_api_key = encrypt_secret(payload["api_key"])
        else:
            saved.encrypted_api_key = ""

    prefs = saved.preferences_json or {}
    if "default_language" in payload:
        prefs["default_language"] = payload["default_language"]
    if "default_grade_level" in payload:
        prefs["default_grade_level"] = payload["default_grade_level"]
    if "default_ppt_template" in payload:
        prefs["default_ppt_template"] = payload["default_ppt_template"]
    saved.preferences_json = prefs

    await db.commit()
    return {
        "message": "设置已保存",
        "api_key_configured": bool(saved.encrypted_api_key),
        "api_key_masked": _mask_key(decrypt_secret(saved.encrypted_api_key) if saved.encrypted_api_key else "")
    }
