import asyncio
import base64
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.http_client import build_async_client
from app.core.security import decrypt_secret
from app.models.entities import ModelConfig


VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
AUDIO_MIME_TYPES = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac"}
ProgressCallback = Callable[[int, str], Awaitable[None]]
JobCallback = Callable[[str], Awaitable[None]]


@dataclass
class MediaResult:
    raw: bytes
    mime_type: str
    provider_job_id: str = ""


class MediaProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True, provider_job_id: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.provider_job_id = provider_job_id


def _json_path(data, path: str):
    value = data
    for part in [item for item in path.strip("$.").split(".") if item]:
        if isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(path)
    return value


def _headers(config: ModelConfig) -> dict[str, str]:
    key = decrypt_secret(config.encrypted_api_key) if config.encrypted_api_key else ""
    if (config.adapter_config_json or {}).get("auth_mode") == "x_api_key":
        return {"x-api-key": key, "content-type": "application/json"}
    return {"authorization": f"Bearer {key}", "content-type": "application/json"}


async def _safe_remote_media(url: str, config: ModelConfig, allowed_mimes: set[str]) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise MediaProviderError("媒体结果 URL 必须使用 HTTPS", retryable=False)
    addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise MediaProviderError("媒体结果 URL 不允许访问内网地址", retryable=False)
    async with build_async_client(url, timeout=config.timeout_seconds, follow_redirects=False) as client:
        response = await client.get(url, headers={"accept": ",".join(sorted(allowed_mimes))})
    response.raise_for_status()
    if response.is_redirect:
        raise MediaProviderError("媒体下载不允许重定向", retryable=False)
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if mime not in allowed_mimes:
        raise MediaProviderError(f"媒体响应类型不受支持：{mime or 'unknown'}", retryable=False)
    configured_limit = int((config.adapter_config_json or {}).get("max_file_mb") or get_settings().video_max_mb)
    limit = min(configured_limit, get_settings().video_max_mb) * 1024 * 1024
    if not response.content or len(response.content) > limit:
        raise MediaProviderError("媒体响应为空或超过文件大小限制", retryable=False)
    return response.content, mime


async def _decode_result(
    data: dict,
    adapter: dict,
    config: ModelConfig,
    allowed_mimes: set[str],
    *,
    base64_path_key: str = "response_base64_path",
    url_path_key: str = "response_url_path",
) -> tuple[bytes, str]:
    encoded = None
    base64_path = adapter.get(base64_path_key)
    if base64_path:
        try:
            encoded = _json_path(data, str(base64_path))
        except (KeyError, IndexError, TypeError):
            encoded = None
    mime = str(adapter.get("response_mime_type") or next(iter(allowed_mimes)))
    if encoded:
        try:
            raw = base64.b64decode(str(encoded), validate=True)
        except Exception as exc:  # noqa: BLE001
            raise MediaProviderError("媒体接口返回了无效的 Base64 数据", retryable=False) from exc
        if mime not in allowed_mimes or not raw:
            raise MediaProviderError("媒体接口返回了不受支持的数据", retryable=False)
        return raw, mime
    url_path = adapter.get(url_path_key)
    if not url_path:
        raise MediaProviderError("媒体接口响应缺少结果文件映射", retryable=False)
    return await _safe_remote_media(str(_json_path(data, str(url_path))), config, allowed_mimes)


async def generate_video(
    config: ModelConfig,
    prompt: str,
    duration_seconds: float,
    resolution: str,
    *,
    progress: ProgressCallback | None = None,
    job_started: JobCallback | None = None,
) -> MediaResult:
    if config.provider == "mock" or config.api_mode == "mock_media":
        return MediaResult(b"", "video/mp4", "mock")
    if config.api_mode != "custom_video_async_http":
        raise MediaProviderError("所选配置不是视频生成接口", retryable=False)
    adapter = config.adapter_config_json or {}
    endpoint = f"{config.base_url.rstrip('/')}/{str(adapter.get('endpoint_path') or '/videos/generations').lstrip('/')}"
    payload = dict(adapter.get("extra_payload") or {})
    payload.update({
        str(adapter.get("model_field") or "model"): config.model_name,
        str(adapter.get("prompt_field") or "prompt"): prompt,
        str(adapter.get("duration_field") or "duration_seconds"): duration_seconds,
        str(adapter.get("size_field") or "resolution"): resolution,
        str(adapter.get("aspect_ratio_field") or "aspect_ratio"): "16:9",
    })
    async with build_async_client(endpoint, timeout=config.timeout_seconds, follow_redirects=False) as client:
        response = await client.post(endpoint, headers=_headers(config), json=payload)
    response.raise_for_status()
    if response.headers.get("content-type", "").split(";", 1)[0] in VIDEO_MIME_TYPES:
        return MediaResult(response.content, response.headers["content-type"].split(";", 1)[0])
    data = response.json()
    job_id_path = str(adapter.get("job_id_path") or "id")
    try:
        job_id = str(_json_path(data, job_id_path))
    except (KeyError, IndexError, TypeError):
        raw, mime = await _decode_result(data, adapter, config, VIDEO_MIME_TYPES)
        return MediaResult(raw, mime)
    if job_started:
        await job_started(job_id)

    poll_template = str(adapter.get("poll_endpoint_path") or "/videos/generations/{job_id}")
    status_path = str(adapter.get("status_path") or "status")
    success_values = {str(item).lower() for item in (adapter.get("success_values") or ["completed", "succeeded", "ready"])}
    failed_values = {str(item).lower() for item in (adapter.get("failed_values") or ["failed", "cancelled", "error"])}
    interval = max(0.5, min(10.0, float(adapter.get("poll_interval_seconds") or 2)))
    deadline = asyncio.get_running_loop().time() + config.timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        poll_path = poll_template.replace("{job_id}", job_id)
        poll_url = f"{config.base_url.rstrip('/')}/{poll_path.lstrip('/')}"
        async with build_async_client(poll_url, timeout=config.timeout_seconds, follow_redirects=False) as client:
            poll_response = await client.get(poll_url, headers=_headers(config))
        poll_response.raise_for_status()
        state = poll_response.json()
        status = str(_json_path(state, status_path)).lower()
        if progress:
            try:
                percent = int(float(_json_path(state, str(adapter.get("progress_path") or "progress"))))
            except (KeyError, TypeError, ValueError):
                percent = 50
            await progress(max(1, min(99, percent)), status)
        if status in success_values:
            result_adapter = {
                **adapter,
                "response_base64_path": adapter.get("result_base64_path") or adapter.get("response_base64_path"),
                "response_url_path": adapter.get("result_url_path") or adapter.get("response_url_path") or "output.url",
            }
            raw, mime = await _decode_result(state, result_adapter, config, VIDEO_MIME_TYPES)
            return MediaResult(raw, mime, job_id)
        if status in failed_values:
            error_path = str(adapter.get("error_path") or "error")
            try:
                detail = str(_json_path(state, error_path))
            except (KeyError, TypeError):
                detail = status
            raise MediaProviderError(f"视频模型任务失败：{detail[:300]}", provider_job_id=job_id)
        await asyncio.sleep(interval)
    raise MediaProviderError("视频模型任务等待超时", provider_job_id=job_id)


async def generate_speech(
    config: ModelConfig,
    text: str,
    voice_style: str,
) -> MediaResult:
    if config.provider == "mock" or config.api_mode == "mock_media":
        return MediaResult(b"", "audio/wav", "mock")
    if config.api_mode != "custom_speech_http":
        raise MediaProviderError("所选配置不是语音生成接口", retryable=False)
    adapter = config.adapter_config_json or {}
    endpoint = f"{config.base_url.rstrip('/')}/{str(adapter.get('endpoint_path') or '/audio/speech').lstrip('/')}"
    payload = dict(adapter.get("extra_payload") or {})
    payload.update({
        str(adapter.get("model_field") or "model"): config.model_name,
        str(adapter.get("prompt_field") or "input"): text,
        str(adapter.get("voice_field") or "voice"): adapter.get("voice_value") or voice_style,
    })
    async with build_async_client(endpoint, timeout=config.timeout_seconds, follow_redirects=False) as client:
        response = await client.post(endpoint, headers=_headers(config), json=payload)
    response.raise_for_status()
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if mime in AUDIO_MIME_TYPES:
        return MediaResult(response.content, mime)
    raw, mime = await _decode_result(response.json(), adapter, config, AUDIO_MIME_TYPES)
    return MediaResult(raw, mime)


async def cancel_video_job(config: ModelConfig, provider_job_id: str) -> None:
    adapter = config.adapter_config_json or {}
    template = adapter.get("cancel_endpoint_path")
    if not provider_job_id or not template:
        return
    path = str(template).replace("{job_id}", provider_job_id)
    endpoint = f"{config.base_url.rstrip('/')}/{path.lstrip('/')}"
    async with build_async_client(endpoint, timeout=min(config.timeout_seconds, 30), follow_redirects=False) as client:
        await client.post(endpoint, headers=_headers(config))
