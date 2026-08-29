import base64
import json

import httpx
import pytest

from app.core.security import encrypt_secret
from app.models.entities import ModelConfig
from app.services import audio_transcription_service as audio_service


def gemini_config() -> ModelConfig:
    return ModelConfig(
        owner_id="owner",
        name="Gemini 3.7",
        provider="anthropic",
        base_url="http://127.0.0.1:8045/v1",
        model_name="gemini-3.7-flash-high",
        encrypted_api_key=encrypt_secret("gateway-key"),
        timeout_seconds=10,
        capabilities_json=["text_generation", "structured_output"],
        api_mode="text_chat",
        adapter_config_json={},
        model_category="text",
        model_purpose="text_chat",
    )


@pytest.mark.asyncio
async def test_existing_gemini_chat_config_transcribes_audio(monkeypatch, tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF-test-audio")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models/gemini-3.7-flash-high:generateContent"
        assert request.headers["x-api-key"] == "gateway-key"
        payload = json.loads(request.content)
        inline = payload["contents"][0]["parts"][1]["inlineData"]
        assert base64.b64decode(inline["data"]) == b"RIFF-test-audio"
        return httpx.Response(200, json={
            "candidates": [{
                "content": {"parts": [{"text": json.dumps({
                    "text": "浮力产生的原因是液体上下表面的压力差。",
                    "segments": [{
                        "start_seconds": 0,
                        "end_seconds": 3.5,
                        "text": "浮力产生的原因是液体上下表面的压力差。",
                    }],
                }, ensure_ascii=False)}]},
            }],
            "usageMetadata": {"totalTokenCount": 32},
        })

    monkeypatch.setattr(
        audio_service,
        "build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await audio_service.transcribe_audio(gemini_config(), audio)
    assert result.text == "浮力产生的原因是液体上下表面的压力差。"
    assert result.segments[0]["end_seconds"] == 3.5
    assert result.usage == {"totalTokenCount": 32}


def test_non_gemini_chat_config_is_not_implicitly_audio_capable():
    config = gemini_config()
    config.model_name = "deepseek-v4-flash"
    assert not audio_service.is_gemini_audio_transcription_config(config)
