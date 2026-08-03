import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import CourseBlueprint, CourseProject, GenerationEvent, GenerationRun, Material
from app.schemas.blueprint import CourseBlueprintSchema
from app.services.agent_initialization_service import create_initialization_run, start_initialization_run
from app.services.course_task_service import ensure_course_tasks
from app.workflows.course_graph import build_blueprint_graph


planning_jobs: dict[str, asyncio.Task] = {}


async def _emit(db, run_id: str, event_type: str, **data):
    db.add(GenerationEvent(run_id=run_id, event_type=event_type, data_json=data))
    await db.commit()


async def execute_blueprint_run(run_id: str):
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        if not run:
            return
        course = await db.get(CourseProject, run.course_id)
        if not course:
            return
        run.status, run.started_at = "running", datetime.now(timezone.utc)
        run.current_node = "requirement_analysis_agent"
        course.status = "blueprint_generating"
        await _emit(db, run_id, "run_started", node="requirement_analysis_agent", progress=5, message="正在核对课程需求")
        try:
            materials = list(await db.scalars(
                select(Material).where(Material.course_id == course.id, Material.parse_status == "completed")
            ))
            result = await build_blueprint_graph().ainvoke(
                {
                    "course_id": course.id,
                    "run_id": run.id,
                    "thread_id": run.thread_id,
                    "requirements": {
                        "title": course.title,
                        "subject": course.subject,
                        "grade_level": course.grade_level,
                        "audience": course.audience,
                        "duration_minutes": course.duration_minutes,
                        "scenario": course.scenario,
                        "language": course.language,
                        "settings_json": course.settings_json,
                    },
                    "material_refs": [
                        {"id": item.id, "summary": item.summary, "usage_policy": item.usage_policy}
                        for item in materials
                    ],
                    "completed_nodes": [],
                    "status": "running",
                },
                config={"configurable": {"thread_id": run.thread_id}},
            )
            run.current_node = "pedagogy_blueprint_agent"
            await _emit(db, run_id, "node_progress", node=run.current_node, progress=80, message="正在形成课程蓝图")
            schema = CourseBlueprintSchema.model_validate(result["blueprint"])
            version = 1
            blueprint = CourseBlueprint(
                course_id=course.id,
                version=version,
                content_json=schema.model_dump(),
                content_markdown=f"# {course.title}课程蓝图\n\n版本：V{version}",
                status="approved",
                is_locked=True,
                approved_at=datetime.now(timezone.utc),
            )
            db.add(blueprint)
            await db.flush()
            await ensure_course_tasks(db, course.id)
            course.status = "resource_generating"
            course.current_blueprint_version = version
            run.status = "completed"
            run.progress = 100
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            await _emit(
                db,
                run_id,
                "project_planning_updated",
                node="project_planning",
                progress=100,
                status="ready",
                message="教学意图已转化为内部规划，正在初始化六个专属 Agent",
            )
            async with SessionLocal() as init_db:
                init_course = await init_db.get(CourseProject, course.id)
                init_run, created = await create_initialization_run(init_db, init_course, "initial")
                await init_db.commit()
            if created:
                start_initialization_run(init_run.id)
        except Exception as exc:
            run.status = "failed"
            run.error_json = {"message": str(exc)}
            run.finished_at = datetime.now(timezone.utc)
            course.status = "failed"
            await db.commit()
            await _emit(db, run_id, "node_failed", node=run.current_node, message=str(exc))
        finally:
            planning_jobs.pop(run_id, None)


def start_blueprint_run(run_id: str):
    task = asyncio.create_task(execute_blueprint_run(run_id))
    planning_jobs[run_id] = task
