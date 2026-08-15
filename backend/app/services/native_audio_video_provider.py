"""Provider boundary for native-audio segmented video generation."""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from app.models.entities import ModelConfig
from app.services.gemini_interactions_video_service import GeminiInteractionsVideoAdapter
from app.services.media_provider_service import MediaProviderError
from app.services.seedance_provider_service import ArkSeedanceAdapter


@runtime_checkable
class NativeAudioVideoProvider(Protocol):
    def capabilities(self) -> dict: ...
    async def generate(self, **kwargs): ...
    async def resume(self, provider_job_id: str, **kwargs): ...
    async def cancel(self, provider_job_id: str) -> None: ...
    def estimate_cost(self, duration_seconds: float) -> tuple[int, int]: ...


class SeedanceNativeAudioVideoProvider(ArkSeedanceAdapter):
    def capabilities(self) -> dict:
        self.validate_capabilities()
        return {
            "model": self.config.model_name,
            "resolution": "720p",
            "duration_seconds": [4, 15],
            "native_audio": True,
        }

    def estimate_cost(self, duration_seconds: float) -> tuple[int, int]:
        adapter = self.config.adapter_config_json or {}
        tokens = math.ceil(duration_seconds * int(adapter["tokens_per_second_720p"]))
        cost = math.ceil(tokens * float(adapter["price_per_million_tokens_cny"]) / 1_000_000 * 100)
        return tokens, cost


def native_audio_video_provider(config: ModelConfig) -> NativeAudioVideoProvider:
    if config.api_mode == "volcengine_ark_video":
        provider = SeedanceNativeAudioVideoProvider(config)
        provider.validate_capabilities()
        return provider
    if config.api_mode == "gemini_interactions_video":
        provider = GeminiInteractionsVideoAdapter(config)
        provider.validate_capabilities()
        return provider
    raise MediaProviderError(
        f"接口模式 {config.api_mode or 'text_chat'} 不支持原生有声视频",
        retryable=False,
        code="video_provider_unsupported",
    )
