"""Shared chat-attachment preparation for the six content Agents.

Uploads are stored as course materials so the existing ownership and cleanup
rules remain the single source of truth.  The database keeps only safe
attachment metadata on an AgentMessage; binary data is loaded into the
per-run runtime immediately before the model call.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import AgentChatSession, CourseProject, Material, MaterialChunk, User
from app.providers.llm.base import DecisionStreamEvent, LLMProvider, T
from app.services.model_config_service import resolve_provider

IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
NATIVE_FILE_MIME_TYPES = IMAGE_MIME_TYPES | {"application/pdf"}
MAX_CHAT_ATTACHMENTS = 5
MAX_ATTACHMENT_PROMPT_CHARS = 24_000


@dataclass(frozen=True)
class ChatAttachment:
    """A validated attachment available to one Agent run.

    ``data_b64`` is intentionally runtime-only and never serialized into the
    AgentMessage metadata or a checkpoint.
    """

    id: str
    filename: str
    mime_type: str
    size_bytes: int
    extracted_text: str = ""
    data_b64: str = ""

    @property
    def is_native(self) -> bool:
        return self.mime_type in NATIVE_FILE_MIME_TYPES and bool(self.data_b64)

    def as_provider_input(self) -> dict[str, str]:
        return {
            "filename": self.filename,
            "mime_type": self.mime_type,
            "data_b64": self.data_b64,
        }


def _upload_path(material: Material) -> Path:
    return get_settings().storage_root / "uploads" / material.storage_name


async def validate_attachment_ids(
    db: AsyncSession,
    user: User,
    course_id: str,
    attachment_ids: list[str] | None,
) -> list[dict[str, Any]]:
    """Validate course ownership and return safe metadata for AgentMessage."""

    ids = list(dict.fromkeys(str(value).strip() for value in (attachment_ids or []) if str(value).strip()))
    if len(ids) > MAX_CHAT_ATTACHMENTS:
        raise HTTPException(422, f"一次最多上传 {MAX_CHAT_ATTACHMENTS} 个附件")
    if not ids:
        return []
    rows = list(await db.scalars(select(Material).where(
        Material.id.in_(ids), Material.course_id == course_id,
    )))
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(ids):
        raise HTTPException(404, "附件不存在或不属于当前课程")
    return [{
        "id": row.id,
        "filename": row.original_filename,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "parse_status": row.parse_status,
    } for row in (by_id[item] for item in ids)]


def attachment_metadata(attachments: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the stable message metadata shape used by every task endpoint."""

    return {"attachments": attachments} if attachments else {}


async def prepare_chat_attachments(
    db: AsyncSession,
    course: CourseProject,
    user_message: Any,
    fallback_provider: LLMProvider,
) -> tuple[list[ChatAttachment], LLMProvider]:
    """Load binary/text input and select the configured vision provider.

    Text-only attachments are represented as extracted text in the prompt.
    Images and PDFs are also sent as native multimodal blocks when a vision
    model is configured for this task.  If no separate vision model is bound,
    the selected task provider remains the fallback; this preserves Mock and
    compatible gateway behavior while still keeping the attachment available.
    """

    metadata = dict(getattr(user_message, "metadata_json", None) or {})
    raw = metadata.get("attachments") or []
    ids = [str(item.get("id")) for item in raw if isinstance(item, dict) and item.get("id")]
    if not ids:
        return [], fallback_provider

    rows = list(await db.scalars(select(Material).where(
        Material.id.in_(ids), Material.course_id == course.id,
    )))
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(set(ids)):
        raise RuntimeError("对话附件不存在或不属于当前课程")
    chunks = list(await db.scalars(select(MaterialChunk).where(MaterialChunk.material_id.in_(ids))))
    chunks_by_material: dict[str, list[MaterialChunk]] = {}
    for chunk in chunks:
        chunks_by_material.setdefault(chunk.material_id, []).append(chunk)

    attachments: list[ChatAttachment] = []
    for material_id in ids:
        material = by_id[material_id]
        path = _upload_path(material)
        if not path.is_file():
            raise RuntimeError(f"附件文件不存在：{material.original_filename}")
        mime_type = material.mime_type or "application/octet-stream"
        data_b64 = ""
        if mime_type in NATIVE_FILE_MIME_TYPES:
            data_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        ordered_chunks = sorted(
            chunks_by_material.get(material_id, []),
            key=lambda item: item.chunk_index,
        )
        extracted_text = "\n\n".join(item.content for item in ordered_chunks if item.content).strip()
        attachments.append(ChatAttachment(
            id=material.id,
            filename=material.original_filename,
            mime_type=mime_type,
            size_bytes=material.size_bytes,
            extracted_text=extracted_text,
            data_b64=data_b64,
        ))

    # A task-level vision model is optional for legacy projects, but when it is
    # configured it must be the model that receives the native image/PDF blocks.
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == getattr(user_message, "module_type", ""),
    ))
    vision_id = session.vision_model_config_id if session else None
    provider = fallback_provider
    if vision_id:
        provider, _ = await resolve_provider(db, course.owner_id, vision_id, "vision")
    # Deterministic local runs must stay deterministic even when a user adds a
    # file.  The attachment is still persisted and shown in the transcript;
    # real providers below receive the native blocks.
    if getattr(provider, "name", "") == "mock":
        return attachments, provider
    return attachments, AttachmentAwareProvider(provider, attachments)


async def apply_runtime_attachments(
    db: AsyncSession,
    course: CourseProject,
    runtime: Any,
    metadata: dict[str, Any] | None,
) -> list[ChatAttachment]:
    """Refresh a live runtime when a queued instruction carries attachments."""

    if not (metadata or {}).get("attachments"):
        return []
    fallback = getattr(runtime, "provider", None)
    # Do not wrap an already attachment-aware provider repeatedly as queued
    # instructions are consumed at multiple safe boundaries.
    fallback = getattr(fallback, "provider", fallback)
    message = SimpleNamespace(
        module_type=getattr(getattr(runtime, "task", None), "task_type", ""),
        metadata_json=metadata or {},
        content="",
    )
    attachments, provider = await prepare_chat_attachments(db, course, message, fallback)
    if not attachments:
        return []
    runtime.provider = provider
    tool_context = getattr(runtime, "tool_context", None)
    if tool_context is not None:
        tool_context.provider = provider
    context = getattr(runtime, "context", None)
    if context is not None:
        context.add_note(attachment_prompt(attachments))
    request_metadata = getattr(runtime, "request_metadata", None)
    if isinstance(request_metadata, dict):
        request_metadata.update(metadata or {})
    return attachments


def attachment_prompt(attachments: list[ChatAttachment]) -> str:
    """Serialize extracted file text and visual instructions into the prompt."""

    if not attachments:
        return ""
    parts = ["\n\n## 用户本轮上传的附件\n请优先依据附件中的事实回答或修改，不要臆造附件未提供的内容。"]
    remaining = MAX_ATTACHMENT_PROMPT_CHARS
    for item in attachments:
        label = f"### {item.filename} ({item.mime_type})"
        if item.mime_type in IMAGE_MIME_TYPES:
            body = "该图片已作为原始视觉输入传给模型，请直接观察图片中的文字、结构、图表与版式。"
        elif item.mime_type == "application/pdf" and item.data_b64:
            body = "该 PDF 已作为原始文件输入传给模型。" + (f"\n提取文本：\n{item.extracted_text}" if item.extracted_text else "")
        else:
            body = item.extracted_text or "文件未提取到可用文本，请基于文件类型和可见内容处理。"
        text = f"{label}\n{body}"
        if len(text) > remaining:
            text = text[: max(0, remaining - 1)] + "…"
        parts.append(text)
        remaining -= len(text)
        if remaining <= 0:
            break
    return "\n\n".join(parts)


class AttachmentAwareProvider(LLMProvider):
    """Provider facade that transparently upgrades calls to multimodal input."""

    def __init__(self, provider: LLMProvider, attachments: list[ChatAttachment]):
        self.provider = provider
        self.attachments = [item.as_provider_input() for item in attachments if item.is_native]
        self.attachment_prompt_text = attachment_prompt(attachments)
        self.name = getattr(provider, "name", "")
        self.supports_native_tools = bool(getattr(provider, "supports_native_tools", False))

    async def structured(self, system: str, prompt: str, schema: type[T]) -> T:
        return await self.provider.structured(system, prompt + self.attachment_prompt_text, schema) if not self.attachments else await self.provider.structured_with_attachments(
            system, prompt + self.attachment_prompt_text, self.attachments, schema,
        )

    async def structured_with_image(self, system: str, prompt: str, image_b64: str, image_media_type: str, schema: type[T]) -> T:
        return await self.provider.structured_with_image(system, prompt, image_b64, image_media_type, schema)

    async def stream_decision(self, system: str, prompt: str, schema: type[T]):
        full_prompt = prompt + self.attachment_prompt_text
        if self.attachments:
            async for event in self.provider.stream_decision_with_attachments(system, full_prompt, self.attachments, schema):
                yield event
            return
        async for event in self.provider.stream_decision(system, full_prompt, schema):
            yield event

    async def native_agent_decision(self, system: str, prompt: str, tools: list[dict[str, Any]]):
        full_prompt = prompt + self.attachment_prompt_text
        if self.attachments:
            return await self.provider.native_agent_decision_with_attachments(system, full_prompt, self.attachments, tools)
        return await self.provider.native_agent_decision(system, full_prompt, tools)

    async def stream_text(self, system: str, prompt: str):
        async for chunk in self.provider.stream_text(system, prompt):
            yield chunk

    async def test_connection(self) -> tuple[bool, str]:
        return await self.provider.test_connection()

    def __getattr__(self, name: str):
        return getattr(self.provider, name)
