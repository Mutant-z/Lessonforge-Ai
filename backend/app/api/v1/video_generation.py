from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_asset_token, decode_asset_token
from app.models.entities import ArtifactAsset, CourseProject, CourseTask, User, VideoGenerationQuote, VideoSceneJob
from app.schemas.video import (
    SeedanceSceneRegenerateRequest,
    VideoGenerationMetricsResponse,
    VideoGenerationQuoteRequest,
    VideoGenerationQuoteResponse,
)
from app.services.course_task_service import start_task_run
from app.services.seedance_video_generation_service import (
    create_seedance_scene_regeneration_run,
    create_video_generation_quote,
)


router = APIRouter(tags=["视频生成"])


async def _owned_video_asset(asset_id: str, user: User, db: AsyncSession) -> tuple[ArtifactAsset, Path]:
    asset = await db.get(ArtifactAsset, asset_id)
    if not asset or asset.owner_id != user.id or asset.asset_type not in {
        "video_clip", "video_preview", "video_final", "audio_narration", "subtitle", "thumbnail",
    }:
        raise HTTPException(404, "视频资源不存在")
    await owned_course(asset.course_id, user, db)
    if asset.status not in {"preview", "approved"}:
        raise HTTPException(409, "视频资源尚未准备完成")
    root = get_settings().storage_root.resolve()
    path = (root / asset.relative_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "视频资源文件不存在")
    return asset, path


@router.post("/courses/{course_id}/tasks/video_generation/scenes/{scene_id}/regenerate", status_code=202)
async def regenerate_video_scene(
    course_id: str,
    scene_id: str,
    payload: SeedanceSceneRegenerateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await owned_course(course_id, user, db)
    from app.models.entities import CourseTask
    from sqlalchemy import select

    task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == course_id,
        CourseTask.task_type == "video_generation",
    ))
    if not task:
        raise HTTPException(404, "视频生成任务不存在")
    try:
        run = await create_seedance_scene_regeneration_run(db, task, scene_id, payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"run_id": run.id, "task_id": task.id, "scene_id": scene_id, "status": "queued"}


@router.post(
    "/courses/{course_id}/tasks/video_generation/quotes",
    response_model=VideoGenerationQuoteResponse,
)
async def quote_video_generation(
    course_id: str,
    payload: VideoGenerationQuoteRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await owned_course(course_id, user, db)
    from sqlalchemy import select
    task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == course_id, CourseTask.task_type == "video_generation",
    ))
    if not task:
        raise HTTPException(404, "视频生成任务不存在")
    try:
        quote = await create_video_generation_quote(db, task, user.id, payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    return quote


@router.get(
    "/courses/{course_id}/tasks/video_generation/metrics",
    response_model=VideoGenerationMetricsResponse,
)
async def video_generation_metrics(
    course_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return course-scoped, audit-table-derived Seedance operating metrics."""
    await owned_course(course_id, user, db)
    jobs = list(await db.scalars(select(VideoSceneJob).where(
        VideoSceneJob.course_id == course_id,
        VideoSceneJob.scene_id != "__run__",
        VideoSceneJob.operation == "generate",
    )))
    terminal = [job for job in jobs if job.status in {"completed", "qa_failed", "failed"}]
    completed = [job for job in terminal if job.status == "completed"]
    scene_attempts: dict[tuple[str, str], int] = {}
    for job in jobs:
        key = (job.generation_run_id, job.scene_id)
        scene_attempts[key] = max(scene_attempts.get(key, 0), int(job.attempt or 1))
    retried = sum(1 for attempt in scene_attempts.values() if attempt > 1)

    actual_cost = sum(int(job.actual_cost_fen or 0) for job in jobs)
    estimated_cost = sum(int(job.estimated_cost_fen or 0) for job in jobs)
    billable_duration = sum(
        float((job.input_json or {}).get("duration_seconds") or 0)
        for job in jobs if int(job.actual_cost_fen or 0) > 0
    )
    qa_checked = [job for job in terminal if (job.qa_json or {}).get("status")]
    qa_failed = [job for job in qa_checked if (job.qa_json or {}).get("status") != "passed"]

    quotes = list(await db.scalars(select(VideoGenerationQuote).where(
        VideoGenerationQuote.course_id == course_id,
    )))
    quoted_scenes = [scene for quote in quotes for scene in (quote.scenes_json or [])]
    reusable = sum(1 for scene in quoted_scenes if scene.get("reusable"))

    return VideoGenerationMetricsResponse(
        scene_attempt_count=len(terminal),
        completed_attempt_count=len(completed),
        generation_success_rate=len(completed) / len(terminal) if terminal else 0,
        retried_scene_count=retried,
        scene_retry_rate=retried / len(scene_attempts) if scene_attempts else 0,
        actual_cost_fen=actual_cost,
        estimated_cost_fen=estimated_cost,
        estimate_actual_deviation_rate=(actual_cost - estimated_cost) / estimated_cost if estimated_cost else 0,
        billable_duration_seconds=billable_duration,
        average_cost_fen_per_minute=actual_cost / (billable_duration / 60) if billable_duration else 0,
        qa_checked_attempt_count=len(qa_checked),
        qa_failed_attempt_count=len(qa_failed),
        asr_fact_failure_rate=len(qa_failed) / len(qa_checked) if qa_checked else 0,
        quoted_scene_count=len(quoted_scenes),
        reusable_scene_count=reusable,
        cache_reuse_rate=reusable / len(quoted_scenes) if quoted_scenes else 0,
    )


def _range_response(path: Path, mime_type: str, range_header: str | None):
    size = path.stat().st_size
    if not range_header:
        return FileResponse(
            path,
            media_type=mime_type,
            headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
        )
    if not range_header.startswith("bytes=") or "," in range_header:
        raise HTTPException(416, "不支持的 Range 请求")
    value = range_header.removeprefix("bytes=")
    start_text, _, end_text = value.partition("-")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            suffix = int(end_text)
            start = max(0, size - suffix)
            end = size - 1
    except ValueError as exc:
        raise HTTPException(416, "Range 格式不正确") from exc
    if start < 0 or start >= size or end < start:
        raise HTTPException(416, "Range 超出文件范围")
    end = min(end, size - 1)
    length = end - start + 1

    def iterator():
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    return StreamingResponse(
        iterator(),
        status_code=206,
        media_type=mime_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/video-assets/{asset_id}/stream")
async def stream_video_asset(
    asset_id: str,
    token: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    user_id = decode_asset_token(token, asset_id)
    asset = await db.get(ArtifactAsset, asset_id)
    course = await db.get(CourseProject, asset.course_id) if asset else None
    if not asset or asset.owner_id != user_id or not course or course.owner_id != user_id:
        raise HTTPException(404, "视频资源不存在")
    if asset.status not in {"preview", "approved"}:
        raise HTTPException(409, "视频资源尚未准备完成")
    root = get_settings().storage_root.resolve()
    path = (root / asset.relative_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "视频资源文件不存在")
    return _range_response(path, asset.mime_type, range_header)


@router.post("/video-assets/{asset_id}/token")
async def video_asset_token(
    asset_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_video_asset(asset_id, user, db)
    return {"token": create_asset_token(user.id, asset_id), "expires_in": 900}


@router.get("/video-assets/{asset_id}/download")
async def download_video_asset(
    asset_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    asset, path = await _owned_video_asset(asset_id, user, db)
    return FileResponse(path, media_type=asset.mime_type, filename=path.name)
