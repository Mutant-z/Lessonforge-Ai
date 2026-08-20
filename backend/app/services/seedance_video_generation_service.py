"""Seedance 2.5 native-audio segmented video workflow.

This module intentionally has no PPT, image-generation, speech-synthesis or legacy
video-generation imports. FFmpeg is used only to normalize/mux provider outputs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import (
    AgentChatSession,
    AgentMessage,
    Artifact,
    ArtifactAsset,
    CourseProject,
    CourseTask,
    GenerationEvent,
    GenerationRun,
    ModelConfig,
    VideoGenerationQuote,
    VideoSceneJob,
)
from app.schemas.artifact import SeedanceVideoScriptContent
from app.schemas.video_script_v4 import VIDEO_SCRIPT_V4, seedance_video_script_for_generation
from app.schemas.video import (
    NATIVE_VIDEO_RESOLUTIONS,
    SeedanceNativeScene,
    SeedanceNativeSettings,
    SeedanceSceneRegenerateRequest,
    SeedanceVideoGenerationContent,
    SeedanceVideoGenerationRunRequest,
    VideoGenerationOutputs,
    VideoGenerationQuoteRequest,
    VideoGenerationQuoteResponse,
    seedance_video_generation_markdown,
)
from app.services.media_provider_service import MediaProviderError
from app.services.native_audio_video_provider import native_audio_video_provider
from app.services.seedance_provider_service import transcribe_doubao_audio
from app.services.video_generation_settings_service import effective_video_resolution


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def _ffmpeg() -> str:
    configured = get_settings().ffmpeg_binary
    if configured:
        return configured
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


@lru_cache(maxsize=1)
def _ffprobe() -> str:
    configured = get_settings().ffprobe_binary
    if configured:
        return configured
    binary = shutil.which("ffprobe")
    if binary:
        return binary
    sibling = Path(_ffmpeg()).with_name("ffprobe")
    if sibling.is_file():
        return str(sibling)
    raise RuntimeError("Seedance 视频质量检查需要 FFprobe")


async def _run(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(f"视频封装失败：{stderr.decode('utf-8', 'replace')[-800:]}")


async def _probe(path: Path) -> dict:
    process = await asyncio.create_subprocess_exec(
        _ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(f"媒体检查失败：{stderr.decode('utf-8', 'replace')[-500:]}")
    data = json.loads(stdout)
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise MediaProviderError(
            "Provider 返回片段必须同时包含视频流和原生音轨",
            retryable=False,
            code="video_native_audio_missing",
        )
    return {
        "duration_seconds": float((data.get("format") or {}).get("duration") or 0),
        "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
        "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9.%℃°]+", value)).lower()


def _fact_qa(scene: SeedanceNativeScene, transcript: str) -> dict:
    normalized = _normalized(transcript)
    missing_terms = [item for item in scene.required_terms if _normalized(item) not in normalized]
    missing_numbers = [item for item in scene.required_numbers if _normalized(item) not in normalized]
    missing_facts = []
    transcript_chars = set(normalized)
    for fact in scene.required_facts:
        fact_chars = set(_normalized(fact))
        overlap = len(fact_chars & transcript_chars) / max(1, len(fact_chars))
        if overlap < .62:
            missing_facts.append(fact)
    passed = not (missing_terms or missing_numbers or missing_facts)
    return {
        "status": "passed" if passed else "failed",
        "missing_terms": missing_terms,
        "missing_numbers": missing_numbers,
        "missing_facts": missing_facts,
    }


def _subtitle_segments(items: list[dict], duration: float, fallback_text: str) -> list[dict]:
    normalized = []
    for item in items:
        try:
            start = float(item.get("start_seconds", item.get("start", 0)))
            end = float(item.get("end_seconds", item.get("end", duration)))
            text = str(item.get("text") or item.get("transcript") or "").strip()
        except (TypeError, ValueError):
            continue
        if text and 0 <= start < end <= duration + .5:
            normalized.append({"start_seconds": start, "end_seconds": min(duration, end), "text": text})
    return normalized or [{"start_seconds": 0.0, "end_seconds": duration, "text": fallback_text}]


def _request_hash(scene, model: ModelConfig, resolution: str, instruction: str = "") -> str:
    payload = {
        "model_config_id": model.id, "provider": model.provider, "api_mode": model.api_mode,
        "model_name": model.model_name, "resolution": resolution,
        "duration": round(scene.end_seconds - scene.start_seconds, 3),
        "continuity_group": scene.continuity_group,
        "visual_prompt": scene.visual_prompt, "spoken_text": scene.spoken_text,
        "voice_direction": scene.voice_direction, "sound_design": scene.sound_design,
        "camera_beats": [beat.model_dump() for beat in getattr(scene, "camera_beats", [])],
        "negative_constraints": getattr(scene, "negative_constraints", []),
        "reference_scene_ids": getattr(scene, "reference_scene_ids", []),
        "instruction": instruction,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _prompt(script: SeedanceVideoScriptContent, scene, *, qa_retry: dict | None = None, instruction: str = "") -> str:
    duration = scene.end_seconds - scene.start_seconds
    beats = "；".join(
        f"[{beat.start_offset_seconds:.1f}s-{beat.end_offset_seconds:.1f}s] {beat.instruction}"
        for beat in scene.camera_beats
    )
    retry = ""
    if qa_retry:
        missing = qa_retry.get("missing_terms", []) + qa_retry.get("missing_numbers", []) + qa_retry.get("missing_facts", [])
        retry = f"上次口播遗漏以下教学信息，本次必须清楚说出：{'；'.join(missing)}。"
    return "\n".join(filter(None, [
        f"生成一段 {duration:.1f} 秒、16:9、720p 的原生有声中文教学视频。",
        "使用单一连续镜头完成全段，不切镜、不跳时空，镜头运动必须平滑连贯。",
        f"全片视觉风格：{script.production_settings.global_visual_style}",
        f"连续性分组：{scene.continuity_group}",
        f"画面：{scene.visual_prompt}", f"镜头节拍：{beats or '稳定中景，聚焦教学主体'}",
        f"教师声音：{scene.voice_direction or script.production_settings.global_voice_direction}",
        f"教师必须自然、完整地说：\"{scene.spoken_text}\"",
        f"声音设计：{'；'.join(scene.sound_design) or '口播清晰，环境声克制'}",
        f"禁止：{'；'.join(scene.negative_constraints)}",
        "不要生成字幕、标题、PPT、幻灯片、信息图、软件界面、水印或任何大段可读文字。",
        "画面和口播中的教学事实、数字、单位与结论必须准确，不得自行添加未经脚本确认的知识。",
        retry, f"教师补充要求：{instruction}" if instruction else "",
    ]))


async def _latest_artifact(db, course_id: str, kind: str) -> Artifact | None:
    return await db.scalar(select(Artifact).where(
        Artifact.course_id == course_id, Artifact.artifact_type == kind,
    ).order_by(Artifact.version.desc()))


async def _configs(db, course: CourseProject) -> tuple[ModelConfig, ModelConfig]:
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id, AgentChatSession.module_type == "video_generation",
    ))
    video = await db.get(ModelConfig, session.video_model_config_id) if session and session.video_model_config_id else None
    if not video or video.api_mode not in {"volcengine_ark_video", "gemini_interactions_video"}:
        raise ValueError("请先配置并选择原生有声视频模型")
    capabilities = set(video.capabilities_json or [])
    if not {"video_generation", "native_audio_video_generation"} <= capabilities:
        raise ValueError("视频配置必须声明视频生成和原生有声视频能力")
    native_audio_video_provider(video)
    configs = list(await db.scalars(select(ModelConfig).where(ModelConfig.owner_id == course.owner_id)))
    asr = next((item for item in configs if item.api_mode == "volcengine_asr" and "speech_recognition" in (item.capabilities_json or [])), None)
    if not asr:
        raise ValueError("原生音轨教学事实严格模式需要配置语音识别 / ASR 模型")
    return video, asr


async def _cached_asset(db, course_id: str, request_hash: str) -> ArtifactAsset | None:
    jobs = list(await db.scalars(select(VideoSceneJob).where(
        VideoSceneJob.course_id == course_id,
        VideoSceneJob.request_hash == request_hash,
        VideoSceneJob.status == "completed",
        VideoSceneJob.output_asset_id.is_not(None),
    ).order_by(VideoSceneJob.created_at.desc()).limit(20)))
    for job in jobs:
        if (job.qa_json or {}).get("status") != "passed":
            continue
        asset = await db.get(ArtifactAsset, job.output_asset_id)
        if asset and asset.status in {"preview", "approved"}:
            path = (get_settings().storage_root / asset.relative_path).resolve()
            if path.is_file() and get_settings().storage_root.resolve() in path.parents:
                return asset
    return None


async def create_video_generation_quote(
    db, task: CourseTask, owner_id: str, request: VideoGenerationQuoteRequest,
) -> VideoGenerationQuoteResponse:
    course = await db.get(CourseProject, task.course_id)
    script_artifact = await _latest_artifact(db, task.course_id, "video_script")
    schema_version = (script_artifact.content_json or {}).get("schema_version") if script_artifact else None
    if not course or not script_artifact or schema_version not in {"3.0", VIDEO_SCRIPT_V4}:
        raise ValueError("请先生成或同步 Seedance V3/V4 视频脚本")
    script = seedance_video_script_for_generation(script_artifact.content_json)
    video, _ = await _configs(db, course)
    provider = native_audio_video_provider(video)
    resolution = request.resolution or await _preferred_video_resolution(course, provider)
    if resolution not in NATIVE_VIDEO_RESOLUTIONS:
        raise ValueError(f"不支持的视频分辨率：{resolution}")
    requested = provider.capabilities().get("resolutions") or [provider.capabilities().get("resolution")]
    if resolution not in requested:
        label = "、".join(str(item) for item in requested if item)
        raise ValueError(f"当前视频模型不支持 {resolution}；该模型仅支持：{label or '720p'}")
    request = request.model_copy(update={"resolution": resolution})
    selected = list(script.scenes)
    if request.target_scene_id:
        target = next((item for item in selected if item.id == request.target_scene_id), None)
        if not target:
            raise ValueError("指定的视频片段不存在")
        selected = [target]
        if request.include_dependents:
            selected += [
                item for item in script.scenes
                if item.sequence > target.sequence and item.continuity_group == target.continuity_group
            ]
    scene_quotes = []
    total_tokens = total_cost = reusable = 0
    unsupported: list[tuple[str, float]] = []
    for scene in selected:
        quoted_scene = scene.model_copy(deep=True)
        if scene.id == request.target_scene_id:
            if request.visual_prompt:
                quoted_scene.visual_prompt = request.visual_prompt
            if request.spoken_text:
                quoted_scene.spoken_text = request.spoken_text
            if request.voice_direction:
                quoted_scene.voice_direction = request.voice_direction
            if request.duration_seconds is not None:
                quoted_scene.end_seconds = quoted_scene.start_seconds + request.duration_seconds
        request_hash = _request_hash(quoted_scene, video, request.resolution, request.instruction)
        cached = await _cached_asset(db, course.id, request_hash)
        duration = quoted_scene.end_seconds - quoted_scene.start_seconds
        minimum, maximum = provider.capabilities()["duration_seconds"]
        if not minimum <= duration <= maximum:
            unsupported.append((scene.id, duration))
            continue
        estimated_tokens, cost_fen = (0, 0) if cached else provider.estimate_cost(duration)
        total_tokens += estimated_tokens
        total_cost += cost_fen
        reusable += int(bool(cached))
        scene_quotes.append({
            "scene_id": scene.id, "duration_seconds": duration,
            "request_hash": request_hash, "reusable": bool(cached),
            "estimated_tokens": estimated_tokens, "estimated_cost_fen": cost_fen,
        })
    if unsupported:
        details = "、".join(f"{scene_id}（{duration:.1f} 秒）" for scene_id, duration in unsupported)
        raise ValueError(
            f"video_scene_duration_unsupported：以下分镜不符合 {video.model_name} 的单段时长限制：{details}。"
            "请前往视频脚本运行“按 Gemini 时长拆分分镜”后重新报价。"
        )
    expires = utcnow() + timedelta(minutes=15)
    quote = VideoGenerationQuote(
        owner_id=owner_id, course_id=course.id, script_artifact_id=script_artifact.id,
        model_config_id=video.id, request_json=request.model_dump(), scenes_json=scene_quotes,
        estimated_tokens=total_tokens, estimated_cost_fen=total_cost,
        maximum_cost_fen=total_cost * 2 if total_cost else 0, expires_at=expires,
    )
    db.add(quote)
    await db.flush()
    return VideoGenerationQuoteResponse(
        quote_id=quote.id, expires_at=expires, script_version=script_artifact.version,
        model_config_id=video.id, model_name=video.model_name, provider=video.provider,
        api_mode=video.api_mode, resolution=request.resolution,
        scene_count=len(selected), reusable_scene_count=reusable,
        duration_seconds=sum(float(item["duration_seconds"]) for item in scene_quotes),
        estimated_tokens=total_tokens, estimated_cost_fen=total_cost,
        maximum_cost_fen=quote.maximum_cost_fen, scenes=scene_quotes,
    )


async def _preferred_video_resolution(course: CourseProject, provider) -> str:
    """返回课程保存的偏好分辨率；未设置或不支持时退回模型默认。"""
    supported = provider.capabilities().get("resolutions") or [provider.capabilities().get("resolution")]
    fallback = str(provider.capabilities().get("resolution") or "1280x720")
    return effective_video_resolution(course, supported, fallback)


async def _consume_quote(db, task: CourseTask, quote_id: str, approved_max_cost_fen: int) -> VideoGenerationQuote:
    quote = await db.get(VideoGenerationQuote, quote_id)
    now = utcnow()
    if not quote or quote.course_id != task.course_id or quote.status != "pending":
        raise ValueError("视频报价不存在、已使用或已失效")
    expires = quote.expires_at if quote.expires_at.tzinfo else quote.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        quote.status = "expired"
        raise ValueError("视频报价已过期，请重新估算")
    script = await _latest_artifact(db, task.course_id, "video_script")
    if not script or script.id != quote.script_artifact_id:
        raise ValueError("视频脚本已经变化，请重新估算")
    course = await db.get(CourseProject, task.course_id)
    video, _ = await _configs(db, course)
    if video.id != quote.model_config_id:
        raise ValueError("原生有声视频模型配置已经变化，请重新估算")
    if approved_max_cost_fen < quote.maximum_cost_fen:
        raise ValueError("确认的最高费用低于本次最坏重试费用")
    consumed = await db.execute(update(VideoGenerationQuote).where(
        VideoGenerationQuote.id == quote.id,
        VideoGenerationQuote.status == "pending",
    ).values(status="confirmed", confirmed_at=now, used_at=now))
    if consumed.rowcount != 1:
        raise ValueError("视频报价已被其他请求使用，请重新估算")
    quote.status = "confirmed"
    quote.confirmed_at = now
    quote.used_at = now
    return quote


async def create_seedance_video_run(
    db, task: CourseTask, request: SeedanceVideoGenerationRunRequest,
) -> GenerationRun:
    if task.active_run_id or task.status in {"queued", "running"}:
        raise ValueError("当前视频任务已经在运行")
    if request.action == "recompose":
        if not task.current_artifact_id:
            raise ValueError("视频尚未生成，无法重新合成")
        quote = None
    else:
        if not request.quote_id or request.approved_max_cost_fen is None:
            raise ValueError("提交原生有声视频任务前必须确认有效报价")
        quote = await _consume_quote(db, task, request.quote_id, request.approved_max_cost_fen)
    run = GenerationRun(
        course_id=task.course_id, course_task_id=task.id, thread_id=str(uuid4()),
        run_type="task", trigger_type=request.action, status="queued", current_node="seedance_native_video",
    )
    db.add(run)
    await db.flush()
    db.add(VideoSceneJob(
        generation_run_id=run.id, course_id=task.course_id,
        source_artifact_id=task.current_artifact_id or (quote.script_artifact_id if quote else None),
        scene_id="__run__", operation=request.action, status="queued",
        input_json={
            **request.model_dump(),
            "quote": quote.scenes_json if quote else [],
            "quote_request": quote.request_json if quote else {},
        },
        estimated_tokens=quote.estimated_tokens if quote else 0,
        estimated_cost_fen=quote.estimated_cost_fen if quote else 0,
    ))
    task.active_run_id = run.id
    task.status = "queued"
    task.progress = 0
    task.error_json = None
    return run


async def create_seedance_scene_regeneration_run(
    db, task: CourseTask, scene_id: str, request: SeedanceSceneRegenerateRequest,
) -> GenerationRun:
    if not task.current_artifact_id:
        raise ValueError("视频尚未生成，无法调整片段")
    if task.active_run_id or task.status in {"queued", "running"}:
        raise ValueError("当前视频任务已经在运行")
    quote = await _consume_quote(db, task, request.quote_id, request.approved_max_cost_fen)
    source = await db.get(Artifact, task.current_artifact_id)
    content = SeedanceVideoGenerationContent.model_validate(source.content_json)
    target = next((item for item in content.scenes if item.id == scene_id or item.script_scene_id == scene_id), None)
    quoted_ids = {item["scene_id"] for item in quote.scenes_json}
    if not target or target.script_scene_id not in quoted_ids:
        raise ValueError("报价与目标片段不一致")
    quoted_request = quote.request_json or {}
    for field in ("instruction", "visual_prompt", "spoken_text", "voice_direction", "duration_seconds", "include_dependents"):
        if request.model_dump().get(field) != quoted_request.get(field):
            raise ValueError("片段调整内容与已确认报价不一致，请重新估算")
    run = GenerationRun(
        course_id=task.course_id, course_task_id=task.id, thread_id=str(uuid4()),
        run_type="task", trigger_type="scene_regenerate", status="queued", current_node="seedance_native_video",
    )
    db.add(run)
    await db.flush()
    db.add(VideoSceneJob(
        generation_run_id=run.id, course_id=task.course_id, source_artifact_id=task.current_artifact_id,
        scene_id=scene_id, operation="scene_regenerate", status="queued",
        input_json={**request.model_dump(), "quote": quote.scenes_json, "quote_request": quote.request_json},
        estimated_tokens=quote.estimated_tokens, estimated_cost_fen=quote.estimated_cost_fen,
    ))
    task.active_run_id = run.id
    task.status = "queued"
    task.progress = 0
    task.error_json = None
    return run


async def _emit(db, run: GenerationRun, task: CourseTask, event_type: str, **data) -> None:
    db.add(GenerationEvent(run_id=run.id, event_type=event_type, data_json={
        "course_id": task.course_id, "run_id": run.id, "task_id": task.id,
        "task_type": task.task_type, **data,
    }))


async def _publish(run_id: str, event_type: str, **data) -> None:
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        task = await db.get(CourseTask, run.course_task_id) if run else None
        if run and task:
            if "progress" in data:
                run.progress = task.progress = int(data["progress"])
            await _emit(db, run, task, event_type, **data)
            await db.commit()


async def _store_asset(db, *, course, run, path: Path, asset_type: str, scene_id: str = "", status: str = "preview", metadata: dict | None = None) -> ArtifactAsset:
    root = get_settings().storage_root.resolve()
    resolved = path.resolve()
    if root not in resolved.parents:
        raise RuntimeError("生成资源不在受控存储目录")
    mime = "video/mp4" if path.suffix == ".mp4" else "image/png" if path.suffix == ".png" else "text/vtt"
    asset = ArtifactAsset(
        owner_id=course.owner_id, course_id=course.id, generation_run_id=run.id,
        asset_type=asset_type, relative_path=str(resolved.relative_to(root)), mime_type=mime,
        source_scene_id=scene_id, size_bytes=resolved.stat().st_size, checksum=_sha256(resolved),
        provider=(metadata or {}).get("provider", "local") if asset_type == "video_clip" else "local",
        model_name=metadata.get("model_name", "") if metadata else "", status=status,
        metadata_json=metadata or {},
    )
    db.add(asset)
    await db.flush()
    return asset


def _dimensions_for_resolution(resolution: str) -> tuple[int, int]:
    """把分辨率字符串解析为输出宽高；无法解析时回退 1280x720。"""
    try:
        width, height = (int(part) for part in str(resolution).lower().split("x", 1))
    except (TypeError, ValueError):
        return 1280, 720
    return width, height


async def _normalize_clip(source: Path, target: Path, resolution: str = "1280x720") -> dict:
    probe = await _probe(source)
    width, height = _dimensions_for_resolution(resolution)
    await _run(
        "-i", str(source), "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-r", "25", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-af", "loudnorm=I=-16:LRA=9:TP=-1.5", "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(target),
    )
    normalized = await _probe(target)
    if abs(normalized["duration_seconds"] - probe["duration_seconds"]) > 1:
        raise RuntimeError("标准化后片段时长异常")
    return normalized


async def _extract_audio(video: Path, audio: Path) -> None:
    await _run("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio))


async def _thumbnail(video: Path, image: Path) -> None:
    await _run("-ss", "0.2", "-i", str(video), "-frames:v", "1", "-vf", "scale=640:-2", str(image))


def _vtt(scenes: list[SeedanceNativeScene]) -> str:
    def stamp(value: float) -> str:
        ms = max(0, round(value * 1000)); hours, ms = divmod(ms, 3_600_000); minutes, ms = divmod(ms, 60_000); seconds, ms = divmod(ms, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"
    lines = ["WEBVTT", ""]
    for scene in scenes:
        segments = scene.subtitle_segments or [{
            "start_seconds": 0, "end_seconds": scene.end_seconds - scene.start_seconds,
            "text": scene.actual_transcript,
        }]
        for segment in segments:
            text = str(segment.get("text") or "").strip()
            if text:
                lines += [
                    f"{stamp(scene.start_seconds + float(segment.get('start_seconds', 0)))} --> {stamp(scene.start_seconds + float(segment.get('end_seconds', scene.end_seconds - scene.start_seconds)))}",
                    text, "",
                ]
    return "\n".join(lines)


async def _compose(paths: list[Path], output_dir: Path, subtitle: Path, subtitle_enabled: bool, resolution: str = "1280x720") -> tuple[Path, Path, Path]:
    listing = output_dir / "concat.txt"
    listing.write_text("\n".join(f"file '{path.resolve().as_posix()}'" for path in paths), encoding="utf-8")
    base = output_dir / "base.mp4"
    await _run("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(base))
    final = output_dir / "final.mp4"
    if subtitle_enabled and subtitle.stat().st_size:
        await _run("-i", str(base), "-i", str(subtitle), "-map", "0:v", "-map", "0:a", "-map", "1:0", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-movflags", "+faststart", str(final))
    else:
        shutil.copy2(base, final)
    width, _ = _dimensions_for_resolution(resolution)
    preview_width = min(width, 960)
    preview = output_dir / "preview.mp4"
    await _run("-i", str(final), "-vf", f"scale={preview_width}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "29", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(preview))
    thumb = output_dir / "thumbnail.png"
    await _thumbnail(final, thumb)
    await _probe(final); await _probe(preview)
    return final, preview, thumb


async def execute_seedance_video_run(run_id: str) -> None:
    from app.services.course_task_service import artifact_payload, task_jobs

    output_dir: Path | None = None
    try:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run else None
            if not run or not task or run.status != "queued":
                return
            claimed = await db.execute(update(GenerationRun).where(
                GenerationRun.id == run_id, GenerationRun.status == "queued",
            ).values(status="running", started_at=utcnow()))
            if claimed.rowcount != 1:
                await db.rollback(); return
            task.status = "running"; task.started_at = task.started_at or utcnow()
            script_artifact = await _latest_artifact(db, task.course_id, "video_script")
            course = await db.get(CourseProject, task.course_id)
            schema_version = (script_artifact.content_json or {}).get("schema_version") if script_artifact else None
            if not script_artifact or schema_version not in {"3.0", VIDEO_SCRIPT_V4} or not course:
                raise ValueError("Seedance V3/V4 视频脚本不存在")
            script = seedance_video_script_for_generation(script_artifact.content_json)
            video_config, asr_config = await _configs(db, course)
            control = await db.scalar(select(VideoSceneJob).where(
                VideoSceneJob.generation_run_id == run_id,
            ).order_by(VideoSceneJob.created_at))
            request_data = control.input_json or {}
            source = await db.get(Artifact, control.source_artifact_id) if control and control.source_artifact_id else None
            source_content = SeedanceVideoGenerationContent.model_validate(source.content_json) if source and source.artifact_type == "video_generation" and (source.content_json or {}).get("schema_version") == "3.0" else None
            quote_id = str(request_data.get("quote_id") or (source_content.production_settings.quote_id if source_content else ""))
            approved = int(request_data.get("approved_max_cost_fen") or (source_content.production_settings.approved_max_cost_fen if source_content else 0))
            quoted_request = dict(request_data.get("quote_request") or {})
            run_resolution = str(quoted_request.get("resolution") or request_data.get("resolution") or (source_content.production_settings.resolution if source_content else "1280x720"))
            if run_resolution not in NATIVE_VIDEO_RESOLUTIONS:
                raise ValueError(f"video_generation_quote_resolution_mismatch：报价分辨率 {run_resolution} 已失效，请重新报价")
            settings = SeedanceNativeSettings(
                model_config_id=video_config.id, model_name=video_config.model_name,
                quote_id=quote_id or "recompose", approved_max_cost_fen=approved,
                subtitle_enabled=bool((request_data.get("subtitle_enabled") if "subtitle_enabled" in request_data else True)),
                provider=video_config.provider, api_mode=video_config.api_mode,
                resolution=run_resolution,
            )
            if source_content:
                scenes = [item.model_copy(deep=True) for item in source_content.scenes]
            else:
                scenes = [SeedanceNativeScene(
                    id=f"VG-{scene.sequence:02d}", script_scene_id=scene.id, sequence=scene.sequence,
                    start_seconds=scene.start_seconds, end_seconds=scene.end_seconds,
                    continuity_group=scene.continuity_group, visual_prompt=scene.visual_prompt,
                    spoken_text=scene.spoken_text, voice_direction=scene.voice_direction,
                    sound_design=scene.sound_design, required_terms=scene.required_terms,
                    required_numbers=scene.required_numbers, required_facts=scene.required_facts,
                    estimated_tokens=next((item["estimated_tokens"] for item in request_data.get("quote", []) if item["scene_id"] == scene.id), 0),
                    estimated_cost_fen=next((item["estimated_cost_fen"] for item in request_data.get("quote", []) if item["scene_id"] == scene.id), 0),
                ) for scene in script.scenes]
            target_id = control.scene_id if run.trigger_type == "scene_regenerate" and control else ""
            regenerate_script_ids = {
                str(item["scene_id"]) for item in request_data.get("quote", [])
            } if target_id else set()
            if target_id:
                target = next((item for item in scenes if item.id == target_id or item.script_scene_id == target_id), None)
                if not target:
                    raise ValueError("目标片段不存在")
                if request_data.get("visual_prompt"): target.visual_prompt = str(request_data["visual_prompt"])
                if request_data.get("spoken_text"): target.spoken_text = str(request_data["spoken_text"])
                if request_data.get("voice_direction"): target.voice_direction = str(request_data["voice_direction"])
                if request_data.get("duration_seconds") is not None:
                    delta = float(request_data["duration_seconds"]) - (target.end_seconds - target.start_seconds)
                    target.end_seconds += delta
                    for item in scenes:
                        if item.sequence > target.sequence: item.start_seconds += delta; item.end_seconds += delta
                target.status = "pending"; target.video_asset_id = None; target.thumbnail_asset_id = None
                quote_item = next((item for item in request_data.get("quote", []) if item["scene_id"] == target.script_scene_id), None)
                if quote_item:
                    target.estimated_tokens = int(quote_item["estimated_tokens"])
                    target.estimated_cost_fen = int(quote_item["estimated_cost_fen"])
                for dependent in scenes:
                    if dependent.script_scene_id in regenerate_script_ids:
                        dependent.status = "pending"
                        dependent.video_asset_id = None
                        dependent.thumbnail_asset_id = None
                        dependent_quote = next((item for item in request_data.get("quote", []) if item["scene_id"] == dependent.script_scene_id), None)
                        if dependent_quote:
                            dependent.estimated_tokens = int(dependent_quote["estimated_tokens"])
                            dependent.estimated_cost_fen = int(dependent_quote["estimated_cost_fen"])
            run.progress = task.progress = 2
            await _emit(
                db, run, task, "video_generation_started", progress=2, scene_count=len(scenes),
                mode="seedance_native", provider=video_config.provider,
                api_mode=video_config.api_mode, model_name=video_config.model_name,
                completed_scene_count=0,
            )
            await db.commit()

        output_dir = (get_settings().storage_root / "generated" / course.id / "native-audio-video" / run_id).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        concurrency = max(1, min(2, int((video_config.adapter_config_json or {}).get("max_concurrency") or 2)))
        video_provider = native_audio_video_provider(video_config)
        semaphore = asyncio.Semaphore(concurrency)
        actual_cost_lock = asyncio.Lock()
        progress_lock = asyncio.Lock()
        completed_scene_ids: set[str] = set()
        stop_submitting = asyncio.Event()
        async with SessionLocal() as db:
            prior_cost = await db.scalar(select(func.coalesce(func.sum(VideoSceneJob.actual_cost_fen), 0)).where(
                VideoSceneJob.generation_run_id == run_id,
                VideoSceneJob.scene_id != "__run__",
            ))
        actual_cost = int(prior_cost or 0)
        reserved_cost = 0

        async def process_scene(scene: SeedanceNativeScene) -> Path:
            nonlocal actual_cost, reserved_cost
            if run.trigger_type == "recompose" and scene.video_asset_id:
                async with SessionLocal() as db:
                    asset = await db.get(ArtifactAsset, scene.video_asset_id)
                path = (get_settings().storage_root / asset.relative_path).resolve() if asset else None
                if path and path.is_file(): return path
            if target_id and scene.script_scene_id not in regenerate_script_ids and scene.video_asset_id:
                async with SessionLocal() as db:
                    asset = await db.get(ArtifactAsset, scene.video_asset_id)
                path = (get_settings().storage_root / asset.relative_path).resolve() if asset else None
                if path and path.is_file(): return path
            source_scene = next(item for item in script.scenes if item.id == scene.script_scene_id)
            prompt_scene = source_scene.model_copy(deep=True)
            prompt_scene.visual_prompt = scene.visual_prompt
            prompt_scene.spoken_text = scene.spoken_text
            prompt_scene.voice_direction = scene.voice_direction
            prompt_scene.sound_design = list(scene.sound_design)
            prompt_scene.end_seconds = prompt_scene.start_seconds + (scene.end_seconds - scene.start_seconds)
            instruction = str(request_data.get("instruction") or "") if target_id else ""
            request_hash = _request_hash(prompt_scene, video_config, settings.resolution, instruction)
            scene.request_hash = request_hash
            async with SessionLocal() as db:
                cached = await _cached_asset(db, course.id, request_hash)
            if cached:
                scene.video_asset_id = cached.id; scene.status = "ready"
                scene.qa = (cached.metadata_json or {}).get("qa", {"status": "passed"})
                scene.actual_transcript = (cached.metadata_json or {}).get("transcript", "")
                scene.subtitle_segments = (cached.metadata_json or {}).get("subtitle_segments", [])
                path = (get_settings().storage_root / cached.relative_path).resolve()
                async with progress_lock:
                    completed_scene_ids.add(scene.id)
                    completed = len(completed_scene_ids)
                await _publish(
                    run_id, "video_scene_reused", progress=5 + round(completed / len(scenes) * 70),
                    scene_id=scene.id, provider=video_config.provider, api_mode=video_config.api_mode,
                    model_name=video_config.model_name, completed_scene_count=completed,
                )
                return path
            async with semaphore:
                if stop_submitting.is_set():
                    raise RuntimeError(f"片段 {scene.id} 尚未提交：已有片段最终失败")
                last_qa = None
                for attempt in (1, 2):
                    scene.status = "generating"
                    async with SessionLocal() as db:
                        job = await db.scalar(select(VideoSceneJob).where(
                            VideoSceneJob.generation_run_id == run_id,
                            VideoSceneJob.scene_id == scene.id,
                            VideoSceneJob.attempt == attempt,
                        ))
                        if job and job.status == "qa_failed":
                            last_qa = job.qa_json or {}
                            scene.actual_cost_fen += int(job.actual_cost_fen or 0)
                            scene.actual_tokens += int(job.actual_tokens or 0)
                            continue
                        if not job:
                            job = VideoSceneJob(
                                generation_run_id=run_id, course_id=course.id, source_artifact_id=script_artifact.id,
                                scene_id=scene.id, operation="generate", status="running", attempt=attempt,
                                input_json={
                                    "prompt": _prompt(script, prompt_scene, qa_retry=last_qa, instruction=instruction),
                                    "duration_seconds": scene.end_seconds - scene.start_seconds,
                                },
                                request_hash=request_hash, provider=video_config.provider,
                                api_mode=video_config.api_mode, model_name=video_config.model_name,
                                estimated_tokens=scene.estimated_tokens, estimated_cost_fen=scene.estimated_cost_fen,
                                started_at=utcnow(),
                            )
                            db.add(job)
                        provider_job_id = job.provider_job_id
                        provider_file_id = job.provider_file_id
                        await db.commit()

                    async with actual_cost_lock:
                        estimate = int(scene.estimated_cost_fen)
                        if actual_cost + reserved_cost + estimate > settings.approved_max_cost_fen:
                            raise RuntimeError("剩余预算不足，未提交新的 Seedance Provider 任务")
                        reserved_cost += estimate

                    async def record_job(job_id: str):
                        scene.provider_job_id = job_id
                        async with SessionLocal() as db:
                            row = await db.scalar(select(VideoSceneJob).where(VideoSceneJob.generation_run_id == run_id, VideoSceneJob.scene_id == scene.id, VideoSceneJob.attempt == attempt))
                            if row: row.provider_job_id = job_id; await db.commit()

                    async def record_file(file_id: str):
                        async with SessionLocal() as db:
                            row = await db.scalar(select(VideoSceneJob).where(VideoSceneJob.generation_run_id == run_id, VideoSceneJob.scene_id == scene.id, VideoSceneJob.attempt == attempt))
                            if row: row.provider_file_id = file_id; await db.commit()

                    try:
                        if provider_job_id:
                            if video_config.api_mode == "gemini_interactions_video":
                                result = await video_provider.resume(
                                    provider_job_id, provider_file_id=provider_file_id,
                                    file_started=record_file,
                                )
                            else:
                                result = await video_provider.resume(provider_job_id)
                        else:
                            generate_kwargs = {
                                "prompt": _prompt(script, prompt_scene, qa_retry=last_qa, instruction=instruction),
                                "duration_seconds": scene.end_seconds - scene.start_seconds,
                                "resolution": settings.resolution,
                                "idempotency_key": f"{course.id}:{request_hash}:{attempt}",
                                "job_started": record_job,
                            }
                            if video_config.api_mode == "gemini_interactions_video":
                                generate_kwargs["file_started"] = record_file
                            result = await video_provider.generate(**generate_kwargs)
                    except Exception:
                        async with actual_cost_lock:
                            reserved_cost -= estimate
                        stop_submitting.set()
                        raise
                    raw = output_dir / f"{scene.id}-attempt-{attempt}-raw.mp4"; raw.write_bytes(result.raw)
                    normalized = output_dir / f"{scene.id}-attempt-{attempt}.mp4"
                    try:
                        probe = await _normalize_clip(raw, normalized, settings.resolution)
                        audio = output_dir / f"{scene.id}-attempt-{attempt}.wav"
                        await _extract_audio(normalized, audio)
                    except Exception:
                        stop_submitting.set()
                        raise
                    try:
                        transcript = await transcribe_doubao_audio(asr_config, audio)
                    except Exception as exc:  # noqa: BLE001
                        stop_submitting.set()
                        raise MediaProviderError(
                            f"原生音轨 ASR 失败：{str(exc)[:300]}",
                            code="video_asr_qa_failed",
                        ) from exc
                    subtitle_segments = _subtitle_segments(
                        transcript.segments,
                        scene.end_seconds - scene.start_seconds,
                        transcript.text,
                    )
                    qa = _fact_qa(scene, transcript.text)
                    tokens = int(result.usage.get("total_tokens") or result.usage.get("output_tokens") or scene.estimated_tokens)
                    if video_config.api_mode == "volcengine_ark_video":
                        price = float((video_config.adapter_config_json or {})["price_per_million_tokens_cny"])
                        cost_fen = math.ceil(tokens * price / 1_000_000 * 100)
                    else:
                        _, cost_fen = video_provider.estimate_cost(scene.end_seconds - scene.start_seconds)
                    async with actual_cost_lock:
                        reserved_cost -= estimate
                        actual_cost += cost_fen
                        budget_overrun = actual_cost > settings.approved_max_cost_fen
                    scene.actual_cost_fen += cost_fen
                    scene.actual_tokens += tokens
                    async with SessionLocal() as db:
                        row = await db.scalar(select(VideoSceneJob).where(VideoSceneJob.generation_run_id == run_id, VideoSceneJob.scene_id == scene.id, VideoSceneJob.attempt == attempt))
                        if row:
                            row.actual_tokens = tokens; row.actual_cost_fen = cost_fen; row.usage_json = result.usage; row.qa_json = qa
                            row.provider_file_id = getattr(result, "provider_file_id", "")
                            row.actual_model_name = getattr(result, "actual_model_name", "") or video_config.model_name
                            if budget_overrun:
                                row.error_json = {
                                    "code": "provider_usage_exceeded_quote",
                                    "message": "Provider 回传实耗高于已确认报价；实耗已审计，后续任务将被预算闸门阻断",
                                }
                            row.status = "completed" if qa["status"] == "passed" else "qa_failed"; row.finished_at = utcnow()
                            await db.commit()
                    if qa["status"] != "passed":
                        last_qa = qa
                        if attempt == 1:
                            async with progress_lock:
                                completed = len(completed_scene_ids)
                            await _publish(
                                run_id, "video_scene_qa_retry",
                                progress=5 + round(completed / len(scenes) * 70),
                                scene_id=scene.id, qa=qa, provider=video_config.provider,
                                api_mode=video_config.api_mode, model_name=video_config.model_name,
                                completed_scene_count=completed,
                            )
                            continue
                        scene.status = "qa_failed"; scene.qa = qa; scene.actual_transcript = transcript.text
                        stop_submitting.set()
                        raise RuntimeError(f"video_asr_qa_failed：片段 {scene.id} 的原生口播未通过教学事实检查")
                    thumb = output_dir / f"{scene.id}.png"; await _thumbnail(normalized, thumb)
                    async with SessionLocal() as db:
                        run_row = await db.get(GenerationRun, run_id); course_row = await db.get(CourseProject, course.id)
                        asset = await _store_asset(db, course=course_row, run=run_row, path=normalized, asset_type="video_clip", scene_id=scene.id, metadata={
                            "model_name": video_config.model_name, "actual_model_name": getattr(result, "actual_model_name", "") or video_config.model_name,
                            "provider": video_config.provider, "api_mode": video_config.api_mode,
                            "provider_job_id": result.provider_job_id,
                            "provider_file_id": getattr(result, "provider_file_id", ""),
                            "request_hash": request_hash, "native_audio": True, "qa": qa,
                            "transcript": transcript.text, "subtitle_segments": subtitle_segments, "probe": probe,
                        })
                        thumb_asset = await _store_asset(db, course=course_row, run=run_row, path=thumb, asset_type="thumbnail", scene_id=scene.id)
                        row = await db.scalar(select(VideoSceneJob).where(VideoSceneJob.generation_run_id == run_id, VideoSceneJob.scene_id == scene.id, VideoSceneJob.attempt == attempt))
                        if row: row.output_asset_id = asset.id
                        await db.commit()
                    scene.video_asset_id = asset.id; scene.thumbnail_asset_id = thumb_asset.id
                    scene.provider_job_id = result.provider_job_id; scene.actual_transcript = transcript.text
                    scene.subtitle_segments = subtitle_segments
                    scene.qa = qa; scene.usage = result.usage; scene.status = "ready"
                    async with progress_lock:
                        completed_scene_ids.add(scene.id)
                        completed = len(completed_scene_ids)
                    await _publish(
                        run_id, "video_scene_completed", progress=5 + round(completed / len(scenes) * 70),
                        scene_id=scene.id, video_asset_id=asset.id, actual_cost_fen=cost_fen,
                        provider=video_config.provider, api_mode=video_config.api_mode,
                        model_name=video_config.model_name, completed_scene_count=completed,
                    )
                    return normalized
                raise RuntimeError(f"片段 {scene.id} 生成失败")

        results = await asyncio.gather(*(process_scene(scene) for scene in scenes), return_exceptions=True)
        failures = [(scenes[index].id, result) for index, result in enumerate(results) if isinstance(result, BaseException)]
        if failures:
            first_scene_id, first_error = failures[0]
            if isinstance(first_error, Exception):
                raise first_error
            raise RuntimeError(f"{len(failures)} 个片段未完成；首个失败片段 {first_scene_id}")
        paths = [result for result in results if isinstance(result, Path)]
        cursor = 0.0
        for scene, path in zip(scenes, paths):
            duration = (await _probe(path))["duration_seconds"]
            scene.start_seconds = cursor; scene.end_seconds = cursor + duration; cursor += duration
        subtitle_path = output_dir / "subtitles.vtt"; subtitle_path.write_text(_vtt(scenes), encoding="utf-8")
        await _publish(run_id, "video_composition_started", progress=82)
        final, preview, thumb = await _compose(paths, output_dir, subtitle_path, settings.subtitle_enabled, settings.resolution)

        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id); task = await db.get(CourseTask, run.course_task_id); course = await db.get(CourseProject, run.course_id)
            final_asset = await _store_asset(db, course=course, run=run, path=final, asset_type="video_final", status="approved", metadata={"native_audio": True, "model_name": video_config.model_name, "provider": video_config.provider, "api_mode": video_config.api_mode})
            preview_asset = await _store_asset(db, course=course, run=run, path=preview, asset_type="video_preview", status="approved")
            thumb_asset = await _store_asset(db, course=course, run=run, path=thumb, asset_type="thumbnail", status="approved")
            subtitle_asset = await _store_asset(db, course=course, run=run, path=subtitle_path, asset_type="subtitle", status="approved")
            settings.interaction_ids = list(dict.fromkeys(
                scene.provider_job_id for scene in scenes
                if scene.provider_job_id and video_config.api_mode == "gemini_interactions_video"
            ))
            content = SeedanceVideoGenerationContent(
                production_settings=settings, source_versions={"video_script": script_artifact.version}, scenes=scenes,
                outputs=VideoGenerationOutputs(preview_asset_id=preview_asset.id, final_asset_id=final_asset.id, subtitle_asset_id=subtitle_asset.id, thumbnail_asset_id=thumb_asset.id, duration_seconds=cursor),
                cost_summary={"estimated_cost_fen": control.estimated_cost_fen if control else 0, "approved_max_cost_fen": settings.approved_max_cost_fen, "actual_cost_fen": actual_cost, "currency": "CNY"},
            )
            version = (await db.scalar(select(func.max(Artifact.version)).where(Artifact.course_id == course.id, Artifact.artifact_type == "video_generation")) or 0) + 1
            artifact = Artifact(
                course_id=course.id, artifact_type="video_generation", version=version,
                blueprint_version=course.current_blueprint_version, content_json=content.model_dump(),
                content_markdown=seedance_video_generation_markdown(content), status="draft",
                model_name=video_config.model_name, prompt_version="seedance-native-v3",
                change_summary="片段调整并重新拼接" if target_id else "原生有声分段生成",
                source_versions_json=content.source_versions,
            )
            db.add(artifact); await db.flush()
            assets = list(await db.scalars(select(ArtifactAsset).where(ArtifactAsset.generation_run_id == run.id, ArtifactAsset.artifact_id.is_(None))))
            for asset in assets: asset.artifact_id = artifact.id; asset.status = "approved"
            task.current_artifact_id = artifact.id; task.status = "review"; task.progress = 100; task.active_run_id = None; task.error_json = None; task.completed_at = utcnow()
            run.status = "completed"; run.progress = 100; run.finished_at = utcnow()
            if control: control.status = "completed"; control.progress = 100; control.finished_at = utcnow()
            await _emit(db, run, task, "artifact_version_created", status="review", progress=100, artifact=artifact_payload(artifact))
            await _emit(db, run, task, "video_generation_completed", status="review", progress=100, artifact=artifact_payload(artifact))
            await db.commit()
    except asyncio.CancelledError:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id); task = await db.get(CourseTask, run.course_task_id) if run else None
            if run: run.status = "cancelled"; run.finished_at = utcnow()
            if task: task.status = "cancelled"; task.active_run_id = None
            await db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id); task = await db.get(CourseTask, run.course_task_id) if run else None
            error_code = exc.code if isinstance(exc, MediaProviderError) else ("video_asr_qa_failed" if "video_asr_qa_failed" in str(exc) else "video_provider_unsupported")
            if run: run.status = "failed"; run.finished_at = utcnow(); run.error_json = {"code": error_code, "message": str(exc)[:500], "retryable": getattr(exc, "retryable", True)}
            if task: task.status = "failed"; task.active_run_id = None; task.error_json = run.error_json; await _emit(db, run, task, "video_generation_failed", status="failed", progress=task.progress, error=run.error_json)
            await db.commit()
    finally:
        task_jobs.pop(run_id, None)


async def cancel_seedance_provider_jobs(db, task: CourseTask) -> None:
    if not task.active_run_id:
        return
    course = await db.get(CourseProject, task.course_id)
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == task.course_id,
        AgentChatSession.module_type == "video_generation",
    ))
    video = await db.get(ModelConfig, session.video_model_config_id) if session and session.video_model_config_id else None
    if not video or video.api_mode not in {"volcengine_ark_video", "gemini_interactions_video"}:
        return
    jobs = list(await db.scalars(select(VideoSceneJob).where(
        VideoSceneJob.generation_run_id == task.active_run_id,
        VideoSceneJob.provider_job_id != "", VideoSceneJob.status == "running",
    )))
    try:
        provider = native_audio_video_provider(video)
    except Exception:
        return
    await asyncio.gather(*(provider.cancel(job.provider_job_id) for job in jobs), return_exceptions=True)
    for job in jobs: job.status = "cancelled"; job.finished_at = utcnow()
