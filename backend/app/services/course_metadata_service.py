"""课程项目元数据更新的唯一事务内入口。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import CourseBlueprint, CourseProject, CourseRequirement


@dataclass(frozen=True)
class CourseTitleUpdate:
    previous_title: str
    title: str
    changed: bool
    initialization_run: object | None = None
    initialization_created: bool = False


async def apply_course_title_update(
    db: AsyncSession,
    course: CourseProject,
    title: str,
    *,
    raw_prompt: str = "教师更新项目设置",
    force_context_update: bool = False,
) -> CourseTitleUpdate:
    """在调用方事务中更新课程名并记录需求版本，不 commit。"""
    normalized = str(title or "").strip()
    if not normalized:
        raise ValueError("课程名称不能为空")
    if len(normalized) > 200:
        raise ValueError("课程名称不能超过 200 个字符")
    previous = str(course.title or "")
    if previous == normalized and not force_context_update:
        return CourseTitleUpdate(previous, normalized, False)

    course.title = normalized
    latest = await db.scalar(
        select(CourseRequirement)
        .where(CourseRequirement.course_id == course.id)
        .order_by(CourseRequirement.version.desc())
    )
    settings = dict(course.settings_json or {})
    form = {
        "title": course.title,
        "subject": course.subject,
        "grade_level": course.grade_level,
        "audience": course.audience,
        "duration_minutes": course.duration_minutes,
        "scenario": course.scenario,
        "language": course.language,
        **settings,
    }
    db.add(CourseRequirement(
        course_id=course.id,
        version=(latest.version if latest else 0) + 1,
        form_json=form,
        raw_prompt=raw_prompt,
    ))
    await db.flush()

    init_run = None
    init_created = False
    blueprint = await db.scalar(
        select(CourseBlueprint).where(
            CourseBlueprint.course_id == course.id,
            CourseBlueprint.version == course.current_blueprint_version,
            CourseBlueprint.status == "approved",
        )
    )
    if blueprint:
        from app.services.agent_initialization_service import create_initialization_run

        init_run, init_created = await create_initialization_run(db, course, "requirement_updated")
    return CourseTitleUpdate(previous, normalized, True, init_run, init_created)
