"""Run-centric PPT Agent API with compatibility over CourseTask execution."""
import asyncio
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.event_protocol import canonical_event
from app.agent.events import PipelineEventEmitter
from app.api.deps import current_user, owned_course
from app.api.v1.projects import _owned_task, _validated_chat_attachment_metadata
from app.core.database import SessionLocal, get_db
from app.models.entities import (
    AgentMessage, Artifact, CourseTask, GenerationEvent, GenerationRun, PipelineRun,
    PPTAgentInstruction, PPTHumanRequest, PPTRevision, PPTSlideArtifact,
    PPTSlideRevision, User,
)
from app.services.course_task_service import create_task_run, start_task_run, task_jobs
from app.services.ppt_pipeline_service import PAUSE_EVENTS, _workspace_root

router = APIRouter(prefix="/ppt-agent", tags=["PPT Agent Runtime"])


class PolishOptions(BaseModel):
    strength: Literal["subtle", "moderate", "strong"] | None = None
    content_policy: Literal["preserve", "edit"] | None = None
    image_policy: Literal["preserve", "geometry", "replace"] | None = None
    page_count_policy: Literal["preserve", "allow_change"] | None = None
    preserve_text: bool | None = None
    preserve_images: bool | None = None
    preserve_notes: bool | None = None
    preserve_page_count: bool | None = None
    confirmation_token: str | None = Field(default=None, max_length=300)

class CreateRunRequest(BaseModel):
    course_id: str
    instruction: str = Field(default="", max_length=8000)
    action: str = "initial"
    selected_slide_ids: list[str] = Field(default_factory=list, max_length=50)
    target_slide_ids: list[str] = Field(default_factory=list, max_length=50)
    modality: str = Field(default="auto", description="auto|layout|text|image")
    active_slide_id: str | None = Field(default=None, max_length=120)
    polish_options: PolishOptions = Field(default_factory=PolishOptions)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


class InstructionRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    selected_slide_ids: list[str] = Field(default_factory=list, max_length=50)
    target_slide_ids: list[str] = Field(default_factory=list, max_length=50)
    resume_if_paused: bool = False
    modality: str = Field(default="auto", description="auto|layout|text|image")
    active_slide_id: str | None = Field(default=None, max_length=120)
    polish_options: PolishOptions = Field(default_factory=PolishOptions)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


class HumanResponseRequest(BaseModel):
    request_id: str
    choice: str = Field(min_length=1, max_length=200)
    data: dict = Field(default_factory=dict)


class TemplateSwitchRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=120)
    selected_slide_ids: list[str] = Field(default_factory=list, max_length=50)


def _target_slide_ids(payload: CreateRunRequest | InstructionRequest) -> list[str]:
    """New field wins; selected_slide_ids remains a wire-compatible alias."""
    values = payload.target_slide_ids or payload.selected_slide_ids
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _message_metadata(payload: CreateRunRequest | InstructionRequest, attachments: list[dict[str, Any]] | None = None) -> dict:
    targets = _target_slide_ids(payload)
    metadata = {
        "target_slide_ids": targets,
        "selected_slide_ids": targets,
        "active_slide_id": payload.active_slide_id,
        "modality": payload.modality,
        "polish_options": payload.polish_options.model_dump(exclude_none=True),
    }
    if attachments:
        metadata["attachments"] = attachments
    return metadata


_NO_CHANGE_HUMAN_CHOICES = {
    "cancel", "discard", "edit", "keep", "no_change", "none", "reject",
}
_CONTINUABLE_HUMAN_REQUESTS = {
    "candidate_selection", "layout_candidate_selection",
    "polish_candidate_confirmation", "polish_intent_confirmation",
}


def _human_option(row: PPTHumanRequest, choice: str) -> dict[str, Any] | None:
    return next(
        (
            dict(option)
            for option in (row.options_json or [])
            if str((option or {}).get("id") or "") == choice
        ),
        None,
    )


def _confirmed_modality(resolved_command: dict[str, Any]) -> str:
    domains = {
        str(item.get("domain") or "")
        for item in (resolved_command.get("operations") or [])
        if isinstance(item, dict)
    }
    if domains and domains <= {"text"}:
        return "text"
    if domains and domains <= {"image_asset", "image_geometry"}:
        return "image"
    if domains and domains <= {"layout", "typography", "style"}:
        return "layout"
    return "auto"


def _confirmed_instruction(resolved_command: dict[str, Any], fallback: str) -> str:
    """Create an unambiguous execution turn from the reviewed command.

    Page scope remains structured metadata.  In particular, we must not replay
    a raw sentence whose page reference conflicted with the UI selection, or
    the deterministic resolver would correctly request the same confirmation
    again.
    """
    explicit = str(resolved_command.get("execution_instruction") or "").strip()
    if explicit:
        return explicit[:8000]
    operation_labels = {
        "layout": "重新排版并优化页面布局",
        "typography": "调整字号和字体",
        "text": "润色文字表达",
        "image_asset": "替换图片素材",
        "image_geometry": "调整图片大小和位置",
        "style": "优化配色、对比度和视觉层级",
        "template": "优化页面模板",
        "notes": "调整教师讲解备注",
        "timing": "调整页面讲解时长",
        "restore": "恢复上一版本",
        "qa": "检查页面质量",
        "export": "导出课件",
    }
    objective_labels = {
        "font_size": {"increase": "放大正文字号", "decrease": "缩小字号", "optimize": "优化字号"},
        "vertical_utilization": {"increase": "提高纵向空间利用率", "optimize": "优化纵向空间利用率"},
        "horizontal_utilization": {"increase": "提高横向空间利用率", "optimize": "优化横向空间利用率"},
        "whitespace_balance": {"increase": "改善留白平衡", "decrease": "减少过多留白", "optimize": "改善留白平衡"},
        "spacing": {"increase": "增大间距", "decrease": "收紧间距", "optimize": "优化间距"},
        "alignment": {"optimize": "优化对齐"},
        "density": {"decrease": "降低内容密度", "optimize": "优化内容密度"},
        "image_scale": {"increase": "放大图片", "decrease": "缩小图片", "optimize": "优化图片大小"},
        "contrast": {"increase": "增强对比度", "optimize": "优化对比度"},
    }
    clauses: list[str] = []
    for operation in resolved_command.get("operations") or []:
        if isinstance(operation, dict):
            label = operation_labels.get(str(operation.get("domain") or ""))
            if label and label not in clauses:
                clauses.append(label)
    for objective in resolved_command.get("objectives") or []:
        if not isinstance(objective, dict):
            continue
        labels = objective_labels.get(str(objective.get("metric") or ""), {})
        label = labels.get(str(objective.get("direction") or "optimize")) or labels.get("optimize")
        if label and label not in clauses:
            clauses.append(label)
    if clauses:
        return "请" + "，并".join(clauses) + "；严格保留已确认的页面范围和保护项。"
    # This fallback is retained for old human-request rows that predate the V2
    # resolved-command snapshot.  Such rows are resolved, but are not treated
    # as automatically continuable below unless their request type opts in.
    return (str(resolved_command.get("raw_text") or fallback).strip() or fallback)[:8000]


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
    plan = pipeline.plan_json or {}
    return {
        "id": generation.id, "pipeline_run_id": pipeline.id, "course_id": generation.course_id,
        "status": pipeline.status, "current_agent": pipeline.current_agent,
        "current_step_index": pipeline.current_step_index, "plan": plan,
        "token_usage": pipeline.token_usage_json, "revision_round": pipeline.revision_round,
        "error": pipeline.error_json,
        "resolved_request": plan.get("resolved_request"),
        "change_set": plan.get("change_set"),
        "diagnostics": plan.get("diagnostics") or [],
        "fallback_used": bool(plan.get("fallback_used")),
        "result_status": plan.get("result_status"),
    }


@router.post("/runs", status_code=202)
async def create_run(payload: CreateRunRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(payload.course_id, "ppt", user, db)
    message = None
    trigger = payload.action
    targets = _target_slide_ids(payload)
    if payload.instruction:
        if not task.current_artifact_id:
            raise HTTPException(409, "PPT 尚未生成，不能提交修改指令")
        attachment_meta = await _validated_chat_attachment_metadata(db, user, payload.course_id, payload.attachment_ids)
        message = AgentMessage(
            course_id=payload.course_id, task_id=task.id, module_type="ppt", role="user",
            content=payload.instruction.strip(), metadata_json=_message_metadata(payload, attachment_meta.get("attachments")), status="pending",
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
        "status": "queued", "selected_slide_ids": targets, "target_slide_ids": targets,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    generation, pipeline = await _owned_run(run_id, user, db)
    instructions = list(await db.scalars(select(PPTAgentInstruction).where(PPTAgentInstruction.pipeline_run_id == pipeline.id).order_by(PPTAgentInstruction.created_at)))
    human = list(await db.scalars(select(PPTHumanRequest).where(PPTHumanRequest.pipeline_run_id == pipeline.id, PPTHumanRequest.status == "pending")))
    return {
        **_run_payload(generation, pipeline),
        "instructions": [{
            "id": x.id, "content": x.content,
            "selected_slide_ids": x.selected_slide_ids_json,
            "target_slide_ids": x.selected_slide_ids_json,
            "request_metadata": (x.result_json or {}).get("request_metadata") or {},
            "disposition": x.disposition,
        } for x in instructions],
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
    targets = _target_slide_ids(payload)
    attachment_meta = await _validated_chat_attachment_metadata(db, user, generation.course_id, payload.attachment_ids)
    metadata = _message_metadata(payload, attachment_meta.get("attachments"))
    content = payload.content.strip()
    row = PPTAgentInstruction(
        pipeline_run_id=pipeline.id, user_id=user.id, content=content,
        selected_slide_ids_json=targets, disposition="queued",
        result_json={"request_metadata": metadata},
    )
    user_message = AgentMessage(
        course_id=generation.course_id,
        task_id=generation.course_task_id,
        run_id=generation.id,
        module_type="ppt",
        role="user",
        content=content,
        metadata_json=metadata,
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
        "metadata": user_message.metadata_json or {},
    }
    await db.commit()
    emitter = await PipelineEventEmitter.for_run(generation, pipeline)
    await emitter.emit_domain("run.instruction.queued", message=(
        "教师指令已加入执行队列并恢复运行" if should_resume else "教师指令已加入执行队列"
    ), payload={
        "instruction_id": instruction_id,
        "selected_slide_ids": targets,
        "target_slide_ids": targets,
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
    generation, pipeline = await _owned_run(run_id, user, db)
    row = await db.get(PPTHumanRequest, payload.request_id)
    if row is None or row.pipeline_run_id != pipeline.id or row.status != "pending":
        raise HTTPException(404, "待处理的人机协作请求不存在")

    option = _human_option(row, payload.choice)
    if row.options_json and option is None:
        raise HTTPException(422, "选择项不属于当前人机协作请求")

    previous_response = dict(row.response_json or {})
    resolved_command = dict(previous_response.get("resolved_command") or {})
    option_action = str((option or {}).get("action") or "")
    rejected = payload.choice in _NO_CHANGE_HUMAN_CHOICES or option_action in {
        "cancel", "edit", "keep", "no_change", "reject",
    }
    continuable = row.request_type in _CONTINUABLE_HUMAN_REQUESTS
    requested_candidate_id = str((payload.data or {}).get("candidate_id") or "").strip()
    option_candidate_id = str(
        (option or {}).get("candidate_id")
        or ((option or {}).get("id") if "candidate" in row.request_type else "")
        or ""
    ).strip()
    if requested_candidate_id and option is not None:
        if requested_candidate_id != option_candidate_id:
            raise HTTPException(422, "候选方案与选择项不一致")
    selected_candidate_id = option_candidate_id or requested_candidate_id or None

    confirmation_token = secrets.token_urlsafe(24)
    resolution = {
        **previous_response,
        "choice": payload.choice,
        "data": payload.data,
        "user_id": user.id,
        "confirmation_token": confirmation_token,
        "selected_candidate_id": selected_candidate_id,
        "source_run_id": generation.id,
    }

    # Claim the response atomically.  Row-level ``FOR UPDATE`` is ignored by
    # SQLite, while this conditional UPDATE also protects production databases
    # and prevents two fast clicks from spawning two continuation runs.
    claimed = await db.execute(
        update(PPTHumanRequest).where(
            PPTHumanRequest.id == row.id,
            PPTHumanRequest.status == "pending",
        ).values(status="processing")
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "该人机协作请求已被处理")
    row.status = "processing"

    # Rejection is a successful no-op.  The original needs-confirmation run
    # has already skipped publication, so resolving it must not create either
    # a continuation run or an empty Artifact version.
    if rejected or not continuable:
        resolution["resolution"] = (
            "rejected" if rejected else "manual_review" if payload.choice == "review" else "resolved"
        )
        row.status = "resolved"
        row.response_json = resolution
        row.resolved_at = datetime.now(timezone.utc)
        pipeline.plan_json = {
            **(pipeline.plan_json or {}),
            "result_status": "no_change",
            "human_resolution": {
                "request_id": row.id,
                "choice": payload.choice,
                "resolution": resolution["resolution"],
            },
        }
        await db.commit()
        return {
            "request_id": row.id,
            "status": "resolved",
            "resolution": resolution["resolution"],
            "result_status": "no_change",
            "continuation_run_id": None,
        }

    task = await db.get(CourseTask, generation.course_task_id) if generation.course_task_id else None
    if task is None:
        raise HTTPException(409, "原 Run 未关联可继续执行的 PPT 任务")
    if not task.current_artifact_id:
        raise HTTPException(409, "PPT 尚未生成，不能继续润色确认")

    original_message = await db.scalar(select(AgentMessage).where(
        AgentMessage.run_id == generation.id,
        AgentMessage.role == "user",
    ).order_by(AgentMessage.created_at.desc()))
    original_metadata = dict(getattr(original_message, "metadata_json", None) or {})
    scope = dict(resolved_command.get("scope") or {})
    confirmed_all_scope = scope.get("source") == "all"
    target_slide_ids = list(dict.fromkeys(
        str(value) for value in (scope.get("target_slide_ids") or []) if str(value)
    ))
    reference_slide_ids = list(dict.fromkeys(
        str(value) for value in (scope.get("reference_slide_ids") or []) if str(value)
    ))
    if not target_slide_ids and not confirmed_all_scope:
        # Candidate requests produced after compilation may keep their target
        # in the option rather than in a full ResolvedPolishCommand snapshot.
        target_slide_ids = list(dict.fromkeys(
            str(value)
            for value in (
                (option or {}).get("target_slide_ids")
                or previous_response.get("target_slide_ids")
                or original_metadata.get("target_slide_ids")
                or original_metadata.get("selected_slide_ids")
                or []
            )
            if str(value)
        ))
    if not target_slide_ids and not confirmed_all_scope:
        raise HTTPException(409, "确认请求缺少可验证的目标页面范围")

    polish_options = dict(original_metadata.get("polish_options") or {})
    preservation = dict(resolved_command.get("preservation") or {})
    if preservation:
        polish_options.update({
            "preserve_text": bool(preservation.get("semantic_text", True)),
            "preserve_images": bool(preservation.get("images_and_assets", True)),
            "preserve_notes": bool(preservation.get("notes", True)),
            "preserve_page_count": bool(preservation.get("page_count", True)),
        })
    polish_options["confirmation_token"] = confirmation_token
    execution_instruction = _confirmed_instruction(resolved_command, row.prompt)
    command_fields = {
        "raw_text", "turn_relation", "scope", "operations", "objectives",
        "preservation", "confidence", "ambiguities", "needs_confirmation", "summary",
    }
    confirmed_resolved_command = {
        **{key: value for key, value in resolved_command.items() if key in command_fields},
        "raw_text": execution_instruction,
        "confidence": 1.0,
        "ambiguities": [],
        "needs_confirmation": False,
        "summary": str(resolved_command.get("summary") or row.prompt).replace(
            "；执行前需要确认", "",
        ),
    }
    continuation_metadata = {
        **original_metadata,
        "target_slide_ids": target_slide_ids,
        "selected_slide_ids": target_slide_ids,
        "reference_slide_ids": reference_slide_ids,
        "active_slide_id": target_slide_ids[0] if len(target_slide_ids) == 1 else None,
        "modality": _confirmed_modality(resolved_command),
        "polish_options": polish_options,
        "human_confirmation": {
            "request_id": row.id,
            "source_run_id": generation.id,
            "request_type": row.request_type,
            "choice": payload.choice,
            "confirmation_token": confirmation_token,
            "selected_candidate_id": selected_candidate_id,
        },
        # This snapshot differs from the audit copy kept on PPTHumanRequest:
        # the teacher has now explicitly resolved its ambiguities.  A runtime
        # may consume it only after validating the server-issued token/link.
        "confirmed_resolved_command": confirmed_resolved_command,
        "selected_candidate_id": selected_candidate_id,
        "selected_candidate": (
            dict((option or {}).get("candidate") or {}) if selected_candidate_id else None
        ),
    }
    continuation_message = AgentMessage(
        course_id=generation.course_id,
        task_id=task.id,
        module_type="ppt",
        role="user",
        content=execution_instruction,
        metadata_json=continuation_metadata,
        status="pending",
    )
    db.add(continuation_message)
    try:
        continuation_run = await create_task_run(db, task, "message", continuation_message)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc

    resolution.update({
        "resolution": "continued",
        "continuation_run_id": continuation_run.id,
        "continuation_message_id": continuation_message.id,
        "resolved_command": confirmed_resolved_command,
    })
    row.status = "resolved"
    row.response_json = resolution
    row.resolved_at = datetime.now(timezone.utc)
    pipeline.plan_json = {
        **(pipeline.plan_json or {}),
        "human_resolution": {
            "request_id": row.id,
            "choice": payload.choice,
            "resolution": "continued",
            "continuation_run_id": continuation_run.id,
            "selected_candidate_id": selected_candidate_id,
        },
    }
    await db.commit()
    start_task_run(continuation_run.id)
    return {
        "request_id": row.id,
        "status": "resolved",
        "resolution": "continued",
        "result_status": "queued",
        "run_id": continuation_run.id,
        "continuation_run_id": continuation_run.id,
        "message_id": continuation_message.id,
        "confirmation_token": confirmation_token,
        "selected_candidate_id": selected_candidate_id,
        "target_slide_ids": target_slide_ids,
    }


@router.get("/runs/{run_id}/candidate-previews/{request_id}/{option_id}")
async def candidate_preview(
    run_id: str, request_id: str, option_id: str,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    generation, pipeline = await _owned_run(run_id, user, db)
    request = await db.get(PPTHumanRequest, request_id)
    if request is None or request.pipeline_run_id != pipeline.id:
        raise HTTPException(404, "候选预览不存在")
    option = _human_option(request, option_id)
    raw_path = str((option or {}).get("render_path") or "")
    if not raw_path:
        raise HTTPException(404, "候选预览尚未生成")
    path = Path(raw_path).resolve()
    root = _workspace_root(generation.course_id, generation.id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(403, "候选预览路径无效") from exc
    if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(404, "候选预览文件不存在")
    return FileResponse(path, media_type=f"image/{'jpeg' if path.suffix.lower() in {'.jpg', '.jpeg'} else path.suffix[1:]}")


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
    targets = list(dict.fromkeys(str(value) for value in payload.selected_slide_ids if str(value)))
    message = AgentMessage(
        course_id=artifact.course_id, task_id=task.id, module_type="ppt", role="user",
        content=f"切换模板为 {payload.template_id}，保留当前内容和视觉资源并重新布局。",
        metadata_json={
            "target_slide_ids": targets,
            "selected_slide_ids": targets,
            "active_slide_id": targets[0] if len(targets) == 1 else None,
            "modality": "auto",
            "polish_options": {
                "content_policy": "preserve", "image_policy": "preserve",
                "page_count_policy": "preserve",
            },
        },
        status="pending",
    )
    db.add(message)
    try:
        run = await create_task_run(db, task, "message", message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    start_task_run(run.id)
    return {
        "run_id": run.id, "status": "queued", "template_id": payload.template_id,
        "selected_slide_ids": targets, "target_slide_ids": targets,
    }
