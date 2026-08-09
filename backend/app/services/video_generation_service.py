import asyncio
import hashlib
import json
import logging
import re
import shutil
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

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
    VideoSceneRegenerateRequest,
    video_generation_markdown,
)
from app.services.media_provider_service import MediaProviderError, cancel_video_job, generate_speech, generate_video
from app.services.model_config_service import resolve_model_config
from app.services.quality_service import validate_video_script


logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


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
        "text/plain": ".srt", "text/vtt": ".vtt",
    }.get(mime, ".bin")


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
    for index, scene in enumerate(scenes, 1):
        text = scene.subtitle_text.strip() or scene.narration_text.strip()
        if not text:
            continue
        srt.extend([
            str(index),
            f"{_timecode(scene.start_seconds)} --> {_timecode(scene.end_seconds)}",
            text,
            "",
        ])
        vtt.extend([
            f"{_timecode(scene.start_seconds, vtt=True)} --> {_timecode(scene.end_seconds, vtt=True)}",
            text,
            "",
        ])
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


def _visual_prompt(script_scene: dict, ppt: dict) -> str:
    slide_id = script_scene.get("slide_id", "")
    slide = next((item for item in ppt.get("slides", []) if item.get("id") == slide_id), {})
    visual = (script_scene.get("visual_track") or {}).get("composition", "")
    notes = "；".join(script_scene.get("production_notes") or [])
    slide_context = "；".join(filter(None, [slide.get("title"), slide.get("purpose"), slide.get("visual_suggestion")]))
    learning_context = "；".join(filter(None, [
        script_scene.get("pedagogical_role"),
        script_scene.get("learning_purpose"),
        f"教学环节 {script_scene.get('lesson_stage_id')}" if script_scene.get("lesson_stage_id") else "",
        f"目标 {','.join(script_scene.get('objective_ids') or [])}",
        f"知识点 {','.join(script_scene.get('knowledge_point_ids') or [])}",
        (script_scene.get("audio_track") or {}).get("narration_text", ""),
    ]))
    return (
        f"教学微课分镜，16:9，画面任务：{visual}。PPT 页面语义：{slide_context}。"
        f"教学语义：{learning_context}。制作要求：{notes}。"
        "保持课程统一色彩、人物和物体连续；不得生成文字、公式、标签、字幕或水印；"
        "不添加脚本之外的事实，画面适合当前学习者年龄。"
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
    validated_script = VideoScriptContent.model_validate(script.content_json)
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


async def _media_configs(db, course: CourseProject) -> tuple[ModelConfig | None, ModelConfig | None, bool]:
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == "video_generation",
    ))
    video_config = await db.get(ModelConfig, session.video_model_config_id) if session and session.video_model_config_id else None
    speech_config = await db.get(ModelConfig, session.speech_model_config_id) if session and session.speech_model_config_id else None
    active = await resolve_model_config(db, course.owner_id, course.model_config_id)
    mock_mode = bool(active and active.provider == "mock" and not video_config and not speech_config)
    if not mock_mode:
        if not video_config or "video_generation" not in (video_config.capabilities_json or []):
            raise ValueError("请先为视频生成任务配置具备 video_generation 能力的模型")
        if not speech_config or "speech_generation" not in (speech_config.capabilities_json or []):
            raise ValueError("请先为视频生成任务配置具备 speech_generation 能力的模型")
    return video_config, speech_config, mock_mode


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
        video_config, _, mock_mode = await _media_configs(db, course)
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
            run.progress = progress
            task.progress = progress
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
    concat_file.write_text("\n".join(f"file '{path.as_posix()}'" for path in scene_paths), encoding="utf-8")
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
            status="pending",
        ))
    return scenes


async def execute_video_generation_run(run_id: str) -> None:
    from app.services.course_task_service import artifact_payload, task_jobs

    try:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            if not run or not task:
                return
            script, ppt, course = await _validate_sources(db, task)
            video_config, speech_config, mock_mode = await _media_configs(db, course)
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
            if request_data.get("resolution"):
                settings.resolution = request_data["resolution"]
            if request_data.get("voice_style"):
                settings.voice_style = request_data["voice_style"]
            if "subtitle_enabled" in request_data:
                settings.subtitle_enabled = bool(request_data["subtitle_enabled"])
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

            run.status = "running"
            run.started_at = run.started_at or utcnow()
            run.progress = 3
            task.status = "running"
            task.progress = 3
            task.started_at = task.started_at or utcnow()
            if control:
                control.status = "running"
                control.started_at = control.started_at or utcnow()
            await _emit(db, run, task, "video_generation_started", status="running", progress=3, scene_count=len(scenes))
            await db.commit()

        output_dir = get_settings().storage_root / "generated" / course.id / "video" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        if run.trigger_type == "retry":
            await _restore_retry_assets(task.id, run.id, scenes)

        total = len(scenes)
        semaphore = asyncio.Semaphore(_media_limit(
            video_config, "max_concurrency", get_settings().video_max_concurrency,
        ))
        completed_count = 0
        progress_lock = asyncio.Lock()

        async def process_scene(index: int, scene: VideoGenerationScene) -> Path:
            nonlocal completed_count
            async with semaphore:
                duration = scene.end_seconds - scene.start_seconds
                progress_start = 5 + round((index - 1) / total * 70)
                targeted = bool(target_scene_id and scene.id == target_scene_id)
                old_clip_asset, old_clip_path = await _asset_file(scene.video_asset_id)
                old_audio_asset, old_audio_path = await _asset_file(scene.audio_asset_id)
                _, old_thumb_path = await _asset_file(scene.thumbnail_asset_id)

                regenerate_visual = run.trigger_type in {"initial", "sync_dependencies"}
                regenerate_audio = run.trigger_type in {"initial", "sync_dependencies"}
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

                    audio_path = old_audio_path
                    audio_mime = old_audio_asset.mime_type if old_audio_asset else "audio/wav"
                    speech_provider = old_audio_asset.provider if old_audio_asset else "mock"
                    speech_model = old_audio_asset.model_name if old_audio_asset else "mock-speech"
                    if regenerate_audio or not audio_path:
                        if speech_config and not mock_mode:
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
                            _write_silent_wav(audio_path, duration)
                            audio_mime = "audio/wav"
                            speech_provider = "mock"
                            speech_model = "mock-speech"
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
                            metadata={"provider_job_id": provider_job_id, "visual_prompt": scene.visual_prompt},
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

        scene_results = await asyncio.gather(
            *(process_scene(index, scene) for index, scene in enumerate(scenes, 1)),
            return_exceptions=True,
        )
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
                model_name=video_config.model_name if video_config and not mock_mode else "mock-media",
                prompt_version="video-v1",
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
