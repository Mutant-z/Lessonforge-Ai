import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import CourseBlueprint, CourseProject, CourseTask, GenerationEvent, GenerationRun, Material
from app.schemas.blueprint import CourseBlueprintSchema
from app.services.course_task_service import ensure_course_tasks
from app.services.agent_initialization_service import create_initialization_run, start_initialization_run
from app.workflows.course_graph import build_blueprint_graph

tasks: dict[str, asyncio.Task] = {}


async def emit(db, run_id: str, event_type: str, **data):
    db.add(GenerationEvent(run_id=run_id, event_type=event_type, data_json=data))
    await db.commit()


async def execute_run(run_id: str):
    try:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            if not run:
                return
            course = await db.get(CourseProject, run.course_id)
            blueprint = await db.scalar(select(CourseBlueprint).where(
                CourseBlueprint.course_id == run.course_id,
                CourseBlueprint.version == course.current_blueprint_version,
                CourseBlueprint.status == "approved",
            ))
            if not blueprint:
                raise RuntimeError("课程蓝图尚未确认")
            await ensure_course_tasks(db, course.id)
            init_run, created = await create_initialization_run(db, course, "legacy_full_run")
            run.status, run.started_at = "running", datetime.now(timezone.utc)
            run.current_node = "agent_profile_initializer"
            course.status = "resource_generating"
            await emit(db, run_id, "run_started", node=run.current_node, progress=5)
            await db.commit()
            course_id = course.id
        if created:
            start_initialization_run(init_run.id)

        for _ in range(1800):
            async with SessionLocal() as db:
                current = await db.get(GenerationRun, init_run.id)
                if current and current.status == "completed":
                    break
                if current and current.status == "failed":
                    raise RuntimeError("项目专属 Agent 初始化失败")
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("项目专属 Agent 初始化超时")

        for _ in range(3600):
            async with SessionLocal() as db:
                project_tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course_id)))
                if project_tasks and all(item.current_artifact_id and item.status in {"review", "approved", "stale"} for item in project_tasks):
                    break
                if any(item.status == "failed" for item in project_tasks):
                    raise RuntimeError("至少一个子任务生成失败")
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("子任务生成超时")

        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            course = await db.get(CourseProject, course_id)
            run.status, run.progress, run.finished_at = "waiting_human", 100, datetime.now(timezone.utc)
            run.current_node = "final_teacher_review"
            course.status = "teacher_review"
            await emit(db, run_id, "human_input_required", node="final_review", progress=100, message="请完成教师终审后导出")
            await db.commit()
    except asyncio.CancelledError:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            if run:
                run.status = "cancelled"
                await emit(db, run_id, "run_cancelled", progress=run.progress)
                await db.commit()
    except Exception as exc:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            course = await db.get(CourseProject, run.course_id) if run else None
            if run:
                run.status, run.error_json = "failed", {"message": str(exc)}
                run.finished_at = datetime.now(timezone.utc)
                await emit(db, run_id, "node_failed", node=run.current_node, message=str(exc))
            if course:
                course.status = "needs_attention"
            await db.commit()
    finally:
        tasks.pop(run_id, None)


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
        await emit(db, run_id, "run_started", node="requirement_analysis_agent", progress=5, message="正在核对课程需求")
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
            await emit(db, run_id, "node_progress", node=run.current_node, progress=80, message="正在形成课程蓝图")
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
            await emit(db, run_id, "project_planning_updated", node="project_planning", progress=100, status="ready", message="教学意图已转化为内部规划，正在初始化六个专属 Agent")
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
            await emit(db, run_id, "node_failed", node=run.current_node, message=str(exc))
        finally:
            tasks.pop(run_id, None)


def start_run(run_id: str):
    task = asyncio.create_task(execute_run(run_id))
    tasks[run_id] = task


def start_blueprint_run(run_id: str):
    task = asyncio.create_task(execute_blueprint_run(run_id))
    tasks[run_id] = task
