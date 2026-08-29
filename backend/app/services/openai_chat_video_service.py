"""Native-audio video generation through protocol-compatible gateways.

OpenAI-compatible/NewAPI gateways expose video jobs through
``/v1/video/generations``.  Anthropic-compatible gateways retain the message
transport because Anthropic does not define a corresponding public video-job
endpoint.  The adapter remains model-name agnostic and accepts both synchronous
media responses and asynchronous jobs.
"""

from __future__ import annotations

import base64
import binascii
import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import get_settings
from app.core.http_client import build_async_client
from app.core.security import decrypt_secret
from app.models.entities import ModelConfig
from app.services.media_provider_service import (
    MediaProviderError,
    VIDEO_MIME_TYPES,
    _headers,
    _safe_remote_media,
)


_probe_reports: dict[str, dict] = {}


async def record_video_capability_status(config_id: str, status: str, error: str = "") -> None:
    from app.core.database import SessionLocal
    from app.models.entities import now

    try:
        async with SessionLocal() as db:
            row = await db.get(ModelConfig, config_id)
            if not row:
                return
            row.video_capability_status = status
            row.video_capability_error = error[:500]
            row.video_capability_verified_at = now() if status == "verified" else None
            await db.commit()
    except Exception:
        return


@dataclass
class OpenAIChatVideoResult:
    raw: bytes
    mime_type: str
    provider_job_id: str
    provider_file_id: str = ""
    actual_model_name: str = ""
    usage: dict | None = None


def _video_url(config: ModelConfig) -> str:
    base = config.base_url.strip().rstrip("/")
    adapter = config.adapter_config_json or {}
    endpoint_path = str(adapter.get("endpoint_path") or "").strip()
    if endpoint_path:
        if endpoint_path.startswith("/"):
            parsed = urlparse(base)
            # A Base URL commonly already includes /v1.  Keep that prefix when
            # the configured endpoint is relative to the API root.
            api_root = f"{parsed.scheme}://{parsed.netloc}"
            if base.endswith("/v1") and not endpoint_path.startswith("/v1/"):
                return base + endpoint_path
            return api_root + endpoint_path
        return base + "/" + endpoint_path
    if config.provider == "anthropic":
        if base.endswith("/messages"):
            return base
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/messages"
    if base.endswith("/video/generations"):
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/video/generations"


def _uses_message_protocol(config: ModelConfig, url: str) -> bool:
    return config.provider == "anthropic" or url.endswith(("/messages", "/chat/completions"))


def _resolution_tier(resolution: str) -> str:
    return {
        "1280x720": "720p",
        "854x480": "480p",
        "1920x1080": "1080p",
    }.get(resolution, resolution)


def _http_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:500]
    if not isinstance(body, dict):
        return str(body)[:500]
    error = body.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("detail") or error.get("code")
    else:
        detail = error
    detail = detail or body.get("message") or body.get("detail") or body.get("code")
    return str(detail or "").strip()[:500]


def _request_headers(config: ModelConfig) -> dict[str, str]:
    if config.provider != "anthropic":
        return _headers(config)
    key = decrypt_secret(config.encrypted_api_key) if config.encrypted_api_key else ""
    return {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _walk_video_candidates(value):
    if isinstance(value, dict):
        mime = str(value.get("mime_type") or value.get("mimeType") or "").split(";", 1)[0].lower()
        kind = str(value.get("type") or value.get("kind") or "").lower()
        # NewAPI-compatible video gateways commonly wrap the completed media URL
        # as ``data.video_url`` instead of the generic OpenAI ``url`` field.
        has_media_value = any(value.get(key) for key in ("b64_json", "base64", "url", "uri", "video_url"))
        if mime in VIDEO_MIME_TYPES or kind in {"video", "video_url", "output_video"} or has_media_value:
            yield value
        for nested in value.values():
            yield from _walk_video_candidates(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_video_candidates(nested)


def _walk_response_text(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"content", "text", "output_text"} and isinstance(nested, str):
                yield nested
            else:
                yield from _walk_response_text(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_response_text(nested)


def _response_payload(response: httpx.Response) -> dict:
    """Normalize regular JSON and OpenAI/Anthropic SSE into one inspectable value."""
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if mime != "text/event-stream":
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("response is not an object")
        return value
    events: list[dict] = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return {"events": events}


def _response_job_id(data: dict, fallback: str) -> str:
    direct = data.get("task_id") or data.get("id")
    if direct:
        return str(direct)
    for event in data.get("events", []):
        if isinstance(event, dict) and (event.get("task_id") or event.get("id")):
            return str(event.get("task_id") or event["id"])
    return fallback


def _inline_video(candidate: dict, limit: int) -> tuple[bytes, str] | None:
    encoded = candidate.get("b64_json") or candidate.get("data") or candidate.get("base64")
    if isinstance(encoded, dict):
        encoded = encoded.get("data") or encoded.get("bytes") or encoded.get("b64_json")
    if not isinstance(encoded, str) or not encoded:
        return None
    if encoded.startswith("data:"):
        match = re.match(r"data:([^;,]+);base64,(.+)", encoded, re.DOTALL)
        if not match:
            return None
        mime, encoded = match.group(1).lower(), match.group(2)
    else:
        mime = str(candidate.get("mime_type") or candidate.get("mimeType") or "video/mp4").split(";", 1)[0].lower()
    if mime not in VIDEO_MIME_TYPES:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise MediaProviderError("视频模型返回了无效的媒体数据", retryable=False) from exc
    if not raw or len(raw) > limit:
        raise MediaProviderError("视频模型返回的文件为空或过大", retryable=False)
    return raw, mime


class OpenAIChatVideoAdapter:
    def __init__(self, config: ModelConfig):
        self.config = config

    def validate_capabilities(self) -> None:
        capabilities = set(self.config.capabilities_json or [])
        if self.config.provider not in {"openai_compatible", "anthropic"}:
            raise MediaProviderError("视频模型仅支持 OpenAI 兼容协议或 Anthropic 协议", retryable=False)
        if "video_generation" not in capabilities:
            raise MediaProviderError("当前模型未启用视频生成能力", retryable=False)

    def capabilities(self) -> dict:
        self.validate_capabilities()
        adapter = self.config.adapter_config_json or {}
        resolutions = adapter.get("resolutions") or ["1280x720"]
        return {
            "model": self.config.model_name,
            "resolution": resolutions[0],
            "resolutions": resolutions,
            "duration_seconds": [
                float(adapter.get("min_duration_seconds") or 3),
                float(adapter.get("max_duration_seconds") or 15),
            ],
            "native_audio": True,
        }

    def estimate_cost(self, duration_seconds: float) -> tuple[int, int]:
        price = float((self.config.adapter_config_json or {}).get("price_per_second_cny") or 0)
        return 0, int(-(-duration_seconds * price * 100 // 1)) if price else 0

    async def probe_capabilities(self) -> dict:
        """Compatibility-only connectivity probe; never claims video output support."""
        self.validate_capabilities()
        return {**self.capabilities(), "source": "declared_protocol_capability", "status": "unverified"}

    async def _record_status(self, status: str, error: str = "") -> None:
        if not getattr(self.config, "id", None):
            return
        await record_video_capability_status(self.config.id, status, error)

    async def _result_from_data(self, data: dict, job_id: str, limit: int) -> OpenAIChatVideoResult | None:
        state = str(data.get("status") or data.get("state") or "").lower()
        if state in {"queued", "pending", "processing", "running", "in_progress", "submitted"}:
            # Some job responses expose their status URL in a generic ``url``
            # field.  It is JSON, not the generated media, and must be polled.
            return None
        for candidate in _walk_video_candidates(data):
            inline = _inline_video(candidate, limit)
            if inline:
                raw, mime = inline
                return OpenAIChatVideoResult(raw, mime, job_id, actual_model_name=str(data.get("model") or self.config.model_name), usage=data.get("usage"))
            url_value = candidate.get("video_url") or candidate.get("url") or candidate.get("uri")
            if isinstance(url_value, dict):
                url_value = url_value.get("url")
            if isinstance(url_value, str) and url_value.startswith("https://"):
                raw, mime = await _safe_remote_media(url_value, self.config, VIDEO_MIME_TYPES)
                return OpenAIChatVideoResult(raw, mime, job_id, actual_model_name=str(data.get("model") or self.config.model_name), usage=data.get("usage"))
        # Many compatible gateways stream a Markdown link in message content
        # instead of emitting a typed video block.
        seen_urls: set[str] = set()
        for text in _walk_response_text(data):
            for url_value in re.findall(r"https://[^\s\]\[()<>{}\"']+", text):
                url_value = url_value.rstrip(".,;:!?")
                if url_value in seen_urls:
                    continue
                seen_urls.add(url_value)
                try:
                    raw, mime = await _safe_remote_media(url_value, self.config, VIDEO_MIME_TYPES)
                except (MediaProviderError, httpx.HTTPError, OSError):
                    continue
                return OpenAIChatVideoResult(raw, mime, job_id, actual_model_name=str(data.get("model") or self.config.model_name), usage=data.get("usage"))
        return None

    async def _poll_async_result(
        self, data: dict, response, job_id: str, limit: int, progress=None,
    ) -> OpenAIChatVideoResult | None:
        status_url = response.headers.get("location")
        if not status_url:
            status_url = data.get("status_url") or data.get("poll_url")
            if isinstance(data.get("task"), dict):
                status_url = status_url or data["task"].get("status_url") or data["task"].get("url")
        generation_url = _video_url(self.config)
        state = str(data.get("status") or data.get("state") or "").lower()
        is_newapi_job = bool(data.get("task_id")) or state in {
            "queued", "pending", "processing", "running", "in_progress", "submitted",
        }
        if not status_url and job_id and not _uses_message_protocol(self.config, generation_url) and is_newapi_job:
            status_url = f"{generation_url.rstrip('/')}/{job_id}"
        if not isinstance(status_url, str) or not status_url:
            return None
        status_url = urljoin(generation_url, status_url)
        gateway = urlparse(generation_url)
        target = urlparse(status_url)
        if target.scheme != gateway.scheme or target.netloc != gateway.netloc:
            raise MediaProviderError("异步任务地址不属于当前模型网关", retryable=False, code="video_response_invalid_status_url")
        deadline = time.monotonic() + self.config.timeout_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            async with build_async_client(status_url, timeout=min(30, self.config.timeout_seconds), follow_redirects=False) as client:
                poll = await client.get(status_url, headers=_request_headers(self.config))
            poll.raise_for_status()
            mime = poll.headers.get("content-type", "").split(";", 1)[0].lower()
            if mime in VIDEO_MIME_TYPES:
                return OpenAIChatVideoResult(poll.content, mime, job_id, actual_model_name=self.config.model_name)
            current = poll.json()
            result = await self._result_from_data(current, job_id, limit)
            if result:
                return result
            state = str(current.get("status") or current.get("state") or "").lower()
            if progress:
                try:
                    percent = int(float(current.get("progress", 50)))
                except (TypeError, ValueError):
                    percent = 50
                await progress(max(1, min(99, percent)), state or "processing")
            if state in {"failed", "error", "cancelled", "canceled"}:
                detail = current.get("error") or current.get("message") or state
                raise MediaProviderError(
                    f"视频模型返回生成失败状态：{str(detail)[:300]}",
                    retryable=False,
                    code="video_generation_rejected",
                )
        raise MediaProviderError("视频模型生成超时，请稍后重试", code="video_generation_timeout")

    async def generate(
        self,
        *,
        prompt: str,
        duration_seconds: float,
        resolution: str,
        idempotency_key: str,
        progress=None,
        job_started=None,
        file_started=None,
        **_: object,
    ) -> OpenAIChatVideoResult:
        self.validate_capabilities()
        url = _video_url(self.config)
        if _uses_message_protocol(self.config, url):
            payload = {
                "model": self.config.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "video": {
                    "resolution": resolution,
                    "duration_seconds": duration_seconds,
                    "audio": True,
                },
                "stream": True,
            }
            if self.config.provider == "anthropic":
                payload["max_tokens"] = 4096
                payload["output_modalities"] = ["video", "audio"]
            else:
                payload["modalities"] = ["text", "video", "audio"]
        else:
            resolution_tier = _resolution_tier(resolution)
            payload = {
                "model": self.config.model_name,
                "prompt": prompt,
                "duration": int(duration_seconds) if float(duration_seconds).is_integer() else duration_seconds,
                "size": resolution_tier,
            }
        headers = _request_headers(self.config)
        headers["x-idempotency-key"] = idempotency_key
        try:
            async with build_async_client(url, timeout=self.config.timeout_seconds, follow_redirects=False) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = _http_error_detail(exc.response)
            message = f"视频模型拒绝了生成请求（HTTP {status}）"
            if detail:
                message += f"：{detail}"
            if status == 404:
                message = f"视频生成端点不存在（HTTP 404）：请确认网关支持 {_video_url(self.config)}"
            if status >= 500:
                message = f"视频模型服务暂时不可用（HTTP {status}），请稍后重试"
                await self._record_status("unverified", message)
                raise MediaProviderError(message, retryable=True, code="video_service_unavailable") from exc
            await self._record_status("failed", message)
            raise MediaProviderError(message, retryable=False, code="video_generation_rejected") from exc
        except httpx.TimeoutException as exc:
            message = "视频生成连接超时，网关尚未返回任务或视频结果，请稍后重试"
            await self._record_status("unverified", message)
            raise MediaProviderError(message, retryable=True, code="video_transport_timeout") from exc
        except httpx.TransportError as exc:
            message = "视频生成过程中网关连接中断，未能确认任务结果；请稍后使用同一模型重试"
            await self._record_status("unverified", message)
            raise MediaProviderError(message, retryable=True, code="video_transport_disconnected") from exc
        except Exception as exc:  # noqa: BLE001
            message = f"视频生成请求处理失败：{str(exc)[:300]}"
            await self._record_status("unverified", message)
            raise MediaProviderError(message, retryable=True, code="video_transport_error") from exc
        direct_mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        job_id = response.headers.get("x-request-id") or str(uuid.uuid4())
        if direct_mime in VIDEO_MIME_TYPES:
            result = OpenAIChatVideoResult(response.content, direct_mime, job_id, actual_model_name=self.config.model_name)
            return result
        try:
            data = _response_payload(response)
        except ValueError as exc:
            await self._record_status("failed", "视频模型响应格式不受支持")
            raise MediaProviderError("视频模型响应中没有可用的视频文件", retryable=False, code="video_response_missing_media") from exc
        job_id = _response_job_id(data, job_id)
        if job_started:
            await job_started(job_id)
        limit = min(
            int((self.config.adapter_config_json or {}).get("max_file_mb") or get_settings().video_max_mb),
            get_settings().video_max_mb,
        ) * 1024 * 1024
        result = await self._result_from_data(data, job_id, limit)
        if not result:
            result = await self._poll_async_result(data, response, job_id, limit, progress)
        if result:
            return result
        await self._record_status("failed", "该模型本次没有返回视频文件")
        raise MediaProviderError(
            "该模型本次没有返回视频文件，请确认网关已为它启用视频输出能力",
            retryable=False,
            code="video_response_missing_media",
        )

    async def resume(self, provider_job_id: str, progress=None, **kwargs):
        generation_url = _video_url(self.config)
        if _uses_message_protocol(self.config, generation_url):
            raise MediaProviderError(
                "消息协议未返回可恢复的异步任务",
                retryable=False,
                provider_job_id=provider_job_id,
            )
        limit = min(
            int((self.config.adapter_config_json or {}).get("max_file_mb") or get_settings().video_max_mb),
            get_settings().video_max_mb,
        ) * 1024 * 1024
        response = httpx.Response(
            202,
            headers={"location": f"{generation_url.rstrip('/')}/{provider_job_id}"},
        )
        result = await self._poll_async_result(
            {"task_id": provider_job_id, "status": "processing"},
            response,
            provider_job_id,
            limit,
            progress,
        )
        if result:
            return result
        raise MediaProviderError(
            "视频任务没有返回可用的视频文件",
            retryable=False,
            provider_job_id=provider_job_id,
            code="video_response_missing_media",
        )

    async def cancel(self, provider_job_id: str) -> None:
        return None


# New code uses the protocol-oriented name.  The alias keeps historical tests
# and serialized task metadata readable without exposing the old transport name.
ProtocolVideoAdapter = OpenAIChatVideoAdapter


async def probe_configured_openai_chat_video_models(db) -> list[dict]:
    from sqlalchemy import select

    configs = list(await db.scalars(select(ModelConfig).where(ModelConfig.api_mode == "openai_chat_video")))
    _probe_reports.clear()
    reports = []
    for config in configs:
        try:
            result = await OpenAIChatVideoAdapter(config).probe_capabilities()
            item = {"model_config_id": config.id, "status": "ready", **result}
        except Exception as exc:  # noqa: BLE001
            item = {"model_config_id": config.id, "model": config.model_name, "status": "blocked", "error": str(exc)[:500]}
        _probe_reports[config.id] = item
        reports.append(item)
    return reports


def configured_openai_chat_video_probe(config_id: str) -> dict | None:
    return _probe_reports.get(config_id)
