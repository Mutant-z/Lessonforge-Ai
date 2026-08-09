from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_asset_token, decode_asset_token
from app.models.entities import ArtifactAsset, CourseProject, User
from app.schemas.video import VideoSceneRegenerateRequest
from app.services.course_task_service import start_task_run
from app.services.video_generation_service import create_video_scene_regeneration_run


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
    payload: VideoSceneRegenerateRequest,
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
        run = await create_video_scene_regeneration_run(db, task, scene_id, payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"run_id": run.id, "task_id": task.id, "scene_id": scene_id, "status": "queued"}


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
