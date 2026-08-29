import base64
import json

import httpx
import pytest

from app.core.security import encrypt_secret
from app.models.entities import ModelConfig
from app.services.media_provider_service import MediaProviderError, media_transport_supports
from app.services.openai_chat_video_service import OpenAIChatVideoAdapter


def _config(model_name: str = "gemini-3.7-flash-high", provider: str = "openai_compatible") -> ModelConfig:
    return ModelConfig(
        owner_id="owner",
        name="General model",
        provider=provider,
        base_url="http://127.0.0.1:8045",
        model_name=model_name,
        encrypted_api_key=encrypt_secret("test-secret"),
        timeout_seconds=10,
        capabilities_json=[
            "text_generation",
            "structured_output",
            "video_generation",
            "native_audio_video_generation",
        ],
        api_mode="protocol_video",
        model_category="video",
        model_purpose="video_generation",
    )


def test_general_model_transport_supports_native_video():
    assert media_transport_supports("openai_compatible", "protocol_video", "video_generation")
    assert media_transport_supports("anthropic", "protocol_video", "native_audio_video_generation")


@pytest.mark.asyncio
async def test_general_model_name_is_forwarded(monkeypatch):
    raw = b"generated-video"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/video/generations"
        payload = request.read().decode()
        assert '"model":"gemini-3.7-flash-high"' in payload
        assert '"duration":8' in payload
        assert '"size":"720p"' in payload
        assert '"metadata"' not in payload
        assert '"width"' not in payload
        assert '"height"' not in payload
        return httpx.Response(200, json={
            "id": "request-1",
            "model": "gemini-3.7-flash-high",
            "choices": [{"message": {"content": [{
                "type": "video",
                "mime_type": "video/mp4",
                "data": base64.b64encode(raw).decode(),
            }]}}],
        })

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await OpenAIChatVideoAdapter(_config()).generate(
        prompt="generate a lesson video",
        duration_seconds=8,
        resolution="1280x720",
        idempotency_key="idem-1",
    )
    assert result.raw == raw
    assert result.actual_model_name == "gemini-3.7-flash-high"


@pytest.mark.asyncio
async def test_anthropic_protocol_accepts_video_content_block(monkeypatch):
    raw = b"anthropic-video"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-secret"
        payload = request.read().decode()
        assert '"output_modalities":["video","audio"]' in payload
        return httpx.Response(200, json={
            "id": "message-1",
            "model": "universal-video-model",
            "content": [{
                "type": "video",
                "mime_type": "video/mp4",
                "data": base64.b64encode(raw).decode(),
            }],
        })

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await OpenAIChatVideoAdapter(_config("universal-video-model", "anthropic")).generate(
        prompt="generate a lesson video",
        duration_seconds=8,
        resolution="1280x720",
        idempotency_key="idem-anthropic",
    )
    assert result.raw == raw
    assert result.actual_model_name == "universal-video-model"


@pytest.mark.asyncio
async def test_protocol_video_accepts_sse_video_content(monkeypatch):
    raw = b"streamed-video"

    def handler(request: httpx.Request) -> httpx.Response:
        event = {
            "id": "stream-request-1",
            "choices": [{"delta": {"content": [{
                "type": "video",
                "mime_type": "video/mp4",
                "data": base64.b64encode(raw).decode(),
            }]}}],
        }
        body = f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await OpenAIChatVideoAdapter(_config("Seedance-2.0")).generate(
        prompt="generate a lesson video",
        duration_seconds=8,
        resolution="1280x720",
        idempotency_key="idem-stream",
    )
    assert result.raw == raw
    assert result.provider_job_id == "stream-request-1"


@pytest.mark.asyncio
async def test_newapi_video_job_is_polled_by_task_id(monkeypatch):
    raw = b"newapi-video"
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(201, json={
                "id": "video-wrapper-1",
                "task_id": "task-1",
                "status": "processing",
            })
        return httpx.Response(200, json={
            "task_id": "task-1",
            "status": "succeeded",
            "url": "https://media.example.test/result.mp4",
        })

    async def safe_download(url, config, allowed_mimes):
        assert url == "https://media.example.test/result.mp4"
        return raw, "video/mp4"

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr("app.services.openai_chat_video_service._safe_remote_media", safe_download)
    monkeypatch.setattr("app.services.openai_chat_video_service.asyncio.sleep", lambda _: _noop())
    result = await OpenAIChatVideoAdapter(_config("Seedance-2.0")).generate(
        prompt="lesson scene",
        duration_seconds=10,
        resolution="1280x720",
        idempotency_key="idem-newapi",
    )
    assert requests == [
        ("POST", "/v1/video/generations"),
        ("GET", "/v1/video/generations/task-1"),
    ]
    assert result.raw == raw
    assert result.provider_job_id == "task-1"


@pytest.mark.asyncio
async def test_newapi_nested_video_url_is_downloaded(monkeypatch):
    raw = b"nested-newapi-video"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"task_id": "task-nested"})
        return httpx.Response(200, json={
            "code": "success",
            "data": {
                "task_id": "task-nested",
                "status": "SUCCESS",
                "data": {
                    "status": "completed",
                    "video_url": "https://media.example.test/nested.mp4",
                },
            },
        })

    async def safe_download(url, config, allowed_mimes):
        assert url == "https://media.example.test/nested.mp4"
        return raw, "video/mp4"

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr("app.services.openai_chat_video_service._safe_remote_media", safe_download)
    monkeypatch.setattr("app.services.openai_chat_video_service.asyncio.sleep", lambda _: _noop())
    result = await OpenAIChatVideoAdapter(_config("Seedance-2.0")).generate(
        prompt="lesson scene",
        duration_seconds=10,
        resolution="1280x720",
        idempotency_key="idem-nested",
    )
    assert result.raw == raw
    assert result.provider_job_id == "task-nested"


@pytest.mark.asyncio
async def test_newapi_task_id_without_status_is_polled_and_can_resume(monkeypatch):
    raw = b"resumed-newapi-video"
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(201, json={"task_id": "task-without-status"})
        return httpx.Response(200, json={
            "task_id": "task-without-status",
            "status": "succeeded",
            "url": "https://media.example.test/resumed.mp4",
        })

    async def safe_download(url, config, allowed_mimes):
        assert url == "https://media.example.test/resumed.mp4"
        return raw, "video/mp4"

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr("app.services.openai_chat_video_service._safe_remote_media", safe_download)
    monkeypatch.setattr("app.services.openai_chat_video_service.asyncio.sleep", lambda _: _noop())
    adapter = OpenAIChatVideoAdapter(_config("Seedance-2.0"))
    generated = await adapter.generate(
        prompt="lesson scene",
        duration_seconds=10,
        resolution="1280x720",
        idempotency_key="idem-no-status",
    )
    resumed = await adapter.resume("task-without-status")
    assert generated.raw == resumed.raw == raw
    assert requests == [
        ("POST", "/v1/video/generations"),
        ("GET", "/v1/video/generations/task-without-status"),
        ("GET", "/v1/video/generations/task-without-status"),
    ]


async def _noop():
    return None


@pytest.mark.asyncio
async def test_protocol_disconnect_is_retryable_transport_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(MediaProviderError) as caught:
        await OpenAIChatVideoAdapter(_config("Seedance-2.0")).generate(
            prompt="generate a lesson video",
            duration_seconds=8,
            resolution="1280x720",
            idempotency_key="idem-disconnect",
        )
    assert caught.value.code == "video_transport_disconnected"
    assert caught.value.retryable is True
    assert "模型拒绝" not in str(caught.value)


@pytest.mark.asyncio
async def test_protocol_rejection_includes_gateway_detail(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "code": "invalid_resolution",
            "message": 'Seedance-2.0 resolution "1280x720" is not supported',
        })

    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(MediaProviderError) as caught:
        await OpenAIChatVideoAdapter(_config("Seedance-2.0")).generate(
            prompt="generate a lesson video",
            duration_seconds=8,
            resolution="1280x720",
            idempotency_key="idem-invalid-resolution",
        )
    assert caught.value.code == "video_generation_rejected"
    assert "invalid_resolution" not in str(caught.value)
    assert 'resolution "1280x720" is not supported' in str(caught.value)


@pytest.mark.asyncio
async def test_general_model_probe_uses_existing_chat_route(monkeypatch):
    monkeypatch.setattr(
        "app.services.openai_chat_video_service.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(405, headers={"allow": "POST"}))
        ),
    )
    result = await OpenAIChatVideoAdapter(_config("any-capable-model")).probe_capabilities()
    assert result["model"] == "any-capable-model"
    assert result["native_audio"] is True
