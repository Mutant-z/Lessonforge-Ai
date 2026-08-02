from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.database import get_db
from app.models.entities import CourseProject, CourseRequirement, User
from app.schemas.course import CourseCreate, CourseList, CourseRead, CourseUpdate
from app.services.model_config_service import owned_model_config, resolve_model_config

router = APIRouter(prefix="/courses", tags=["课程"])


@router.post("", response_model=CourseRead, status_code=201)
async def create_course(payload: CourseCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if payload.model_config_id:
        await owned_model_config(db, user.id, payload.model_config_id)
    model_config = await resolve_model_config(db, user.id, payload.model_config_id)
    course = CourseProject(
        owner_id=user.id, title=payload.title, subject=payload.subject, grade_level=payload.grade_level,
        model_config_id=model_config.id if model_config else None,
        audience=payload.audience, duration_minutes=payload.duration_minutes, scenario=payload.scenario,
        language=payload.language,
        settings_json={
            "course_task": payload.course_task, "teaching_objectives": payload.teaching_objectives,
            "key_points": payload.key_points, "difficulty_points": payload.difficulty_points,
            "teaching_method": payload.teaching_method, "style_requirements": payload.style_requirements,
        },
    )
    db.add(course)
    await db.flush()
    db.add(CourseRequirement(course_id=course.id, version=1, form_json=course.settings_json, raw_prompt=payload.raw_prompt))
    await db.commit()
    await db.refresh(course)
    return course


@router.get("", response_model=CourseList)
async def list_courses(
    search: str | None = None, subject: str | None = None, status: str | None = None,
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    filters = [CourseProject.owner_id == user.id, CourseProject.deleted_at.is_(None)]
    if search:
        filters.append(CourseProject.title.contains(search))
    if subject:
        filters.append(CourseProject.subject == subject)
    if status:
        filters.append(CourseProject.status == status)
    total = await db.scalar(select(func.count()).select_from(CourseProject).where(*filters))
    rows = await db.scalars(select(CourseProject).where(*filters).order_by(CourseProject.updated_at.desc()).limit(limit).offset(offset))
    return CourseList(items=list(rows), total=total or 0)


@router.get("/{course_id}", response_model=CourseRead)
async def get_course(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await owned_course(course_id, user, db)


@router.patch("/{course_id}", response_model=CourseRead)
async def update_course(course_id: str, payload: CourseUpdate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, key, value)
    await db.commit()
    await db.refresh(course)
    return course


@router.delete("/{course_id}", status_code=204)
async def delete_course(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    course.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.post("/{course_id}/duplicate", response_model=CourseRead, status_code=201)
async def duplicate_course(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    source = await owned_course(course_id, user, db)
    copy = CourseProject(
        owner_id=user.id, title=f"{source.title}（副本）", subject=source.subject,
        model_config_id=source.model_config_id,
        grade_level=source.grade_level, audience=source.audience, duration_minutes=source.duration_minutes,
        scenario=source.scenario, language=source.language, settings_json=source.settings_json,
    )
    db.add(copy)
    await db.commit()
    await db.refresh(copy)
    return copy


@router.post("/{course_id}/archive", response_model=CourseRead)
async def archive_course(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    course.status = "archived"
    await db.commit()
    await db.refresh(course)
    return course
