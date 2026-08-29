"""Provider-neutral transcription for native-video audio QA and subtitles."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select

from app.core.http_client import build_async_client
from app.core.security import decrypt_secret
from app.models.entities import ModelConfig
from app.services.gemini_interactions_video_service import normalize_gateway_origin
from app.services.media_provider_service import MediaProviderError
from app.services.seedance_provider_service import TranscriptResult, transcribe_doubao_audio


def is_gemini_audio_transcription_config(config: ModelConfig) -> bool:
    """Whether an existing Gemini chat config can be reused for audio input."""
    return bool(
        config.encrypted_api_key
        and config.model_name.lower().startswith("gemini-")
        and config.api_mode == "text_chat"
        and config.provider in {"anthropic", "openai_compatible"}
    )


async def resolve_audio_transcription_config(db, owner_id: str) -> ModelConfig | None:
    configs = list(await db.scalars(select(ModelConfig).where(ModelConfig.owner_id == owner_id)))
    explicit = next((
        item for item in configs
        if item.api_mode == "volcengine_asr"
        and "speech_recognition" in (item.capabilities_json or [])
    ), None)
    if explicit:
        return explicit
    candidates = [item for item in configs if is_gemini_audio_transcription_config(item)]
    candidates.sort(key=lambda item: (
        item.model_name != "gemini-3.7-flash-high",
        item.model_category != "text",
        item.name,
    ))
    return candidates[0] if candidates else None


def audio_transcription_source(config: ModelConfig) -> str:
    return "gemini_audio" if is_gemini_audio_transcription_config(config) else config.api_mode


def _clean_json_text(value: str) -> str:
    clean = value.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    start, end = clean.find("{"), clean.rfind("}")
    return clean[start:end + 1] if 0 <= start < end else clean


async def transcribe_gemini_audio(config: ModelConfig, audio_path: Path) -> TranscriptResult:
    if not is_gemini_audio_transcription_config(config):
        raise MediaProviderError(
            "所选 Gemini 配置不能处理音频输入",
            retryable=False,
            code="audio_transcription_provider_unsupported",
        )
    mime = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mp4"
    origin = normalize_gateway_origin(config.base_url)
    model = quote(config.model_name, safe="-._")
    url = f"{origin}/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {
                    "text": (
                        "请逐字转写这段中文教学音频，并给出尽可能准确的分段起止秒数。"
                        "只返回符合 schema 的 JSON；不得概括、改写或补充音频中不存在的内容。"
                    ),
                },
                {
                    "inlineData": {
                        "mimeType": mime,
                        "data": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
                    },
                },
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "segments": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start_seconds": {"type": "NUMBER"},
                                "end_seconds": {"type": "NUMBER"},
                                "text": {"type": "STRING"},
                            },
                            "required": ["start_seconds", "end_seconds", "text"],
                        },
                    },
                },
                "required": ["text", "segments"],
            },
        },
    }
    key = decrypt_secret(config.encrypted_api_key)
    try:
        async with build_async_client(url, timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(
                url,
                headers={"x-api-key": key, "content-type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        raw = response.json()
        parts = (((raw.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        rendered = "".join(
            str(item.get("text") or "")
            for item in parts
            if isinstance(item, dict) and not item.get("thought")
        )
        parsed = json.loads(_clean_json_text(rendered))
    except MediaProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MediaProviderError(
            f"Gemini 音频转写失败：{str(exc)[:300]}",
            code="video_asr_qa_failed",
        ) from exc
    text = str(parsed.get("text") or "").strip()
    if not text:
        raise MediaProviderError(
            "Gemini 音频转写未返回文本",
            retryable=False,
            code="video_asr_qa_failed",
        )
    segments = parsed.get("segments") or []
    return TranscriptResult(
        text=text,
        segments=segments if isinstance(segments, list) else [],
        usage=raw.get("usageMetadata") if isinstance(raw.get("usageMetadata"), dict) else {},
    )


async def transcribe_audio(config: ModelConfig, audio_path: Path) -> TranscriptResult:
    if config.api_mode == "volcengine_asr":
        return await transcribe_doubao_audio(config, audio_path)
    if is_gemini_audio_transcription_config(config):
        return await transcribe_gemini_audio(config, audio_path)
    raise MediaProviderError(
        "没有可用的音频转写 Provider",
        retryable=False,
        code="audio_transcription_provider_unsupported",
    )
