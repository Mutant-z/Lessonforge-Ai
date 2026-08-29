from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.database import get_db
from app.models.entities import CourseBlueprint, Material, User
from app.schemas.blueprint import BlueprintUpdate, CourseBlueprintSchema, normalize_blueprint_references
from app.services.quality_service import validate_blueprint
from app.workflows.course_graph import build_blueprint_graph
from app.services.agent_initialization_service import create_initialization_run, start_initialization_run
from app.services.course_task_service import ensure_course_tasks

router = APIRouter(tags=["课程蓝图"])


def output(item: CourseBlueprint) -> dict:
    return {"id": item.id, "course_id": item.course_id, "version": item.version, "content": item.content_json, "content_markdown": item.content_markdown, "status": item.status, "is_locked": item.is_locked, "created_at": item.created_at, "approved_at": item.approved_at, "issues": validate_blueprint(CourseBlueprintSchema.model_validate(item.content_json))}


@router.post("/courses/{course_id}/blueprint/generate", status_code=201)
async def generate_blueprint(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    course.status = "blueprint_generating"
    await db.flush()
    materials = list(await db.scalars(select(Material).where(Material.course_id == course_id, Material.parse_status == "completed")))
    graph = build_blueprint_graph()
    result = await graph.ainvoke(
        {
            "course_id": course.id, "run_id": f"blueprint-{course.id}", "thread_id": f"blueprint-{course.id}",
            "requirements": {"title": course.title, "subject": course.subject, "grade_level": course.grade_level, "audience": course.audience, "duration_minutes": course.duration_minutes, "scenario": course.scenario, "language": course.language, "settings_json": course.settings_json},
            "material_refs": [{"id": item.id, "summary": item.summary, "usage_policy": item.usage_policy} for item in materials],
            "completed_nodes": [], "status": "running",
        },
        config={"configurable": {"thread_id": f"blueprint-{course.id}-{course.current_blueprint_version + 1}"}},
    )
    schema = normalize_blueprint_references(CourseBlueprintSchema.model_validate(result["blueprint"]))
    version = (await db.scalar(select(func.max(CourseBlueprint.version)).where(CourseBlueprint.course_id == course_id)) or 0) + 1
    item = CourseBlueprint(course_id=course_id, version=version, content_json=schema.model_dump(), content_markdown=f"# {course.title}课程蓝图\n\n版本：V{version}", status="review")
    db.add(item)
    course.status = "blueprint_review"
    course.current_blueprint_version = version
    await db.commit()
    await db.refresh(item)
    return output(item)


@router.get("/courses/{course_id}/blueprints")
async def list_blueprints(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    items = await db.scalars(select(CourseBlueprint).where(CourseBlueprint.course_id == course_id).order_by(CourseBlueprint.version.desc()))
    return [output(x) for x in items]


@router.get("/blueprints/{blueprint_id}")
async def get_blueprint(blueprint_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(CourseBlueprint, blueprint_id)
    if not item:
        raise HTTPException(404, "蓝图不存在")
    await owned_course(item.course_id, user, db)
    return output(item)


@router.patch("/blueprints/{blueprint_id}", status_code=201)
async def update_blueprint(blueprint_id: str, payload: BlueprintUpdate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    source = await db.get(CourseBlueprint, blueprint_id)
    if not source:
        raise HTTPException(404, "蓝图不存在")
    course = await owned_course(source.course_id, user, db)
    if source.is_locked:
        raise HTTPException(409, "蓝图已锁定，请创建修订版本")
    version = (await db.scalar(select(func.max(CourseBlueprint.version)).where(CourseBlueprint.course_id == source.course_id)) or 0) + 1
    schema = normalize_blueprint_references(payload.content)
    item = CourseBlueprint(course_id=source.course_id, version=version, content_json=schema.model_dump(), content_markdown=source.content_markdown, status="review", created_by="teacher")
    db.add(item)
    course.current_blueprint_version = version
    course.status = "blueprint_review"
    await db.commit()
    await db.refresh(item)
    return output(item)


@router.post("/blueprints/{blueprint_id}/approve")
async def approve_blueprint(blueprint_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(CourseBlueprint, blueprint_id)
    if not item:
        raise HTTPException(404, "蓝图不存在")
    course = await owned_course(item.course_id, user, db)
    schema = normalize_blueprint_references(CourseBlueprintSchema.model_validate(item.content_json))
    item.content_json = schema.model_dump()
    issues = validate_blueprint(schema)
    if any(x["severity"] == "critical" for x in issues):
        raise HTTPException(409, "蓝图仍有严重规则问题")
    item.status = "approved"
    item.is_locked = True
    item.approved_at = datetime.now(timezone.utc)
    course.current_blueprint_version = item.version
    course.status = "resource_generating"
    # 共享项目记忆：已批准蓝图进入项目记忆（同一事务，先写后 bump）。
    from app.services.project_knowledge_service import bump, index_blueprint

    await index_blueprint(db, item, created_by="teacher")
    await bump(
        db, course.id, f"蓝图 V{item.version} 已确认",
        source_type="blueprint", source_id=item.id, created_by="teacher",
    )
    await ensure_course_tasks(db, course.id)
    run, created = await create_initialization_run(db, course, "blueprint_updated")
    await db.commit()
    if created:
        start_initialization_run(run.id)
    return output(item)


@router.post("/blueprints/{blueprint_id}/revise")
async def revise_blueprint(blueprint_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(CourseBlueprint, blueprint_id)
    if not item:
        raise HTTPException(404, "蓝图不存在")
    course = await owned_course(item.course_id, user, db)
    item.status = "revision_requested"
    course.status = "blueprint_generating"
    await db.commit()
    return output(item)
