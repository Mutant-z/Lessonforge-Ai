"""Gemini Interactions native-audio video transport.

The adapter intentionally talks only to the configured gateway origin. Secrets are
never copied to media URIs on another origin, and response payloads are not logged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.http_client import build_async_client
from app.models.entities import ModelConfig
from app.services.media_provider_service import MediaProviderError, VIDEO_MIME_TYPES, _headers


ProgressCallback = Callable[[int, str], Awaitable[None]]
JobCallback = Callable[[str], Awaitable[None]]
FileCallback = Callable[[str], Awaitable[None]]
_configured_probe_reports: dict[str, dict] = {}


@dataclass
class GeminiVideoResult:
    raw: bytes
    mime_type: str
    provider_job_id: str
    provider_file_id: str = ""
    actual_model_name: str = ""
    usage: dict = field(default_factory=dict)


def normalize_gateway_origin(base_url: str) -> str:
    """Normalize origin-like, /v1 and /v1/messages gateway URLs."""
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MediaProviderError("Gemini 网关 Base URL 无效", retryable=False)
    path = re.sub(r"/(?:v1/messages|v1)/?$", "", parsed.path.rstrip("/"))
    return parsed._replace(path=path, params="", query="", fragment="").geturl().rstrip("/")


def _path(adapter: dict, key: str, default: str) -> str:
    return str(adapter.get(key) or default)


def _gateway_url(config: ModelConfig, path: str) -> str:
    if not path.startswith("/") or "://" in path or ".." in path:
        raise MediaProviderError("Gemini 网关路径不是安全的站内绝对路径", retryable=False)
    return f"{normalize_gateway_origin(config.base_url)}{path}"


def _status(data: dict) -> str:
    return str(data.get("status") or data.get("state") or "").upper()


def _interaction_id(data: dict) -> str:
    return str(data.get("id") or data.get("interaction_id") or "")


def _file_id_from_uri(uri: str) -> str:
    match = re.search(r"/files/([^/:?]+)", uri)
    return match.group(1) if match else ""


def _video_candidates(data: dict) -> list[dict]:
    candidates: list[dict] = []
    top = data.get("output_video")
    if isinstance(top, dict):
        candidates.append(top)
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for content in step.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "video":
                candidates.append(content)
    output = data.get("output")
    if isinstance(output, list):
        candidates.extend(item for item in output if isinstance(item, dict) and item.get("type") == "video")
    return candidates


def _decode_inline(candidate: dict, max_bytes: int) -> tuple[bytes, str] | None:
    encoded = candidate.get("data")
    if isinstance(encoded, dict):
        encoded = encoded.get("data") or encoded.get("bytes")
    if not encoded:
        return None
    mime = str(candidate.get("mime_type") or candidate.get("mimeType") or "video/mp4").split(";", 1)[0].lower()
    if mime not in VIDEO_MIME_TYPES:
        raise MediaProviderError("Gemini 返回了不受支持的视频 MIME", retryable=False, code="video_response_missing_media")
    try:
        raw = base64.b64decode(str(encoded), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise MediaProviderError("Gemini 返回了无效的视频 Base64", retryable=False, code="video_response_missing_media") from exc
    if not raw or len(raw) > max_bytes:
        raise MediaProviderError("Gemini 视频为空或超过文件大小限制", retryable=False, code="video_response_missing_media")
    return raw, mime


class GeminiInteractionsVideoAdapter:
    def __init__(self, config: ModelConfig):
        self.config = config

    def validate_capabilities(self, *, require_enabled: bool = True) -> None:
        capabilities = set(self.config.capabilities_json or [])
        if self.config.api_mode != "gemini_interactions_video":
            raise MediaProviderError("所选配置不是 Gemini Interactions 视频接口", retryable=False)
        if not {"video_generation", "native_audio_video_generation"} <= capabilities:
            raise MediaProviderError("Gemini 配置缺少原生有声视频能力声明", retryable=False)
        if require_enabled and not get_settings().gemini_interactions_video_enabled:
            raise MediaProviderError(
                "Gemini Interactions 视频功能尚未启用；请先完成本地网关能力探测",
                retryable=False,
                code="video_interactions_endpoint_unavailable",
            )

    def capabilities(self) -> dict:
        self.validate_capabilities(require_enabled=False)
        return {
            "model": self.config.model_name,
            "resolution": "720p",
            "resolutions": ["1280x720"],
            "duration_seconds": [3, 10],
            "native_audio": True,
            "delivery": str((self.config.adapter_config_json or {}).get("delivery") or "uri"),
        }

    def estimate_cost(self, duration_seconds: float) -> tuple[int, int]:
        adapter = self.config.adapter_config_json or {}
        price_per_second = float(adapter.get("price_per_second_cny") or 0)
        cost_fen = int(-(-duration_seconds * price_per_second * 100 // 1)) if price_per_second else 0
        return 0, cost_fen

    async def probe_capabilities(self) -> dict:
        self.validate_capabilities(require_enabled=False)
        adapter = self.config.adapter_config_json or {}
        url = _gateway_url(self.config, _path(adapter, "interactions_path", "/v1beta/interactions"))
        try:
            async with build_async_client(url, timeout=min(10, self.config.timeout_seconds), follow_redirects=False) as client:
                # A gateway-wide CORS handler can return 200 to OPTIONS even when
                # the requested route does not exist.  An authenticated GET is a
                # safe, non-billable route check: POST-only endpoints normally
                # answer 405, while a missing proxy route answers 404.
                response = await client.get(url, headers=_headers(self.config))
            if response.status_code in {404, 501}:
                raise MediaProviderError(
                    "本地网关尚未暴露 /v1beta/interactions",
                    retryable=False,
                    code="video_interactions_endpoint_unavailable",
                )
            if response.status_code >= 500:
                raise MediaProviderError(
                    f"Gemini Interactions 网关暂不可用（HTTP {response.status_code}）",
                    code="video_interactions_endpoint_unavailable",
                )
        except MediaProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MediaProviderError(
                f"Gemini Interactions 网关探测失败：{str(exc)[:240]}",
                code="video_interactions_endpoint_unavailable",
            ) from exc
        return {**self.capabilities(), "source": "gateway_endpoint_probe"}

    async def generate(
        self,
        *,
        prompt: str,
        duration_seconds: float,
        resolution: str,
        idempotency_key: str,
        progress: ProgressCallback | None = None,
        job_started: JobCallback | None = None,
        file_started: FileCallback | None = None,
        **_: object,
    ) -> GeminiVideoResult:
        self.validate_capabilities()
        if resolution != "1280x720" or not 3 <= duration_seconds <= 10:
            raise MediaProviderError(
                "Gemini Omni 仅支持 3–10 秒、720p 原生有声片段",
                retryable=False,
                code="video_scene_duration_unsupported",
            )
        adapter = self.config.adapter_config_json or {}
        url = _gateway_url(self.config, _path(adapter, "interactions_path", "/v1beta/interactions"))
        payload = {
            "model": self.config.model_name,
            "input": prompt,
            "response_format": {"type": "video", "aspect_ratio": "16:9", "delivery": "uri"},
            "background": False,
            "store": False,
            "stream": False,
        }
        headers = _headers(self.config)
        headers[str(adapter.get("idempotency_header") or "x-idempotency-key")] = idempotency_key
        try:
            async with build_async_client(url, timeout=self.config.timeout_seconds, follow_redirects=False) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 404:
                raise MediaProviderError(
                    "本地网关尚未暴露 Gemini Interactions 端点",
                    retryable=False,
                    code="video_interactions_endpoint_unavailable",
                )
            response.raise_for_status()
            data = response.json()
        except MediaProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MediaProviderError(f"Gemini 视频任务创建失败：{str(exc)[:300]}") from exc
        interaction_id = _interaction_id(data)
        if interaction_id and job_started:
            await job_started(interaction_id)
        return await self._resolve(
            data,
            interaction_id=interaction_id,
            progress=progress,
            file_started=file_started,
        )

    async def resume(
        self,
        provider_job_id: str,
        progress: ProgressCallback | None = None,
        *,
        provider_file_id: str = "",
        file_started: FileCallback | None = None,
    ) -> GeminiVideoResult:
        self.validate_capabilities()
        if provider_file_id:
            return await self._poll_file(provider_job_id, provider_file_id, progress)
        adapter = self.config.adapter_config_json or {}
        template = _path(adapter, "interaction_status_path", "/v1beta/interactions/{id}")
        deadline = asyncio.get_running_loop().time() + self.config.timeout_seconds
        interval = max(.5, min(10, float(adapter.get("poll_interval_seconds") or 2)))
        while asyncio.get_running_loop().time() < deadline:
            url = _gateway_url(self.config, template.replace("{id}", provider_job_id))
            async with build_async_client(url, timeout=self.config.timeout_seconds, follow_redirects=False) as client:
                response = await client.get(url, headers=_headers(self.config))
            response.raise_for_status()
            data = response.json()
            status = _status(data)
            if status in {"FAILED", "CANCELLED", "EXPIRED"}:
                raise MediaProviderError(
                    f"Gemini interaction 失败：{status}", provider_job_id=provider_job_id,
                    code="video_file_processing_failed",
                )
            try:
                return await self._resolve(data, interaction_id=provider_job_id, progress=progress, file_started=file_started)
            except MediaProviderError as exc:
                if exc.code != "video_response_missing_media" or status in {"COMPLETED", "SUCCEEDED"}:
                    raise
            if progress:
                await progress(45, status.lower() or "processing")
            await asyncio.sleep(interval)
        raise MediaProviderError("Gemini interaction 等待超时", provider_job_id=provider_job_id)

    async def _resolve(
        self,
        data: dict,
        *,
        interaction_id: str,
        progress: ProgressCallback | None,
        file_started: FileCallback | None,
    ) -> GeminiVideoResult:
        max_bytes = min(
            int((self.config.adapter_config_json or {}).get("max_file_mb") or get_settings().video_max_mb),
            get_settings().video_max_mb,
        ) * 1024 * 1024
        for candidate in _video_candidates(data):
            inline = _decode_inline(candidate, max_bytes)
            if inline:
                raw, mime = inline
                return GeminiVideoResult(
                    raw, mime, interaction_id,
                    actual_model_name=str(data.get("model") or self.config.model_name),
                    usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
                )
            uri = str(candidate.get("uri") or candidate.get("url") or "")
            if uri:
                file_id = str(candidate.get("file_id") or _file_id_from_uri(uri))
                if not file_id:
                    raise MediaProviderError("Gemini 视频 URI 缺少 file ID", retryable=False, code="video_response_missing_media")
                if file_started:
                    await file_started(file_id)
                return await self._poll_file(interaction_id, file_id, progress)
        raise MediaProviderError("Gemini 响应缺少视频媒体", retryable=False, code="video_response_missing_media")

    async def _poll_file(
        self,
        interaction_id: str,
        file_id: str,
        progress: ProgressCallback | None,
    ) -> GeminiVideoResult:
        adapter = self.config.adapter_config_json or {}
        status_template = _path(adapter, "file_status_path", "/v1beta/files/{file_id}")
        interval = max(.5, min(10, float(adapter.get("poll_interval_seconds") or 2)))
        deadline = asyncio.get_running_loop().time() + self.config.timeout_seconds
        state: dict = {}
        while asyncio.get_running_loop().time() < deadline:
            url = _gateway_url(self.config, status_template.replace("{file_id}", file_id))
            async with build_async_client(url, timeout=self.config.timeout_seconds, follow_redirects=False) as client:
                response = await client.get(url, headers=_headers(self.config))
            response.raise_for_status()
            state = response.json()
            status = _status(state)
            if status in {"ACTIVE", "READY", "SUCCEEDED", "COMPLETED"}:
                break
            if status in {"FAILED", "CANCELLED", "EXPIRED"}:
                raise MediaProviderError(
                    f"Gemini 文件处理失败：{status}", provider_job_id=interaction_id,
                    code="video_file_processing_failed",
                )
            if progress:
                await progress(70, status.lower() or "file_processing")
            await asyncio.sleep(interval)
        else:
            raise MediaProviderError("Gemini 文件处理等待超时", provider_job_id=interaction_id, code="video_file_processing_failed")

        download_template = _path(adapter, "file_download_path", "/v1beta/files/{file_id}:download?alt=media")
        download_url = _gateway_url(self.config, download_template.replace("{file_id}", file_id))
        # _gateway_url guarantees same-origin delivery; authentication is never sent elsewhere.
        async with build_async_client(download_url, timeout=self.config.timeout_seconds, follow_redirects=False) as client:
            response = await client.get(download_url, headers={**_headers(self.config), "accept": "video/mp4"})
        response.raise_for_status()
        if response.is_redirect:
            raise MediaProviderError("Gemini 文件下载不允许跨站重定向", retryable=False, code="video_file_processing_failed")
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        max_bytes = min(int(adapter.get("max_file_mb") or get_settings().video_max_mb), get_settings().video_max_mb) * 1024 * 1024
        if mime not in VIDEO_MIME_TYPES or not response.content or len(response.content) > max_bytes:
            raise MediaProviderError("Gemini 下载文件类型、大小或内容无效", retryable=False, code="video_file_processing_failed")
        return GeminiVideoResult(
            response.content, mime, interaction_id, file_id,
            str(state.get("model") or self.config.model_name),
            state.get("usage") if isinstance(state.get("usage"), dict) else {},
        )

    async def cancel(self, provider_job_id: str) -> None:
        if not provider_job_id:
            return
        adapter = self.config.adapter_config_json or {}
        template = str(adapter.get("cancel_endpoint_path") or "").strip()
        if not template:
            return
        url = _gateway_url(self.config, template.replace("{id}", provider_job_id).replace("{job_id}", provider_job_id))
        async with build_async_client(url, timeout=min(30, self.config.timeout_seconds), follow_redirects=False) as client:
            response = await client.post(url, headers=_headers(self.config))
        if response.status_code not in {200, 202, 204, 404, 409}:
            response.raise_for_status()


async def probe_configured_gemini_video_models(db) -> list[dict]:
    """Audit enabled Gemini Interactions configs without submitting paid media."""
    from sqlalchemy import select

    configs = list(await db.scalars(select(ModelConfig).where(
        ModelConfig.api_mode == "gemini_interactions_video",
    )))
    _configured_probe_reports.clear()
    report: list[dict] = []
    for config in configs:
        try:
            result = await GeminiInteractionsVideoAdapter(config).probe_capabilities()
            status = "ready" if get_settings().gemini_interactions_video_enabled else "disabled"
            item = {"model_config_id": config.id, "status": status, **result}
        except Exception as exc:  # noqa: BLE001
            item = {
                "model_config_id": config.id,
                "model": config.model_name,
                "status": "blocked",
                "error": str(exc)[:500],
            }
        report.append(item)
        _configured_probe_reports[config.id] = item
    return report


def configured_gemini_video_probe(config_id: str) -> dict | None:
    """Return the startup probe snapshot used by task preflight checks."""
    return _configured_probe_reports.get(config_id)
