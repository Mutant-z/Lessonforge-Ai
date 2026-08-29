import base64

import httpx
import pytest

from app.core.config import get_settings
from app.core.security import encrypt_secret
from app.models.entities import ModelConfig
from app.services import gemini_interactions_video_service as gemini
from app.services.media_provider_service import MediaProviderError, media_transport_supports


def _config(base_url: str = "http://127.0.0.1:8045/v1/messages") -> ModelConfig:
    return ModelConfig(
        owner_id="owner",
        name="Gemini Omni",
        provider="openai_compatible",
        base_url=base_url,
        model_name="gemini-omni-flash-preview",
        encrypted_api_key=encrypt_secret("test-secret"),
        timeout_seconds=10,
        capabilities_json=["video_generation", "native_audio_video_generation"],
        api_mode="gemini_interactions_video",
        adapter_config_json={"max_file_mb": 1, "poll_interval_seconds": .5},
    )


@pytest.fixture(autouse=True)
def enable_gemini_video():
    settings = get_settings()
    previous = settings.gemini_interactions_video_enabled
    settings.gemini_interactions_video_enabled = True
    yield
    settings.gemini_interactions_video_enabled = previous


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:8045",
        "http://127.0.0.1:8045/",
        "http://127.0.0.1:8045/v1",
        "http://127.0.0.1:8045/v1/messages",
    ],
)
def test_gateway_origin_normalization(value):
    assert gemini.normalize_gateway_origin(value) == "http://127.0.0.1:8045"


def test_transport_claims_are_strict():
    assert media_transport_supports("openai_compatible", "gemini_interactions_video", "native_audio_video_generation")
    assert not media_transport_supports("openai_compatible", "text_chat", "native_audio_video_generation")


@pytest.mark.asyncio
async def test_inline_base64_video_response(monkeypatch):
    raw = b"small-mp4-payload"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/interactions"
        assert request.headers["authorization"] == "Bearer test-secret"
        payload = request.read().decode()
        assert '"model":"gemini-omni-flash-preview"' in payload
        return httpx.Response(200, json={
            "id": "interaction-1",
            "model": "gemini-omni-flash-preview",
            "steps": [{"content": [{
                "type": "video",
                "mime_type": "video/mp4",
                "data": base64.b64encode(raw).decode(),
            }]}],
        })

    monkeypatch.setattr(
        gemini,
        "build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    started = []
    result = await gemini.GeminiInteractionsVideoAdapter(_config()).generate(
        prompt="生成中文口播视频",
        duration_seconds=6,
        resolution="1280x720",
        idempotency_key="idem-1",
        job_started=lambda value: _append(started, value),
    )
    assert result.raw == raw
    assert result.provider_job_id == "interaction-1"
    assert started == ["interaction-1"]


async def _append(target: list[str], value: str) -> None:
    target.append(value)


@pytest.mark.asyncio
async def test_uri_file_poll_and_same_origin_download(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query.decode()))
        assert request.headers["authorization"] == "Bearer test-secret"
        if request.method == "POST":
            return httpx.Response(200, json={
                "id": "interaction-2",
                "output_video": {"uri": "/v1beta/files/file-2"},
            })
        if request.url.path == "/v1beta/files/file-2":
            return httpx.Response(200, json={"name": "files/file-2", "state": "ACTIVE"})
        if request.url.path == "/v1beta/files/file-2:download":
            return httpx.Response(200, content=b"downloaded-mp4", headers={"content-type": "video/mp4"})
        return httpx.Response(404)

    monkeypatch.setattr(
        gemini,
        "build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    files = []
    result = await gemini.GeminiInteractionsVideoAdapter(_config("http://127.0.0.1:8045/v1")).generate(
        prompt="prompt",
        duration_seconds=10,
        resolution="1280x720",
        idempotency_key="idem-2",
        file_started=lambda value: _append(files, value),
    )
    assert result.raw == b"downloaded-mp4"
    assert result.provider_file_id == "file-2"
    assert files == ["file-2"]
    assert ("GET", "/v1beta/files/file-2:download", "alt=media") in calls


@pytest.mark.asyncio
async def test_missing_media_is_structured_error(monkeypatch):
    monkeypatch.setattr(
        gemini,
        "build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "COMPLETED"}))
        ),
    )
    with pytest.raises(MediaProviderError) as caught:
        await gemini.GeminiInteractionsVideoAdapter(_config()).generate(
            prompt="prompt", duration_seconds=6, resolution="1280x720", idempotency_key="idem-3",
        )
    assert caught.value.code == "video_response_missing_media"


@pytest.mark.asyncio
async def test_duration_range_is_enforced_before_request():
    with pytest.raises(MediaProviderError) as caught:
        await gemini.GeminiInteractionsVideoAdapter(_config()).generate(
            prompt="prompt", duration_seconds=11, resolution="1280x720", idempotency_key="idem-4",
        )
    assert caught.value.code == "video_scene_duration_unsupported"


@pytest.mark.asyncio
async def test_probe_rejects_gateway_wide_options_false_positive(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        # This mirrors the local gateway: generic CORS OPTIONS succeeds even
        # though the authenticated route lookup proves the endpoint is absent.
        if request.method == "OPTIONS":
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(404)

    monkeypatch.setattr(
        gemini,
        "build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(MediaProviderError) as caught:
        await gemini.GeminiInteractionsVideoAdapter(_config()).probe_capabilities()
    assert caught.value.code == "video_interactions_endpoint_unavailable"
    assert calls == ["GET"]


@pytest.mark.asyncio
async def test_probe_accepts_existing_post_only_route(monkeypatch):
    monkeypatch.setattr(
        gemini,
        "build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(405, headers={"allow": "POST"}))
        ),
    )
    result = await gemini.GeminiInteractionsVideoAdapter(_config()).probe_capabilities()
    assert result["native_audio"] is True
    assert result["source"] == "gateway_endpoint_probe"
