"""Typed Volcano Ark transports for Seedance native-audio video and Doubao ASR."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import select

from app.core.http_client import build_async_client
from app.models.entities import ModelConfig
from app.services.media_provider_service import (
    AUDIO_MIME_TYPES,
    VIDEO_MIME_TYPES,
    MediaProviderError,
    _headers,
    _json_path,
    _safe_remote_media,
)


ProgressCallback = Callable[[int, str], Awaitable[None]]
JobCallback = Callable[[str], Awaitable[None]]


@dataclass
class SeedanceResult:
    raw: bytes
    mime_type: str
    provider_job_id: str
    usage: dict = field(default_factory=dict)


@dataclass
class TranscriptResult:
    text: str
    segments: list[dict]
    usage: dict = field(default_factory=dict)


class ArkSeedanceAdapter:
    """Official Seedance 2.5 native-audio task adapter.

    Model IDs and billing rules remain account configuration; the validated
    family marker prevents a generic/legacy video model from entering V3.
    """

    def __init__(self, config: ModelConfig):
        self.config = config

    def validate_capabilities(self) -> None:
        adapter = self.config.adapter_config_json or {}
        capabilities = set(self.config.capabilities_json or [])
        if self.config.provider != "volcengine_ark" or self.config.api_mode != "volcengine_ark_video":
            raise MediaProviderError("必须使用官方火山方舟视频接口", retryable=False)
        if adapter.get("model_family") != "doubao-seedance-2.5":
            raise MediaProviderError("模型配置必须明确标记 doubao-seedance-2.5，禁止沿用 2.0 或通用视频模型", retryable=False)
        if not {"video_generation", "native_audio_video_generation"} <= capabilities:
            raise MediaProviderError("模型缺少原生有声视频能力声明", retryable=False)
        if float(adapter.get("price_per_million_tokens_cny") or 0) <= 0:
            raise MediaProviderError("缺少账号内官方 2.5 Token 单价", retryable=False)
        if int(adapter.get("tokens_per_second_720p") or 0) <= 0:
            raise MediaProviderError("缺少账号内官方 720p Token 规则", retryable=False)

    async def probe_capabilities(self) -> dict:
        """Validate local claims and an optional account capability endpoint."""
        self.validate_capabilities()
        adapter = self.config.adapter_config_json or {}
        path = str(adapter.get("capability_probe_endpoint_path") or "").strip()
        if not path:
            return {
                "model": self.config.model_name,
                "model_family": "doubao-seedance-2.5",
                "resolution": "720p",
                "resolutions": ["1280x720", "854x480"],
                "duration_seconds": [4, 15],
                "native_audio": True,
                "source": "validated_configuration",
            }
        url = _endpoint(self.config, path.replace("{model}", self.config.model_name))
        async with build_async_client(url, timeout=min(5, self.config.timeout_seconds), follow_redirects=False) as client:
            response = await client.get(url, headers=_headers(self.config))
        response.raise_for_status()
        data = response.json()
        try:
            model = str(_json_path(data, str(adapter.get("probe_model_path") or "model")))
            native_audio = bool(_json_path(data, str(adapter.get("probe_native_audio_path") or "capabilities.native_audio")))
            resolutions = _json_path(data, str(adapter.get("probe_resolutions_path") or "capabilities.resolutions"))
            minimum = float(_json_path(data, str(adapter.get("probe_min_duration_path") or "capabilities.min_duration_seconds")))
            maximum = float(_json_path(data, str(adapter.get("probe_max_duration_path") or "capabilities.max_duration_seconds")))
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaProviderError("Seedance 能力探测响应缺少必要字段", retryable=False) from exc
        if model != self.config.model_name:
            raise MediaProviderError("Seedance 能力探测返回了不同的模型身份", retryable=False)
        if not native_audio or not isinstance(resolutions, list) or "720p" not in resolutions or minimum > 8 or maximum < 15:
            raise MediaProviderError("Seedance 账号能力不满足原生音频、720p 或 8–15 秒片段要求", retryable=False)
        return {
            "model": model,
            "model_family": "doubao-seedance-2.5",
            "resolution": "720p",
            "resolutions": ["1280x720", "854x480"],
            "duration_seconds": [minimum, maximum],
            "native_audio": native_audio,
            "source": "provider_capability_probe",
        }

    async def generate(self, **kwargs) -> SeedanceResult:
        self.validate_capabilities()
        return await generate_seedance_video(self.config, **kwargs)

    async def resume(self, provider_job_id: str, progress: ProgressCallback | None = None) -> SeedanceResult:
        self.validate_capabilities()
        return await resume_seedance_video(self.config, provider_job_id=provider_job_id, progress=progress)

    async def cancel(self, provider_job_id: str) -> None:
        await cancel_seedance_video(self.config, provider_job_id)


def _endpoint(config: ModelConfig, path: str) -> str:
    return f"{config.base_url.rstrip('/')}/{path.lstrip('/')}"


def _adapter_path(adapter: dict, key: str, default: str) -> str:
    return str(adapter.get(key) or default)


def _resolution_label(resolution: str) -> str | None:
    """把分辨率字符串映射为 Provider 规格标记；不支持时返回 None。"""
    return {
        "1280x720": "720p",
        "854x480": "480p",
    }.get(str(resolution).lower())


async def generate_seedance_video(
    config: ModelConfig,
    *,
    prompt: str,
    duration_seconds: float,
    resolution: str,
    idempotency_key: str,
    reference_urls: list[str] | None = None,
    progress: ProgressCallback | None = None,
    job_started: JobCallback | None = None,
) -> SeedanceResult:
    if config.api_mode != "volcengine_ark_video":
        raise MediaProviderError("所选配置不是火山方舟原生有声视频接口", retryable=False)
    if "native_audio_video_generation" not in (config.capabilities_json or []):
        raise MediaProviderError("所选配置未声明原生有声视频能力", retryable=False)
    resolution_label = _resolution_label(resolution)
    if resolution_label is None or not 4 <= duration_seconds <= 15:
        raise MediaProviderError("当前工作流只允许 720p/480p、4–15 秒的原生有声片段", retryable=False)

    adapter = config.adapter_config_json or {}
    content: list[dict] = [{"type": "text", "text": prompt}]
    for url in reference_urls or []:
        content.append({"type": "image_url", "role": "reference_image", "image_url": {"url": url}})
    payload = dict(adapter.get("extra_payload") or {})
    payload.update({
        str(adapter.get("model_field") or "model"): config.model_name,
        "content": content,
        str(adapter.get("duration_field") or "duration"): round(duration_seconds, 3),
        str(adapter.get("size_field") or "resolution"): resolution_label,
        str(adapter.get("aspect_ratio_field") or "ratio"): "16:9",
        "generate_audio": True,
    })
    headers = _headers(config)
    headers[str(adapter.get("idempotency_header") or "x-idempotency-key")] = idempotency_key
    create_url = _endpoint(config, _adapter_path(adapter, "endpoint_path", "/contents/generations/tasks"))
    try:
        async with build_async_client(create_url, timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(create_url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        job_id = str(_json_path(data, _adapter_path(adapter, "job_id_path", "id")))
    except Exception as exc:  # noqa: BLE001
        raise MediaProviderError(f"Seedance 任务创建失败：{str(exc)[:300]}") from exc
    if job_started:
        await job_started(job_id)

    return await resume_seedance_video(config, provider_job_id=job_id, progress=progress)


async def resume_seedance_video(
    config: ModelConfig,
    *,
    provider_job_id: str,
    progress: ProgressCallback | None = None,
) -> SeedanceResult:
    """Continue polling an already-created paid task without submitting it again."""
    if config.api_mode != "volcengine_ark_video":
        raise MediaProviderError("所选配置不是火山方舟原生有声视频接口", retryable=False)
    adapter = config.adapter_config_json or {}
    job_id = provider_job_id

    poll_template = _adapter_path(adapter, "poll_endpoint_path", "/contents/generations/tasks/{job_id}")
    status_path = _adapter_path(adapter, "status_path", "status")
    success_values = {str(value).lower() for value in adapter.get("success_values", ["completed", "succeeded"])}
    failed_values = {str(value).lower() for value in adapter.get("failed_values", ["failed", "cancelled", "expired"])}
    interval = max(.5, min(10, float(adapter.get("poll_interval_seconds") or 2)))
    deadline = asyncio.get_running_loop().time() + config.timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        poll_url = _endpoint(config, poll_template.replace("{job_id}", job_id))
        try:
            async with build_async_client(poll_url, timeout=config.timeout_seconds, follow_redirects=False) as client:
                response = await client.get(poll_url, headers=_headers(config))
            response.raise_for_status()
            state = response.json()
            status = str(_json_path(state, status_path)).lower()
        except Exception as exc:  # noqa: BLE001
            # Polling is safe to retry: the paid provider task already exists.
            if progress:
                await progress(50, "poll_retry")
            await asyncio.sleep(interval)
            continue
        if progress:
            try:
                percent = int(_json_path(state, _adapter_path(adapter, "progress_path", "progress")))
            except (KeyError, TypeError, ValueError):
                percent = 50
            await progress(max(1, min(99, percent)), status)
        if status in success_values:
            url = str(_json_path(state, _adapter_path(adapter, "result_url_path", "content.video_url")))
            raw, mime = await _safe_remote_media(url, config, VIDEO_MIME_TYPES)
            usage_path = adapter.get("usage_path")
            usage = _json_path(state, str(usage_path)) if usage_path else state.get("usage", {})
            return SeedanceResult(raw, mime, job_id, usage if isinstance(usage, dict) else {})
        if status in failed_values:
            try:
                detail = str(_json_path(state, _adapter_path(adapter, "error_path", "error")))
            except (KeyError, TypeError):
                detail = status
            raise MediaProviderError(f"Seedance 任务失败：{detail[:300]}", provider_job_id=job_id)
        await asyncio.sleep(interval)
    raise MediaProviderError("Seedance 任务等待超时", provider_job_id=job_id)


async def cancel_seedance_video(config: ModelConfig, provider_job_id: str) -> None:
    if not provider_job_id or config.api_mode != "volcengine_ark_video":
        return
    adapter = config.adapter_config_json or {}
    template = _adapter_path(adapter, "cancel_endpoint_path", "/contents/generations/tasks/{job_id}")
    url = _endpoint(config, template.replace("{job_id}", provider_job_id))
    async with build_async_client(url, timeout=min(30, config.timeout_seconds), follow_redirects=False) as client:
        response = await client.delete(url, headers=_headers(config))
    if response.status_code not in {200, 202, 204, 404, 409}:
        response.raise_for_status()


async def transcribe_doubao_audio(config: ModelConfig, audio_path: Path) -> TranscriptResult:
    if config.api_mode != "volcengine_asr":
        raise MediaProviderError("所选配置不是豆包 ASR 接口", retryable=False)
    adapter = config.adapter_config_json or {}
    endpoint = _endpoint(config, _adapter_path(adapter, "endpoint_path", "/audio/transcriptions"))
    mime = "audio/mp4" if audio_path.suffix.lower() in {".m4a", ".mp4"} else "audio/wav"
    if mime not in AUDIO_MIME_TYPES:
        mime = "audio/wav"
    payload = dict(adapter.get("extra_payload") or {})
    payload.update({
        str(adapter.get("model_field") or "model"): config.model_name,
        "audio": {"format": mime, "data": base64.b64encode(audio_path.read_bytes()).decode("ascii")},
        "timestamps": True,
    })
    async with build_async_client(endpoint, timeout=config.timeout_seconds, follow_redirects=False) as client:
        response = await client.post(endpoint, headers=_headers(config), json=payload)
    response.raise_for_status()
    data = response.json()
    text = str(_json_path(data, _adapter_path(adapter, "transcript_path", "text"))).strip()
    try:
        segments = _json_path(data, _adapter_path(adapter, "segments_path", "segments"))
    except (KeyError, TypeError):
        segments = []
    usage = data.get("usage", {})
    if not text:
        raise MediaProviderError("豆包 ASR 未返回转写文本", retryable=False)
    return TranscriptResult(text, segments if isinstance(segments, list) else [], usage if isinstance(usage, dict) else {})


async def probe_configured_seedance_models(db) -> list[dict]:
    """Audit every enabled Ark video config during application startup."""
    configs = list(await db.scalars(select(ModelConfig).where(
        ModelConfig.is_active.is_(True),
        ModelConfig.provider == "volcengine_ark",
        ModelConfig.api_mode == "volcengine_ark_video",
    )))
    report: list[dict] = []
    for config in configs:
        try:
            result = await ArkSeedanceAdapter(config).probe_capabilities()
            report.append({"model_config_id": config.id, "status": "ready", **result})
        except Exception as exc:  # noqa: BLE001
            report.append({
                "model_config_id": config.id,
                "model": config.model_name,
                "status": "blocked",
                "error": str(exc)[:500],
            })
    return report
