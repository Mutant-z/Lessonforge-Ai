import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.generators import to_markdown
from app.core.database import SessionLocal
from app.models.entities import Artifact, CourseBlueprint, CourseProject, GenerationEvent, GenerationRun, GenerationStep, Material, QualityIssue, QualityReport
from app.schemas.blueprint import CourseBlueprintSchema
from app.services.quality_service import validate_resources
from app.services.model_config_service import resolve_provider, resolved_model_name
from app.services.course_task_service import ensure_course_tasks, schedule_ready_tasks
from app.workflows.course_graph import build_blueprint_graph, build_course_graph

tasks: dict[str, asyncio.Task] = {}
ARTIFACT_KEYS = {"lesson_plan_agent": "lesson_plan", "ppt_agent": "ppt", "task_sheet_agent": "task_sheet", "exercise_agent": "exercise", "video_script_agent": "video_script", "verbatim_agent": "verbatim"}


async def emit(db, run_id: str, event_type: str, **data):
    db.add(GenerationEvent(run_id=run_id, event_type=event_type, data_json=data))
    await db.commit()


async def execute_run(run_id: str):
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        if not run:
            return
        course = await db.get(CourseProject, run.course_id)
        provider, selected_config = await resolve_provider(db, course.owner_id, course.model_config_id)
        generation_model_name = resolved_model_name(provider, selected_config)
        blueprint = await db.scalar(select(CourseBlueprint).where(CourseBlueprint.course_id == run.course_id, CourseBlueprint.version == course.current_blueprint_version))
        if not blueprint or blueprint.status != "approved":
            run.status = "failed"
            run.error_json = {"message": "课程蓝图尚未确认"}
            await emit(db, run_id, "node_failed", node="supervisor", message="课程蓝图尚未确认")
            return
        run.status, run.started_at = "running", datetime.now(timezone.utc)
        course.status = "resource_generating"
        await emit(db, run_id, "run_started", node="supervisor", progress=0)
        graph = build_course_graph()
        state = {"course_id": course.id, "run_id": run.id, "thread_id": run.thread_id, "blueprint": blueprint.content_json, "blueprint_version": blueprint.version, "blueprint_approved": True, "completed_nodes": [], "locked_paths": [], "retry_counts": {}, "status": "running"}
        complete_data: dict[str, dict] = {}
        try:
            completed = 0
            async for update in graph.astream(state, config={"configurable": {"thread_id": run.thread_id}}, stream_mode="updates"):
                for node, values in update.items():
                    run.current_node = node
                    await emit(db, run_id, "node_started", node=node, progress=min(90, completed * 14))
                    if node in ARTIFACT_KEYS:
                        key = ARTIFACT_KEYS[node]
                        content = values[key]
                        complete_data[key] = content
                        artifact = Artifact(course_id=course.id, artifact_type=key, version=1, blueprint_version=blueprint.version, content_json=content, content_markdown=to_markdown(key, _validate_artifact(key, content)), model_name=generation_model_name, prompt_version="v1")
                        db.add(artifact)
                        await db.flush()
                        db.add(GenerationStep(run_id=run_id, node_name=node, status="completed", output_ref=artifact.id))
                    completed += 1
                    run.progress = min(95, completed * 14)
                    await emit(db, run_id, "node_completed", node=node, progress=run.progress)
            course.status = "quality_checking"
            issues = validate_resources(CourseBlueprintSchema.model_validate(blueprint.content_json), complete_data)
            report = QualityReport(course_id=course.id, run_id=run.id, score=max(0, 100 - len(issues) * 8), dimensions_json={"structure": 5, "alignment": 5 if not issues else 4}, summary="已完成 Schema、引用、时长、目标覆盖和题目结构检查。")
            db.add(report)
            await db.flush()
            for item in issues:
                db.add(QualityIssue(report_id=report.id, **item))
                await emit(db, run_id, "quality_issue_found", **item)
            quality_markdown = "# 质量报告\n\n" + report.summary + f"\n\n- 综合分数：{report.score}\n- 问题数量：{len(issues)}"
            citation_refs = blueprint.content_json.get("source_refs", [])
            citation_markdown = "# 引用来源\n\n" + ("\n".join(f"- {ref}" for ref in citation_refs) if citation_refs else "本课程未引用上传材料片段。")
            db.add_all([
                Artifact(course_id=course.id, artifact_type="quality_report", version=1, blueprint_version=blueprint.version, content_json={"score": report.score, "summary": report.summary, "issues": issues}, content_markdown=quality_markdown, model_name="rules+mock", prompt_version="v1"),
                Artifact(course_id=course.id, artifact_type="citation_report", version=1, blueprint_version=blueprint.version, content_json={"source_refs": citation_refs}, content_markdown=citation_markdown, model_name="deterministic", prompt_version="v1"),
            ])
            run.status, run.progress, run.finished_at = "waiting_human", 100, datetime.now(timezone.utc)
            course.status = "teacher_review"
            await emit(db, run_id, "human_input_required", node="final_review", progress=100, message="请完成教师终审后导出")
        except asyncio.CancelledError:
            run.status = "cancelled"
            await emit(db, run_id, "run_cancelled", progress=run.progress)
        except Exception as exc:
            run.status, run.error_json = "failed", {"message": str(exc)}
            course.status = "failed"
            await emit(db, run_id, "node_failed", node=run.current_node, message=str(exc))
        finally:
            await db.commit()
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
            await emit(db, run_id, "project_planning_updated", node="project_planning", progress=100, status="ready", message="教学意图已转化为内部规划，任务 Agent 开始工作")
            await schedule_ready_tasks(course.id)
        except Exception as exc:
            run.status = "failed"
            run.error_json = {"message": str(exc)}
            run.finished_at = datetime.now(timezone.utc)
            course.status = "failed"
            await db.commit()
            await emit(db, run_id, "node_failed", node=run.current_node, message=str(exc))
        finally:
            tasks.pop(run_id, None)


def _validate_artifact(key: str, content: dict):
    from app.schemas.artifact import ExerciseContent, LessonPlanContent, PPTContent, TaskSheetContent, VerbatimContent, VideoScriptContent
    return {"lesson_plan": LessonPlanContent, "ppt": PPTContent, "task_sheet": TaskSheetContent, "exercise": ExerciseContent, "video_script": VideoScriptContent, "verbatim": VerbatimContent}[key].model_validate(content)


def start_run(run_id: str):
    task = asyncio.create_task(execute_run(run_id))
    tasks[run_id] = task


def start_blueprint_run(run_id: str):
    task = asyncio.create_task(execute_blueprint_run(run_id))
    tasks[run_id] = task
