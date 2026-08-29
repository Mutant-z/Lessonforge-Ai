from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.core.database import get_db
from app.models.entities import CourseIntakeSession, Material, MaterialChunk, User
from app.services.material_service import extract_text, safe_filename, save_upload

router = APIRouter(tags=["材料"])


def material_dict(item: Material) -> dict:
    return {key: getattr(item, key) for key in ("id", "course_id", "intake_session_id", "original_filename", "mime_type", "size_bytes", "usage_policy", "parse_status", "summary", "error_message", "created_at")}


async def _save_course_material(course_id: str, file: UploadFile, usage_policy: str, db: AsyncSession) -> Material:
    settings = get_settings()
    path, size, checksum = await save_upload(file, settings.storage_root / "uploads", settings.max_upload_mb * 1024 * 1024)
    material = Material(
        course_id=course_id, original_filename=safe_filename(file.filename or "material"), storage_name=path.name,
        mime_type=file.content_type or "application/octet-stream", size_bytes=size, usage_policy=usage_policy, checksum=checksum,
    )
    db.add(material)
    await db.flush()
    try:
        text, chunks = extract_text(path)
        material.parse_status = "completed"
        material.summary = (
            "图片附件（原图将发送给视觉模型）"
            if material.mime_type.startswith("image/")
            else text[:500] + ("…" if len(text) > 500 else "")
        )
        db.add_all([MaterialChunk(material_id=material.id, chunk_index=i, **chunk) for i, chunk in enumerate(chunks)])
    except Exception as exc:
        material.parse_status = "failed"
        material.error_message = str(exc)
    return material


async def owned_material(item: Material, user: User, db: AsyncSession):
    if item.course_id:
        await owned_course(item.course_id, user, db)
        return
    intake = await db.get(CourseIntakeSession, item.intake_session_id) if item.intake_session_id else None
    if not intake or intake.owner_id != user.id:
        raise HTTPException(404, "材料不存在")


@router.post("/courses/{course_id}/materials", status_code=201)
async def upload_material(
    course_id: str, file: UploadFile = File(...), usage_policy: str = Form("priority_reference"),
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    await owned_course(course_id, user, db)
    material = await _save_course_material(course_id, file, usage_policy, db)
    await db.commit()
    await db.refresh(material)
    return material_dict(material)


@router.post("/courses/{course_id}/chat-attachments", status_code=201)
async def upload_chat_attachment(
    course_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload one file that can be attached to any of the six Agent chats."""
    await owned_course(course_id, user, db)
    material = await _save_course_material(course_id, file, "chat_attachment", db)
    await db.commit()
    await db.refresh(material)
    return material_dict(material)


@router.get("/courses/{course_id}/materials")
async def list_materials(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    items = await db.scalars(select(Material).where(Material.course_id == course_id).order_by(Material.created_at.desc()))
    return [material_dict(item) for item in items]


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(material_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    material = await db.get(Material, material_id)
    if material is None:
        raise HTTPException(404, "材料不存在")
    await owned_material(material, user, db)
    path = get_settings().storage_root / "uploads" / material.storage_name
    path.unlink(missing_ok=True)
    await db.delete(material)
    await db.commit()


@router.patch("/materials/{material_id}/policy")
async def set_policy(material_id: str, usage_policy: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    material = await db.get(Material, material_id)
    if material is None:
        raise HTTPException(404, "材料不存在")
    await owned_material(material, user, db)
    material.usage_policy = usage_policy
    await db.commit()
    return material_dict(material)
