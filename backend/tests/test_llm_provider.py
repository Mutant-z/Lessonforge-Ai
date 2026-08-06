import json

import httpx
import pytest
from pydantic import BaseModel

from app.providers.llm.base import LLMProviderError
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.llm.streaming import ThinkingStreamParser, extract_thinking


class Probe(BaseModel):
    ok: bool


def provider_with_handler(monkeypatch, handler):
    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        # MockTransport 与 proxy 在 httpx 中互斥，注入 transport 时移除代理
        kwargs.pop("proxy", None)
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
async def test_structured_recovers_after_two_empty_content_responses(monkeypatch):
    payloads = []

    def handler(request: httpx.Request):
        payloads.append(json.loads(request.content))
        if len(payloads) < 3:
            return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    provider = provider_with_handler(monkeypatch, handler)
    result = await provider.structured("system", "probe", Probe)

    assert result.ok is True
    assert len(payloads) == 3
    assert "上一次返回为空或不符合结构" in payloads[2]["messages"][1]["content"]


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
async def test_strip_json_fence_extracts_embedded_json():
    content = "Here is the result:\n```json\n{\"ok\": true}\n```\nHope this helps!"
    assert OpenAICompatibleProvider._strip_json_fence(content) == '{"ok": true}'

    content_text_around = "Sure! {\"ok\": true} Thank you."
    assert OpenAICompatibleProvider._strip_json_fence(content_text_around) == '{"ok": true}'


@pytest.mark.asyncio
async def test_connection_probe_rejects_empty_success_response(monkeypatch):
    provider = provider_with_handler(monkeypatch, lambda _request: httpx.Response(200, content=b""))

    success, message = await provider.test_connection()

    assert success is False
    assert "空响应" in message


def _sse_body(chunks):
    """把 JSON 内容块拼成 OpenAI 流式 SSE 响应体。"""
    lines = "".join(
        f'data: {{"choices":[{{"delta":{{"content":{json.dumps(c)}}}}}]}}\n\n'
        for c in chunks
    )
    return lines + "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_decision_yields_thought_deltas_and_decision(monkeypatch):
    from app.agent.schemas import AgentDecision

    chunks = [
        '{"thinking": "先分析需求，',
        '再决定是否调用工具。", "tool_calls": [{"tool_name": "get_blueprint", "input": {}}], "completed": false}',
    ]

    def handler(_request):
        return httpx.Response(200, content=_sse_body(chunks).encode())

    provider = provider_with_handler(monkeypatch, handler)
    thoughts = []
    decision = None
    async for kind, payload in provider.stream_decision("system", "prompt", AgentDecision):
        if kind == "thought_delta":
            thoughts.append(payload)
        elif kind == "decision_ready":
            decision = payload

    assert "".join(thoughts) == "先分析需求，再决定是否调用工具。"
    assert decision is not None
    assert decision.tool_calls[0].tool_name == "get_blueprint"


@pytest.mark.asyncio
async def test_stream_decision_falls_back_to_structured_on_empty_stream(monkeypatch):
    from app.agent.schemas import AgentDecision

    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(200, content=_sse_body([""]).encode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"thinking": "兜底", "completed": true, "output": {"slides": []}, "summary": "完成"}'}}],
        })

    provider = provider_with_handler(monkeypatch, handler)
    decision = None
    async for kind, payload in provider.stream_decision("system", "prompt", AgentDecision):
        if kind == "decision_ready":
            decision = payload

    assert decision is not None
    assert decision.completed is True


def test_thinking_stream_parser_incremental_extraction():
    parser = ThinkingStreamParser()
    emitted = ""
    for chunk in ['{"thinking": "逐步', '推理', '，再行动。"}', '{"completed": true}']:
        emitted += parser.feed(chunk)
    assert emitted == "逐步推理，再行动。"
    assert extract_thinking('{"a": {"thinking": "内层"}, "thinking": "外层"}') == "外层"
    assert extract_thinking('{"thinking": "未闭合') == "未闭合"


def test_sanitize_control_chars_escapes_raw_newlines_inside_strings():
    raw = '{"ok": "是\n否\t\\n已转义\r", "list": ["a\nb"]}'
    sanitized = OpenAICompatibleProvider._sanitize_control_chars(raw)
    # 已转义的 \\n 原样保留
    assert "\\n已转义" in sanitized
    parsed = json.loads(sanitized)
    assert parsed["ok"] == "是\n否\t\n已转义\r"
    assert parsed["list"] == ["a\nb"]


def test_sanitize_control_chars_preserves_escaped_sequences():
    raw = r'{"ok": "line1\nline2\ttab", "n": 1}'
    sanitized = OpenAICompatibleProvider._sanitize_control_chars(raw)
    assert sanitized == raw
    assert json.loads(sanitized)["ok"] == "line1\nline2\ttab"


def test_try_repair_truncated_json_closes_structures():
    cases = [
        '{"content_json": {"items": [1, 2, 3], "name": "test"',
        '{"content_json": {"name": "test',
        '{"content_json": {"items": [1, 2,',
        '{"content_json": {"name":',
        '{"content_json": {"items": [1, 2], "name": "test",',
    ]
    for case in cases:
        repaired = OpenAICompatibleProvider._try_repair_truncated_json(case)
        assert repaired is not None, case
        assert "content_json" in repaired


def test_finish_reason_is_length_detects_truncation():
    assert OpenAICompatibleProvider._finish_reason_is_length(
        {"choices": [{"finish_reason": "length"}]}
    ) is True
    assert OpenAICompatibleProvider._finish_reason_is_length(
        {"choices": [{"finish_reason": "stop"}]}
    ) is False
    assert OpenAICompatibleProvider._finish_reason_is_length({}) is False
