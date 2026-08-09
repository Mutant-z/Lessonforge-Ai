import base64
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.models.entities import ModelConfig
from app.services import exercise_visual_service


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), "navy").save(buffer, format="PNG")
    return buffer.getvalue()


def _config(**overrides) -> ModelConfig:
    values = {
        "owner_id": "owner",
        "name": "image",
        "provider": "openai_compatible",
        "base_url": "https://images.example/v1",
        "model_name": "image-model",
        "timeout_seconds": 5,
        "api_mode": "custom_image_http",
        "adapter_config_json": {},
        "capabilities_json": ["image_generation"],
        "is_active": True,
    }
    values.update(overrides)
    return ModelConfig(**values)


def _mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def factory(_url, **kwargs):
        kwargs.pop("follow_redirects", None)
        return httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(exercise_visual_service, "build_async_client", factory)


@pytest.mark.asyncio
async def test_custom_image_http_accepts_base64_response(monkeypatch):
    encoded = base64.b64encode(_png()).decode()

    def handler(request: httpx.Request):
        assert str(request.url) == "https://images.example/v1/images/generations"
        return httpx.Response(200, json={"data": [{"b64_json": encoded}]})

    _mock_client(monkeypatch, handler)
    raw, mime = await exercise_visual_service.generate_image(_config(), "submarine", "1024x768")
    assert raw == _png()
    assert mime == "image/png"


@pytest.mark.asyncio
async def test_custom_image_http_accepts_url_mapping(monkeypatch):
    def handler(_request: httpx.Request):
        return httpx.Response(200, json={"result": {"url": "https://cdn.example/image.png"}})

    _mock_client(monkeypatch, handler)
    async def fake_download(*_args, **_kwargs):
        return _png(), "image/png"

    monkeypatch.setattr(exercise_visual_service, "_safe_remote_image", fake_download)
    config = _config(adapter_config_json={
        "response_base64_path": "result.missing",
        "response_url_path": "result.url",
    })
    raw, mime = await exercise_visual_service.generate_image(config, "submarine", "1024x768")
    assert raw == _png() and mime == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {"unexpected": True},
    {"data": [{"b64_json": "not-base64"}]},
])
async def test_custom_image_http_rejects_invalid_response(monkeypatch, response):
    _mock_client(monkeypatch, lambda _request: httpx.Response(200, json=response))
    with pytest.raises((KeyError, ValueError)):
        await exercise_visual_service.generate_image(_config(), "submarine", "1024x768")


@pytest.mark.asyncio
async def test_custom_image_http_propagates_timeout(monkeypatch):
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    _mock_client(monkeypatch, handler)
    with pytest.raises(httpx.ReadTimeout):
        await exercise_visual_service.generate_image(_config(), "submarine", "1024x768")
