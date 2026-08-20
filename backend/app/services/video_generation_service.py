import asyncio
import copy
import hashlib
import json
import logging
import math
import platform
import re
import shutil
import struct
import wave
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from PIL import Image, ImageStat
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import (
    AgentChatSession,
    AgentMessage,
    Artifact,
    ArtifactAsset,
    ArtifactLock,
    CourseBlueprint,
    CourseProject,
    CourseTask,
    GenerationEvent,
    GenerationRun,
    ModelConfig,
    VideoSceneJob,
)
from app.schemas.artifact import LessonPlanContent, PPTContent, VideoScriptContent
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.video import (
    VideoGenerationContent,
    VideoGenerationOutputs,
    VideoGenerationRunRequest,
    VideoGenerationScene,
    VideoGenerationSettings,
    VideoShot,
    VideoSceneRegenerateRequest,
    video_generation_markdown,
)
from app.services.media_provider_service import (
    MediaProviderError,
    cancel_video_job,
    generate_speech,
    generate_video,
    media_transport_supports,
)
from app.services.model_config_service import resolve_model_config
from app.services.quality_service import validate_video_script
from app.renderers.presentation_builder import PresentationBuilder
from app.renderers.ppt_visual_qa import PPTVisualQARenderer
from app.services.exercise_visual_service import generate_image


logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def _media_error_detail(exc: Exception) -> str:
    """Keep provider failures useful even when the exception has an empty message."""
    detail = str(exc).strip()
    if detail:
        return detail
    return exc.__class__.__name__


def _retryable_image_error(exc: Exception) -> bool:
    detail = _media_error_detail(exc).lower()
    return any(marker in detail for marker in (
        "429", "timeout", "timed out", "readtimeout", "connecttimeout",
        "remoteprotocolerror", "connection reset", "server disconnected",
        "500 internal server error", "502 bad gateway", "503 service unavailable",
        "504 gateway timeout",
    ))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extension(mime: str) -> str:
    return {
        "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
        "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/mp4": ".m4a", "audio/aac": ".aac", "image/png": ".png",
        "image/jpeg": ".jpg", "image/webp": ".webp",
        "text/plain": ".srt", "text/vtt": ".vtt",
    }.get(mime, ".bin")


@lru_cache(maxsize=1)
def _ffmpeg_binary() -> str:
    settings = get_settings()
    if settings.ffmpeg_binary:
        return settings.ffmpeg_binary
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("视频合成需要 FFmpeg；请安装 FFmpeg 或 imageio-ffmpeg") from exc


async def _run_ffmpeg(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        _ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        detail = stderr.decode("utf-8", "replace").strip()[-1200:]
        raise RuntimeError(f"视频合成失败：{detail or 'FFmpeg 返回非零状态'}")


async def _validate_media(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 1024:
        raise RuntimeError("生成的视频文件为空或不完整")
    process = await asyncio.create_subprocess_exec(
        _ffmpeg_binary(), "-v", "error", "-i", str(path),
        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(f"视频完整性检查失败：{stderr.decode('utf-8', 'replace')[-500:]}")


def _timecode(seconds: float, *, vtt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _subtitle_documents(scenes: list[VideoGenerationScene]) -> tuple[str, str]:
    srt = []
    vtt = ["WEBVTT", ""]
    cue_index = 0
    for scene in scenes:
        text = scene.subtitle_text.strip() or scene.narration_text.strip()
        if not text:
            continue
        # Never display an entire 30–90 second narration as one cue. Split on
        # natural punctuation, then hard-wrap long clauses to two short lines.
        clauses = [item.strip() for item in re.split(r"(?<=[。！？；!?;])", text) if item.strip()]
        chunks: list[str] = []
        for clause in clauses or [text]:
            while len(clause) > 30:
                boundary = max(clause.rfind(mark, 0, 31) for mark in "，、：,: ")
                cut = boundary + 1 if boundary >= 12 else 30
                chunks.append(clause[:cut].strip())
                clause = clause[cut:].strip()
            if clause:
                chunks.append(clause)
        weights = [max(1, len(chunk)) for chunk in chunks]
        duration = scene.end_seconds - scene.start_seconds
        cursor = scene.start_seconds
        total_weight = sum(weights)
        for chunk_index, (chunk, weight) in enumerate(zip(chunks, weights)):
            cue_index += 1
            end = scene.end_seconds if chunk_index == len(chunks) - 1 else min(
                scene.end_seconds, cursor + duration * weight / total_weight,
            )
            lines = [chunk] if len(chunk) <= 16 else [chunk[:16], chunk[16:30]]
            display = "\n".join(line for line in lines if line)
            srt.extend([
                str(cue_index),
                f"{_timecode(cursor)} --> {_timecode(end)}",
                display,
                "",
            ])
            vtt.extend([
                f"{_timecode(cursor, vtt=True)} --> {_timecode(end, vtt=True)}",
                display,
                "",
            ])
            cursor = end
    return "\n".join(srt), "\n".join(vtt)


def _write_silent_wav(path: Path, duration_seconds: float) -> None:
    sample_rate = 16_000
    frames = max(1, int(duration_seconds * sample_rate))
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        block = b"\x00\x00" * min(frames, sample_rate)
        remaining = frames
        while remaining:
            current = min(remaining, sample_rate)
            target.writeframes(block[: current * 2])
            remaining -= current


def _local_tts_engine() -> tuple[str, str] | None:
    if platform.system() == "Darwin" and Path("/usr/bin/say").is_file():
        return "macos_say", "/usr/bin/say"
    for name in ("espeak-ng", "espeak"):
        binary = shutil.which(name)
        if binary:
            return name, binary
    if platform.system() == "Windows":
        binary = shutil.which("powershell") or shutil.which("pwsh")
        if binary:
            return "windows_sapi", binary
    return None


def _pcm_rms(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        width = source.getsampwidth()
        frames = source.readframes(source.getnframes())
    if width != 2 or not frames:
        return 0.0
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    return math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))


async def _generate_local_speech(
    text: str,
    output: Path,
    duration_seconds: float,
    voice_style: str,
    speaking_rate_cps: float,
) -> tuple[str, str]:
    engine = _local_tts_engine()
    if not engine:
        raise RuntimeError("未配置语音模型，且系统未安装本地 TTS（macOS say / espeak-ng / Windows SAPI）")
    name, binary = engine
    raw = output.with_suffix(".tts.aiff" if name == "macos_say" else ".tts.wav")
    rate = max(120, min(260, round(175 * speaking_rate_cps / 4.0)))
    if voice_style == "calm":
        rate = round(rate * 0.9)
    elif voice_style == "friendly":
        rate = round(rate * 1.08)
    if name == "macos_say":
        command = [binary, "-v", "Tingting", "-r", str(rate), "-o", str(raw), text]
    elif name in {"espeak-ng", "espeak"}:
        command = [binary, "-v", "zh", "-s", str(rate), "-w", str(raw), text]
    else:
        escaped_text = text.replace("'", "''")
        escaped_path = str(raw).replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.SetOutputToWaveFile('{escaped_path}');$s.Speak('{escaped_text}');$s.Dispose()"
        )
        command = [binary, "-NoProfile", "-Command", script]
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode or not raw.is_file() or raw.stat().st_size < 1024:
        raise RuntimeError(f"本地旁白生成失败：{stderr.decode('utf-8', 'replace')[-300:]}")
    await _run_ffmpeg(
        "-i", str(raw), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
        "-af", f"loudnorm=I=-18:LRA=7:TP=-2,apad=pad_dur={duration_seconds:.3f}",
        "-t", f"{duration_seconds:.3f}", str(output),
    )
    raw.unlink(missing_ok=True)
    if _pcm_rms(output) < 80:
        raise RuntimeError("本地旁白音频为空或音量过低")
    return name, "local-tts"


def _validate_visual_image(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        if width < 640 or height < 360:
            raise ValueError("视觉图片尺寸过小")
        sample = image.convert("RGB").resize((64, 36))
        if sum(ImageStat.Stat(sample).stddev) < 8:
            raise ValueError("视觉图片疑似空白或纯色")
    return width, height


async def _prepare_ppt_pages(ppt: Artifact, output_dir: Path) -> dict[str, Path]:
    content = copy.deepcopy(ppt.content_json or {})
    root = get_settings().storage_root.resolve()
    async with SessionLocal() as db:
        for slide in content.get("slides") or []:
            for element in slide.get("elements") or []:
                asset_id = str(element.get("asset_id") or "")
                if element.get("kind") != "image" or not asset_id:
                    continue
                asset = await db.get(ArtifactAsset, asset_id)
                candidate = (root / asset.relative_path).resolve() if asset else None
                if candidate and candidate.is_file() and root in candidate.parents:
                    element["asset_path"] = str(candidate)
    render_root = output_dir / "ppt-render"
    pptx = render_root / "source.pptx"
    pages_dir = render_root / "pages"
    builder = PresentationBuilder().from_ppt_content(content)
    await asyncio.to_thread(builder.render, pptx)
    pages = await asyncio.to_thread(PPTVisualQARenderer.convert_pptx_to_images, pptx, pages_dir, 144)
    slides = content.get("slides") or []
    if len(pages) != len(slides):
        raise RuntimeError(f"PPT 页面渲染不完整：预期 {len(slides)} 页，实际 {len(pages)} 页")
    result: dict[str, Path] = {}
    for index, slide in enumerate(slides):
        _validate_visual_image(pages[index])
        result[str(slide.get("id") or f"slide-{index + 1}")] = pages[index].resolve()
    return result


def _ai_visual_scene_ids(scenes: list[VideoGenerationScene], visual_mode: str) -> set[str]:
    if visual_mode == "ppt_only":
        return set()
    if visual_mode == "ai_visual_first":
        return {scene.id for scene in scenes}
    priority = {"示范": 5, "情境": 4, "概念讲解": 3, "导入": 2, "检查点": 1}
    ranked = sorted(
        (scene for scene in scenes if scene.pedagogical_role in priority),
        key=lambda scene: (-priority[scene.pedagogical_role], scene.sequence),
    )
    return {scene.id for scene in ranked[:8]}


def _shot_plan(
    scene: VideoGenerationScene,
    *,
    enhanced: bool,
    visual_mode: str,
    ai_asset_id: str | None = None,
    fallback_reason: str = "",
) -> list[VideoShot]:
    duration = scene.end_seconds - scene.start_seconds
    if enhanced and ai_asset_id:
        if visual_mode == "ai_visual_first":
            # In AI-first mode the generated illustration is the actual scene
            # material, rather than a short insert between two text-heavy slides.
            return [
                VideoShot(
                    id=f"{scene.id}-S1",
                    start_offset_seconds=0,
                    end_offset_seconds=duration,
                    source_type="ai_image",
                    asset_id=ai_asset_id,
                    motion="slow_zoom_in" if scene.sequence % 2 else "pan_right",
                    prompt=scene.visual_prompt,
                ),
            ]
        first = round(duration * 0.18, 3)
        last = round(duration * 0.18, 3)
        return [
            VideoShot(id=f"{scene.id}-S1", start_offset_seconds=0, end_offset_seconds=first, source_type="ppt", motion="slow_zoom_in"),
            VideoShot(id=f"{scene.id}-S2", start_offset_seconds=first, end_offset_seconds=duration - last, source_type="ai_image", asset_id=ai_asset_id, motion="pan_right", prompt=scene.visual_prompt),
            VideoShot(id=f"{scene.id}-S3", start_offset_seconds=duration - last, end_offset_seconds=duration, source_type="ppt", motion="focus"),
        ]
    midpoint = round(duration * 0.55, 3)
    return [
        VideoShot(id=f"{scene.id}-S1", start_offset_seconds=0, end_offset_seconds=midpoint, source_type="ppt", motion="slow_zoom_in", fallback_reason=fallback_reason),
        VideoShot(id=f"{scene.id}-S2", start_offset_seconds=midpoint, end_offset_seconds=duration, source_type="ppt", motion="focus"),
    ]


def _visual_cache_key(
    scene: VideoGenerationScene,
    *,
    script_version: int,
    ppt_version: int,
    model_config: ModelConfig,
    resolution: str,
) -> str:
    payload = "|".join((
        scene.script_scene_id, scene.visual_prompt, str(script_version), str(ppt_version),
        model_config.id, model_config.model_name, resolution,
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _cached_visual_asset(course_id: str, cache_key: str) -> tuple[ArtifactAsset | None, Path | None]:
    async with SessionLocal() as db:
        candidates = list(await db.scalars(select(ArtifactAsset).where(
            ArtifactAsset.course_id == course_id,
            ArtifactAsset.asset_type == "video_visual",
            ArtifactAsset.status.in_(["preview", "approved"]),
        ).order_by(ArtifactAsset.created_at.desc()).limit(100)))
    asset = next((item for item in candidates if (item.metadata_json or {}).get("cache_key") == cache_key), None)
    if not asset:
        return None, None
    path = (get_settings().storage_root / asset.relative_path).resolve()
    root = get_settings().storage_root.resolve()
    return (asset, path) if root in path.parents and path.is_file() else (asset, None)


def _visual_prompt(script_scene: dict, ppt: dict) -> str:
    slide_id = script_scene.get("slide_id", "")
    slide = next((item for item in ppt.get("slides", []) if item.get("id") == slide_id), {})
    # PPT visual suggestions describe slide layouts (columns, cards, titles),
    # which image models tend to reproduce as text-heavy infographics. The video
    # needs semantic scene material instead, so only pass the teaching meaning.
    semantic_context = "；".join(filter(None, [
        slide.get("title"),
        slide.get("purpose"),
        script_scene.get("learning_purpose"),
        (script_scene.get("audio_track") or {}).get("narration_text", ""),
    ]))
    return (
        "为八年级物理微课创作一幅 16:9 横版、无文字的教学场景插画。"
        f"本镜头要表达的教学语义：{semantic_context}。"
        "把抽象概念转化为真实物体、实验器材、水体、受力方向和空间关系；"
        "可以使用无文字箭头或高亮来引导观察，科学关系必须准确。"
        "只生成完整画面，不得生成 PPT、幻灯片、信息图、流程图、左右分栏、卡片、步骤框、表格或界面。"
        "画面中不得出现任何可读字符，包括中文、英文、数字、公式、标题、标签、字幕、刻度文字和水印。"
        "保持同一课程的深蓝与青色视觉基调、真实光照和适龄表达，不添加脚本之外的事实。"
    )


async def _latest_artifact(db, course_id: str, artifact_type: str) -> Artifact | None:
    return await db.scalar(select(Artifact).where(
        Artifact.course_id == course_id,
        Artifact.artifact_type == artifact_type,
    ).order_by(Artifact.version.desc()))


async def _validate_sources(db, task: CourseTask) -> tuple[Artifact, Artifact, CourseProject]:
    course = await db.get(CourseProject, task.course_id)
    script = await _latest_artifact(db, task.course_id, "video_script")
    ppt = await _latest_artifact(db, task.course_id, "ppt")
    lesson = await _latest_artifact(db, task.course_id, "lesson_plan")
    blueprint = await db.scalar(select(CourseBlueprint).where(
        CourseBlueprint.course_id == task.course_id,
        CourseBlueprint.version == course.current_blueprint_version if course else 0,
    ))
    if not course or not script or not ppt or not lesson or not blueprint:
        raise ValueError("视频生成所需的视频脚本、PPT、教学设计或课程蓝图尚未准备完成")
    script_task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == task.course_id,
        CourseTask.task_type == "video_script",
    ))
    if script_task and script_task.status not in {"review", "approved"}:
        raise ValueError("视频脚本存在未同步的上游更新，请先在“视频脚本”任务中同步最新内容")
    if (script.content_json or {}).get("schema_version") != "2.0":
        raise ValueError("当前视频脚本是旧版结构，请先在“视频脚本”任务中同步最新内容，升级后再生成视频")
    try:
        validated_script = VideoScriptContent.model_validate(script.content_json)
    except ValidationError as exc:
        logger.warning("Video script %s failed generation preflight validation: %s", script.id, exc)
        raise ValueError("视频脚本结构不完整，请先在“视频脚本”任务中同步或修复后再生成视频") from exc
    PPTContent.model_validate(ppt.content_json)
    issues = validate_video_script(
        CourseBlueprintSchema.model_validate(blueprint.content_json),
        validated_script.model_dump(),
        LessonPlanContent.model_validate(lesson.content_json).model_dump(),
        ppt.content_json,
    )
    blocking = [item for item in issues if item["severity"] in {"critical", "major"}]
    if blocking:
        raise ValueError(f"视频脚本存在阻断问题：{blocking[0]['description']}")
    script_ppt_version = (script.source_versions_json or {}).get("ppt")
    if script_ppt_version and script_ppt_version != ppt.version:
        raise ValueError("视频脚本尚未同步最新 PPT，请先更新视频脚本")
    return script, ppt, course


async def _media_configs(
    db, course: CourseProject,
) -> tuple[ModelConfig | None, ModelConfig | None, ModelConfig | None, bool]:
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == "video_generation",
    ))
    video_config = await db.get(ModelConfig, session.video_model_config_id) if session and session.video_model_config_id else None
    speech_config = await db.get(ModelConfig, session.speech_model_config_id) if session and session.speech_model_config_id else None
    image_config = await db.get(ModelConfig, session.image_model_config_id) if session and session.image_model_config_id else None
    if not video_config:
        video_config = await resolve_model_config(db, course.owner_id, model_category="video")
    if not image_config:
        ppt_session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course.id,
            AgentChatSession.module_type == "ppt",
        ))
        inherited = await db.get(ModelConfig, ppt_session.image_model_config_id) if ppt_session and ppt_session.image_model_config_id else None
        if inherited and "image_generation" in (inherited.capabilities_json or []) and media_transport_supports(
            inherited.provider, inherited.api_mode, "image_generation",
        ):
            image_config = inherited
            if session:
                session.image_model_config_id = inherited.id
    if video_config and (
        "video_generation" not in (video_config.capabilities_json or [])
        or not media_transport_supports(video_config.provider, video_config.api_mode, "video_generation")
    ):
        logger.warning(
            "Ignoring incompatible video model config %s (provider=%s, api_mode=%s)",
            video_config.id, video_config.provider, video_config.api_mode,
        )
        video_config = None
        session.video_model_config_id = None
    if speech_config and (
        "speech_generation" not in (speech_config.capabilities_json or [])
        or not media_transport_supports(speech_config.provider, speech_config.api_mode, "speech_generation")
    ):
        logger.warning(
            "Ignoring incompatible speech model config %s (provider=%s, api_mode=%s)",
            speech_config.id, speech_config.provider, speech_config.api_mode,
        )
        speech_config = None
        session.speech_model_config_id = None
    if image_config and (
        "image_generation" not in (image_config.capabilities_json or [])
        or not media_transport_supports(image_config.provider, image_config.api_mode, "image_generation")
    ):
        logger.warning(
            "Ignoring incompatible image model config %s (provider=%s, api_mode=%s)",
            image_config.id, image_config.provider, image_config.api_mode,
        )
        image_config = None
        if session:
            session.image_model_config_id = None

    # 私有媒体模型是可选增强项；缺失或历史配置不兼容时使用内置 FFmpeg/Mock 渲染。
    mock_mode = not video_config and not speech_config
    return video_config, speech_config, image_config, mock_mode


def _media_limit(config: ModelConfig | None, key: str, default: int) -> int:
    try:
        configured = int((config.adapter_config_json or {}).get(key)) if config else default
    except (TypeError, ValueError):
        configured = default
    return max(1, min(default, configured))


async def create_video_generation_run(
    db,
    task: CourseTask,
    request: VideoGenerationRunRequest,
) -> GenerationRun:
    if task.task_type != "video_generation":
        raise ValueError("当前任务不是视频生成任务")
    if task.active_run_id or task.status in {"queued", "running"}:
        raise ValueError("当前视频任务已经在运行")
    script, _, course = await _validate_sources(db, task)
    await _media_configs(db, course)
    if request.action == "initial" and task.current_artifact_id:
        raise ValueError("视频已经生成，请使用重新合成或分镜调整")
    if request.action == "retry" and task.status not in {"failed", "cancelled"}:
        raise ValueError("只有失败或已取消的视频任务可以重试")
    if request.action == "recompose" and not task.current_artifact_id:
        raise ValueError("视频尚未生成，无法重新合成")
    if request.action == "sync_dependencies" and not task.current_artifact_id:
        raise ValueError("视频尚未生成，请使用首次生成")
    run = GenerationRun(
        course_id=task.course_id,
        course_task_id=task.id,
        thread_id=str(uuid4()),
        run_type="task",
        trigger_type=request.action,
        status="queued",
        current_node="video_generation_pipeline",
    )
    db.add(run)
    await db.flush()
    db.add(VideoSceneJob(
        generation_run_id=run.id,
        course_id=task.course_id,
        source_artifact_id=task.current_artifact_id or script.id,
        scene_id="__run__",
        operation=request.action,
        status="queued",
        input_json=request.model_dump(),
    ))
    task.active_run_id = run.id
    task.status = "queued"
    task.progress = 0
    task.error_json = None
    await _emit(db, run, task, "task_status_changed", status="queued", progress=0)
    return run


async def create_video_scene_regeneration_run(
    db,
    task: CourseTask,
    scene_id: str,
    request: VideoSceneRegenerateRequest,
    user_message: AgentMessage | None = None,
) -> GenerationRun:
    if task.active_run_id or task.status in {"queued", "running"}:
        raise ValueError("当前视频任务已经在运行")
    if not task.current_artifact_id:
        raise ValueError("视频尚未生成，无法调整分镜")
    source = await db.get(Artifact, task.current_artifact_id)
    content = VideoGenerationContent.model_validate(source.content_json)
    scene = next((item for item in content.scenes if item.id == scene_id or item.script_scene_id == scene_id), None)
    if not scene:
        raise ValueError("指定的视频分镜不存在")
    locks = list(await db.scalars(select(ArtifactLock).where(ArtifactLock.artifact_id == source.id)))
    if request.preserve_locked_content and any(lock.json_path == "$" or scene.id in lock.json_path or scene.script_scene_id in lock.json_path for lock in locks):
        raise ValueError("该分镜已锁定，不能重新生成")
    _, _, course = await _validate_sources(db, task)
    await _media_configs(db, course)
    run = GenerationRun(
        course_id=task.course_id,
        course_task_id=task.id,
        thread_id=str(uuid4()),
        run_type="task",
        trigger_type="scene_regenerate",
        status="queued",
        current_node="video_generation_pipeline",
    )
    db.add(run)
    await db.flush()
    db.add(VideoSceneJob(
        generation_run_id=run.id,
        course_id=task.course_id,
        source_artifact_id=source.id,
        scene_id=scene.id,
        operation="scene_regenerate",
        status="queued",
        input_json={**request.model_dump(), "settings": content.production_settings.model_dump()},
    ))
    task.active_run_id = run.id
    task.status = "queued"
    task.progress = 0
    task.error_json = None
    if user_message:
        user_message.task_id = task.id
        user_message.run_id = run.id
        user_message.status = "pending"
    await _emit(db, run, task, "task_status_changed", status="queued", progress=0)
    return run


async def create_video_instruction_run(db, task: CourseTask, message: AgentMessage) -> GenerationRun:
    match = re.search(r"第\s*(\d+)\s*个?分镜|\b(?:VS|VG)-(\d+)\b", message.content, re.I)
    if not match:
        raise ValueError("请在指令中指定需要调整的分镜编号，例如“第 3 个分镜”")
    number = int(next(value for value in match.groups() if value))
    source = await db.get(Artifact, task.current_artifact_id) if task.current_artifact_id else None
    if not source:
        raise ValueError("视频尚未生成")
    content = VideoGenerationContent.model_validate(source.content_json)
    scene = next((item for item in content.scenes if item.sequence == number), None)
    if not scene:
        raise ValueError("指定的视频分镜不存在")
    text = message.content
    preserve_audio = bool(re.search(r"(?:保留|不要(?:改变|修改|重生成)|不改).*?(?:旁白|语音|声音|配音)", text))
    preserve_subtitle = bool(re.search(r"(?:保留|不要(?:改变|修改|重生成)|不改).*?字幕", text))
    audio = bool(re.search(r"旁白|语音|声音|配音", text)) and not preserve_audio
    subtitle = "字幕" in text and not preserve_subtitle
    visual = bool(re.search(r"画面|场景|镜头|视觉|动效", text)) or not (audio or subtitle)
    request = VideoSceneRegenerateRequest(
        instruction=text,
        regenerate_visual=visual,
        regenerate_audio=audio,
        regenerate_subtitle=subtitle,
    )
    return await create_video_scene_regeneration_run(db, task, scene.id, request, message)


async def cancel_video_provider_jobs(db, task: CourseTask) -> None:
    """Best-effort cancellation of provider-side jobs before the local coroutine stops."""
    if task.task_type != "video_generation" or not task.active_run_id:
        return
    course = await db.get(CourseProject, task.course_id)
    if not course:
        return
    try:
        video_config, _, _, mock_mode = await _media_configs(db, course)
    except ValueError:
        return
    if not video_config or mock_mode:
        return
    jobs = list(await db.scalars(select(VideoSceneJob).where(
        VideoSceneJob.generation_run_id == task.active_run_id,
        VideoSceneJob.provider_job_id != "",
        VideoSceneJob.status.in_(["queued", "running"]),
    )))
    for job in jobs:
        try:
            await cancel_video_job(video_config, job.provider_job_id)
        except Exception:  # noqa: BLE001
            logger.warning("Unable to cancel provider video job", extra={"provider_job_id": job.provider_job_id})


async def _emit(db, run: GenerationRun, task: CourseTask, event_type: str, **data) -> None:
    db.add(GenerationEvent(run_id=run.id, event_type=event_type, data_json={
        "course_id": run.course_id,
        "run_id": run.id,
        "task_id": task.id,
        "task_type": task.task_type,
        **data,
    }))


async def _publish(run_id: str, event_type: str, *, progress: int | None = None, **data) -> None:
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
        if not run or not task:
            return
        if progress is not None:
            # Concurrent scene workers can publish out of order. Progress must
            # remain monotonic or the UI appears to move backwards.
            run.progress = max(run.progress or 0, progress)
            task.progress = max(task.progress or 0, progress)
        await _emit(db, run, task, event_type, status=task.status, progress=task.progress, **data)
        await db.commit()


async def _store_asset(
    db,
    *,
    course: CourseProject,
    run: GenerationRun,
    path: Path,
    asset_type: str,
    mime_type: str,
    scene_id: str = "",
    duration_seconds: float = 0,
    width: int = 0,
    height: int = 0,
    provider: str = "local",
    model_name: str = "ffmpeg",
    status: str = "preview",
    metadata: dict | None = None,
) -> ArtifactAsset:
    relative = str(path.resolve().relative_to(get_settings().storage_root.resolve()))
    asset = ArtifactAsset(
        owner_id=course.owner_id,
        course_id=course.id,
        generation_run_id=run.id,
        json_path=f"$.scenes.{scene_id}" if scene_id else "$.outputs",
        asset_type=asset_type,
        relative_path=relative,
        mime_type=mime_type,
        width=width,
        height=height,
        duration_ms=round(duration_seconds * 1000),
        source_scene_id=scene_id,
        metadata_json=metadata or {},
        size_bytes=path.stat().st_size,
        checksum=_sha256(path),
        provider=provider,
        model_name=model_name,
        status=status,
        review_json={},
    )
    db.add(asset)
    await db.flush()
    return asset


async def _asset_file(asset_id: str | None) -> tuple[ArtifactAsset | None, Path | None]:
    if not asset_id:
        return None, None
    async with SessionLocal() as db:
        asset = await db.get(ArtifactAsset, asset_id)
        if not asset:
            return None, None
        path = (get_settings().storage_root / asset.relative_path).resolve()
        root = get_settings().storage_root.resolve()
        if root not in path.parents or not path.is_file():
            return asset, None
        return asset, path


async def _retry_provider_call(call, on_retry, attempts: int = 3):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            retryable = not isinstance(exc, MediaProviderError) or exc.retryable
            if not retryable or attempt == attempts:
                raise
            await on_retry(attempt + 1, exc)
            await asyncio.sleep(min(8, 2 ** (attempt - 1)))
    raise last_error or RuntimeError("媒体服务调用失败")


async def _restore_retry_assets(task_id: str, current_run_id: str, scenes: list[VideoGenerationScene]) -> None:
    """Reuse completed scene outputs from the most recent failed/cancelled run."""
    async with SessionLocal() as db:
        previous = await db.scalar(select(GenerationRun).where(
            GenerationRun.course_task_id == task_id,
            GenerationRun.id != current_run_id,
            GenerationRun.status.in_(["failed", "cancelled"]),
        ).order_by(GenerationRun.created_at.desc()))
        if not previous:
            return
        assets = list(await db.scalars(select(ArtifactAsset).where(
            ArtifactAsset.generation_run_id == previous.id,
            ArtifactAsset.asset_type.in_(["video_clip", "audio_narration", "thumbnail"]),
            ArtifactAsset.status.in_(["preview", "approved"]),
        ).order_by(ArtifactAsset.created_at.desc())))
    by_scene: dict[tuple[str, str], ArtifactAsset] = {}
    for asset in assets:
        by_scene.setdefault((asset.source_scene_id, asset.asset_type), asset)
    for scene in scenes:
        clip = by_scene.get((scene.id, "video_clip"))
        audio = by_scene.get((scene.id, "audio_narration"))
        thumb = by_scene.get((scene.id, "thumbnail"))
        _, clip_path = await _asset_file(clip.id if clip else None)
        if clip_path:
            scene.video_asset_id = clip.id
            scene.audio_asset_id = audio.id if audio else None
            scene.thumbnail_asset_id = thumb.id if thumb else None
            scene.provider_job_id = str((clip.metadata_json or {}).get("provider_job_id") or "") or None
            scene.status = "ready"


async def _clone_reused_scene_assets(
    run_id: str,
    course_id: str,
    scene: VideoGenerationScene,
) -> Path:
    """Bind reused media to the new run/version while keeping the immutable file bytes."""
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        course = await db.get(CourseProject, course_id)
        if not run or not course:
            raise RuntimeError("视频生成运行已不存在")
        replacements: dict[str, ArtifactAsset] = {}
        for field_name, asset_type in (
            ("video_asset_id", "video_clip"),
            ("audio_asset_id", "audio_narration"),
            ("thumbnail_asset_id", "thumbnail"),
        ):
            old_id = getattr(scene, field_name)
            old = await db.get(ArtifactAsset, old_id) if old_id else None
            if not old:
                continue
            path = (get_settings().storage_root / old.relative_path).resolve()
            if not path.is_file():
                continue
            cloned = await _store_asset(
                db,
                course=course,
                run=run,
                path=path,
                asset_type=asset_type,
                mime_type=old.mime_type,
                scene_id=scene.id,
                duration_seconds=old.duration_ms / 1000,
                width=old.width,
                height=old.height,
                provider=old.provider,
                model_name=old.model_name,
                metadata={**(old.metadata_json or {}), "reused_from_asset_id": old.id},
            )
            replacements[field_name] = cloned
        clip = replacements.get("video_asset_id")
        if not clip:
            raise RuntimeError(f"分镜 {scene.id} 缺少可复用的视频片段")
        for field_name, asset in replacements.items():
            setattr(scene, field_name, asset.id)
        scene.status = "ready"
        clip_path = (get_settings().storage_root / clip.relative_path).resolve()
        await db.commit()
        return clip_path


async def _scene_clip(
    output: Path,
    visual_path: Path | None,
    audio_path: Path,
    duration: float,
    resolution: str,
    sequence: int,
) -> None:
    width, height = (int(value) for value in resolution.split("x", 1))
    color = ["0xEEF2FF", "0xE0F2FE", "0xECFDF5", "0xFFF7ED"][sequence % 4]
    if visual_path:
        input_args = ["-stream_loop", "-1", "-i", str(visual_path)]
    else:
        input_args = ["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:r=25:d={duration:.3f}"]
    await _run_ffmpeg(
        *input_args,
        "-i", str(audio_path),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-af", f"apad=pad_dur={duration:.3f}",
        "-t", f"{duration:.3f}",
        "-r", "25", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output),
    )


async def _still_shot(
    image_path: Path,
    output: Path,
    duration: float,
    resolution: str,
    motion: str,
) -> None:
    width, height = (int(value) for value in resolution.split("x", 1))
    frames = max(1, round(duration * 25))
    if motion == "slow_zoom_out":
        zoom = "if(eq(on,1),1.08,max(1.0,zoom-0.0007))"
    elif motion in {"focus", "pan_left", "pan_right"}:
        zoom = "min(zoom+0.0012,1.12)"
    elif motion == "static":
        zoom = "1.0"
    else:
        zoom = "min(zoom+0.0007,1.08)"
    x_expr = "iw/2-(iw/zoom/2)"
    if motion == "pan_left":
        x_expr = "(iw-iw/zoom)*(1-on/{})".format(frames)
    elif motion == "pan_right":
        x_expr = "(iw-iw/zoom)*on/{}".format(frames)
    filters = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='{zoom}':x='{x_expr}':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps=25,"
        "format=yuv420p"
    )
    await _run_ffmpeg(
        "-loop", "1", "-i", str(image_path), "-vf", filters,
        "-t", f"{duration:.3f}", "-r", "25", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", str(output),
    )


async def _directed_visual(
    scene: VideoGenerationScene,
    ppt_page: Path,
    ai_image: Path | None,
    output_dir: Path,
    resolution: str,
) -> Path:
    segment_paths: list[Path] = []
    for index, shot in enumerate(scene.shots, 1):
        image_path = ai_image if shot.source_type == "ai_image" and ai_image else ppt_page
        segment = output_dir / f"{scene.id}-shot-{index:02d}.mp4"
        await _still_shot(
            image_path,
            segment,
            shot.end_offset_seconds - shot.start_offset_seconds,
            resolution,
            shot.motion,
        )
        segment_paths.append(segment)
    if not segment_paths:
        raise RuntimeError(f"分镜 {scene.id} 没有可渲染镜头")
    concat_file = output_dir / f"{scene.id}-shots.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in segment_paths),
        encoding="utf-8",
    )
    visual = output_dir / f"{scene.id}-visual.mp4"
    await _run_ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(visual))
    return visual


async def _thumbnail(video: Path, output: Path) -> None:
    await _run_ffmpeg("-ss", "0.2", "-i", str(video), "-frames:v", "1", "-vf", "scale=640:-2", str(output))


async def _compose(
    scene_paths: list[Path],
    output_dir: Path,
    resolution: str,
    subtitle_enabled: bool,
    srt_path: Path,
) -> tuple[Path, Path, Path]:
    concat_file = output_dir / "concat.txt"
    # FFmpeg resolves concat entries relative to concat.txt, not the process cwd.
    # Storage roots may be configured as relative paths, so always write absolute inputs.
    concat_file.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in scene_paths),
        encoding="utf-8",
    )
    base = output_dir / "base.mp4"
    await _run_ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(base))
    final = output_dir / "final.mp4"
    if subtitle_enabled and srt_path.stat().st_size:
        await _run_ffmpeg(
            "-i", str(base), "-i", str(srt_path), "-map", "0:v", "-map", "0:a?", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=zho",
            "-movflags", "+faststart", str(final),
        )
    else:
        shutil.copy2(base, final)
    preview = output_dir / "preview.mp4"
    target_width = min(1280, int(resolution.split("x", 1)[0]))
    await _run_ffmpeg(
        "-i", str(final), "-vf", f"scale={target_width}:-2", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "30", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(preview),
    )
    thumb = output_dir / "thumbnail.png"
    await _thumbnail(final, thumb)
    await _validate_media(final)
    await _validate_media(preview)
    return final, preview, thumb


def _scenes_from_script(script: Artifact, ppt: Artifact) -> list[VideoGenerationScene]:
    validated = VideoScriptContent.model_validate(script.content_json)
    scenes = []
    for index, source in enumerate(validated.scenes, 1):
        subtitle = "".join(chunk.text for chunk in source.text_track.subtitle_chunks)
        scenes.append(VideoGenerationScene(
            id=f"VG-{index:02d}",
            script_scene_id=source.id,
            sequence=index,
            start_seconds=source.start_seconds,
            end_seconds=source.end_seconds,
            visual_prompt=_visual_prompt(source.model_dump(), ppt.content_json),
            narration_text=source.audio_track.narration_text,
            subtitle_text=subtitle or source.audio_track.narration_text,
            production_notes=source.production_notes,
            source_slide_id=source.slide_id,
            pedagogical_role=source.pedagogical_role,
            animation_cues=[cue.model_dump() for cue in source.visual_track.animation_cues],
            speaking_rate_cps=source.audio_track.speaking_rate_cps,
            status="pending",
        ))
    return scenes


def _hydrate_scene_director_data(
    scenes: list[VideoGenerationScene],
    script: Artifact,
    ppt: Artifact | None = None,
    *,
    refresh_visual_prompts: bool = False,
) -> None:
    script_content = VideoScriptContent.model_validate(script.content_json)
    source_by_id = {scene.id: scene for scene in script_content.scenes}
    for scene in scenes:
        source = source_by_id.get(scene.script_scene_id)
        if not source:
            continue
        scene.source_slide_id = scene.source_slide_id or source.slide_id
        scene.pedagogical_role = scene.pedagogical_role or source.pedagogical_role
        scene.animation_cues = scene.animation_cues or [cue.model_dump() for cue in source.visual_track.animation_cues]
        scene.speaking_rate_cps = scene.speaking_rate_cps or source.audio_track.speaking_rate_cps
        if refresh_visual_prompts and ppt:
            scene.visual_prompt = _visual_prompt(source.model_dump(), ppt.content_json)


async def execute_video_generation_run(run_id: str) -> None:
    from app.services.course_task_service import artifact_payload, task_jobs

    try:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            if not run or not task:
                return
            # A run can be dispatched by both an API background task and a recovery
            # scheduler. Only the queued claimant may execute it; a late duplicate
            # must never overwrite an already completed artifact with a failure.
            if run.status != "queued":
                logger.info("Skipping duplicate video run execution", extra={"run_id": run_id, "status": run.status})
                return
            claimed_at = utcnow()
            claimed = await db.execute(
                update(GenerationRun)
                .where(GenerationRun.id == run_id, GenerationRun.status == "queued")
                .values(status="running", started_at=claimed_at)
            )
            if claimed.rowcount != 1:
                await db.rollback()
                logger.info("Skipping concurrently claimed video run", extra={"run_id": run_id})
                return
            task.status = "running"
            task.started_at = task.started_at or utcnow()
            await db.commit()
            await db.refresh(run)
            script, ppt, course = await _validate_sources(db, task)
            video_config, speech_config, image_config, mock_mode = await _media_configs(db, course)
            control = await db.scalar(select(VideoSceneJob).where(
                VideoSceneJob.generation_run_id == run.id,
            ).order_by(VideoSceneJob.created_at))
            request_data = control.input_json or {}
            source_video = await db.get(Artifact, control.source_artifact_id) if control and control.source_artifact_id else None
            if run.trigger_type in {"recompose", "scene_regenerate"} and source_video and source_video.artifact_type == "video_generation":
                source_content = VideoGenerationContent.model_validate(source_video.content_json)
                scenes = [scene.model_copy(deep=True) for scene in source_content.scenes]
                settings = source_content.production_settings.model_copy(deep=True)
            else:
                scenes = _scenes_from_script(script, ppt)
                settings = VideoGenerationSettings.model_validate(request_data)
            _hydrate_scene_director_data(
                scenes,
                script,
                ppt,
                refresh_visual_prompts=run.trigger_type in {"recompose", "sync_dependencies"},
            )
            source_video_schema = str((source_video.content_json or {}).get("schema_version") or "") if source_video else ""
            if request_data.get("resolution"):
                settings.resolution = request_data["resolution"]
            if request_data.get("voice_style"):
                settings.voice_style = request_data["voice_style"]
            if "subtitle_enabled" in request_data:
                settings.subtitle_enabled = bool(request_data["subtitle_enabled"])
            if request_data.get("visual_mode") in {"hybrid_director", "ppt_only", "ai_visual_first"}:
                settings.visual_mode = request_data["visual_mode"]
            duration_limit = _media_limit(
                video_config, "max_duration_seconds", get_settings().video_max_duration_seconds,
            )
            if scenes[-1].end_seconds > duration_limit:
                raise ValueError(
                    f"视频总时长超过当前配置上限（{duration_limit} 秒）"
                )

            locked_scene_ids: set[str] = set()
            if (
                run.trigger_type == "sync_dependencies"
                and source_video
                and source_video.artifact_type == "video_generation"
            ):
                source_content = VideoGenerationContent.model_validate(source_video.content_json)
                locks = list(await db.scalars(select(ArtifactLock).where(
                    ArtifactLock.artifact_id == source_video.id,
                )))
                lock_paths = [lock.json_path for lock in locks]
                lock_all = source_video.is_locked or "$" in lock_paths
                previous_by_script = {scene.script_scene_id: scene for scene in source_content.scenes}
                for scene in scenes:
                    previous = previous_by_script.get(scene.script_scene_id)
                    is_locked = bool(previous and (
                        lock_all
                        or any(previous.id in path or previous.script_scene_id in path for path in lock_paths)
                    ))
                    if not is_locked or not previous:
                        continue
                    scene.visual_prompt = previous.visual_prompt
                    scene.visual_style = previous.visual_style
                    scene.narration_text = previous.narration_text
                    scene.subtitle_text = previous.subtitle_text
                    scene.production_notes = list(previous.production_notes)
                    scene.video_asset_id = previous.video_asset_id
                    scene.audio_asset_id = previous.audio_asset_id
                    scene.thumbnail_asset_id = previous.thumbnail_asset_id
                    scene.provider_job_id = previous.provider_job_id
                    scene.status = previous.status
                    scene.error = previous.error
                    locked_scene_ids.add(scene.id)

            target_scene_id = control.scene_id if run.trigger_type == "scene_regenerate" and control else ""
            duration_changed_ids: set[str] = set()
            if target_scene_id:
                target = next(scene for scene in scenes if scene.id == target_scene_id)
                instruction = str(request_data.get("instruction") or "").strip()
                if request_data.get("visual_prompt"):
                    target.visual_prompt = str(request_data["visual_prompt"]).strip()
                if request_data.get("visual_style"):
                    target.visual_style = str(request_data["visual_style"]).strip()
                if request_data.get("narration_text"):
                    target.narration_text = str(request_data["narration_text"]).strip()
                if request_data.get("subtitle_text") is not None:
                    target.subtitle_text = str(request_data["subtitle_text"]).strip()
                if request_data.get("production_notes") is not None:
                    target.production_notes = [str(item).strip() for item in request_data["production_notes"] if str(item).strip()]
                if request_data.get("duration_seconds") is not None:
                    new_duration = float(request_data["duration_seconds"])
                    old_duration = target.end_seconds - target.start_seconds
                    delta = new_duration - old_duration
                    target.end_seconds = target.start_seconds + new_duration
                    for following in scenes:
                        if following.sequence > target.sequence:
                            following.start_seconds += delta
                            following.end_seconds += delta
                    duration_changed_ids.add(target.id)
                if request_data.get("regenerate_visual"):
                    target.visual_prompt = f"{target.visual_prompt} 用户调整要求：{instruction}" if instruction else target.visual_prompt
                    target.video_asset_id = None
                    target.thumbnail_asset_id = None
                if request_data.get("regenerate_audio"):
                    target.audio_asset_id = None
                if request_data.get("regenerate_subtitle"):
                    target.subtitle_text = target.narration_text
                target.status = "pending"
            if scenes[-1].end_seconds > duration_limit:
                raise ValueError(f"视频总时长超过当前配置上限（{duration_limit} 秒）")

            run.progress = 3
            task.progress = 3
            if control:
                control.status = "running"
                control.started_at = control.started_at or utcnow()
            await _emit(db, run, task, "video_generation_started", status="running", progress=3, scene_count=len(scenes))
            await db.commit()

        output_dir = (get_settings().storage_root / "generated" / course.id / "video" / run_id).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        await _publish(run_id, "video_ppt_render_started", progress=4, detail="正在渲染 PPT 视觉底图")
        ppt_pages = await _prepare_ppt_pages(ppt, output_dir)
        await _publish(run_id, "video_visual_planning_started", progress=9, detail="正在根据脚本规划镜头")
        ai_scene_ids = _ai_visual_scene_ids(scenes, settings.visual_mode) if image_config else set()
        generation_warnings: list[str] = []
        if settings.visual_mode != "ppt_only" and not image_config:
            generation_warnings.append("未配置可用图片模型，关键分镜已自动降级为动态 PPT")
        if not speech_config and not _local_tts_engine():
            raise RuntimeError("未配置语音模型，且当前系统没有可用的本地 TTS 引擎")
        if run.trigger_type == "retry":
            await _restore_retry_assets(task.id, run.id, scenes)

        total = len(scenes)
        semaphore = asyncio.Semaphore(_media_limit(
            video_config, "max_concurrency", get_settings().video_max_concurrency,
        ))
        image_semaphore = asyncio.Semaphore(1)
        image_request_lock = asyncio.Lock()
        last_image_request_at = 0.0
        completed_count = 0
        progress_lock = asyncio.Lock()

        async def process_scene(index: int, scene: VideoGenerationScene) -> Path:
            nonlocal completed_count, last_image_request_at
            async with semaphore:
                duration = scene.end_seconds - scene.start_seconds
                progress_start = 5 + round((index - 1) / total * 70)
                targeted = bool(target_scene_id and scene.id == target_scene_id)
                old_clip_asset, old_clip_path = await _asset_file(scene.video_asset_id)
                old_audio_asset, old_audio_path = await _asset_file(scene.audio_asset_id)
                _, old_thumb_path = await _asset_file(scene.thumbnail_asset_id)
                silent_legacy_audio = bool(
                    old_audio_path
                    and old_audio_path.suffix.lower() == ".wav"
                    and old_audio_asset
                    and old_audio_asset.model_name == "mock-speech"
                    and _pcm_rms(old_audio_path) < 80
                )

                regenerate_visual = run.trigger_type in {"initial", "sync_dependencies"} or (
                    run.trigger_type == "recompose" and source_video_schema != "2.0"
                )
                # A visual-mode change must invalidate old rendered clips. In
                # AI-first mode, also retry scenes that previously degraded to PPT.
                source_visual_mode = (
                    source_content.production_settings.visual_mode
                    if source_video and run.trigger_type in {"recompose", "scene_regenerate"}
                    else settings.visual_mode
                )
                if run.trigger_type == "recompose" and (
                    source_visual_mode != settings.visual_mode
                    or (settings.visual_mode == "ai_visual_first" and scene.visual_source != "ai_image")
                ):
                    regenerate_visual = True
                regenerate_audio = run.trigger_type in {"initial", "sync_dependencies"} or (
                    run.trigger_type == "recompose" and source_video_schema != "2.0"
                )
                if silent_legacy_audio:
                    regenerate_audio = True
                    old_audio_path = None
                if scene.id in locked_scene_ids:
                    regenerate_visual = False
                    regenerate_audio = False
                if run.trigger_type == "retry":
                    regenerate_visual = old_clip_path is None
                    regenerate_audio = old_audio_path is None
                if targeted:
                    regenerate_visual = bool(request_data.get("regenerate_visual"))
                    regenerate_audio = bool(request_data.get("regenerate_audio"))
                normalize_existing = bool(
                    source_video
                    and source_video.artifact_type == "video_generation"
                    and VideoGenerationContent.model_validate(source_video.content_json).production_settings.resolution
                    != settings.resolution
                ) or scene.id in duration_changed_ids
                rebuild_clip = regenerate_visual or regenerate_audio or normalize_existing

                if old_clip_path and not rebuild_clip:
                    reused_path = await _clone_reused_scene_assets(run_id, course.id, scene)
                    async with progress_lock:
                        completed_count += 1
                        scene_progress = 5 + round(completed_count / total * 70)
                    await _publish(
                        run_id, "video_scene_completed", progress=scene_progress,
                        scene_id=scene.id, video_asset_id=scene.video_asset_id, reused=True,
                    )
                    return reused_path

                await _publish(
                    run_id, "video_scene_started", progress=progress_start,
                    scene_id=scene.id, sequence=scene.sequence,
                )
                async with SessionLocal() as db:
                    job = await db.scalar(select(VideoSceneJob).where(
                        VideoSceneJob.generation_run_id == run_id,
                        VideoSceneJob.scene_id == scene.id,
                    ).order_by(VideoSceneJob.attempt.desc()))
                    if not job:
                        job = VideoSceneJob(
                            generation_run_id=run_id, course_id=course.id,
                            source_artifact_id=source_video.id if source_video else script.id,
                            scene_id=scene.id, operation="regenerate" if targeted else "generate",
                            status="running", progress=5, input_json={"visual_prompt": scene.visual_prompt},
                            started_at=utcnow(),
                        )
                        db.add(job)
                    else:
                        job.status = "running"
                        job.error_json = None
                        job.started_at = job.started_at or utcnow()
                    await db.commit()

                async def mark_attempt(attempt: int, exc: Exception):
                    async with SessionLocal() as db:
                        job = await db.scalar(select(VideoSceneJob).where(
                            VideoSceneJob.generation_run_id == run_id,
                            VideoSceneJob.scene_id == scene.id,
                        ).order_by(VideoSceneJob.attempt.desc()))
                        if job:
                            job.attempt = attempt
                            job.error_json = {"message": str(exc)[:500], "retrying": True}
                            await db.commit()
                    await _publish(
                        run_id, "video_scene_progress", progress=min(progress_start + 5, 74),
                        scene_id=scene.id, detail=f"媒体服务暂时失败，正在进行第 {attempt} 次尝试",
                    )

                async def record_provider_job(job_id: str):
                    async with SessionLocal() as db:
                        job = await db.scalar(select(VideoSceneJob).where(
                            VideoSceneJob.generation_run_id == run_id,
                            VideoSceneJob.scene_id == scene.id,
                        ).order_by(VideoSceneJob.attempt.desc()))
                        if job:
                            job.provider_job_id = job_id
                            await db.commit()

                try:
                    visual_path = old_clip_path
                    provider_job_id = str((old_clip_asset.metadata_json or {}).get("provider_job_id") or "reused") if old_clip_asset else "mock"
                    visual_provider = old_clip_asset.provider if old_clip_asset else "mock"
                    visual_model = old_clip_asset.model_name if old_clip_asset else "mock-video"
                    if regenerate_visual:
                        visual_path = None
                        provider_job_id = "mock"
                        visual_provider = "mock"
                        visual_model = "mock-video"
                        if video_config and not mock_mode:
                            async def report(percent: int, status: str):
                                async with SessionLocal() as db:
                                    job = await db.scalar(select(VideoSceneJob).where(
                                        VideoSceneJob.generation_run_id == run_id,
                                        VideoSceneJob.scene_id == scene.id,
                                    ).order_by(VideoSceneJob.attempt.desc()))
                                    if job:
                                        job.progress = max(1, min(99, percent))
                                        await db.commit()
                                await _publish(
                                    run_id, "video_scene_progress", progress=min(progress_start + 8, 74),
                                    scene_id=scene.id, provider_progress=percent, detail=status,
                                )

                            visual = await _retry_provider_call(
                                lambda: generate_video(
                                    video_config, scene.visual_prompt, duration, settings.resolution,
                                    progress=report, job_started=record_provider_job,
                                ),
                                mark_attempt,
                            )
                            provider_job_id = visual.provider_job_id
                            visual_path = output_dir / f"{scene.id}-provider{_extension(visual.mime_type)}"
                            visual_path.write_bytes(visual.raw)
                            visual_provider = video_config.provider
                            visual_model = video_config.model_name
                        else:
                            ppt_page = ppt_pages.get(scene.source_slide_id)
                            if not ppt_page:
                                raise RuntimeError(f"分镜 {scene.id} 对应的 PPT 页面 {scene.source_slide_id} 不存在")
                            ai_path: Path | None = None
                            ai_asset_id: str | None = None
                            fallback_reason = ""
                            wants_ai = scene.id in ai_scene_ids
                            if targeted and request_data.get("visual_source") == "ppt":
                                wants_ai = False
                            elif targeted and request_data.get("visual_source") == "ai_image":
                                wants_ai = True
                            if wants_ai and image_config and image_config.provider != "mock":
                                max_image_attempts = 6 if settings.visual_mode == "ai_visual_first" else 4
                                try:
                                    await _publish(
                                        run_id, "video_scene_progress", progress=min(progress_start + 4, 74),
                                        scene_id=scene.id, detail="正在生成关键分镜视觉图片",
                                    )
                                    cache_key = _visual_cache_key(
                                        scene, script_version=script.version, ppt_version=ppt.version,
                                        model_config=image_config, resolution=settings.resolution,
                                    )
                                    cached_asset, cached_path = await _cached_visual_asset(course.id, cache_key)
                                    if cached_asset and cached_path:
                                        ai_path = cached_path
                                        ai_asset_id = cached_asset.id
                                        await _publish(
                                            run_id, "video_scene_progress", progress=min(progress_start + 4, 74),
                                            scene_id=scene.id, detail="已复用相同脚本与模型生成的视觉图片",
                                        )
                                    else:
                                        last_image_error: Exception | None = None
                                        raw = b""
                                        mime = "image/png"
                                        async with image_semaphore:
                                            for image_attempt in range(1, max_image_attempts + 1):
                                                try:
                                                    # Keep requests spaced out: several compatible image
                                                    # gateways accept only a small number of jobs per minute.
                                                    async with image_request_lock:
                                                        now = asyncio.get_running_loop().time()
                                                        wait_seconds = max(0.0, 10.0 - (now - last_image_request_at))
                                                        if wait_seconds:
                                                            await asyncio.sleep(wait_seconds)
                                                        raw, mime = await generate_image(
                                                            image_config, scene.visual_prompt, "1536x1024",
                                                        )
                                                        last_image_request_at = asyncio.get_running_loop().time()
                                                    break
                                                except Exception as exc:  # noqa: BLE001
                                                    last_image_error = exc
                                                    if image_attempt == max_image_attempts or not _retryable_image_error(exc):
                                                        raise
                                                    detail = _media_error_detail(exc)
                                                    is_rate_limited = "429" in detail
                                                    is_timeout = "timeout" in detail.lower() or "timed out" in detail.lower()
                                                    retry_after = 12 * image_attempt if is_rate_limited else 5 * image_attempt
                                                    response = getattr(exc, "response", None)
                                                    if response is not None:
                                                        try:
                                                            retry_after = max(retry_after, int(response.headers.get("retry-after", 0)))
                                                        except (TypeError, ValueError):
                                                            pass
                                                    await _publish(
                                                        run_id, "video_scene_progress", progress=min(progress_start + 4, 74),
                                                        scene_id=scene.id,
                                                        detail=(
                                                            f"图片服务限流，{retry_after} 秒后重试"
                                                            if is_rate_limited
                                                            else f"图片生成响应超时，{retry_after} 秒后重试"
                                                            if is_timeout
                                                            else f"图片服务暂时不可用，{retry_after} 秒后重试"
                                                        ),
                                                    )
                                                    await asyncio.sleep(retry_after)
                                        if not raw:
                                            raise last_image_error or RuntimeError("图片模型没有返回内容")
                                        ai_path = output_dir / f"{scene.id}-ai{_extension(mime)}"
                                        ai_path.write_bytes(raw)
                                        image_width, image_height = _validate_visual_image(ai_path)
                                        async with SessionLocal() as db:
                                            run_row = await db.get(GenerationRun, run_id)
                                            course_row = await db.get(CourseProject, course.id)
                                            visual_asset = await _store_asset(
                                                db, course=course_row, run=run_row, path=ai_path,
                                                asset_type="video_visual", mime_type=mime, scene_id=scene.id,
                                                width=image_width, height=image_height,
                                                provider=image_config.provider, model_name=image_config.model_name,
                                                metadata={
                                                    "prompt": scene.visual_prompt,
                                                    "source_slide_id": scene.source_slide_id,
                                                    "visual_mode": settings.visual_mode,
                                                    "cache_key": cache_key,
                                                },
                                            )
                                            await db.commit()
                                            ai_asset_id = visual_asset.id
                                    scene.visual_source = "ai_image"
                                except Exception as exc:  # noqa: BLE001
                                    if settings.visual_mode == "ai_visual_first":
                                        raise RuntimeError(
                                            f"分镜 {scene.id} 的 AI 图片在 {max_image_attempts} 次尝试后仍未生成："
                                            f"{_media_error_detail(exc)[:180]}"
                                        ) from exc
                                    fallback_reason = f"AI 图片生成失败，已回退动态 PPT：{_media_error_detail(exc)[:180]}"
                                    scene.generation_warnings.append(fallback_reason)
                                    generation_warnings.append(f"{scene.id}：{fallback_reason}")
                                    ai_path = None
                                    await _publish(
                                        run_id, "video_scene_degraded", progress=min(progress_start + 4, 74),
                                        scene_id=scene.id, detail=fallback_reason,
                                    )
                            scene.shots = _shot_plan(
                                scene, enhanced=bool(ai_path), ai_asset_id=ai_asset_id,
                                visual_mode=settings.visual_mode, fallback_reason=fallback_reason,
                            )
                            scene.visual_source = "ai_image" if ai_path else "ppt"
                            visual_path = await _directed_visual(
                                scene, ppt_page, ai_path, output_dir, settings.resolution,
                            )
                            provider_job_id = ai_asset_id or "ppt-director"
                            visual_provider = image_config.provider if ai_path and image_config else "local"
                            visual_model = image_config.model_name if ai_path and image_config else "ppt-director"

                    audio_path = old_audio_path
                    audio_mime = old_audio_asset.mime_type if old_audio_asset else "audio/wav"
                    speech_provider = old_audio_asset.provider if old_audio_asset else "mock"
                    speech_model = old_audio_asset.model_name if old_audio_asset else "mock-speech"
                    if regenerate_audio or not audio_path:
                        if speech_config and speech_config.provider != "mock" and speech_config.api_mode != "mock_media":
                            speech = await _retry_provider_call(
                                lambda: generate_speech(speech_config, scene.narration_text, settings.voice_style),
                                mark_attempt,
                            )
                            audio_path = output_dir / f"{scene.id}-narration{_extension(speech.mime_type)}"
                            audio_path.write_bytes(speech.raw)
                            audio_mime = speech.mime_type
                            speech_provider = speech_config.provider
                            speech_model = speech_config.model_name
                        else:
                            audio_path = output_dir / f"{scene.id}-narration.wav"
                            speech_provider, speech_model = await _generate_local_speech(
                                scene.narration_text, audio_path, duration,
                                settings.voice_style, scene.speaking_rate_cps,
                            )
                            audio_mime = "audio/wav"
                    if not audio_path:
                        raise RuntimeError(f"分镜 {scene.id} 缺少旁白音频")

                    clip_path = output_dir / f"{scene.id}.mp4"
                    thumb_path = output_dir / f"{scene.id}.png"
                    await _scene_clip(clip_path, visual_path, audio_path, duration, settings.resolution, scene.sequence)
                    await _thumbnail(clip_path, thumb_path)
                    await _validate_media(clip_path)
                    width, height = (int(value) for value in settings.resolution.split("x", 1))
                    async with SessionLocal() as db:
                        run_row = await db.get(GenerationRun, run_id)
                        course_row = await db.get(CourseProject, course.id)
                        audio_asset = await _store_asset(
                            db, course=course_row, run=run_row, path=audio_path,
                            asset_type="audio_narration", mime_type=audio_mime,
                            scene_id=scene.id, duration_seconds=duration,
                            provider=speech_provider, model_name=speech_model,
                            metadata={"reused_from_asset_id": old_audio_asset.id} if old_audio_asset and not regenerate_audio else None,
                        )
                        clip_asset = await _store_asset(
                            db, course=course_row, run=run_row, path=clip_path,
                            asset_type="video_clip", mime_type="video/mp4", scene_id=scene.id,
                            duration_seconds=duration, width=width, height=height,
                            provider=visual_provider, model_name=visual_model,
                            metadata={
                                "provider_job_id": provider_job_id,
                                "visual_prompt": scene.visual_prompt,
                                "visual_source": scene.visual_source,
                                "shots": [shot.model_dump() for shot in scene.shots],
                            },
                        )
                        thumb_asset = await _store_asset(
                            db, course=course_row, run=run_row, path=thumb_path,
                            asset_type="thumbnail", mime_type="image/png", scene_id=scene.id,
                            width=640, height=round(640 * height / width),
                            metadata={"reused_source": bool(old_thumb_path and not regenerate_visual)},
                        )
                        job = await db.scalar(select(VideoSceneJob).where(
                            VideoSceneJob.generation_run_id == run_id,
                            VideoSceneJob.scene_id == scene.id,
                        ).order_by(VideoSceneJob.attempt.desc()))
                        if job:
                            job.status = "completed"
                            job.progress = 100
                            job.provider_job_id = provider_job_id
                            job.output_asset_id = clip_asset.id
                            job.finished_at = utcnow()
                        scene.audio_asset_id = audio_asset.id
                        scene.video_asset_id = clip_asset.id
                        scene.thumbnail_asset_id = thumb_asset.id
                        scene.provider_job_id = provider_job_id
                        scene.status = "ready"
                        scene.error = None
                        await db.commit()
                    async with progress_lock:
                        completed_count += 1
                        scene_progress = 5 + round(completed_count / total * 70)
                    await _publish(
                        run_id, "video_scene_completed", progress=scene_progress,
                        scene_id=scene.id, video_asset_id=scene.video_asset_id,
                    )
                    return clip_path
                except asyncio.CancelledError:
                    async with SessionLocal() as db:
                        job = await db.scalar(select(VideoSceneJob).where(
                            VideoSceneJob.generation_run_id == run_id,
                            VideoSceneJob.scene_id == scene.id,
                        ).order_by(VideoSceneJob.attempt.desc()))
                        if job:
                            job.status = "cancelled"
                            job.finished_at = utcnow()
                            await db.commit()
                    raise
                except Exception as exc:  # noqa: BLE001
                    scene.status = "failed"
                    scene.error = {"message": str(exc)[:500]}
                    async with SessionLocal() as db:
                        job = await db.scalar(select(VideoSceneJob).where(
                            VideoSceneJob.generation_run_id == run_id,
                            VideoSceneJob.scene_id == scene.id,
                        ).order_by(VideoSceneJob.attempt.desc()))
                        if job:
                            job.status = "failed"
                            job.error_json = scene.error
                            job.finished_at = utcnow()
                            await db.commit()
                    await _publish(
                        run_id, "video_scene_failed", progress=progress_start,
                        scene_id=scene.id, error=scene.error,
                    )
                    raise

        scene_tasks = [
            asyncio.create_task(process_scene(index, scene))
            for index, scene in enumerate(scenes, 1)
        ]
        if settings.visual_mode == "ai_visual_first":
            try:
                scene_results = await asyncio.gather(*scene_tasks)
            except BaseException:
                # Strict AI mode cannot publish a mixed result. Stop outstanding
                # provider calls immediately after the first terminal failure.
                for scene_task in scene_tasks:
                    if not scene_task.done():
                        scene_task.cancel()
                await asyncio.gather(*scene_tasks, return_exceptions=True)
                raise
        else:
            scene_results = await asyncio.gather(*scene_tasks, return_exceptions=True)
        failed_scenes = [
            (scenes[index].id, result)
            for index, result in enumerate(scene_results)
            if isinstance(result, BaseException)
        ]
        if failed_scenes:
            scene_id, error = failed_scenes[0]
            raise RuntimeError(f"{len(failed_scenes)} 个分镜生成失败；首个失败分镜 {scene_id}：{error}")
        scene_paths = [result for result in scene_results if isinstance(result, Path)]

        await _publish(run_id, "video_composition_started", progress=80, detail="正在合成完整视频")
        srt_text, vtt_text = _subtitle_documents(scenes)
        srt_path = output_dir / "subtitles.srt"
        vtt_path = output_dir / "subtitles.vtt"
        srt_path.write_text(srt_text, encoding="utf-8")
        vtt_path.write_text(vtt_text, encoding="utf-8")
        final_path, preview_path, thumb_path = await _compose(
            scene_paths, output_dir, settings.resolution, settings.subtitle_enabled, srt_path,
        )
        file_limit_mb = _media_limit(video_config, "max_file_mb", get_settings().video_max_mb)
        max_bytes = file_limit_mb * 1024 * 1024
        if final_path.stat().st_size > max_bytes:
            raise RuntimeError(f"最终视频超过当前配置文件大小上限（{file_limit_mb} MB）")
        duration_seconds = scenes[-1].end_seconds
        width, height = (int(value) for value in settings.resolution.split("x", 1))

        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id)
            course = await db.get(CourseProject, run.course_id)
            script = await _latest_artifact(db, course.id, "video_script")
            ppt = await _latest_artifact(db, course.id, "ppt")
            final_asset = await _store_asset(
                db, course=course, run=run, path=final_path, asset_type="video_final",
                mime_type="video/mp4", duration_seconds=duration_seconds, width=width, height=height,
                status="approved", metadata={"quality": "ffmpeg_decode_passed"},
            )
            preview_asset = await _store_asset(
                db, course=course, run=run, path=preview_path, asset_type="video_preview",
                mime_type="video/mp4", duration_seconds=duration_seconds,
                width=min(1280, width), height=round(min(1280, width) * height / width), status="approved",
            )
            thumbnail_asset = await _store_asset(
                db, course=course, run=run, path=thumb_path, asset_type="thumbnail",
                mime_type="image/png", width=640, height=round(640 * height / width), status="approved",
            )
            subtitle_asset = await _store_asset(
                db, course=course, run=run, path=vtt_path, asset_type="subtitle",
                mime_type="text/vtt", duration_seconds=duration_seconds, status="approved",
            )
            content = VideoGenerationContent(
                production_settings=settings,
                source_versions={"video_script": script.version, "ppt": ppt.version},
                scenes=scenes,
                generation_warnings=list(dict.fromkeys(generation_warnings)),
                outputs=VideoGenerationOutputs(
                    preview_asset_id=preview_asset.id,
                    final_asset_id=final_asset.id,
                    subtitle_asset_id=subtitle_asset.id,
                    thumbnail_asset_id=thumbnail_asset.id,
                    duration_seconds=duration_seconds,
                ),
            )
            version = (await db.scalar(select(func.max(Artifact.version)).where(
                Artifact.course_id == course.id,
                Artifact.artifact_type == "video_generation",
            )) or 0) + 1
            artifact = Artifact(
                course_id=course.id,
                artifact_type="video_generation",
                version=version,
                blueprint_version=course.current_blueprint_version,
                content_json=content.model_dump(),
                content_markdown=video_generation_markdown(content),
                status="draft",
                model_name=video_config.model_name if video_config and not mock_mode else "hybrid-director",
                prompt_version="video-v2",
                change_summary="分镜调整并重新合成" if target_scene_id else "首次生成" if version == 1 else "重新合成",
                source_versions_json=content.source_versions,
            )
            db.add(artifact)
            await db.flush()
            generated_assets = list(await db.scalars(select(ArtifactAsset).where(
                ArtifactAsset.generation_run_id == run.id,
                ArtifactAsset.artifact_id.is_(None),
            )))
            for asset in generated_assets:
                asset.artifact_id = artifact.id
                if asset.status == "preview":
                    asset.status = "approved"
            task.current_artifact_id = artifact.id
            task.status = "review"
            task.progress = 100
            task.active_run_id = None
            task.error_json = None
            task.completed_at = utcnow()
            run.status = "completed"
            run.progress = 100
            run.finished_at = utcnow()
            control = await db.scalar(select(VideoSceneJob).where(
                VideoSceneJob.generation_run_id == run.id,
                VideoSceneJob.scene_id == "__run__",
            ))
            if control:
                control.status = "completed"
                control.progress = 100
                control.finished_at = utcnow()
            user_message = await db.scalar(select(AgentMessage).where(
                AgentMessage.run_id == run.id,
                AgentMessage.role == "user",
            ))
            if user_message:
                user_message.status = "completed"
                reply = AgentMessage(
                    course_id=course.id,
                    task_id=task.id,
                    run_id=run.id,
                    module_type="video_generation",
                    role="assistant",
                    content=f"已完成分镜调整并生成视频 V{version}，原版本仍可在版本历史中恢复。",
                    status="completed",
                    artifact_id=artifact.id,
                )
                db.add(reply)
            await _emit(db, run, task, "video_composition_completed", status="review", progress=96, final_asset_id=final_asset.id)
            await _emit(db, run, task, "artifact_version_created", status="review", progress=100, artifact=artifact_payload(artifact))
            await _emit(db, run, task, "video_generation_completed", status="review", progress=100, artifact=artifact_payload(artifact))
            await _emit(db, run, task, "task_status_changed", status="review", progress=100)
            await db.commit()
    except asyncio.CancelledError:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            if run:
                run.status = "cancelled"
                run.finished_at = utcnow()
            if task:
                task.status = "cancelled"
                task.active_run_id = None
                await _emit(db, run, task, "task_status_changed", status="cancelled", progress=task.progress)
            await db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Video generation failed", extra={"run_id": run_id})
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            if not run or not task:
                return
            retryable = exc.retryable if isinstance(exc, MediaProviderError) else True
            error = {
                "code": "video_generation_failed",
                "message": str(exc)[:500] or "视频生成失败，请重试。",
                "retryable": retryable,
            }
            run.status = "failed"
            run.error_json = error
            run.finished_at = utcnow()
            task.status = "failed"
            task.active_run_id = None
            task.error_json = error
            await _emit(db, run, task, "video_generation_failed", status="failed", progress=task.progress, error=error)
            await _emit(db, run, task, "task_failed", status="failed", progress=task.progress, error=error)
            await db.commit()
    finally:
        task_jobs.pop(run_id, None)
