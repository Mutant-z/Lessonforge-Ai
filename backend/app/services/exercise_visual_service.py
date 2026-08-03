import asyncio
import base64
import hashlib
import ipaddress
import json
import socket
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.models.entities import AgentChatSession, ArtifactAsset, CourseProject, GenerationRun, ModelConfig


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class VisualReviewResult(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)


def render_deterministic_svg(diagram_type: str, spec: dict, alt_text: str) -> bytes:
    width, height = 960, 600
    elements = [
        '<rect width="960" height="600" fill="white"/>',
        f'<title>{escape(alt_text)}</title>',
    ]
    if diagram_type == "coordinate":
        elements.extend([
            '<line x1="80" y1="520" x2="900" y2="520" stroke="#172033" stroke-width="3"/>',
            '<line x1="100" y1="560" x2="100" y2="50" stroke="#172033" stroke-width="3"/>',
        ])
        for point in spec.get("points", [])[:24]:
            x = max(110, min(890, 100 + float(point.get("x", 0)) * 70))
            y = max(60, min(510, 520 - float(point.get("y", 0)) * 50))
            elements.append(f'<circle cx="{x}" cy="{y}" r="7" fill="#4F46E5"/>')
    elif diagram_type == "force":
        elements.append('<rect x="380" y="245" width="200" height="110" fill="#EEF2FF" stroke="#172033" stroke-width="3"/>')
        for index, arrow in enumerate(spec.get("arrows", [])[:8]):
            x2 = 480 + float(arrow.get("dx", (index % 2) * 2 - 1)) * 130
            y2 = 300 - float(arrow.get("dy", 1 if index < 2 else -1)) * 130
            elements.append(f'<line x1="480" y1="300" x2="{x2}" y2="{y2}" stroke="#4F46E5" stroke-width="5"/>')
            elements.append(f'<circle cx="{x2}" cy="{y2}" r="7" fill="#4F46E5"/>')
    elif diagram_type == "geometry":
        points = spec.get("points") or [{"x": 220, "y": 460}, {"x": 480, "y": 100}, {"x": 740, "y": 460}]
        coords = [(float(item.get("x", 0)), float(item.get("y", 0))) for item in points[:12]]
        if coords:
            elements.append('<polygon points="' + " ".join(f"{x},{y}" for x, y in coords) + '" fill="#EEF2FF" stroke="#172033" stroke-width="4"/>')
            for index, (x, y) in enumerate(coords):
                elements.append(f'<circle cx="{x}" cy="{y}" r="7" fill="#4F46E5"/><text x="{x + 12}" y="{y - 10}" font-size="24" fill="#172033">{chr(65 + index)}</text>')
    else:
        nodes = spec.get("nodes") or [{"label": "条件"}, {"label": "方法"}, {"label": "结论"}, {"label": "检查"}]
        step = 760 / max(1, len(nodes))
        for index, node in enumerate(nodes[:8]):
            x = 70 + index * step
            elements.append(f'<rect x="{x}" y="240" width="150" height="80" rx="8" fill="#EEF2FF" stroke="#4F46E5" stroke-width="3"/>')
            elements.append(f'<text x="{x + 75}" y="288" text-anchor="middle" font-size="24" fill="#172033">{escape(str(node.get("label", index + 1)))}</text>')
            if index:
                elements.append(f'<line x1="{x - step + 150}" y1="280" x2="{x}" y2="280" stroke="#172033" stroke-width="3"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600" role="img">' + "".join(elements) + '</svg>').encode("utf-8")


def _png_preview(svg: bytes) -> bytes | None:
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=svg, output_width=1440, output_height=900)
    except Exception:
        return None


def _api_key(config: ModelConfig) -> str:
    return decrypt_secret(config.encrypted_api_key) if config.encrypted_api_key else ""


def _json_path(data, path: str):
    value = data
    for part in [item for item in path.strip("$.").split(".") if item]:
        if isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(path)
    return value


async def _safe_remote_image(url: str, timeout: int) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("图片返回 URL 必须使用 HTTPS")
    addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("图片返回 URL 不允许访问内网地址")
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(url, headers={"Accept": "image/png,image/jpeg,image/webp"})
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("图片下载不允许重定向")
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if mime not in ALLOWED_IMAGE_TYPES:
            raise ValueError("图片响应 MIME 类型不受支持")
        if len(response.content) > MAX_IMAGE_BYTES:
            raise ValueError("图片响应超过 10MB 限制")
        return response.content, mime


async def generate_image(config: ModelConfig, prompt: str, size: str) -> tuple[bytes, str]:
    key = _api_key(config)
    mode = config.api_mode or "openai_images"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if mode == "google_gemini_image":
        endpoint = f"{config.base_url.rstrip('/')}/models/{config.model_name}:generateContent"
        async with httpx.AsyncClient(timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(
                endpoint,
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
                },
            )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        inline = next(item.get("inlineData") or item.get("inline_data") for item in parts if item.get("inlineData") or item.get("inline_data"))
        mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
        raw = base64.b64decode(inline["data"], validate=True)
    else:
        adapter = config.adapter_config_json or {}
        endpoint_path = adapter.get("endpoint_path") or "/images/generations"
        endpoint = f"{config.base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"
        if adapter.get("auth_mode") == "x_api_key":
            headers = {"x-api-key": key, "Content-Type": "application/json"}
        payload = {
            adapter.get("model_field", "model"): config.model_name,
            adapter.get("prompt_field", "prompt"): prompt,
            adapter.get("size_field", "size"): size,
        }
        async with httpx.AsyncClient(timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        b64_path = adapter.get("response_base64_path", "data.0.b64_json")
        url_path = adapter.get("response_url_path", "data.0.url")
        try:
            encoded = _json_path(data, b64_path)
        except (KeyError, IndexError, TypeError):
            encoded = None
        if encoded:
            raw = base64.b64decode(encoded, validate=True)
            mime = adapter.get("response_mime_type", "image/png")
        else:
            raw, mime = await _safe_remote_image(str(_json_path(data, url_path)), config.timeout_seconds)
    if mime not in ALLOWED_IMAGE_TYPES or not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("图片响应为空、过大或格式不受支持")
    return raw, mime


async def review_image(
    config: ModelConfig,
    raw: bytes,
    mime: str,
    question_context: dict,
) -> VisualReviewResult:
    key = _api_key(config)
    encoded = base64.b64encode(raw).decode("ascii")
    prompt = (
        "复核图片是否与题目情境、观察要求和答案一致，是否包含答案暗示、错误文字或事实错误，"
        "并检查适龄性、清晰度和灰度打印可辨认性。只返回 JSON："
        '{"passed":true|false,"issues":["具体问题"]}。\n题目上下文：'
        + json.dumps(question_context, ensure_ascii=False)
    )
    if config.provider == "anthropic" or config.api_mode == "anthropic_vision":
        async with httpx.AsyncClient(timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(
                f"{config.base_url.rstrip('/')}/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={
                    "model": config.model_name, "max_tokens": 500,
                    "messages": [{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": encoded}},
                        {"type": "text", "text": prompt},
                    ]}],
                },
            )
        response.raise_for_status()
        text = "".join(item.get("text", "") for item in response.json().get("content", []) if item.get("type") == "text")
    elif config.api_mode == "google_vision":
        async with httpx.AsyncClient(timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(
                f"{config.base_url.rstrip('/')}/models/{config.model_name}:generateContent",
                params={"key": key},
                json={"contents": [{"parts": [{"text": prompt}, {"inlineData": {"mimeType": mime, "data": encoded}}]}]},
            )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    else:
        async with httpx.AsyncClient(timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(
                f"{config.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": config.model_name, "temperature": 0,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    ]}],
                    "response_format": {"type": "json_object"},
                },
            )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return VisualReviewResult.model_validate_json(clean)


def _question_context(block: dict) -> dict:
    return {
        "group_title": block.get("title", ""),
        "instructions": block.get("instructions", ""),
        "questions": [
            {"stem": item.get("stem"), "answer_key": item.get("answer_key")}
            for item in block.get("sub_questions", [])
        ],
    }


async def cleanup_orphan_artifact_assets(db, retention_hours: int = 24) -> int:
    """Remove expired run-bound assets that were never published with an Artifact."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, retention_hours))
    stale_assets = list((await db.scalars(select(ArtifactAsset).where(
        ArtifactAsset.artifact_id.is_(None),
        ArtifactAsset.created_at < cutoff,
    ))).all())
    if not stale_assets:
        return 0

    stale_ids = {asset.id for asset in stale_assets}
    retained_assets = list((await db.scalars(select(ArtifactAsset).where(
        ArtifactAsset.id.not_in(stale_ids),
    ))).all())
    retained_paths = {
        path
        for asset in retained_assets
        for path in (asset.relative_path, asset.preview_relative_path)
        if path
    }
    storage_root = get_settings().storage_root.resolve()
    for asset in stale_assets:
        for relative_path in (asset.relative_path, asset.preview_relative_path):
            if not relative_path or relative_path in retained_paths:
                continue
            candidate = (storage_root / relative_path).resolve()
            try:
                candidate.relative_to(storage_root)
            except ValueError:
                continue
            if candidate.is_file():
                candidate.unlink()
        await db.delete(asset)
    await db.commit()
    return len(stale_assets)


async def process_exercise_visuals(
    db,
    course: CourseProject,
    run: GenerationRun,
    raw: dict,
) -> tuple[dict, list[ArtifactAsset], list[str]]:
    content = json.loads(json.dumps(raw, ensure_ascii=False))
    notes: list[str] = []
    assets: list[ArtifactAsset] = []
    generated_requests = []
    for section_index, section in enumerate(content.get("sections", [])):
        for block_index, block in enumerate(section.get("blocks", [])):
            if block.get("kind") != "question_group":
                continue
            for stimulus_index, stimulus in enumerate(block.get("stimuli", [])):
                visual = stimulus.get("visual") if stimulus.get("kind") == "visual" else None
                if not visual:
                    continue
                if visual.get("mode") == "generated_image":
                    generated_requests.append((section_index, block_index, stimulus_index, block, visual))
                    continue
                path = f"$.sections[{section_index}].blocks[{block_index}].stimuli[{stimulus_index}].visual"
                svg = render_deterministic_svg(
                    visual.get("diagram_type") or "flow",
                    visual.get("diagram_spec") or {},
                    visual.get("alt_text") or visual.get("purpose") or "确定性图示",
                )
                digest = hashlib.sha256(svg).hexdigest()
                relative = Path("generated") / course.id / f"{digest}.svg"
                target = get_settings().storage_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(svg)
                preview_relative = ""
                preview = _png_preview(svg)
                if preview:
                    preview_relative_path = Path("generated") / course.id / f"{digest}.png"
                    preview_target = get_settings().storage_root / preview_relative_path
                    if not preview_target.exists():
                        preview_target.write_bytes(preview)
                    preview_relative = str(preview_relative_path)
                asset = ArtifactAsset(
                    owner_id=course.owner_id, course_id=course.id, generation_run_id=run.id,
                    json_path=path, asset_type="deterministic_diagram", relative_path=str(relative),
                    preview_relative_path=preview_relative, mime_type="image/svg+xml", width=960, height=600,
                    size_bytes=len(svg), checksum=digest, provider="deterministic_svg",
                    model_name=visual.get("diagram_type") or "flow", status="approved",
                    review_json={"passed": True, "method": "typed_deterministic_renderer"},
                )
                db.add(asset)
                await db.flush()
                visual.update({
                    "asset_id": asset.id, "status": "approved", "provider": "deterministic_svg",
                    "model_name": visual.get("diagram_type") or "flow", "review_notes": [],
                })
                assets.append(asset)

    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == "exercise",
    ))
    if not session or not session.image_model_config_id or not session.vision_model_config_id:
        return content, assets, notes
    image_config = await db.get(ModelConfig, session.image_model_config_id)
    vision_config = await db.get(ModelConfig, session.vision_model_config_id)
    if (
        not image_config or image_config.owner_id != course.owner_id
        or not vision_config or vision_config.owner_id != course.owner_id
        or "image_generation" not in (image_config.capabilities_json or [])
        or "vision_review" not in (vision_config.capabilities_json or [])
    ):
        return content, assets, ["图片生成或视觉复核模型配置不可用，已使用替代材料。"]

    semaphore = asyncio.Semaphore(2)

    async def process(entry):
        section_index, block_index, stimulus_index, block, visual = entry
        path = f"$.sections[{section_index}].blocks[{block_index}].stimuli[{stimulus_index}].visual"
        async with semaphore:
            last_issues: list[str] = []
            for _ in range(2):
                try:
                    generated, mime = await generate_image(image_config, visual["generation_prompt"], visual.get("size", "1536x1024"))
                    review = await review_image(vision_config, generated, mime, _question_context(block))
                    if not review.passed:
                        last_issues = review.issues
                        continue
                    digest = hashlib.sha256(generated).hexdigest()
                    suffix = ALLOWED_IMAGE_TYPES[mime]
                    relative = Path("generated") / course.id / f"{digest}{suffix}"
                    target = get_settings().storage_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        target.write_bytes(generated)
                    asset = ArtifactAsset(
                        owner_id=course.owner_id, course_id=course.id, generation_run_id=run.id,
                        json_path=path, asset_type="generated_image", relative_path=str(relative),
                        mime_type=mime, size_bytes=len(generated), checksum=digest,
                        provider=image_config.provider, model_name=image_config.model_name,
                        status="approved", review_json=review.model_dump(),
                    )
                    db.add(asset)
                    await db.flush()
                    visual.update({
                        "asset_id": asset.id, "status": "approved", "provider": image_config.provider,
                        "model_name": image_config.model_name, "review_notes": [],
                    })
                    assets.append(asset)
                    return
                except Exception as exc:
                    last_issues = [str(exc)[:240]]
            visual["status"] = "degraded"
            visual["review_notes"] = last_issues
            notes.append(f"{visual.get('visual_id', '视觉材料')} 生成或复核失败，已使用替代材料。")

    await asyncio.gather(*(process(entry) for entry in generated_requests[:3]))
    for entry in generated_requests[3:]:
        entry[-1]["status"] = "degraded"
        notes.append(f"{entry[-1].get('visual_id', '视觉材料')} 超过单卷三张配图上限，已使用替代材料。")
    return content, assets, notes
