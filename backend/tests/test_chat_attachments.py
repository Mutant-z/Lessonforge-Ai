"""多模态对话附件：Provider 线路与提示词拼装测试。"""

import json

import httpx
import pytest

from app.providers.llm.anthropic import AnthropicProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.services.chat_attachment_service import ChatAttachment, attachment_prompt
from app.agent.tools.vision_tools import ReviewVerdict


def test_attachment_prompt_contains_filename_and_extracted_text():
    prompt = attachment_prompt([
        ChatAttachment(
            id="m1",
            filename="课堂观察记录.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=12,
            extracted_text="学生在小组讨论中能够说明理由。",
        ),
    ])

    assert "课堂观察记录.docx" in prompt
    assert "学生在小组讨论中能够说明理由。" in prompt


@pytest.mark.asyncio
async def test_chat_attachment_upload_is_course_owned_and_keeps_material_metadata(client, auth_headers):
    course = await client.post("/api/v1/courses", headers=auth_headers, json={
        "title": "附件测试课",
        "subject": "语文",
        "grade_level": "八年级",
        "audience": "测试教师",
        "duration_minutes": 10,
        "scenario": "课堂讲解",
        "course_task": "根据材料设计课堂活动",
    })
    assert course.status_code == 201, course.text

    uploaded = await client.post(
        f"/api/v1/courses/{course.json()['id']}/chat-attachments",
        headers=auth_headers,
        files={"file": ("课堂观察.md", "学生能够说明理由。".encode(), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    assert payload["original_filename"] == "课堂观察.md"
    assert payload["usage_policy"] == "chat_attachment"
    assert payload["parse_status"] == "completed"

    listed = await client.get(f"/api/v1/courses/{course.json()['id']}/materials", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == payload["id"] for item in listed.json())


@pytest.mark.asyncio
async def test_openai_compatible_attachments_send_image_and_pdf_blocks(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"pass": true, "issues": []}'}}],
        })

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    provider = OpenAICompatibleProvider(
        api_key="test-key", base_url="https://model.test/v1", model_name="vision-model",
    )

    result = await provider.structured_with_attachments(
        "system",
        "请检查附件",
        [
            {"filename": "课堂照片.png", "mime_type": "image/png", "data_b64": "aW1hZ2U="},
            {"filename": "课标.pdf", "mime_type": "application/pdf", "data_b64": "cGRm"},
        ],
        ReviewVerdict,
    )

    assert result.pass_ is True
    content = captured["body"]["messages"][1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/png;base64,aW1hZ2U="
    assert content[1]["type"] == "file"
    assert content[1]["file"]["filename"] == "课标.pdf"
    assert content[1]["file"]["file_data"] == "data:application/pdf;base64,cGRm"
    assert content[2]["type"] == "text"


@pytest.mark.asyncio
async def test_anthropic_attachments_send_image_and_pdf_blocks(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "content": [{"type": "tool_use", "name": "output", "input": {"pass": True, "issues": []}}],
        })

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    provider = AnthropicProvider(api_key="test-key", base_url="https://api.anthropic.com")

    result = await provider.structured_with_attachments(
        "system",
        "请检查附件",
        [
            {"filename": "课堂照片.webp", "mime_type": "image/webp", "data_b64": "aW1hZ2U="},
            {"filename": "课标.pdf", "mime_type": "application/pdf", "data_b64": "cGRm"},
        ],
        ReviewVerdict,
    )

    assert result.pass_ is True
    content = captured["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/webp"
    assert content[1]["type"] == "document"
    assert content[1]["source"]["media_type"] == "application/pdf"
    assert content[2]["type"] == "text"
