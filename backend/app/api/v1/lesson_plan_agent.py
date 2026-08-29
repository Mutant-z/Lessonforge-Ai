"""教学设计 Agent API：runs / messages / 通用人工确认。

- POST /courses/{course_id}/tasks/lesson_plan/runs —— 创建运行（initial 或带指令的 message）
- POST /courses/{course_id}/tasks/lesson_plan/messages —— 教师修改指令（携带章节作用域与 mode）
- POST /agent-runs/{run_id}/human-response —— 通用人工确认（目录候选/意图确认等）
- GET /agent-runs/{run_id} / events —— 运行详情与 SSE 事件流

流水线详情 / pause / resume 复用已 task_type 参数化的 /tasks/{task_type}/pipeline 等端点。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.v1.projects import _owned_task, _validated_chat_attachment_metadata
from app.agent.event_protocol import canonical_event
from app.core.database import SessionLocal, get_db
from app.models.entities import (
    AgentHumanRequest,
    AgentMessage,
    CourseTask,
    GenerationEvent,
    GenerationRun,
    PipelineRun,
    User,
)
from app.services.course_task_service import (
    create_task_run,
    start_task_run,
    task_jobs,
)
from app.services.ppt_pipeline_service import PAUSE_EVENTS

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])
lesson_plan_router = APIRouter(tags=["lesson-plan-agent"])

TASK_TYPE = "lesson_plan"

_NO_CHANGE_HUMAN_CHOICES = {"cancel", "discard", "edit", "keep", "no_change", "none", "reject"}
_CONTINUABLE_HUMAN_REQUESTS = {"outline_confirmation", "intent_confirmation", "lesson_plan_candidate_confirmation"}


class LessonPlanMessageRequest(BaseModel):
    content: str = Field(default="", max_length=8000)
    #: 兼容旧客户端操作（initial / retry / sync_dependencies / sync_context）；
    #: 新客户端不传该字段（默认走 message 动态流水线）。
    action: str = Field(default="message", max_length=30)
    selected_section_ids: list[str] = Field(default_factory=list, max_length=50)
    active_section_id: str | None = None
    mode: str = Field(default="auto", pattern="^(auto|content|structure|timing|qa)$")
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


class HumanResponseRequest(BaseModel):
    request_id: str = Field(min_length=1)
    choice: str = Field(min_length=1, max_length=200)
    data: dict = Field(default_factory=dict)


async def _owned_task_by_run(run_id: str, user: User, db: AsyncSession) -> tuple[GenerationRun, CourseTask]:
    """定位运行所属任务（通用：不限定 lesson_plan，供所有动态 Agent 流水线复用）。"""
    run = await db.get(GenerationRun, run_id)
    if not run or not run.course_task_id:
        raise HTTPException(404, "运行不存在")
    task = await db.get(CourseTask, run.course_task_id)
    if not task:
        raise HTTPException(404, "运行所属任务不存在")
    owned = await _owned_task(run.course_id, task.task_type, user, db)
    if owned.id != task.id:
        raise HTTPException(404, "运行不属于该任务")
    return run, task


@lesson_plan_router.post("/courses/{course_id}/tasks/lesson_plan/runs", status_code=202)
async def create_lesson_plan_run(
    course_id: str,
    payload: LessonPlanMessageRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _owned_task(course_id, TASK_TYPE, user, db)
    # 兼容旧客户端操作：initial / retry / sync_dependencies / sync_context 委托通用分发。
    if payload.action != "message":
        from app.api.v1.projects import dispatch_task_run_action

        return await dispatch_task_run_action(db, task, payload.action)
    content = payload.content.strip()
    if not content:
        raise HTTPException(422, "修改指令不能为空")
    attachment_meta = await _validated_chat_attachment_metadata(db, user, course_id, payload.attachment_ids)
    message = AgentMessage(
        course_id=course_id, task_id=task.id, module_type=TASK_TYPE,
        role="user", content=content, status="pending",
    )
    if any((payload.selected_section_ids, payload.active_section_id, payload.mode != "auto")) or attachment_meta:
        message.metadata_json = {
            "selected_section_ids": list(payload.selected_section_ids),
            "active_section_id": payload.active_section_id,
            "mode": payload.mode,
            **attachment_meta,
        }
    db.add(message)
    try:
        run = await create_task_run(db, task, "message", message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"message_id": message.id, "run_id": run.id, "task_id": task.id, "status": "queued"}


@lesson_plan_router.post("/courses/{course_id}/tasks/lesson_plan/messages", status_code=202)
async def send_lesson_plan_message(
    course_id: str,
    payload: LessonPlanMessageRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_lesson_plan_run(course_id, payload, user, db)


# ---------------------------------------------------------------------------
# 通用人工确认
# ---------------------------------------------------------------------------


def _human_option(request: AgentHumanRequest, choice: str) -> dict:
    for option in request.options_json or []:
        if option.get("id") == choice:
            return option
    raise HTTPException(422, "人工确认选项不存在")


@router.get("/{run_id}")
async def get_agent_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await _owned_task_by_run(run_id, user, db)
    run = await db.get(GenerationRun, run_id)
    pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
    pending = list(await db.scalars(select(AgentHumanRequest).where(
        AgentHumanRequest.pipeline_run_id == pipeline.id,
        AgentHumanRequest.status == "pending",
    ).order_by(AgentHumanRequest.created_at))) if pipeline else []
    return {
        "run": {
            "id": run.id, "status": run.status, "progress": run.progress,
            "current_node": run.current_node, "trigger_type": run.trigger_type,
            "error": run.error_json, "created_at": run.created_at.isoformat() if run.created_at else "",
        },
        "pipeline": {
            "id": pipeline.id, "status": pipeline.status, "current_agent": pipeline.current_agent,
            "plan": pipeline.plan_json, "token_usage": pipeline.token_usage_json,
        } if pipeline else None,
        "pending_human_requests": [
            {"id": row.id, "type": row.request_type, "prompt": row.prompt, "options": row.options_json}
            for row in pending
        ],
    }


@router.get("/{run_id}/events")
async def stream_agent_run_events(run_id: str, request: Request, after: int = Query(0, ge=0), user: User = Depends(current_user)):
    db_session = SessionLocal()
    try:
        await _owned_task_by_run(run_id, user, db_session)
    finally:
        await db_session.close()
    last_event_id = int(request.headers.get("last-event-id", 0) or 0)
    cursor = max(after, last_event_id)

    async def stream():
        while True:
            async with SessionLocal() as db:
                run = await db.get(GenerationRun, run_id)
                if not run:
                    break
                rows = list(await db.scalars(select(GenerationEvent).where(
                    GenerationEvent.run_id == run_id,
                    GenerationEvent.id > cursor,
                ).order_by(GenerationEvent.id).limit(200)))
                for row in rows:
                    event = canonical_event(
                        event_id=row.id, event_type=row.event_type,
                        data=row.data_json or {}, created_at=row.created_at,
                    )
                    yield f"id: {row.id}\nevent: {event['type']}\ndata: {row.data_json or {}}\n\n"
                cursor = max(cursor, max((row.id for row in rows), default=cursor))
                terminal = run.status in {"completed", "failed", "cancelled"}
            if terminal or request.is_disconnected():
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.post("/{run_id}/human-response")
async def resolve_human_response(run_id: str, payload: HumanResponseRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await _owned_task_by_run(run_id, user, db)
    run = await db.get(GenerationRun, run_id)
    pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
    if pipeline is None:
        raise HTTPException(404, "流水线运行不存在")
    request_row = await db.scalar(select(AgentHumanRequest).where(
        AgentHumanRequest.id == payload.request_id,
        AgentHumanRequest.pipeline_run_id == pipeline.id,
    ))
    if request_row is None or request_row.status != "pending":
        raise HTTPException(409, "人工确认请求不存在或已处理")
    option = _human_option(request_row, payload.choice)

    # 原子认领：防双点击。
    claimed = await db.execute(
        select(AgentHumanRequest).where(
            AgentHumanRequest.id == payload.request_id,
            AgentHumanRequest.status == "pending",
        )
    )
    row = claimed.scalar_one_or_none()
    if row is None:
        raise HTTPException(409, "人工确认请求已被处理")
    row.status = "processing"

    resolution = str(option.get("action") or option.get("id") or payload.choice)
    if payload.choice in _NO_CHANGE_HUMAN_CHOICES:
        row.status = "resolved"
        row.resolved_at = datetime.now(timezone.utc)
        row.response_json = {**payload.data, "choice": payload.choice, "resolution": "rejected"}
        pipeline.plan_json = {**(pipeline.plan_json or {}), "result_status": "no_change"}
        await db.commit()
        return {"status": "resolved", "resolution": "rejected", "result_status": "no_change", "continuation_run_id": None}

    row.status = "resolved"
    row.resolved_at = datetime.now(timezone.utc)
    row.response_json = {**payload.data, "choice": payload.choice, "resolution": "confirmed"}
    await db.commit()

    # 续跑：创建带确认凭证的 continuation message（服务端验证由 runtime 完成）。
    task = await db.get(CourseTask, run.course_task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    source_message = await db.scalar(select(AgentMessage).where(
        AgentMessage.run_id == run_id, AgentMessage.role == "user",
    ).order_by(AgentMessage.created_at.desc()))
    continuation = AgentMessage(
        course_id=task.course_id, task_id=task.id, module_type=task.task_type,
        role="user", content=(source_message.content if source_message else "继续执行"),
        status="pending",
        metadata_json={
            "human_confirmation": {
                "request_id": request_row.id, "source_run_id": run_id,
                "request_type": request_row.request_type, "choice": payload.choice,
                "confirmation_token": f"agent-{request_row.id}",
            },
            "mode": "auto",
        },
    )
    db.add(continuation)
    try:
        new_run = await create_task_run(db, task, "message", continuation)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(new_run.id)
    return {"status": "resolved", "resolution": "confirmed", "result_status": "continued", "continuation_run_id": new_run.id}
