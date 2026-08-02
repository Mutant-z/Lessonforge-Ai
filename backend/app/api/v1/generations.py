import asyncio
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.core.database import SessionLocal, get_db
from app.core.security import create_stream_token, decode_stream_token
from app.models.entities import CourseBlueprint, CourseProject, GenerationEvent, GenerationRun, User
from app.services.generation_service import start_run, tasks

router = APIRouter(tags=["生成运行"])


@router.post("/courses/{course_id}/generations", status_code=202)
async def create_run(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    course = await owned_course(course_id, user, db)
    blueprint = await db.scalar(select(CourseBlueprint).where(CourseBlueprint.course_id == course_id, CourseBlueprint.version == course.current_blueprint_version))
    if not blueprint or blueprint.status != "approved":
        raise HTTPException(409, "请先确认并锁定课程蓝图")
    run = GenerationRun(course_id=course_id, thread_id=str(uuid4()), status="queued")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    start_run(run.id)
    return run_summary(run)


def run_summary(run: GenerationRun) -> dict:
    return {"id": run.id, "course_id": run.course_id, "thread_id": run.thread_id, "run_type": run.run_type, "status": run.status, "current_node": run.current_node, "progress": run.progress, "error": run.error_json, "created_at": run.created_at}


@router.get("/generations/{run_id}")
async def get_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    run = await db.get(GenerationRun, run_id)
    if not run:
        raise HTTPException(404, "生成任务不存在")
    await owned_course(run.course_id, user, db)
    return run_summary(run)


@router.get("/courses/{course_id}/generations")
async def list_runs(course_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await owned_course(course_id, user, db)
    runs = await db.scalars(select(GenerationRun).where(GenerationRun.course_id == course_id).order_by(GenerationRun.created_at.desc()))
    return [run_summary(x) for x in runs]


@router.post("/generations/{run_id}/cancel")
async def cancel_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    run = await db.get(GenerationRun, run_id)
    if not run:
        raise HTTPException(404, "生成任务不存在")
    await owned_course(run.course_id, user, db)
    task = tasks.get(run_id)
    if task:
        task.cancel()
    run.status = "cancelled"
    await db.commit()
    return run_summary(run)


@router.post("/generations/{run_id}/continue")
async def continue_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    run = await db.get(GenerationRun, run_id)
    if not run:
        raise HTTPException(404, "生成任务不存在")
    course = await owned_course(run.course_id, user, db)
    if run.status == "waiting_human":
        run.status = "completed"
        course.status = "completed"
        await db.commit()
    return run_summary(run)


@router.get("/generations/{run_id}/events")
async def events(run_id: str, token: str):
    user_id = decode_stream_token(token, run_id)
    async with SessionLocal() as db:
        run = await db.get(GenerationRun, run_id)
        course = await db.get(CourseProject, run.course_id) if run else None
        if not run or not course or course.owner_id != user_id:
            raise HTTPException(404, "生成任务不存在")
    async def stream():
        cursor = 0
        idle = 0
        while idle < 600:
            async with SessionLocal() as db:
                rows = await db.scalars(select(GenerationEvent).where(GenerationEvent.run_id == run_id, GenerationEvent.id > cursor).order_by(GenerationEvent.id))
                items = list(rows)
                for item in items:
                    cursor = item.id
                    payload = json.dumps(item.data_json, ensure_ascii=False, default=str)
                    yield f"id: {item.id}\nevent: {item.event_type}\ndata: {payload}\n\n"
                run = await db.get(GenerationRun, run_id)
                if run and run.status in {"completed", "failed", "cancelled", "waiting_human"} and not items:
                    yield f"event: stream_closed\ndata: {json.dumps({'status': run.status})}\n\n"
                    break
            idle = 0 if items else idle + 1
            if not items:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/generations/{run_id}/stream-token")
async def stream_token(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    run = await db.get(GenerationRun, run_id)
    if not run:
        raise HTTPException(404, "生成任务不存在")
    await owned_course(run.course_id, user, db)
    return {"token": create_stream_token(user.id, run_id), "expires_in": 300}
