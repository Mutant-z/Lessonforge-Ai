import asyncio
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.database import SessionLocal, get_db
from app.core.security import create_stream_token, decode_stream_token
from app.models.entities import (
    AgentChatSession,
    AgentMessage,
    Artifact,
    CourseBlueprint,
    CourseProject,
    CourseRequirement,
    CourseTask,
    GenerationEvent,
    GenerationRun,
    QualityIssue,
    QualityReport,
    User,
)
from app.services.course_task_service import (
    TASK_SPEC_BY_TYPE,
    create_task_run,
    ensure_course_tasks,
    intent_summary,
    schedule_ready_tasks,
    start_task_run,
    task_jobs,
    task_payload,
)
from app.services.model_config_service import owned_model_config, resolve_provider
from app.services.generation_service import start_blueprint_run
from app.services.agent_initialization_service import (
    create_initialization_run,
    initialization_summary,
    start_initialization_run,
)

router = APIRouter(tags=["课程项目任务"])


class TaskRunRequest(BaseModel):
    action: str = "retry"


class TaskMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class TaskModelRequest(BaseModel):
    model_config_id: str


async def _owned_task(course_id: str, task_type: str, user: User, db: AsyncSession):
    await owned_course(course_id, user, db)
    if task_type not in TASK_SPEC_BY_TYPE:
        raise HTTPException(404, "项目任务不存在")
    await ensure_course_tasks(db, course_id)
    task = await db.scalar(select(CourseTask).where(
        CourseTask.course_id == course_id,
        CourseTask.task_type == task_type,
    ))
    if not task:
        raise HTTPException(404, "项目任务不存在")
    return task


async def _quality_summary(db, course_id: str):
    report = await db.scalar(select(QualityReport).where(
        QualityReport.course_id == course_id,
    ).order_by(QualityReport.created_at.desc()))
    if not report:
        return {"score": None, "summary": "全部任务文件生成后将自动执行质量检查。", "open_issues": 0, "issues": []}
    issues = list(await db.scalars(select(QualityIssue).where(
        QualityIssue.report_id == report.id,
        QualityIssue.status == "open",
    )))
    return {
        "score": report.score,
        "summary": report.summary,
        "open_issues": len(issues),
        "issues": [{
            "id": item.id,
            "artifact_type": item.artifact_type,
            "severity": item.severity,
            "location": item.location,
            "description": item.description,
            "suggestion": item.suggestion,
        } for item in issues[:8]],
    }


@router.get("/courses/{course_id}/project")
async def get_project(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    tasks = await ensure_course_tasks(db, course_id)
    requirement = await db.scalar(select(CourseRequirement).where(
        CourseRequirement.course_id == course_id,
    ).order_by(CourseRequirement.version.desc()))
    blueprint = await db.scalar(select(CourseBlueprint).where(
        CourseBlueprint.course_id == course_id,
    ).order_by(CourseBlueprint.version.desc()))
    planning_run = await db.scalar(select(GenerationRun).where(
        GenerationRun.course_id == course_id,
        GenerationRun.run_type == "blueprint",
    ).order_by(GenerationRun.created_at.desc()))
    await db.commit()
    return {
        "course": course,
        "intent": intent_summary(course, requirement),
        "planning": {
            "status": "ready" if blueprint and blueprint.status == "approved" else (planning_run.status if planning_run else "not_started"),
            "progress": 100 if blueprint and blueprint.status == "approved" else (planning_run.progress if planning_run else 0),
            "error": planning_run.error_json if planning_run and planning_run.status == "failed" else None,
        },
        "agent_initialization": await initialization_summary(db, course_id),
        "tasks": [await task_payload(db, item) for item in tasks],
        "quality": await _quality_summary(db, course_id),
    }


@router.post("/courses/{course_id}/agent-initialization/runs", status_code=202)
async def initialize_project_agents(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    try:
        run, created = await create_initialization_run(db, course, "retry")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    if created:
        start_initialization_run(run.id)
    return {"run_id": run.id, "status": run.status, "created": created}


@router.post("/courses/{course_id}/project/planning/retry", status_code=202)
async def retry_project_planning(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    active = await db.scalar(select(GenerationRun).where(
        GenerationRun.course_id == course_id,
        GenerationRun.run_type == "blueprint",
        GenerationRun.status.in_(["queued", "running"]),
    ))
    if active:
        raise HTTPException(409, "内部规划 Agent 已在运行")
    run = GenerationRun(course_id=course_id, thread_id=str(uuid4()), run_type="blueprint", status="queued")
    db.add(run)
    course.status = "blueprint_generating"
    await db.commit()
    start_blueprint_run(run.id)
    return {"planning_run_id": run.id, "project_status": "planning"}


@router.get("/courses/{course_id}/tasks")
async def list_tasks(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    tasks = await ensure_course_tasks(db, course_id)
    await db.commit()
    return [await task_payload(db, item) for item in tasks]


@router.get("/courses/{course_id}/tasks/{task_type}")
async def get_task(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    course = await owned_course(course_id, user, db)
    rows = list(await db.scalars(select(AgentMessage).where(
        AgentMessage.course_id == course_id,
        AgentMessage.module_type == task_type,
    ).order_by(AgentMessage.created_at)))
    chat_session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course_id,
        AgentChatSession.module_type == task_type,
    ))
    _, config = await resolve_provider(db, user.id, (chat_session.model_config_id if chat_session else None) or course.model_config_id)
    payload = await task_payload(db, task)
    payload["messages"] = [{
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "status": row.status,
        "artifact_id": row.artifact_id,
        "run_id": row.run_id,
        "created_at": row.created_at,
    } for row in rows]
    payload["model_config_id"] = config.id if config else None
    return payload


@router.post("/courses/{course_id}/tasks/{task_type}/runs", status_code=202)
async def run_task(course_id: str, task_type: str, payload: TaskRunRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    allowed = {"initial", "retry", "sync_dependencies", "sync_context"}
    if payload.action not in allowed:
        raise HTTPException(422, "不支持的任务操作")
    if payload.action == "sync_dependencies" and task.status != "stale":
        raise HTTPException(409, "当前任务不需要同步上游内容")
    if payload.action == "sync_context" and task.status != "stale":
        raise HTTPException(409, "当前任务不需要同步项目上下文")
    if payload.action == "retry" and task.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "只有失败或已取消的任务可以重试")
    if payload.action == "initial" and task.current_artifact_id:
        raise HTTPException(409, "任务文件已经生成")
    try:
        retry_message = None
        trigger_type = payload.action
        if payload.action == "retry":
            failed_run = await db.scalar(select(GenerationRun).where(
                GenerationRun.course_task_id == task.id,
                GenerationRun.status == "failed",
            ).order_by(GenerationRun.created_at.desc()))
            if failed_run and failed_run.trigger_type == "message":
                retry_message = await db.scalar(select(AgentMessage).where(
                    AgentMessage.run_id == failed_run.id,
                    AgentMessage.role == "user",
                ).order_by(AgentMessage.created_at.desc()))
                if retry_message:
                    trigger_type = "message"
        run = await create_task_run(db, task, trigger_type, retry_message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"run_id": run.id, "task_id": task.id, "status": "queued"}


@router.post("/courses/{course_id}/tasks/{task_type}/messages", status_code=202)
async def send_task_message(course_id: str, task_type: str, payload: TaskMessageRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    if not task.current_artifact_id:
        raise HTTPException(409, "任务文件尚未生成")
    artifact = await db.get(Artifact, task.current_artifact_id)
    if artifact and artifact.is_locked:
        raise HTTPException(409, "当前任务文件已整体锁定")
    message = AgentMessage(
        course_id=course_id,
        task_id=task.id,
        module_type=task_type,
        role="user",
        content=payload.content.strip(),
        status="pending",
    )
    db.add(message)
    try:
        run = await create_task_run(db, task, "message", message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"message_id": message.id, "run_id": run.id, "task_id": task.id, "status": "queued"}


@router.patch("/courses/{course_id}/tasks/{task_type}/model")
async def change_task_model(course_id: str, task_type: str, payload: TaskModelRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await _owned_task(course_id, task_type, user, db)
    config = await owned_model_config(db, user.id, payload.model_config_id)
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course_id,
        AgentChatSession.module_type == task_type,
    ))
    if session:
        session.model_config_id = config.id
    else:
        db.add(AgentChatSession(course_id=course_id, module_type=task_type, model_config_id=config.id))
    await db.commit()
    return {"model_config_id": config.id}


@router.post("/courses/{course_id}/tasks/{task_type}/approve")
async def approve_task(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    if not task.current_artifact_id:
        raise HTTPException(409, "任务文件尚未生成")
    artifact = await db.get(Artifact, task.current_artifact_id)
    if task.current_agent_profile_id and artifact.agent_profile_id != task.current_agent_profile_id:
        raise HTTPException(409, "当前文件尚未同步最新项目专属 Agent 配置")
    artifact.status = "approved"
    artifact.approved_at = datetime.now(timezone.utc)
    task.status = "approved"
    task.completed_at = datetime.now(timezone.utc)
    tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course_id)))
    course = await owned_course(course_id, user, db)
    course.status = "completed" if all(item.status == "approved" for item in tasks) else "teacher_review"
    await db.commit()
    return await task_payload(db, task)


@router.post("/courses/{course_id}/tasks/{task_type}/cancel")
async def cancel_task(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    if not task.active_run_id:
        raise HTTPException(409, "当前任务没有正在运行的 Agent")
    run_id = task.active_run_id
    job = task_jobs.get(run_id)
    if job:
        job.cancel()
    else:
        run = await db.get(GenerationRun, run_id)
        if run:
            run.status = "cancelled"
            run.finished_at = datetime.now(timezone.utc)
        task.status = "cancelled"
        task.active_run_id = None
        await db.commit()
    return {"task_id": task.id, "status": "cancelled"}


@router.post("/courses/{course_id}/task-events/token")
async def task_event_token(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    return {"token": create_stream_token(user.id, course_id), "expires_in": 300}


@router.get("/courses/{course_id}/task-events")
async def task_events(course_id: str, request: Request, token: str, after: int = Query(0, ge=0)):
    user_id = decode_stream_token(token, course_id)
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        if not course or course.owner_id != user_id:
            raise HTTPException(404, "课程项目不存在")
    header_cursor = request.headers.get("Last-Event-ID", "")
    cursor = int(header_cursor) if header_cursor.isdigit() else after

    async def stream():
        nonlocal cursor
        idle_seconds = 0.0
        fast_until = 0.0
        last_heartbeat = 0.0
        while idle_seconds < 600:
            async with SessionLocal() as db:
                rows = list(await db.scalars(
                    select(GenerationEvent)
                    .join(GenerationRun, GenerationRun.id == GenerationEvent.run_id)
                    .where(GenerationRun.course_id == course_id, GenerationEvent.id > cursor)
                    .order_by(GenerationEvent.id)
                ))
                for row in rows:
                    cursor = row.id
                    payload = {"event_id": row.id, **row.data_json}
                    yield f"id: {row.id}\nevent: {row.event_type}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            now = time.monotonic()
            if rows:
                idle_seconds = 0.0
                fast_until = now + 3
            delay = 0.2 if now < fast_until else 1.0
            if not rows:
                idle_seconds += delay
            if not rows and now - last_heartbeat >= 10:
                yield ": heartbeat\n\n"
                last_heartbeat = now
            await asyncio.sleep(delay)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
