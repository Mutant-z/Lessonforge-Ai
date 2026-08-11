"""Task 9: 几何蓝图图渲染 + 视觉模型自检工具（vision_tools）测试。"""
import json

import httpx
import pytest

from app.agent.layouts.zones import zones_for
from app.agent.tools.vision_tools import (
    ReviewVerdict,
    provider_supports_vision,
    render_geometry_preview,
)
from app.providers.llm.mock import MockProvider


def test_render_geometry_preview_returns_png_b64():
    slide = {"page_type": "concept", "title": "标题", "body": ["要点一", "要点二"]}
    from app.agent.layouts.engine import compile_layout

    spec = compile_layout(
        "lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "bullet_flow"}
    )
    zones = zones_for("lessonforge_deck_academic", "concept")
    png = render_geometry_preview(spec, zones)
    assert png.startswith("iVBOR")  # PNG magic base64
    assert len(png) > 100


def test_provider_supports_vision_mock_false():
    assert provider_supports_vision(MockProvider()) is False


def test_provider_supports_vision_real_providers_true():
    from app.providers.llm.anthropic import AnthropicProvider
    from app.providers.llm.openai_compatible import OpenAICompatibleProvider

    assert provider_supports_vision(AnthropicProvider(api_key="k")) is True
    assert (
        provider_supports_vision(
            OpenAICompatibleProvider(api_key="k", base_url="https://model.test/v1", model_name="m")
        )
        is True
    )


def test_review_verdict_accepts_pass_alias():
    verdict = ReviewVerdict.model_validate({"pass": True, "issues": []})
    assert verdict.pass_ is True
    assert verdict.issues == []
    dumped = verdict.model_dump(by_alias=True)
    assert dumped["pass"] is True
    assert "pass_" not in dumped


def test_tools_registered():
    from app.agent.registry import ensure_loaded, get_tool

    ensure_loaded()
    assert get_tool("render_geometry_preview") is not None
    assert get_tool("review_geometry_vision") is not None


@pytest.mark.asyncio
async def test_review_geometry_vision_no_vision_skip():
    from app.agent.registry import ToolContext, ensure_loaded, execute_tool

    ensure_loaded()

    class _Runtime:
        provider = MockProvider()

    tc = ToolContext(runtime=_Runtime())
    result = await execute_tool("review_geometry_vision", tc, {"slide_id": "S01"})
    assert result.ok is True
    assert result.output.get("skipped") == "no_vision"
    assert result.output["verdict"]["pass"] is True
    assert result.output["verdict"]["issues"] == []


@pytest.mark.asyncio
async def test_render_geometry_preview_tool_via_registry():
    from app.agent.registry import ToolContext, ensure_loaded, execute_tool
    from app.renderers.presentation_builder import PresentationBuilder

    ensure_loaded()
    builder = PresentationBuilder("lessonforge_deck_academic")
    sid = builder.create_slide(page_type="concept", title="标题")
    builder.add_textbox(sid, "要点一", 2.2, 1.7, 8.0, 0.6)
    tc = ToolContext(builder=builder)
    result = await execute_tool("render_geometry_preview", tc, {"slide_id": sid})
    assert result.ok is True
    assert result.output["preview_png"].startswith("iVBOR")


@pytest.mark.asyncio
async def test_anthropic_structured_with_image_sends_image_content_block(monkeypatch):
    from app.providers.llm.anthropic import AnthropicProvider

    captured: dict = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "tool_use", "name": "output", "input": {"pass": True, "issues": []}}
                ]
            },
        )

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)

    provider = AnthropicProvider(api_key="test-key", base_url="https://api.anthropic.com")
    verdict = await provider.structured_with_image(
        "system", "prompt", "aGVsbG8=", "image/png", ReviewVerdict
    )
    assert verdict.pass_ is True
    content = captured["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": "aGVsbG8=",
    }
    assert content[1]["type"] == "text"
    assert content[1]["text"] == "prompt"
    assert captured["body"]["tool_choice"] == {"type": "tool", "name": "output"}


@pytest.mark.asyncio
async def test_openai_compatible_structured_with_image_sends_image_url(monkeypatch):
    from app.providers.llm.openai_compatible import OpenAICompatibleProvider

    payloads: list[dict] = []

    def handler(request: httpx.Request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"pass": true, "issues": []}', "role": "assistant"}}
                ]
            },
        )

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)

    provider = OpenAICompatibleProvider(
        api_key="test-key", base_url="https://model.test/v1", model_name="test-model",
        timeout_seconds=10,
    )
    verdict = await provider.structured_with_image(
        "system", "prompt", "aGVsbG8=", "image/png", ReviewVerdict
    )
    assert verdict.pass_ is True
    content = payloads[0]["messages"][1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="
    assert content[1]["type"] == "text"
    assert payloads[0]["response_format"] == {"type": "json_object"}
