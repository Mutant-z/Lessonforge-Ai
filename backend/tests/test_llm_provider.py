import json

import httpx
import pytest
from pydantic import BaseModel

from app.providers.llm.base import LLMProviderError
from app.providers.llm.openai_compatible import OpenAICompatibleProvider


class Probe(BaseModel):
    ok: bool


def provider_with_handler(monkeypatch, handler):
    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    return OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://model.test/v1",
        model_name="test-model",
        timeout_seconds=10,
    )


@pytest.mark.asyncio
async def test_structured_falls_back_without_json_mode_on_empty_response(monkeypatch):
    payloads = []

    def handler(request: httpx.Request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(200, content=b"")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}]},
        )

    provider = provider_with_handler(monkeypatch, handler)
    result = await provider.structured("system", "probe", Probe)

    assert result.ok is True
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_factory", "code"),
    [
        (lambda: httpx.Response(200, content=b""), "upstream_empty_response"),
        (lambda: httpx.Response(200, text="not-json"), "upstream_invalid_response"),
        (lambda: httpx.Response(200, json={"unexpected": True}), "upstream_invalid_response"),
        (
            lambda: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
            "upstream_empty_content",
        ),
        (
            lambda: httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
            "upstream_invalid_json",
        ),
        (
            lambda: httpx.Response(200, json={"choices": [{"message": {"content": '{"other": 1}'}}]}),
            "upstream_schema_mismatch",
        ),
    ],
)
async def test_structured_reports_stable_content_errors(monkeypatch, response_factory, code):
    provider = provider_with_handler(monkeypatch, lambda _request: response_factory())

    with pytest.raises(LLMProviderError) as caught:
        await provider.structured("system", "probe", Probe)

    assert caught.value.code == code
    assert "Expecting value" not in caught.value.user_message


@pytest.mark.asyncio
async def test_connection_probe_rejects_empty_success_response(monkeypatch):
    provider = provider_with_handler(monkeypatch, lambda _request: httpx.Response(200, content=b""))

    success, message = await provider.test_connection()

    assert success is False
    assert "空响应" in message
