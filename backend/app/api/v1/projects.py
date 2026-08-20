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
    ArtifactAsset,
)
from app.services.course_task_service import (
    CONTENT_TASK_TYPES,
    TASK_SPEC_BY_TYPE,
    create_task_run,
    ensure_course_tasks,
    intent_summary,
    schedule_ready_tasks,
    start_task_run,
    task_jobs,
    task_payload,
)
from app.services.model_config_service import owned_model_config, resolve_model_config, resolve_provider
from app.services.project_planning_service import start_blueprint_run
from app.services.agent_initialization_service import (
    create_initialization_run,
    initialization_summary,
    start_initialization_run,
)

router = APIRouter(tags=["课程项目任务"])


class TaskRunRequest(BaseModel):
    action: str = "retry"
    resolution: str = "1280x720"
    voice_style: str = "natural"
    subtitle_enabled: bool = True
    background_music_enabled: bool = False
    visual_mode: str = "ai_visual_first"
    quote_id: str | None = None
    approved_max_cost_fen: int | None = None


class TaskMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    # 教学设计 V2 指令扩展：章节作用域与显式模式（最终意图仍由 Agent 识别）。
    selected_section_ids: list[str] = Field(default_factory=list, max_length=50)
    active_section_id: str | None = None
    mode: str = Field(default="auto", pattern="^(auto|content|structure|timing|qa)$")


class TaskModelRequest(BaseModel):
    model_config_id: str | None = None
    image_model_config_id: str | None = None
    vision_model_config_id: str | None = None
    video_model_config_id: str | None = None
    speech_model_config_id: str | None = None


async def _course_event_cursor(db: AsyncSession, course_id: str) -> int:
    """Return the durable cursor preceding a course/task snapshot.

    Events committed after this read are intentionally replayed by SSE; events
    at or before it are already represented by the authoritative snapshot.
    """
    value = await db.scalar(
        select(func.max(GenerationEvent.id))
        .join(GenerationRun, GenerationRun.id == GenerationEvent.run_id)
        .where(GenerationRun.course_id == course_id)
    )
    return int(value or 0)


def _generation_event_payload(row: GenerationEvent) -> dict:
    """Build a canonical SSE envelope whose durable sequence cannot be spoofed."""
    return {**(row.data_json or {}), "event_id": row.id, "sequence": row.id}


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


async def _cancel_active_task(db: AsyncSession, task: CourseTask) -> dict:
    """Persist cancellation before returning so a missing/slow worker cannot leave a ghost run."""
    if not task.active_run_id:
        raise HTTPException(409, "当前任务没有正在运行的 Agent")

    run_id = task.active_run_id
    if task.task_type == "video_generation":
        from app.services.seedance_video_generation_service import cancel_seedance_provider_jobs
        await cancel_seedance_provider_jobs(db, task)

    # Provider cancellation can race with normal completion in another session.
    # Refresh before deciding whether there is still anything to cancel.
    await db.refresh(task)
    if task.active_run_id != run_id:
        return {"task_id": task.id, "status": task.status}

    run = await db.get(GenerationRun, run_id)
    if run and run.status in {"completed", "failed", "cancelled"}:
        task.active_run_id = None
        if run.status in {"failed", "cancelled"}:
            task.status = run.status
            task.error_json = run.error_json
        await db.commit()
        return {"task_id": task.id, "status": task.status}

    now = datetime.now(timezone.utc)
    if run:
        run.status = "cancelled"
        run.finished_at = now
        db.add(GenerationEvent(
            run_id=run.id,
            event_type="task_status_changed",
            data_json={
                "course_id": task.course_id,
                "run_id": run.id,
                "task_id": task.id,
                "task_type": task.task_type,
                "status": "cancelled",
                "progress": task.progress,
            },
        ))
    task.status = "cancelled"
    task.active_run_id = None
    task.error_json = None
    await db.commit()

    job = task_jobs.get(run_id)
    if job and not job.done():
        job.cancel()
    return {"task_id": task.id, "status": "cancelled"}


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
    event_cursor = await _course_event_cursor(db, course_id)
    snapshot_at = datetime.now(timezone.utc).isoformat()
    tasks = await ensure_course_tasks(db, course_id)
    # 共享项目记忆：只读回填存量需求/蓝图/材料/Artifact（幂等），返回当前版本。
    from app.services.project_knowledge_service import current_revision, ensure_initialized, list_items

    await ensure_initialized(db, course_id)
    memory_revision = await current_revision(db, course_id)
    memory_items = await list_items(db, course_id, limit=200)
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
        "event_cursor": event_cursor,
        "snapshot_at": snapshot_at,
        "course": course,
        "intent": intent_summary(course, requirement),
        "planning": {
            "status": "ready" if blueprint and blueprint.status == "approved" else (planning_run.status if planning_run else "not_started"),
            "progress": 100 if blueprint and blueprint.status == "approved" else (planning_run.progress if planning_run else 0),
            "error": planning_run.error_json if planning_run and planning_run.status == "failed" else None,
        },
        "agent_initialization": await initialization_summary(db, course_id),
        "tasks": [await task_payload(db, item, event_cursor=event_cursor) for item in tasks],
        "quality": await _quality_summary(db, course_id),
        "memory": {
            "revision": memory_revision,
            "item_count": len(memory_items),
            "items": [{
                "id": item.id,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "source_version": item.source_version,
                "artifact_type": item.artifact_type,
                "summary": item.summary_json,
                "memory_revision": item.memory_revision,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            } for item in memory_items],
        },
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
    event_cursor = await _course_event_cursor(db, course_id)
    tasks = await ensure_course_tasks(db, course_id)
    await db.commit()
    return [await task_payload(db, item, event_cursor=event_cursor) for item in tasks]


@router.get("/courses/{course_id}/tasks/{task_type}")
async def get_task(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    event_cursor = await _course_event_cursor(db, course_id)
    snapshot_at = datetime.now(timezone.utc).isoformat()
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
    vision_config = await resolve_model_config(
        db, user.id, chat_session.vision_model_config_id if chat_session else None, "vision",
    )
    video_config = await resolve_model_config(
        db, user.id, chat_session.video_model_config_id if chat_session else None, "video",
    )
    payload = await task_payload(db, task)
    payload["event_cursor"] = event_cursor
    payload["snapshot_at"] = snapshot_at
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
    payload["image_model_config_id"] = chat_session.image_model_config_id if chat_session else None
    payload["vision_model_config_id"] = vision_config.id if vision_config else None
    payload["video_model_config_id"] = video_config.id if video_config else None
    payload["speech_model_config_id"] = chat_session.speech_model_config_id if chat_session else None
    return payload


@router.post("/courses/{course_id}/tasks/{task_type}/runs", status_code=202)
async def run_task(course_id: str, task_type: str, payload: TaskRunRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    if task_type == "video_generation":
        if payload.action == "cancel":
            return await _cancel_active_task(db, task)
        if payload.action not in {"initial", "retry", "recompose", "sync_dependencies"}:
            raise HTTPException(422, "视频生成不支持该任务操作")
        from app.schemas.video import SeedanceVideoGenerationRunRequest
        from app.services.seedance_video_generation_service import create_seedance_video_run
        try:
            request = SeedanceVideoGenerationRunRequest.model_validate(payload.model_dump())
            run = await create_seedance_video_run(db, task, request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await db.commit()
        start_task_run(run.id)
        return {"run_id": run.id, "task_id": task.id, "status": "queued"}
    return await dispatch_task_run_action(db, task, payload.action)


async def dispatch_task_run_action(db: AsyncSession, task: CourseTask, action: str) -> dict:
    """通用任务操作分发（initial / retry / sync_dependencies / sync_context）。

    供 projects 泛化路由与动态 Agent 专用路由（教学设计/任务单/视频脚本/逐字稿）
    共用：这些 Agent 的 message 路由先按 action 判断，非 message 操作委托到这里。
    """
    allowed = {"initial", "retry", "sync_dependencies", "sync_context"}
    if action not in allowed:
        raise HTTPException(422, "不支持的任务操作")
    if action == "sync_dependencies" and task.status != "stale":
        raise HTTPException(409, "当前任务不需要同步上游内容")
    if action == "sync_context" and not task.current_artifact_id:
        raise HTTPException(409, "任务文件尚未生成，无法同步项目上下文")
    if action == "sync_context":
        artifact = await db.get(Artifact, task.current_artifact_id)
        if artifact and artifact.is_locked:
            raise HTTPException(409, "当前任务文件已整体锁定")
    if action == "retry" and task.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "只有失败或已取消的任务可以重试")
    if action == "initial" and task.current_artifact_id:
        raise HTTPException(409, "任务文件已经生成")
    try:
        retry_message = None
        trigger_type = action
        if action == "retry":
            failed_run = await db.scalar(select(GenerationRun).where(
                GenerationRun.course_task_id == task.id,
                GenerationRun.status == "failed",
            ).order_by(GenerationRun.created_at.desc()))
            if failed_run and failed_run.trigger_type == "retry":
                # A retry must retain the operation that originally failed. Otherwise a
                # failed dependency/context sync silently turns into an initial generation
                # on every subsequent click and loses the migration-specific behavior.
                failed_run = await db.scalar(select(GenerationRun).where(
                    GenerationRun.course_task_id == task.id,
                    GenerationRun.status == "failed",
                    GenerationRun.trigger_type != "retry",
                ).order_by(GenerationRun.created_at.desc()))
            if failed_run and failed_run.trigger_type == "message":
                retry_message = await db.scalar(select(AgentMessage).where(
                    AgentMessage.run_id == failed_run.id,
                    AgentMessage.role == "user",
                ).order_by(AgentMessage.created_at.desc()))
                if retry_message:
                    trigger_type = "message"
            elif failed_run and failed_run.trigger_type in {"initial", "sync_dependencies", "sync_context"}:
                trigger_type = failed_run.trigger_type
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
    if task_type in {"lesson_plan", "exercise"} and any((
        payload.selected_section_ids, payload.active_section_id, payload.mode != "auto",
    )):
        message.metadata_json = {
            "selected_section_ids": list(payload.selected_section_ids),
            "active_section_id": payload.active_section_id,
            "mode": payload.mode,
        }
    db.add(message)
    if task_type == "video_generation":
        await db.rollback()
        raise HTTPException(409, "原生有声视频片段修改必须先在片段编辑器中获取并确认报价")
    try:
        run = await create_task_run(db, task, "message", message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"message_id": message.id, "run_id": run.id, "task_id": task.id, "status": "queued"}


@router.patch("/courses/{course_id}/tasks/{task_type}/model")
async def change_task_model(course_id: str, task_type: str, payload: TaskModelRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from app.services.media_provider_service import media_transport_supports

    await _owned_task(course_id, task_type, user, db)
    if not any((
        payload.model_config_id, payload.image_model_config_id, payload.vision_model_config_id,
        payload.video_model_config_id, payload.speech_model_config_id,
    )):
        raise HTTPException(422, "至少选择一种模型配置")
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course_id,
        AgentChatSession.module_type == task_type,
    ))
    if not session:
        session = AgentChatSession(course_id=course_id, module_type=task_type)
        db.add(session)
    if payload.model_config_id:
        config = await owned_model_config(db, user.id, payload.model_config_id)
        if config.model_category != "text" or config.model_purpose != "text_chat":
            raise HTTPException(422, "文本任务只能选择文本模型配置")
        session.model_config_id = config.id
    if payload.image_model_config_id:
        image_config = await owned_model_config(db, user.id, payload.image_model_config_id)
        if "image_generation" not in (image_config.capabilities_json or []):
            raise HTTPException(422, "所选模型未声明图片生成能力")
        if image_config.model_category != "vision" or image_config.model_purpose != "image_generation":
            raise HTTPException(422, "所选配置不是图片生成服务")
        session.image_model_config_id = image_config.id
    if payload.vision_model_config_id:
        vision_config = await owned_model_config(db, user.id, payload.vision_model_config_id)
        if "vision_review" not in (vision_config.capabilities_json or []):
            raise HTTPException(422, "所选模型未声明视觉复核能力")
        if vision_config.model_category != "vision" or vision_config.model_purpose != "vision_chat":
            raise HTTPException(422, "所选配置不是多模态视觉理解模型")
        session.vision_model_config_id = vision_config.id
    if payload.video_model_config_id:
        video_config = await owned_model_config(db, user.id, payload.video_model_config_id)
        if "video_generation" not in (video_config.capabilities_json or []):
            raise HTTPException(422, "所选模型未声明视频生成能力")
        if video_config.model_category != "video":
            raise HTTPException(422, "所选配置不是视频模型")
        if task_type == "video_generation" and "native_audio_video_generation" not in (video_config.capabilities_json or []):
            raise HTTPException(422, "视频生成任务只接受声明原生有声视频能力的模型配置")
        if not media_transport_supports(video_config.provider, video_config.api_mode, "video_generation"):
            raise HTTPException(422, "所选模型的接口模式不支持视频生成，请配置自定义异步视频 HTTP 接口")
        session.video_model_config_id = video_config.id
    if payload.speech_model_config_id:
        speech_config = await owned_model_config(db, user.id, payload.speech_model_config_id)
        if "speech_generation" not in (speech_config.capabilities_json or []):
            raise HTTPException(422, "所选模型未声明语音生成能力")
        if speech_config.model_category != "video" or speech_config.model_purpose != "speech_generation":
            raise HTTPException(422, "所选配置不是视频列的语音生成服务")
        if not media_transport_supports(speech_config.provider, speech_config.api_mode, "speech_generation"):
            raise HTTPException(422, "所选模型的接口模式不支持语音生成，请配置自定义语音 HTTP 接口")
        session.speech_model_config_id = speech_config.id
    await db.commit()
    return {
        "model_config_id": session.model_config_id,
        "image_model_config_id": session.image_model_config_id,
        "vision_model_config_id": session.vision_model_config_id,
        "video_model_config_id": session.video_model_config_id,
        "speech_model_config_id": session.speech_model_config_id,
    }


@router.post("/courses/{course_id}/tasks/{task_type}/approve")
async def approve_task(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    if not task.current_artifact_id:
        raise HTTPException(409, "任务文件尚未生成")
    artifact = await db.get(Artifact, task.current_artifact_id)
    if task_type == "video_generation":
        from app.services.course_task_service import is_publishable_video_artifact

        if not is_publishable_video_artifact(artifact):
            raise HTTPException(409, "视频尚未生成；请先确认视频脚本，再获取报价并生成视频")
        final_asset_id = ((artifact.content_json or {}).get("outputs") or {}).get("final_asset_id")
        final_asset = await db.get(ArtifactAsset, final_asset_id) if final_asset_id else None
        if not final_asset or final_asset.status != "approved":
            raise HTTPException(409, "最终视频尚未通过媒体质量检查")
    if task.current_agent_profile_id and artifact.agent_profile_id != task.current_agent_profile_id:
        raise HTTPException(409, "当前文件尚未同步最新项目专属 Agent 配置")
    artifact.status = "approved"
    artifact.approved_at = datetime.now(timezone.utc)
    task.status = "approved"
    task.completed_at = datetime.now(timezone.utc)
    # 共享项目记忆：教师确认决策进入项目记忆（同一事务，先写后 bump）。
    from app.services.project_knowledge_service import bump, index_decision

    await index_decision(
        db, course_id, f"decision-{task.task_type}-approved",
        f"确认 {TASK_SPEC_BY_TYPE[task.task_type][1]} V{artifact.version}",
        f"教师确认了 {TASK_SPEC_BY_TYPE[task.task_type][1]} V{artifact.version} 作为交付内容。",
        created_by="teacher",
        summary={"task_type": task.task_type, "artifact_version": artifact.version},
    )
    await bump(
        db, course_id, f"确认 {TASK_SPEC_BY_TYPE[task.task_type][1]} V{artifact.version}",
        source_type="decision", source_id=f"decision-{task.task_type}-approved",
        created_by="teacher",
    )
    tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course_id)))
    course = await owned_course(course_id, user, db)
    content_ready = all(item.status == "approved" for item in tasks if item.task_type in CONTENT_TASK_TYPES)
    video_task = next((item for item in tasks if item.task_type == "video_generation"), None)
    video_ready = not video_task or video_task.status in {"ready_to_generate", "approved"}
    course.status = "completed" if content_ready and video_ready else "teacher_review"
    await db.commit()
    if task_type == "video_script":
        await schedule_ready_tasks(course_id)
        await db.refresh(task)
    return await task_payload(db, task)


@router.post("/courses/{course_id}/tasks/{task_type}/cancel")
async def cancel_task(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    return await _cancel_active_task(db, task)


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
                    payload = _generation_event_payload(row)
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
