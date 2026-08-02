from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.models.entities import ModelConfig
from app.providers.llm.anthropic import AnthropicProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.mock import MockProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider


def get_provider() -> LLMProvider:
    return MockProvider() if get_settings().llm_provider == "mock" else OpenAICompatibleProvider()


def get_provider_for_config(config: ModelConfig | None) -> LLMProvider:
    settings = get_settings()
    if not config:
        return get_provider()

    api_key = decrypt_secret(config.encrypted_api_key) if config.encrypted_api_key else ""
    if config.provider == "mock":
        return MockProvider()
    if config.provider == "anthropic":
        return AnthropicProvider(
            api_key=api_key or settings.openai_api_key,
            base_url=config.base_url or "https://api.anthropic.com",
            model_name=config.model_name or "claude-3-5-sonnet-20241022",
            timeout_seconds=config.timeout_seconds or 90,
        )
    else:
        return OpenAICompatibleProvider(
            api_key=api_key or settings.openai_api_key,
            base_url=config.base_url or settings.openai_base_url,
            model_name=config.model_name or settings.openai_model,
            timeout_seconds=config.timeout_seconds or settings.llm_timeout_seconds,
        )

