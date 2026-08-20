"""学习任务单 Agent API（方案 §3.3）。

- POST /courses/{course_id}/tasks/task_sheet/messages —— 教师修改指令（复用既有接口）
- POST /courses/{course_id}/tasks/{task_type}/runs/{run_id}/instructions —— 运行中追加指令
- POST /courses/{course_id}/tasks/{task_type}/runs/{run_id}/human-responses/{request_id} —— 人工确认
- GET /courses/{course_id}/tasks/{task_type}/pipeline —— 最近运行详情（含 instructions/human_requests）

运行详情 / pause / resume 复用已 task_type 参数化的 /tasks/{task_type}/pipeline 等端点。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.v1.projects import _owned_task
from app.core.database import SessionLocal, get_db
from app.models.entities import (
    AgentHumanRequest,
    AgentMessage,
    AgentRunInstruction,
    CourseTask,
    GenerationRun,
    PipelineRun,
    User,
)
from app.services.course_task_service import start_task_run, task_jobs
from app.services.ppt_pipeline_service import PAUSE_EVENTS

router = APIRouter(tags=["task-sheet-agent"])

TASK_TYPE = "task_sheet"

_CANCEL_CHOICES = {"cancel", "discard", "no_change", "reject", "none"}


class TaskSheetMessageRequest(BaseModel):
    content: str = Field(default="", max_length=8000)
    #: 兼容旧客户端操作（initial / retry / sync_dependencies / sync_context）。
    action: str = Field(default="message", max_length=30)
    selected_section_ids: list[str] = Field(default_factory=list, max_length=50)
    active_section_id: str | None = None
    mode: str = Field(default="auto", pattern="^(auto|content|structure|narration|visual|continuity|timing|qa)$")


class InstructionRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    client_instruction_id: str = Field(default="", max_length=120)
    resume_if_paused: bool = False
    selected_section_ids: list[str] = Field(default_factory=list, max_length=50)
    selected_scene_ids: list[str] = Field(default_factory=list, max_length=100)
    active_section_id: str | None = None
    active_scene_id: str | None = None
    mode: str = Field(default="auto", pattern="^(auto|content|structure|narration|visual|continuity|timing|qa)$")


class HumanResponseRequest(BaseModel):
    choice: str = Field(min_length=1, max_length=200)
    data: dict = Field(default_factory=dict)


async def _owned_run(run_id: str, course_id: str, task_type: str, user: User, db: AsyncSession) -> tuple[GenerationRun, PipelineRun]:
    run = await db.get(GenerationRun, run_id)
    if not run or run.course_id != course_id:
        raise HTTPException(404, "运行不存在")
    task = await _owned_task(course_id, task_type, user, db)
    if task.id != run.course_task_id:
        raise HTTPException(404, "运行不属于该任务")
    pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
    if pipeline is None:
        raise HTTPException(404, "流水线运行不存在")
    return run, pipeline


@router.post("/courses/{course_id}/tasks/task_sheet/runs", status_code=202)
async def create_task_sheet_run(
    course_id: str,
    payload: TaskSheetMessageRequest,
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
    message = AgentMessage(
        course_id=course_id, task_id=task.id, module_type=TASK_TYPE,
        role="user", content=content, status="pending",
    )
    if any((payload.selected_section_ids, payload.active_section_id, payload.mode != "auto")):
        message.metadata_json = {
            "selected_section_ids": list(payload.selected_section_ids),
            "active_section_id": payload.active_section_id,
            "mode": payload.mode,
        }
    db.add(message)
    try:
        from app.services.course_task_service import create_task_run

        run = await create_task_run(db, task, "message", message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"message_id": message.id, "run_id": run.id, "task_id": task.id, "status": "queued"}


@router.post("/courses/{course_id}/tasks/task_sheet/messages", status_code=202)
async def send_task_sheet_message(
    course_id: str,
    payload: TaskSheetMessageRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_task_sheet_run(course_id, payload, user, db)


@router.post("/courses/{course_id}/tasks/{task_type}/runs/{run_id}/instructions", status_code=202)
async def enqueue_instruction(
    course_id: str,
    task_type: str,
    run_id: str,
    payload: InstructionRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """运行中追加教师指令：只允许向属于当前用户、课程和任务的活跃运行追加。

    幂等：client_instruction_id 已存在时直接返回原记录（方案 §3.2）。
    """
    generation, pipeline = await _owned_run(run_id, course_id, task_type, user, db)
    if pipeline.status not in {"queued", "running", "pausing", "paused"}:
        raise HTTPException(409, "当前 Run 已结束，请创建新的修改 Run")
    content = payload.content.strip()
    if payload.client_instruction_id:
        existing = await db.scalar(select(AgentRunInstruction).where(
            AgentRunInstruction.pipeline_run_id == pipeline.id,
            AgentRunInstruction.client_instruction_id == payload.client_instruction_id,
        ))
        if existing is not None:
            return {
                "instruction_id": existing.id, "status": "idempotent",
                "message": "该 client_instruction_id 已提交，本次跳过。",
            }
    user_message = AgentMessage(
        course_id=generation.course_id,
        task_id=generation.course_task_id,
        run_id=generation.id,
        module_type=task_type,
        role="user",
        content=content,
        metadata_json={
            "selected_section_ids": list(payload.selected_section_ids),
            "selected_scene_ids": list(payload.selected_scene_ids),
            "active_section_id": payload.active_section_id,
            "active_scene_id": payload.active_scene_id,
            "mode": payload.mode,
        },
        status="completed",
    )
    db.add(user_message)
    await db.flush()
    row = AgentRunInstruction(
        pipeline_run_id=pipeline.id,
        message_id=user_message.id,
        client_instruction_id=payload.client_instruction_id,
        content=content,
        status="queued",
        metadata_json={
            "selected_section_ids": list(payload.selected_section_ids),
            "selected_scene_ids": list(payload.selected_scene_ids),
            "active_section_id": payload.active_section_id,
            "active_scene_id": payload.active_scene_id,
            "mode": payload.mode,
        },
    )
    db.add(row)
    await db.flush()
    should_resume = payload.resume_if_paused and pipeline.status == "paused"
    if should_resume:
        pause_event = PAUSE_EVENTS.pop(generation.id, None)
        if pause_event is not None:
            pause_event.clear()
        generation.status = pipeline.status = "queued"
        task = await db.get(CourseTask, generation.course_task_id) if generation.course_task_id else None
        if task:
            task.status = "queued"
    instruction_id = row.id
    message_payload = {
        "id": user_message.id, "role": "user", "content": user_message.content,
        "run_id": generation.id, "status": "completed",
    }
    await db.commit()
    from app.agent.events import PipelineEventEmitter

    emitter = await PipelineEventEmitter.for_run(generation, pipeline, task_type=task_type)
    await emitter.emit_domain("run.instruction.queued", message=(
        "教师指令已加入执行队列并恢复运行" if should_resume else "教师指令已加入执行队列"
    ), payload={
        "instruction_id": instruction_id,
        "content": content[:200],
        "user_message": message_payload,
    })
    if should_resume:
        await emitter.task_resumed(resume_from_step=pipeline.current_step_index)
        start_task_run(generation.id)
    return {
        "instruction_id": instruction_id,
        "message_id": user_message.id,
        "message": message_payload,
        "status": "resumed" if should_resume else "queued",
    }


@router.post("/courses/{course_id}/tasks/{task_type}/runs/{run_id}/human-responses/{request_id}", status_code=202)
async def resolve_human_response(
    course_id: str,
    task_type: str,
    run_id: str,
    request_id: str,
    payload: HumanResponseRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """原子解决人工确认请求，从原 checkpoint 恢复同一个 GenerationRun（方案 §3.3）。

    - cancel / no_change → 本轮取消，保留原版本，明确终态。
    - apply / scope_down → 颁发确认令牌，同一 Run 从 checkpoint 续跑。
    """
    generation, pipeline = await _owned_run(run_id, course_id, task_type, user, db)
    request_row = await db.scalar(select(AgentHumanRequest).where(
        AgentHumanRequest.id == request_id,
        AgentHumanRequest.pipeline_run_id == pipeline.id,
    ))
    if request_row is None or request_row.status != "pending":
        raise HTTPException(409, "人工确认请求不存在或已处理")

    claimed = await db.execute(
        select(AgentHumanRequest).where(
            AgentHumanRequest.id == request_id,
            AgentHumanRequest.status == "pending",
        )
    )
    row = claimed.scalar_one_or_none()
    if row is None:
        raise HTTPException(409, "人工确认请求已被处理")

    if payload.choice in _CANCEL_CHOICES:
        row.status = "resolved"
        row.resolved_at = datetime.now(timezone.utc)
        row.response_json = {**payload.data, "choice": payload.choice, "resolution": "rejected"}
        pipeline.plan_json = {**(pipeline.plan_json or {}), "result_status": "no_change"}
        pipeline.status = "completed"
        generation.status = "completed"
        generation.finished_at = datetime.now(timezone.utc)
        task = await db.get(CourseTask, generation.course_task_id) if generation.course_task_id else None
        if task:
            task.status = "review" if task.current_agent_profile_id else "stale"
            task.active_run_id = None
            task.completed_at = datetime.now(timezone.utc)
        await db.commit()
        from app.agent.events import PipelineEventEmitter

        emitter = await PipelineEventEmitter.for_run(generation, pipeline, task_type=task_type)
        await emitter.emit_domain("human.resolved", message="教师选择取消本轮，未创建新版本。",
                                  payload={"request_id": request_id, "choice": payload.choice, "resolution": "rejected"})
        await emitter.pipeline_completed(artifact_id="")
        return {"status": "resolved", "resolution": "rejected", "result_status": "no_change", "continuation_run_id": None}

    row.status = "resolved"
    row.resolved_at = datetime.now(timezone.utc)
    row.response_json = {**payload.data, "choice": payload.choice, "resolution": "confirmed"}
    # 颁发一次性确认令牌（同一 Run 的 runtime 校验）。request_type 沿用原
    # checkpoint（task_sheet_confirmation / exercise_confirmation 等），
    # 使该端点可复用于任一按同构 checkpoint 恢复的流水线。
    token = f"confirm-{request_id}"
    pending = (pipeline.checkpoint_json or {}).get("pending_confirmation") or {}
    pipeline.checkpoint_json = {
        **(pipeline.checkpoint_json or {}),
        "pending_confirmation": {
            "request_id": request_id,
            "request_type": pending.get("request_type") or "task_sheet_confirmation",
            "choice": payload.choice,
            "token": token,
        },
    }
    pipeline.status = "queued"
    generation.status = "queued"
    task = await db.get(CourseTask, generation.course_task_id) if generation.course_task_id else None
    if task:
        task.status = "queued"
    await db.commit()
    pause_event = PAUSE_EVENTS.pop(generation.id, None)
    if pause_event is not None:
        pause_event.clear()
    from app.agent.events import PipelineEventEmitter

    emitter = await PipelineEventEmitter.for_run(generation, pipeline, task_type=task_type)
    await emitter.emit_domain("human.resolved", message="教师已确认，继续执行。",
                              payload={"request_id": request_id, "choice": payload.choice, "resolution": "confirmed"})
    start_task_run(generation.id)
    return {"status": "resolved", "resolution": "confirmed", "result_status": "continued", "continuation_run_id": generation.id}
