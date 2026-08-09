from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.core.database import get_db
from app.models.entities import Artifact, ArtifactAsset, CourseBlueprint, FileRecord, User
from app.services.export_service import build_course_package, sha256

router = APIRouter(tags=["导出"])


@router.post("/courses/{course_id}/exports", status_code=201)
async def create_export(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    blueprint = await db.scalar(select(CourseBlueprint).where(CourseBlueprint.course_id == course_id, CourseBlueprint.version == course.current_blueprint_version))
    if not blueprint or blueprint.status != "approved":
        raise HTTPException(409, "课程蓝图尚未确认")
    rows = list(await db.scalars(select(Artifact).where(Artifact.course_id == course_id).order_by(Artifact.version.desc())))
    artifacts = {}
    for row in rows:
        artifacts.setdefault(row.artifact_type, {
            "id": row.id, "version": row.version, "content_json": row.content_json,
            "content_markdown": row.content_markdown, "source_versions_json": row.source_versions_json,
            "status": row.status,
        })
    required = {"lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim"}
    if missing := required - artifacts.keys():
        raise HTTPException(409, f"缺少资源：{', '.join(sorted(missing))}")
    referenced_asset_ids = {
        visual.get("asset_id")
        for section in artifacts["exercise"]["content_json"].get("sections", [])
        for block in section.get("blocks", [])
        if block.get("kind") == "question_group"
        for stimulus in block.get("stimuli", [])
        if (visual := stimulus.get("visual")) and visual.get("asset_id")
    }
    exercise_assets = list(await db.scalars(select(ArtifactAsset).where(
        ArtifactAsset.id.in_(referenced_asset_ids),
        ArtifactAsset.course_id == course_id,
        ArtifactAsset.owner_id == user.id,
        ArtifactAsset.status == "approved",
    ))) if referenced_asset_ids else []
    artifacts["exercise"]["asset_paths"] = {
        asset.id: str((get_settings().storage_root / (asset.preview_relative_path or asset.relative_path)).resolve())
        for asset in exercise_assets
    }
    video = artifacts.get("video_generation")
    if video and video.get("status") == "approved":
        video_asset_ids = {
            asset_id
            for scene in video["content_json"].get("scenes", [])
            for asset_id in (scene.get("video_asset_id"), scene.get("audio_asset_id"), scene.get("thumbnail_asset_id"))
            if asset_id
        } | {
            asset_id
            for asset_id in (video["content_json"].get("outputs") or {}).values()
            if isinstance(asset_id, str) and asset_id
        }
        video_assets = list(await db.scalars(select(ArtifactAsset).where(
            ArtifactAsset.id.in_(video_asset_ids),
            ArtifactAsset.course_id == course_id,
            ArtifactAsset.owner_id == user.id,
            ArtifactAsset.status == "approved",
        ))) if video_asset_ids else []
        video["asset_paths"] = {
            asset.id: str((get_settings().storage_root / asset.relative_path).resolve())
            for asset in video_assets
        }
    output_dir = get_settings().storage_root / "generated" / course.id
    zip_path, manifest = build_course_package(course.id, course.title, blueprint.content_json, blueprint.version, artifacts, output_dir)
    relative = str(zip_path.relative_to(get_settings().storage_root))
    record = FileRecord(owner_id=user.id, course_id=course.id, file_type="course_package", relative_path=relative, original_filename=zip_path.name, size_bytes=zip_path.stat().st_size, checksum=sha256(zip_path))
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "filename": record.original_filename, "size_bytes": record.size_bytes, "checksum": record.checksum, "manifest": manifest, "download_url": f"/api/v1/exports/{record.id}/download"}


@router.get("/exports/{export_id}/download")
async def download(export_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    record = await db.get(FileRecord, export_id)
    if not record:
        raise HTTPException(404, "导出文件不存在")
    await owned_course(record.course_id, user, db)
    path = (get_settings().storage_root / record.relative_path).resolve()
    root = get_settings().storage_root.resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(404, "导出文件已不存在")
    return FileResponse(path, filename=record.original_filename, media_type="application/zip")
