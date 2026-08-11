"""Run-centric PPT Agent API with compatibility over CourseTask execution."""
import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.event_protocol import canonical_event
from app.agent.events import PipelineEventEmitter
from app.api.deps import current_user, owned_course
from app.api.v1.projects import _owned_task
from app.core.database import SessionLocal, get_db
from app.models.entities import (
    AgentMessage, Artifact, CourseTask, GenerationEvent, GenerationRun, PipelineRun,
    PPTAgentInstruction, PPTHumanRequest, PPTRevision, PPTSlideArtifact,
    PPTSlideRevision, User,
)
from app.services.course_task_service import create_task_run, start_task_run, task_jobs
from app.services.ppt_pipeline_service import PAUSE_EVENTS

router = APIRouter(prefix="/ppt-agent", tags=["PPT Agent Runtime"])

# 前端单页范围选择：modality 非 auto 时在消息前缀加 [范围:布局/文字/图片]，
# 供运行时 _modality_from_instruction 解析并显式覆盖 active_intent。
_MODALITY_SCOPE = {
    "layout": "[范围:布局] ",
    "text": "[范围:文字] ",
    "image": "[范围:图片] ",
}


class CreateRunRequest(BaseModel):
    course_id: str
    instruction: str = Field(default="", max_length=8000)
    action: str = "initial"
    selected_slide_ids: list[str] = Field(default_factory=list, max_length=50)
    modality: str = Field(default="auto", description="auto|layout|text|image")


class InstructionRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    selected_slide_ids: list[str] = Field(default_factory=list, max_length=50)
    resume_if_paused: bool = False
    modality: str = Field(default="auto", description="auto|layout|text|image")


class HumanResponseRequest(BaseModel):
    request_id: str
    choice: str = Field(min_length=1, max_length=200)
    data: dict = Field(default_factory=dict)


class TemplateSwitchRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=120)
    selected_slide_ids: list[str] = Field(default_factory=list, max_length=50)


async def _owned_run(run_id: str, user: User, db: AsyncSession) -> tuple[GenerationRun, PipelineRun]:
    generation = await db.get(GenerationRun, run_id)
    if generation is None:
        pipeline = await db.get(PipelineRun, run_id)
        generation = await db.get(GenerationRun, pipeline.generation_run_id) if pipeline else None
    if generation is None:
        raise HTTPException(404, "PPT Agent Run 不存在")
    await owned_course(generation.course_id, user, db)
    pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == generation.id))
    if pipeline is None:
        raise HTTPException(404, "PPT Agent Runtime 尚未初始化")
    return generation, pipeline


def _run_payload(generation: GenerationRun, pipeline: PipelineRun) -> dict:
    return {
        "id": generation.id, "pipeline_run_id": pipeline.id, "course_id": generation.course_id,
        "status": pipeline.status, "current_agent": pipeline.current_agent,
        "current_step_index": pipeline.current_step_index, "plan": pipeline.plan_json,
        "token_usage": pipeline.token_usage_json, "revision_round": pipeline.revision_round,
        "error": pipeline.error_json,
    }


@router.post("/runs", status_code=202)
async def create_run(payload: CreateRunRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(payload.course_id, "ppt", user, db)
    message = None
    trigger = payload.action
    if payload.instruction:
        if not task.current_artifact_id:
            raise HTTPException(409, "PPT 尚未生成，不能提交修改指令")
        scope = f"[目标页面: {','.join(payload.selected_slide_ids)}] " if payload.selected_slide_ids else ""
        modality_prefix = _MODALITY_SCOPE.get(payload.modality, "")
        message = AgentMessage(
            course_id=payload.course_id, task_id=task.id, module_type="ppt", role="user",
            content=f"{scope}{modality_prefix}{payload.instruction.strip()}", status="pending",
        )
        db.add(message)
        trigger = "message"
    try:
        run = await create_task_run(db, task, trigger, message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {
        "run_id": run.id, "task_id": task.id, "message_id": message.id if message else None,
        "status": "queued", "selected_slide_ids": payload.selected_slide_ids,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    generation, pipeline = await _owned_run(run_id, user, db)
    instructions = list(await db.scalars(select(PPTAgentInstruction).where(PPTAgentInstruction.pipeline_run_id == pipeline.id).order_by(PPTAgentInstruction.created_at)))
    human = list(await db.scalars(select(PPTHumanRequest).where(PPTHumanRequest.pipeline_run_id == pipeline.id, PPTHumanRequest.status == "pending")))
    return {
        **_run_payload(generation, pipeline),
        "instructions": [{"id": x.id, "content": x.content, "selected_slide_ids": x.selected_slide_ids_json, "disposition": x.disposition} for x in instructions],
        "human_requests": [{"id": x.id, "type": x.request_type, "prompt": x.prompt, "options": x.options_json} for x in human],
    }


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request, after: int = Query(0, ge=0), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    generation, _ = await _owned_run(run_id, user, db)
    try:
        last_event_id = int(request.headers.get("Last-Event-ID", "0"))
    except ValueError:
        last_event_id = 0

    async def stream():
        cursor = max(after, last_event_id)
        while True:
            async with SessionLocal() as session:
                rows = list(await session.scalars(select(GenerationEvent).where(GenerationEvent.run_id == generation.id, GenerationEvent.id > cursor).order_by(GenerationEvent.id).limit(200)))
                current = await session.get(GenerationRun, generation.id)
            for row in rows:
                cursor = row.id
                event = canonical_event(event_id=row.id, event_type=row.event_type, data=row.data_json, created_at=row.created_at)
                yield f"id: {row.id}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if current is None or current.status in {"completed", "failed", "cancelled"} or await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/instructions", status_code=202)
async def enqueue_instruction(run_id: str, payload: InstructionRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    generation, pipeline = await _owned_run(run_id, user, db)
    if pipeline.status not in {"queued", "running", "pausing", "paused"}:
        raise HTTPException(409, "当前 Run 已结束，请创建新的修改 Run")
    modality_prefix = _MODALITY_SCOPE.get(payload.modality, "")
    content = f"{modality_prefix}{payload.content.strip()}"
    row = PPTAgentInstruction(pipeline_run_id=pipeline.id, user_id=user.id, content=content, selected_slide_ids_json=payload.selected_slide_ids, disposition="queued")
    user_message = AgentMessage(
        course_id=generation.course_id,
        task_id=generation.course_task_id,
        run_id=generation.id,
        module_type="ppt",
        role="user",
        content=content,
        status="completed",
    )
    db.add(row)
    db.add(user_message)
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
        "id": user_message.id,
        "role": "user",
        "content": user_message.content,
        "run_id": generation.id,
        "status": "completed",
    }
    await db.commit()
    emitter = await PipelineEventEmitter.for_run(generation, pipeline)
    await emitter.emit_domain("run.instruction.queued", message=(
        "教师指令已加入执行队列并恢复运行" if should_resume else "教师指令已加入执行队列"
    ), payload={
        "instruction_id": instruction_id,
        "selected_slide_ids": payload.selected_slide_ids,
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


@router.post("/runs/{run_id}/pause", status_code=202)
async def pause_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    generation, pipeline = await _owned_run(run_id, user, db)
    if pipeline.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "当前 Run 已结束")
    PAUSE_EVENTS[generation.id] = PAUSE_EVENTS.get(generation.id) or asyncio.Event()
    PAUSE_EVENTS[generation.id].set()
    job = task_jobs.get(generation.id)
    next_status = "pausing" if job is not None and not job.done() else "paused"
    generation.status = next_status
    pipeline.status = next_status
    task = await db.get(CourseTask, generation.course_task_id) if generation.course_task_id else None
    if task:
        task.status = next_status
    await db.commit()
    if next_status == "pausing" and job is not None:
        job.cancel()
    return {"run_id": generation.id, "status": next_status}


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    generation, pipeline = await _owned_run(run_id, user, db)
    if pipeline.status != "paused":
        raise HTTPException(409, "当前 Run 不在暂停状态")
    event = PAUSE_EVENTS.pop(generation.id, None)
    if event:
        event.clear()
    generation.status = pipeline.status = "queued"
    task = await db.get(CourseTask, generation.course_task_id) if generation.course_task_id else None
    if task:
        task.status = "queued"
    await db.commit()
    start_task_run(generation.id)
    return {"run_id": generation.id, "status": "resumed"}


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    generation, pipeline = await _owned_run(run_id, user, db)
    job = task_jobs.get(generation.id)
    if job:
        job.cancel()
    generation.status = pipeline.status = "cancelled"
    generation.finished_at = datetime.now(timezone.utc)
    task = await db.get(CourseTask, generation.course_task_id) if generation.course_task_id else None
    if task:
        task.status, task.active_run_id = "cancelled", None
    await db.commit()
    return {"run_id": generation.id, "status": "cancelled"}


@router.post("/runs/{run_id}/human-response")
async def human_response(run_id: str, payload: HumanResponseRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    _, pipeline = await _owned_run(run_id, user, db)
    row = await db.get(PPTHumanRequest, payload.request_id)
    if row is None or row.pipeline_run_id != pipeline.id or row.status != "pending":
        raise HTTPException(404, "待处理的人机协作请求不存在")
    row.status, row.response_json = "resolved", {"choice": payload.choice, "data": payload.data, "user_id": user.id}
    row.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"request_id": row.id, "status": "resolved"}


@router.get("/artifacts/{artifact_id}/slides")
async def artifact_slides(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "PPT Artifact 不存在")
    await owned_course(artifact.course_id, user, db)
    revision = await db.scalar(select(PPTRevision).where(PPTRevision.artifact_id == artifact.id))
    if revision is None:
        return {"artifact_id": artifact.id, "revision": None, "slides": []}
    slides = list(await db.scalars(select(PPTSlideArtifact).where(PPTSlideArtifact.ppt_revision_id == revision.id).order_by(PPTSlideArtifact.page_number)))
    return {"artifact_id": artifact.id, "revision": revision.version, "template_id": revision.template_id, "slides": [{"id": x.id, "slide_id": x.slide_id, "page_number": x.page_number, "revision": x.current_revision, "status": x.status, "qa_status": x.qa_status, "preview_url": x.preview_url, "data": x.data_json} for x in slides]}


@router.get("/slides/{slide_id}/revisions")
async def slide_revisions(slide_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    slide = await db.get(PPTSlideArtifact, slide_id)
    if slide is None:
        raise HTTPException(404, "Slide Artifact 不存在")
    revision = await db.get(PPTRevision, slide.ppt_revision_id)
    await owned_course(revision.course_id, user, db)
    related_slide_ids = list(await db.scalars(
        select(PPTSlideArtifact.id).join(PPTRevision, PPTRevision.id == PPTSlideArtifact.ppt_revision_id).where(
            PPTRevision.course_id == revision.course_id,
            PPTSlideArtifact.slide_id == slide.slide_id,
        )
    ))
    rows = list(await db.scalars(select(PPTSlideRevision).where(PPTSlideRevision.slide_artifact_id.in_(related_slide_ids)).order_by(PPTSlideRevision.revision.desc())))
    return {"slide_id": slide.slide_id, "revisions": [{"id": x.id, "revision": x.revision, "data": x.data_json, "diff": x.diff_json, "summary": x.change_summary, "created_at": x.created_at.isoformat()} for x in rows]}


@router.post("/artifacts/{artifact_id}/template-switch", status_code=202)
async def switch_template(artifact_id: str, payload: TemplateSwitchRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None or artifact.artifact_type != "ppt":
        raise HTTPException(404, "PPT Artifact 不存在")
    await owned_course(artifact.course_id, user, db)
    task = await _owned_task(artifact.course_id, "ppt", user, db)
    message = AgentMessage(course_id=artifact.course_id, task_id=task.id, module_type="ppt", role="user", content=f"切换模板为 {payload.template_id}，保留当前内容和视觉资源并重新布局。", status="pending")
    db.add(message)
    try:
        run = await create_task_run(db, task, "message", message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {"run_id": run.id, "status": "queued", "template_id": payload.template_id, "selected_slide_ids": payload.selected_slide_ids}
