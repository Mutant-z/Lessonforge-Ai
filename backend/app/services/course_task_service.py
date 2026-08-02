import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from app.agents.generators import (
    generate_structured,
    make_exercises,
    make_lesson_plan,
    make_ppt,
    make_task_sheet,
    make_verbatim,
    make_video_script,
    to_markdown,
)
from app.core.database import SessionLocal
from app.models.entities import (
    AgentMessage,
    AgentChatSession,
    Artifact,
    ArtifactLock,
    CourseBlueprint,
    CourseProject,
    CourseRequirement,
    CourseTask,
    GenerationEvent,
    GenerationRun,
    QualityIssue,
    QualityReport,
)
from app.providers.llm.base import LLMProviderError
from app.providers.llm.mock import MockProvider
from app.schemas.artifact import (
    AgentArtifactRevision,
    ExerciseContent,
    LessonPlanContent,
    PPTContent,
    TaskSheetContent,
    VerbatimContent,
    VideoScriptContent,
)
from app.schemas.blueprint import CourseBlueprintSchema
from app.services.model_config_service import resolve_provider, resolved_model_name
from app.services.quality_service import validate_resources

logger = logging.getLogger(__name__)

TASK_SPECS = (
    ("lesson_plan", "教学设计", "教学设计 Agent", "lesson_plan_agent", []),
    ("ppt", "PPT 课件", "PPT Agent", "ppt_agent", []),
    ("task_sheet", "学习任务单", "任务单 Agent", "task_sheet_agent", []),
    ("exercise", "课后练习", "练习 Agent", "exercise_agent", []),
    ("video_script", "视频脚本", "视频脚本 Agent", "video_script_agent", ["ppt"]),
    ("verbatim", "教师逐字稿", "逐字稿 Agent", "verbatim_agent", ["ppt", "video_script"]),
)
TASK_SPEC_BY_TYPE = {item[0]: item for item in TASK_SPECS}
TASK_SCHEMAS = {
    "lesson_plan": LessonPlanContent,
    "ppt": PPTContent,
    "task_sheet": TaskSheetContent,
    "exercise": ExerciseContent,
    "video_script": VideoScriptContent,
    "verbatim": VerbatimContent,
}

task_jobs: dict[str, asyncio.Task] = {}


def utcnow():
    return datetime.now(timezone.utc)


def artifact_payload(item: Artifact | None) -> dict | None:
    if not item:
        return None
    payload = {
        key: getattr(item, key)
        for key in (
            "id", "course_id", "artifact_type", "version", "blueprint_version",
            "content_json", "content_markdown", "status", "model_name", "prompt_version",
            "is_locked", "change_summary", "source_versions_json", "created_at", "approved_at",
        )
    }
    for key in ("created_at", "approved_at"):
        if payload[key] is not None:
            payload[key] = payload[key].isoformat()
    return payload


async def task_payload(db, item: CourseTask) -> dict:
    artifact = await db.get(Artifact, item.current_artifact_id) if item.current_artifact_id else None
    spec = TASK_SPEC_BY_TYPE[item.task_type]
    stale_dependencies = []
    if artifact:
        for dependency in item.dependency_types_json:
            latest_version = await db.scalar(select(func.max(Artifact.version)).where(
                Artifact.course_id == item.course_id,
                Artifact.artifact_type == dependency,
            ))
            if latest_version and (artifact.source_versions_json or {}).get(dependency) != latest_version:
                stale_dependencies.append(dependency)
    return {
        "id": item.id,
        "course_id": item.course_id,
        "task_type": item.task_type,
        "display_name": spec[1],
        "agent_name": spec[2],
        "agent_type": item.agent_type,
        "display_order": item.display_order,
        "status": item.status,
        "progress": item.progress,
        "dependency_types": item.dependency_types_json,
        "stale_dependencies": stale_dependencies,
        "current_artifact": artifact_payload(artifact),
        "active_run_id": item.active_run_id,
        "error": item.error_json,
        "updated_at": item.updated_at,
    }


async def ensure_course_tasks(db, course_id: str) -> list[CourseTask]:
    existing = list(await db.scalars(
        select(CourseTask).where(CourseTask.course_id == course_id).order_by(CourseTask.display_order)
    ))
    by_type = {item.task_type: item for item in existing}
    for order, (task_type, _, _, agent_type, dependencies) in enumerate(TASK_SPECS, 1):
        if task_type in by_type:
            continue
        artifact = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id,
            Artifact.artifact_type == task_type,
        ).order_by(Artifact.version.desc()))
        status = "approved" if artifact and artifact.status == "approved" else "review" if artifact else "waiting_dependency"
        task = CourseTask(
            course_id=course_id,
            task_type=task_type,
            agent_type=agent_type,
            display_order=order,
            status=status,
            progress=100 if artifact else 0,
            dependency_types_json=dependencies,
            current_artifact_id=artifact.id if artifact else None,
            completed_at=artifact.created_at if artifact else None,
        )
        db.add(task)
        by_type[task_type] = task
    await db.flush()
    return sorted(by_type.values(), key=lambda item: item.display_order)


async def _latest_artifact(db, course_id: str, task_type: str) -> Artifact | None:
    return await db.scalar(select(Artifact).where(
        Artifact.course_id == course_id,
        Artifact.artifact_type == task_type,
    ).order_by(Artifact.version.desc()))


async def _emit(db, run: GenerationRun, event_type: str, task: CourseTask | None = None, **data):
    payload = {
        "course_id": run.course_id,
        "run_id": run.id,
        "task_id": task.id if task else None,
        "task_type": task.task_type if task else None,
        **data,
    }
    db.add(GenerationEvent(run_id=run.id, event_type=event_type, data_json=payload))


async def create_task_run(db, task: CourseTask, trigger_type: str, user_message: AgentMessage | None = None) -> GenerationRun:
    if task.active_run_id or task.status in {"queued", "running"}:
        raise ValueError("当前任务已有 Agent 正在运行")
    run = GenerationRun(
        course_id=task.course_id,
        course_task_id=task.id,
        thread_id=str(uuid4()),
        run_type="task",
        trigger_type=trigger_type,
        status="queued",
        current_node=task.agent_type,
    )
    db.add(run)
    await db.flush()
    task.active_run_id = run.id
    task.status = "queued"
    task.progress = 0
    task.error_json = None
    if user_message:
        user_message.task_id = task.id
        user_message.run_id = run.id
        user_message.status = "pending"
    await _emit(db, run, "task_status_changed", task, status="queued", progress=0)
    return run


def start_task_run(run_id: str):
    job = asyncio.create_task(execute_task_run(run_id))
    task_jobs[run_id] = job


async def schedule_ready_tasks(course_id: str):
    run_ids: list[str] = []
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        if not course:
            return
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        if not blueprint or blueprint.status != "approved":
            return
        items = await ensure_course_tasks(db, course_id)
        latest = {kind: await _latest_artifact(db, course_id, kind) for kind, *_ in TASK_SPECS}
        for item in items:
            if item.status != "waiting_dependency" or item.active_run_id or item.current_artifact_id:
                continue
            if all(latest.get(dep) for dep in item.dependency_types_json):
                run = await create_task_run(db, item, "initial")
                run_ids.append(run.id)
        if run_ids:
            course.status = "resource_generating"
        await db.commit()
    for run_id in run_ids:
        start_task_run(run_id)


async def _generate_initial(db, course: CourseProject, task: CourseTask, blueprint: CourseBlueprint):
    bp = CourseBlueprintSchema.model_validate(blueprint.content_json)
    kind = task.task_type
    if kind == "lesson_plan":
        mock = make_lesson_plan(bp)
        value = await generate_structured("Lesson Plan Agent", {"course_id": course.id, "blueprint": blueprint.content_json}, LessonPlanContent, mock)
    elif kind == "ppt":
        mock = make_ppt(bp)
        value = await generate_structured("PPT Agent", {"course_id": course.id, "blueprint": blueprint.content_json}, PPTContent, mock)
    elif kind == "task_sheet":
        mock = make_task_sheet(bp)
        value = await generate_structured("Task Sheet Agent", {"course_id": course.id, "blueprint": blueprint.content_json}, TaskSheetContent, mock)
    elif kind == "exercise":
        mock = make_exercises(bp)
        value = await generate_structured("Exercise Agent", {"course_id": course.id, "blueprint": blueprint.content_json}, ExerciseContent, mock)
    elif kind == "video_script":
        ppt_artifact = await _latest_artifact(db, course.id, "ppt")
        if not ppt_artifact:
            raise RuntimeError("PPT 尚未生成")
        ppt = PPTContent.model_validate(ppt_artifact.content_json)
        mock = make_video_script(bp, ppt)
        value = await generate_structured("Video Script Agent", {"course_id": course.id, "blueprint": blueprint.content_json, "ppt": ppt_artifact.content_json}, VideoScriptContent, mock)
    else:
        ppt_artifact = await _latest_artifact(db, course.id, "ppt")
        script_artifact = await _latest_artifact(db, course.id, "video_script")
        if not ppt_artifact or not script_artifact:
            raise RuntimeError("PPT 或视频脚本尚未生成")
        ppt = PPTContent.model_validate(ppt_artifact.content_json)
        script = VideoScriptContent.model_validate(script_artifact.content_json)
        mock = make_verbatim(bp, ppt, script)
        value = await generate_structured("Verbatim Agent", {"course_id": course.id, "blueprint": blueprint.content_json, "ppt": ppt_artifact.content_json, "video_script": script_artifact.content_json}, VerbatimContent, mock)
    return value


def _locked_value(content: dict, path: str):
    if path in {"", "$"}:
        return content
    value = content
    for part in [part for part in re.split(r"\.|\[|\]", path.removeprefix("$.")) if part]:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, list):
            value = next((entry for entry in value if isinstance(entry, dict) and entry.get("id") == part), None)
        else:
            return None
    return value


async def _generate_revision(db, course: CourseProject, task: CourseTask, run: GenerationRun, source: Artifact):
    message = await db.scalar(select(AgentMessage).where(
        AgentMessage.run_id == run.id,
        AgentMessage.role == "user",
    ).order_by(AgentMessage.created_at.desc()))
    if not message:
        raise RuntimeError("未找到本次教师修改指令")
    locks = list(await db.scalars(select(ArtifactLock).where(ArtifactLock.artifact_id == source.id)))
    if any(lock.json_path in {"", "$"} for lock in locks):
        raise RuntimeError("当前任务文件已整体锁定")
    chat_session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == task.task_type,
    ))
    provider, config = await resolve_provider(
        db,
        course.owner_id,
        (chat_session.model_config_id if chat_session else None) or course.model_config_id,
    )
    version = source.version + 1
    if isinstance(provider, MockProvider):
        content = dict(source.content_json)
        content["revision_note"] = {"instruction": message.content}
        revision = AgentArtifactRevision(
            content_json=content,
            content_markdown=source.content_markdown + f"\n\n> 教师修改指令：{message.content}",
            assistant_reply=f"已根据你的要求创建{TASK_SPEC_BY_TYPE[task.task_type][1]} V{version}，原版本仍可在版本历史中恢复。",
        )
    else:
        history = list(await db.scalars(select(AgentMessage).where(
            AgentMessage.course_id == course.id,
            AgentMessage.module_type == task.task_type,
        ).order_by(AgentMessage.created_at.desc()).limit(12)))
        schema = TASK_SCHEMAS[task.task_type]
        system = (
            f"你是 LessonForge AI 的{TASK_SPEC_BY_TYPE[task.task_type][2]}。"
            "仅修改当前任务文件，不得修改锁定内容，不得捏造引用或质量证据。"
            "只返回符合输出 Schema 的 JSON，不展示隐藏推理。"
        )
        prompt = (
            "当前结构化内容：\n" + json.dumps(source.content_json, ensure_ascii=False)
            + "\n最近对话：\n" + json.dumps([{"role": x.role, "content": x.content} for x in reversed(history)], ensure_ascii=False)
            + "\n锁定路径：\n" + json.dumps([x.json_path for x in locks], ensure_ascii=False)
            + "\n教师指令：\n" + message.content
            + "\ncontent_json 必须符合：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        )
        revision = await provider.structured(system, prompt, AgentArtifactRevision)
    validated = TASK_SCHEMAS[task.task_type].model_validate(revision.content_json).model_dump()
    for lock in locks:
        if _locked_value(source.content_json, lock.json_path) != _locked_value(validated, lock.json_path):
            raise RuntimeError(f"模型修改了已锁定内容：{lock.json_path}")
    return revision, validated, message, resolved_model_name(provider, config)


async def _source_versions(db, task: CourseTask) -> dict[str, int]:
    result = {}
    for dependency in task.dependency_types_json:
        artifact = await _latest_artifact(db, task.course_id, dependency)
        if artifact:
            result[dependency] = artifact.version
    return result


async def _mark_dependents_stale(db, source_task: CourseTask, source_version: int):
    tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == source_task.course_id)))
    stale_tasks = []
    for task in tasks:
        if source_task.task_type not in task.dependency_types_json or not task.current_artifact_id:
            continue
        artifact = await db.get(Artifact, task.current_artifact_id)
        if artifact and (artifact.source_versions_json or {}).get(source_task.task_type) != source_version:
            task.status = "stale"
            task.error_json = None
            stale_tasks.append(task)
    return stale_tasks


async def register_artifact_version(db, artifact: Artifact):
    """Make a teacher-created or legacy Agent version the task's current file."""
    task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == artifact.course_id,
        CourseTask.task_type == artifact.artifact_type,
    ))
    if not task:
        return
    task.current_artifact_id = artifact.id
    task.status = "review" if artifact.status != "approved" else "approved"
    task.progress = 100
    task.error_json = None
    task.completed_at = utcnow()
    await _mark_dependents_stale(db, task, artifact.version)


async def _refresh_quality(db, course: CourseProject, blueprint: CourseBlueprint):
    resources = {}
    for task_type, *_ in TASK_SPECS:
        artifact = await _latest_artifact(db, course.id, task_type)
        if not artifact:
            return
        resources[task_type] = artifact.content_json
    issues = validate_resources(CourseBlueprintSchema.model_validate(blueprint.content_json), resources)
    report = QualityReport(
        course_id=course.id,
        score=max(0, 100 - len(issues) * 8),
        dimensions_json={"structure": 5, "alignment": 5 if not issues else 4},
        summary="已完成结构、引用、时长、目标覆盖和题目结构检查。",
    )
    db.add(report)
    await db.flush()
    for issue in issues:
        db.add(QualityIssue(report_id=report.id, **issue))
    for kind, content, markdown, model in (
        ("quality_report", {"score": report.score, "summary": report.summary, "issues": issues}, f"# 质量报告\n\n{report.summary}\n\n- 综合分数：{report.score}\n- 问题数量：{len(issues)}", "rules"),
        ("citation_report", {"source_refs": blueprint.content_json.get("source_refs", [])}, "# 引用来源\n\n" + ("\n".join(f"- {ref}" for ref in blueprint.content_json.get("source_refs", [])) or "本课程未引用上传材料片段。"), "deterministic"),
    ):
        version = (await db.scalar(select(func.max(Artifact.version)).where(Artifact.course_id == course.id, Artifact.artifact_type == kind)) or 0) + 1
        db.add(Artifact(course_id=course.id, artifact_type=kind, version=version, blueprint_version=blueprint.version, content_json=content, content_markdown=markdown, model_name=model, prompt_version="v2", change_summary="随任务文件自动更新"))


async def _refresh_course_status(db, course: CourseProject):
    tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course.id)))
    statuses = {item.status for item in tasks}
    if tasks and statuses == {"approved"}:
        course.status = "completed"
    elif "failed" in statuses:
        course.status = "needs_attention"
    elif statuses & {"queued", "running", "waiting_dependency"}:
        course.status = "resource_generating"
    else:
        course.status = "teacher_review"


async def execute_task_run(run_id: str):
    try:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            course = await db.get(CourseProject, run.course_id) if run else None
            if not run or not task or not course:
                return
            blueprint = await db.scalar(select(CourseBlueprint).where(
                CourseBlueprint.course_id == course.id,
                CourseBlueprint.version == course.current_blueprint_version,
            ))
            if not blueprint or blueprint.status != "approved":
                raise RuntimeError("课程内部规划尚未完成")
            run.status = "running"
            run.started_at = utcnow()
            task.status = "running"
            task.progress = 12
            task.started_at = task.started_at or utcnow()
            await _emit(db, run, "task_status_changed", task, status="running", progress=12)
            await _emit(db, run, "task_progress_updated", task, status="running", progress=35, phase="正在生成任务文件")
            await db.commit()

            source = await _latest_artifact(db, course.id, task.task_type)
            revision = None
            user_message = None
            if run.trigger_type == "message":
                if not source:
                    raise RuntimeError("任务文件尚未生成")
                revision, validated, user_message, model_name = await _generate_revision(db, course, task, run, source)
                content = validated
                markdown = revision.content_markdown
                change_summary = f"Agent 对话修改：{user_message.content[:80]}"
            else:
                value = await _generate_initial(db, course, task, blueprint)
                content = value.model_dump()
                markdown = to_markdown(task.task_type, value)
                chat_session = await db.scalar(select(AgentChatSession).where(
                    AgentChatSession.course_id == course.id,
                    AgentChatSession.module_type == task.task_type,
                ))
                provider, config = await resolve_provider(
                    db,
                    course.owner_id,
                    (chat_session.model_config_id if chat_session else None) or course.model_config_id,
                )
                model_name = resolved_model_name(provider, config)
                change_summary = "依赖同步生成" if run.trigger_type == "sync_dependencies" else "首次生成"

            await _emit(db, run, "task_progress_updated", task, status="running", progress=82, phase="正在校验并保存新版本")
            version = (await db.scalar(select(func.max(Artifact.version)).where(
                Artifact.course_id == course.id,
                Artifact.artifact_type == task.task_type,
            )) or 0) + 1
            artifact = Artifact(
                course_id=course.id,
                artifact_type=task.task_type,
                version=version,
                blueprint_version=blueprint.version,
                content_json=content,
                content_markdown=markdown,
                status="draft",
                model_name=model_name,
                prompt_version="v2",
                change_summary=change_summary,
                source_versions_json=await _source_versions(db, task),
            )
            db.add(artifact)
            await db.flush()
            task.current_artifact_id = artifact.id
            task.status = "review"
            task.progress = 100
            task.active_run_id = None
            task.error_json = None
            task.completed_at = utcnow()
            run.status = "completed"
            run.progress = 100
            run.finished_at = utcnow()
            if user_message and revision:
                user_message.status = "completed"
                reply = AgentMessage(
                    course_id=course.id,
                    task_id=task.id,
                    run_id=run.id,
                    module_type=task.task_type,
                    role="assistant",
                    content=revision.assistant_reply,
                    artifact_id=artifact.id,
                )
                db.add(reply)
                await _emit(db, run, "agent_message_created", task, message={"id": reply.id, "role": "assistant", "content": reply.content, "artifact_id": artifact.id, "run_id": run.id, "status": "completed"})
            stale_tasks = await _mark_dependents_stale(db, task, version)
            for stale_task in stale_tasks:
                await _emit(
                    db,
                    run,
                    "task_dependency_stale",
                    stale_task,
                    status="stale",
                    progress=stale_task.progress,
                    stale_dependencies=[task.task_type],
                )
            await _refresh_quality(db, course, blueprint)
            await _refresh_course_status(db, course)
            await _emit(db, run, "artifact_version_created", task, status="review", progress=100, artifact=artifact_payload(artifact))
            await _emit(db, run, "task_status_changed", task, status="review", progress=100)
            await db.commit()
        await schedule_ready_tasks(course.id)
    except asyncio.CancelledError:
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            if run:
                run.status = "cancelled"
                run.finished_at = utcnow()
            if task:
                task.status = "cancelled"
                task.active_run_id = None
                await _emit(db, run, "task_status_changed", task, status="cancelled", progress=task.progress)
            await db.commit()
    except Exception as exc:
        logger.exception("Course task run failed", extra={"run_id": run_id})
        async with SessionLocal() as db:
            run = await db.get(GenerationRun, run_id)
            task = await db.get(CourseTask, run.course_task_id) if run and run.course_task_id else None
            course = await db.get(CourseProject, run.course_id) if run else None
            if not run or not task:
                return
            code = exc.code if isinstance(exc, LLMProviderError) else "task_generation_failed"
            message = exc.user_message if isinstance(exc, LLMProviderError) else "任务生成暂时失败，请重试或切换模型。"
            retryable = exc.retryable if isinstance(exc, LLMProviderError) else True
            error = {"code": code, "message": message, "retryable": retryable}
            run.status = "failed"
            run.error_json = error
            run.finished_at = utcnow()
            task.status = "failed"
            task.active_run_id = None
            task.error_json = error
            message_row = await db.scalar(select(AgentMessage).where(AgentMessage.run_id == run.id, AgentMessage.role == "user"))
            if message_row:
                message_row.status = "failed"
            if course:
                await _refresh_course_status(db, course)
            await _emit(db, run, "task_failed", task, status="failed", progress=task.progress, error=error)
            await db.commit()
    finally:
        task_jobs.pop(run_id, None)


async def resume_incomplete_task_runs():
    run_ids = []
    async with SessionLocal() as db:
        runs = list(await db.scalars(select(GenerationRun).where(
            GenerationRun.run_type == "task",
            GenerationRun.status.in_(["queued", "running"]),
        )))
        for run in runs:
            run.status = "queued"
            if run.course_task_id:
                task = await db.get(CourseTask, run.course_task_id)
                if task:
                    task.status = "queued"
                    task.active_run_id = run.id
            run_ids.append(run.id)
        await db.commit()
    for run_id in run_ids:
        start_task_run(run_id)


def intent_summary(course: CourseProject, requirement: CourseRequirement | None) -> dict:
    settings = course.settings_json or {}
    assumptions = requirement.assumptions_json if requirement else []
    return {
        "headline": f"为{course.grade_level or course.audience}设计一节围绕“{course.title}”的{course.subject}微课",
        "title": course.title,
        "subject": course.subject,
        "grade_level": course.grade_level,
        "audience": course.audience,
        "duration_minutes": course.duration_minutes,
        "scenario": course.scenario,
        "course_task": settings.get("course_task", ""),
        "teaching_objectives": settings.get("teaching_objectives", ""),
        "key_points": settings.get("key_points", ""),
        "difficulty_points": settings.get("difficulty_points", ""),
        "teaching_method": settings.get("teaching_method", ""),
        "style_requirements": settings.get("style_requirements", ""),
        "assumptions": assumptions,
        "deliverables": [spec[1] for spec in TASK_SPECS],
    }
