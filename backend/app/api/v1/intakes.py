import asyncio
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.security import create_stream_token, decode_stream_token
from app.models.entities import (
    CourseIntakeEvent,
    CourseIntakeMessage,
    CourseIntakeRevision,
    CourseIntakeSession,
    CourseIntakeTurn,
    CourseProject,
    CourseRequirement,
    GenerationRun,
    Material,
    User,
)
from app.schemas.intake import (
    IntakeConfirm,
    IntakeCreate,
    IntakeDraft,
    IntakeDraftPatch,
    IntakeMessageCreate,
    IntakeModelUpdate,
    REQUIRED_INTAKE_FIELDS,
)
from app.services.project_planning_service import start_blueprint_run
from app.services.course_task_service import ensure_course_tasks, task_payload
from app.services.intake_service import start_intake_turn
from app.services.material_service import extract_text, safe_filename, save_upload
from app.services.model_config_service import owned_model_config, resolve_model_config

router = APIRouter(prefix="/course-intakes", tags=["课程需求会话"])
ALLOWED_EDIT_FIELDS = set(IntakeDraft.model_fields)


async def owned_intake(session_id: str, user: User, db: AsyncSession) -> CourseIntakeSession:
    item = await db.get(CourseIntakeSession, session_id)
    if not item or item.owner_id != user.id:
        raise HTTPException(404, "需求会话不存在")
    return item


async def owned_turn(turn_id: str, user: User, db: AsyncSession) -> CourseIntakeTurn:
    turn = await db.get(CourseIntakeTurn, turn_id)
    if not turn:
        raise HTTPException(404, "需求分析任务不存在")
    await owned_intake(turn.session_id, user, db)
    return turn


async def active_turn_id(session_id: str, db: AsyncSession) -> str | None:
    turn = await db.scalar(
        select(CourseIntakeTurn).where(
            CourseIntakeTurn.session_id == session_id,
            CourseIntakeTurn.status.in_(("queued", "running")),
        ).order_by(CourseIntakeTurn.created_at.desc())
    )
    return turn.id if turn else None


async def serialize_session(item: CourseIntakeSession, db: AsyncSession):
    effective_config = await resolve_model_config(db, item.owner_id, item.model_config_id)
    latest_turn = await db.scalar(
        select(CourseIntakeTurn)
        .where(CourseIntakeTurn.session_id == item.id)
        .order_by(CourseIntakeTurn.created_at.desc())
    )
    last_failure = None
    if latest_turn and latest_turn.status == "failed":
        stored = latest_turn.error_json or {}
        last_failure = {
            "turn_id": latest_turn.id,
            "code": stored.get("code", "intake_internal_error"),
            "message": stored.get("message", "需求分析暂时失败，请重试或切换模型。")
            if stored.get("code")
            else "需求分析暂时失败，请重试或切换模型。",
            "retryable": bool(stored.get("retryable", True)),
        }
    return {
        "id": item.id,
        "status": item.status,
        "current_revision": item.current_revision,
        "draft": item.draft_json,
        "field_sources": item.field_sources_json,
        "missing_fields": item.missing_fields_json,
        "assumptions": item.assumptions_json,
        "conflicts": item.conflicts_json,
        "course_id": item.course_id,
        "active_turn_id": await active_turn_id(item.id, db),
        "model_config_id": effective_config.id if effective_config else None,
        "last_failure": last_failure,
    }


@router.post("", status_code=201)
async def create_intake(
    payload: IntakeCreate | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    requested_id = payload.model_config_id if payload else None
    if requested_id:
        await owned_model_config(db, user.id, requested_id)
    selected_config = await resolve_model_config(db, user.id, requested_id)
    item = CourseIntakeSession(
        owner_id=user.id,
        model_config_id=selected_config.id if selected_config else None,
        draft_json={},
        field_sources_json={},
        missing_fields_json=list(REQUIRED_INTAKE_FIELDS),
        assumptions_json=[],
        conflicts_json=[],
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return await serialize_session(item, db)


@router.get("/{session_id}")
async def get_intake(session_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await serialize_session(await owned_intake(session_id, user, db), db)


@router.patch("/{session_id}/model")
async def update_intake_model(
    session_id: str,
    payload: IntakeModelUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await owned_intake(session_id, user, db)
    if item.status in {"completed", "abandoned", "converting"}:
        raise HTTPException(409, "当前需求会话不能切换模型")
    if await active_turn_id(session_id, db):
        raise HTTPException(409, "需求 Agent 正在处理消息，完成后才能切换模型")
    config = await owned_model_config(db, user.id, payload.model_config_id)
    item.model_config_id = config.id
    await db.commit()
    return await serialize_session(item, db)


@router.delete("/{session_id}", status_code=204)
async def abandon_intake(session_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await owned_intake(session_id, user, db)
    if item.status == "completed":
        raise HTTPException(409, "已创建课程的需求会话不能放弃")
    item.status = "abandoned"
    await db.commit()


@router.get("/{session_id}/messages")
async def intake_messages(session_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_intake(session_id, user, db)
    rows = list(await db.scalars(
        select(CourseIntakeMessage).where(CourseIntakeMessage.session_id == session_id).order_by(CourseIntakeMessage.created_at)
    ))
    return [{"id": row.id, "turn_id": row.turn_id, "role": row.role, "content": row.content, "created_at": row.created_at} for row in rows]


@router.post("/{session_id}/messages", status_code=202)
async def send_intake_message(session_id: str, payload: IntakeMessageCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await owned_intake(session_id, user, db)
    if item.status in {"completed", "abandoned", "converting"}:
        raise HTTPException(409, "当前需求会话不能继续发送消息")
    if payload.expected_revision != item.current_revision:
        raise HTTPException(409, "需求已更新，请刷新后重试")
    if await active_turn_id(session_id, db):
        raise HTTPException(409, "需求 Agent 正在处理上一条消息")
    turn = CourseIntakeTurn(session_id=session_id, status="queued")
    db.add(turn)
    await db.flush()
    db.add(CourseIntakeMessage(session_id=session_id, turn_id=turn.id, role="user", content=payload.content.strip()))
    item.status = "processing"
    await db.commit()
    start_intake_turn(turn.id)
    return {"turn_id": turn.id, "status": turn.status}


@router.post("/turns/{turn_id}/retry", status_code=202)
async def retry_intake_turn(
    turn_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    failed_turn = await owned_turn(turn_id, user, db)
    item = await owned_intake(failed_turn.session_id, user, db)
    if item.status in {"completed", "abandoned", "converting"}:
        raise HTTPException(409, "当前需求会话不能重试")
    if await active_turn_id(item.id, db):
        raise HTTPException(409, "需求 Agent 正在处理其他消息")
    latest_turn = await db.scalar(
        select(CourseIntakeTurn)
        .where(CourseIntakeTurn.session_id == item.id)
        .order_by(CourseIntakeTurn.created_at.desc())
    )
    if not latest_turn or latest_turn.id != failed_turn.id or failed_turn.status != "failed":
        raise HTTPException(409, "只能重试该会话最新的失败任务")
    retry_turn = CourseIntakeTurn(session_id=item.id, status="queued")
    db.add(retry_turn)
    await db.flush()
    item.status = "processing"
    await db.commit()
    start_intake_turn(retry_turn.id)
    return {"turn_id": retry_turn.id, "status": retry_turn.status}


@router.patch("/{session_id}/draft")
async def patch_intake_draft(session_id: str, payload: IntakeDraftPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await owned_intake(session_id, user, db)
    if payload.expected_revision != item.current_revision:
        raise HTTPException(409, "需求已更新，请刷新后重试")
    if payload.field not in ALLOWED_EDIT_FIELDS:
        raise HTTPException(422, "不支持编辑该字段")
    next_draft = dict(item.draft_json)
    if payload.value in (None, ""):
        next_draft.pop(payload.field, None)
    else:
        next_draft[payload.field] = payload.value
    validated = IntakeDraft.model_validate(next_draft).model_dump(exclude_none=True)
    missing = [field for field in REQUIRED_INTAKE_FIELDS if not validated.get(field)]
    assumptions = [entry for entry in item.assumptions_json if entry.get("field") != payload.field]
    sources = dict(item.field_sources_json)
    sources[payload.field] = "manual"
    blocking = any(entry.get("severity") == "blocking" for entry in item.conflicts_json)
    version = item.current_revision + 1
    item.current_revision = version
    item.draft_json = validated
    item.field_sources_json = sources
    item.missing_fields_json = missing
    item.assumptions_json = assumptions
    item.status = "ready" if not missing and not blocking else "collecting"
    db.add(CourseIntakeRevision(
        session_id=item.id,
        version=version,
        draft_json=validated,
        field_sources_json=sources,
        missing_fields_json=missing,
        assumptions_json=assumptions,
        conflicts_json=item.conflicts_json,
        source="manual",
    ))
    db.add(CourseIntakeMessage(session_id=item.id, role="system", content=f"教师修正了字段：{payload.field}"))
    await db.commit()
    return await serialize_session(item, db)


def material_output(item: Material):
    return {key: getattr(item, key) for key in ("id", "course_id", "intake_session_id", "original_filename", "mime_type", "size_bytes", "usage_policy", "parse_status", "summary", "error_message", "created_at")}


@router.post("/{session_id}/materials", status_code=201)
async def upload_intake_material(
    session_id: str,
    file: UploadFile = File(...),
    usage_policy: str = Form("priority_reference"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await owned_intake(session_id, user, db)
    if item.status in {"completed", "abandoned", "converting"}:
        raise HTTPException(409, "当前需求会话不能上传材料")
    settings = get_settings()
    path, size, checksum = await save_upload(file, settings.storage_root / "uploads", settings.max_upload_mb * 1024 * 1024)
    material = Material(
        course_id=None,
        intake_session_id=session_id,
        original_filename=safe_filename(file.filename or "material"),
        storage_name=path.name,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        usage_policy=usage_policy,
        checksum=checksum,
    )
    db.add(material)
    await db.flush()
    try:
        text, chunks = extract_text(path)
        material.parse_status = "completed"
        material.summary = text[:500] + ("…" if len(text) > 500 else "")
        from app.models.entities import MaterialChunk
        db.add_all([MaterialChunk(material_id=material.id, chunk_index=index, **chunk) for index, chunk in enumerate(chunks)])
    except Exception as exc:
        material.parse_status = "failed"
        material.error_message = str(exc)
    await db.commit()
    await db.refresh(material)
    return material_output(material)


@router.get("/{session_id}/materials")
async def list_intake_materials(session_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_intake(session_id, user, db)
    rows = list(await db.scalars(select(Material).where(Material.intake_session_id == session_id).order_by(Material.created_at)))
    return [material_output(row) for row in rows]


@router.post("/turns/{turn_id}/stream-token")
async def intake_stream_token(turn_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_turn(turn_id, user, db)
    return {"token": create_stream_token(user.id, turn_id), "expires_in": 300}


@router.get("/turns/{turn_id}/events")
async def intake_events(turn_id: str, token: str, after: int = 0):
    user_id = decode_stream_token(token, turn_id)
    async with SessionLocal() as db:
        turn = await db.get(CourseIntakeTurn, turn_id)
        session = await db.get(CourseIntakeSession, turn.session_id) if turn else None
        if not turn or not session or session.owner_id != user_id:
            raise HTTPException(404, "需求分析任务不存在")

    async def stream():
        cursor = after
        idle = 0
        while idle < 600:
            async with SessionLocal() as db:
                rows = list(await db.scalars(
                    select(CourseIntakeEvent).where(CourseIntakeEvent.turn_id == turn_id, CourseIntakeEvent.id > cursor).order_by(CourseIntakeEvent.id)
                ))
                for row in rows:
                    cursor = row.id
                    yield f"id: {row.id}\nevent: {row.event_type}\ndata: {json.dumps(row.data_json, ensure_ascii=False, default=str)}\n\n"
                current = await db.get(CourseIntakeTurn, turn_id)
                if current and current.status in {"completed", "failed"} and not rows:
                    yield f"event: stream_closed\ndata: {json.dumps({'status': current.status})}\n\n"
                    break
            idle = 0 if rows else idle + 1
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{session_id}/confirm", status_code=202)
async def confirm_intake(session_id: str, payload: IntakeConfirm, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await owned_intake(session_id, user, db)
    if item.course_id:
        if item.confirm_key != payload.idempotency_key:
            raise HTTPException(409, "该需求会话已经创建课程")
        run = await db.scalar(select(GenerationRun).where(GenerationRun.course_id == item.course_id, GenerationRun.run_type == "blueprint").order_by(GenerationRun.created_at.desc()))
        tasks = await ensure_course_tasks(db, item.course_id)
        await db.commit()
        return {
            "course_id": item.course_id,
            "run_id": run.id if run else None,
            "planning_run_id": run.id if run else None,
            "project_status": "planning" if run and run.status in {"queued", "running"} else "ready",
            "tasks": [await task_payload(db, task) for task in tasks],
            "reused": True,
        }
    if payload.expected_revision != item.current_revision:
        raise HTTPException(409, "需求已更新，请重新确认")
    missing = [field for field in REQUIRED_INTAKE_FIELDS if not item.draft_json.get(field)]
    if missing:
        raise HTTPException(409, f"仍缺少必填需求：{', '.join(missing)}")
    if any(entry.get("severity") == "blocking" for entry in item.conflicts_json):
        raise HTTPException(409, "仍有需要处理的需求冲突")
    draft = IntakeDraft.model_validate(item.draft_json)
    selected_config = await resolve_model_config(db, user.id, item.model_config_id)
    item.status = "converting"
    settings = {
        "course_task": draft.course_task or "",
        "teaching_objectives": draft.teaching_objectives or "",
        "key_points": draft.key_points or "",
        "difficulty_points": draft.difficulty_points or "",
        "teaching_method": draft.teaching_method or "",
        "style_requirements": draft.style_requirements or "",
    }
    course = CourseProject(
        owner_id=user.id,
        model_config_id=selected_config.id if selected_config else None,
        title=draft.title or "",
        subject=draft.subject or "",
        grade_level=draft.grade_level or "",
        audience=draft.audience or "",
        duration_minutes=draft.duration_minutes or 15,
        scenario=draft.scenario or "课堂讲解",
        language=draft.language or "中文",
        status="blueprint_generating",
        settings_json=settings,
    )
    db.add(course)
    await db.flush()
    messages = list(await db.scalars(
        select(CourseIntakeMessage).where(CourseIntakeMessage.session_id == item.id, CourseIntakeMessage.role == "user").order_by(CourseIntakeMessage.created_at)
    ))
    db.add(CourseRequirement(
        course_id=course.id,
        version=1,
        form_json=item.draft_json,
        raw_prompt="\n".join(message.content for message in messages),
        assumptions_json=item.assumptions_json,
        conflicts_json=item.conflicts_json,
    ))
    materials = list(await db.scalars(select(Material).where(Material.intake_session_id == item.id)))
    for material in materials:
        material.course_id = course.id
        material.intake_session_id = None
    # 共享项目记忆：确认需求与上传材料进入项目记忆（同一事务，先写后 bump）。
    requirement = await db.scalar(select(CourseRequirement).where(
        CourseRequirement.course_id == course.id,
    ).order_by(CourseRequirement.version.desc()))
    if requirement:
        from app.services.project_knowledge_service import bump, index_material, index_requirement

        await index_requirement(db, requirement, created_by="teacher")
        await bump(
            db, course.id, "需求已确认", source_type="requirement",
            source_id=requirement.id, created_by="teacher",
        )
        for material in materials:
            await index_material(db, material, created_by="teacher")
    run = GenerationRun(course_id=course.id, thread_id=str(uuid4()), run_type="blueprint", status="queued")
    db.add(run)
    tasks = await ensure_course_tasks(db, course.id)
    item.course_id = course.id
    item.confirm_key = payload.idempotency_key
    item.status = "completed"
    await db.commit()
    start_blueprint_run(run.id)
    return {
        "course_id": course.id,
        "run_id": run.id,
        "planning_run_id": run.id,
        "project_status": "planning",
        "tasks": [await task_payload(db, task) for task in tasks],
        "reused": False,
    }
