from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.core.database import get_db
from app.models.entities import Artifact, CourseBlueprint, FileRecord, User
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
        artifacts.setdefault(row.artifact_type, {"version": row.version, "content_json": row.content_json, "content_markdown": row.content_markdown})
    required = {"lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim"}
    if missing := required - artifacts.keys():
        raise HTTPException(409, f"缺少资源：{', '.join(sorted(missing))}")
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

