"""多 Agent 流水线 API：流水线详情、暂停、恢复。"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, owned_course
from app.api.v1.projects import TASK_SPEC_BY_TYPE, _owned_task  # noqa: F401 复用任务归属校验
from app.core.database import SessionLocal, get_db
from app.models.entities import (
    CourseProject,
    CourseTask,
    GenerationRun,
    PipelineArtifact,
    PipelineEvent,
    PipelineRun,
    PipelineToolCall,
    User,
)
from app.services.course_task_service import start_task_run, task_jobs
from app.services.ppt_pipeline_service import PAUSE_EVENTS

router = APIRouter(tags=["agent-pipeline"])


async def _pipeline_payload(db, task: CourseTask) -> dict:
    """返回流水线运行 + 产物图 + 工具调用 + 事件（供前端工作台初始化和恢复）。

    取该任务最近一次 GenerationRun 对应的 PipelineRun（含已完成的历史运行）。
    """
    generation_run = await db.scalar(select(GenerationRun).where(
        GenerationRun.course_task_id == task.id,
        GenerationRun.run_type == "task",
    ).order_by(GenerationRun.created_at.desc()))
    if not generation_run:
        return {"run": None, "plan": [], "artifacts": [], "tool_calls": [], "events": []}
    pipeline_run = await db.scalar(select(PipelineRun).where(
        PipelineRun.generation_run_id == generation_run.id,
    ))
    if not pipeline_run:
        return {"run": None, "plan": [], "artifacts": [], "tool_calls": [], "events": []}
    # 兼容旧异常路径：GenerationRun 已终止但 PipelineRun 遗留 running，会让 UI 显示无法暂停的幽灵任务。
    if generation_run.status in {"completed", "failed", "cancelled"} and pipeline_run.status in {"queued", "running", "pausing"}:
        pipeline_run.status = generation_run.status
        if generation_run.error_json and not pipeline_run.error_json:
            pipeline_run.error_json = generation_run.error_json
        await db.commit()
    artifacts = list(await db.scalars(select(PipelineArtifact).where(
        PipelineArtifact.pipeline_run_id == pipeline_run.id,
    ).order_by(PipelineArtifact.version)))
    tool_calls = list(await db.scalars(select(PipelineToolCall).where(
        PipelineToolCall.pipeline_run_id == pipeline_run.id,
    ).order_by(PipelineToolCall.created_at)))
    events = list(await db.scalars(select(PipelineEvent).where(
        PipelineEvent.pipeline_run_id == pipeline_run.id,
    ).order_by(PipelineEvent.sequence)))

    def _artifact(row) -> dict:
        return {
            "id": row.id, "artifact_type": row.artifact_type, "name": row.name, "version": row.version,
            "status": row.status, "data": row.data_json, "file_path": row.file_path,
            "mime_type": row.mime_type, "producer_agent": row.producer_agent,
            "producer_tool": row.producer_tool, "dependencies": row.dependencies_json,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }

    def _tool(row) -> dict:
        return {
            "id": row.id, "model_call_id": row.model_call_id, "agent_key": row.agent_key, "tool_name": row.tool_name,
            "input": row.input_json, "output": row.output_json, "status": row.status,
            "duration_ms": row.duration_ms, "error": row.error_json,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }

    def _event(row) -> dict:
        return {
            "id": row.sequence, "event_type": row.event_type, "sequence": row.sequence,
            "data": row.data_json, "created_at": row.created_at.isoformat() if row.created_at else "",
        }

    return {
        "run": {
            "id": pipeline_run.id, "generation_run_id": pipeline_run.generation_run_id,
            "status": pipeline_run.status, "pipeline_type": pipeline_run.pipeline_type,
            "current_agent": pipeline_run.current_agent, "current_step_index": pipeline_run.current_step_index,
            "revision_round": pipeline_run.revision_round, "max_revision_rounds": pipeline_run.max_revision_rounds,
            "plan": pipeline_run.plan_json, "checkpoint": pipeline_run.checkpoint_json,
            "token_usage": pipeline_run.token_usage_json, "error": pipeline_run.error_json,
            "created_at": pipeline_run.created_at.isoformat() if pipeline_run.created_at else "",
        },
        "plan": pipeline_run.plan_json,
        "artifacts": [_artifact(row) for row in artifacts],
        "tool_calls": [_tool(row) for row in tool_calls],
        "events": [_event(row) for row in events],
    }


@router.get("/courses/{course_id}/tasks/{task_type}/pipeline")
async def get_pipeline(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    return await _pipeline_payload(db, task)


@router.post("/courses/{course_id}/tasks/{task_type}/pause", status_code=202)
async def pause_pipeline(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    if not task.active_run_id:
        raise HTTPException(409, "当前任务没有正在运行的 Agent")
    run_id = task.active_run_id
    generation = await db.get(GenerationRun, run_id)
    pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
    if generation is None or pipeline is None or pipeline.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "当前任务已经结束")
    PAUSE_EVENTS[run_id] = PAUSE_EVENTS.get(run_id) or asyncio.Event()
    PAUSE_EVENTS[run_id].set()
    job = task_jobs.get(run_id)
    # 进程重载后的孤儿 Run 没有执行器可抵达边界，直接标记 paused；活跃任务则先进入 pausing。
    next_status = "pausing" if job is not None and not job.done() else "paused"
    generation.status = next_status
    pipeline.status = next_status
    task.status = next_status
    await db.commit()
    if next_status == "pausing" and job is not None:
        job.cancel()
    return {"task_id": task.id, "run_id": run_id, "status": next_status}


@router.post("/courses/{course_id}/tasks/{task_type}/resume", status_code=202)
async def resume_pipeline(course_id: str, task_type: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    task = await _owned_task(course_id, task_type, user, db)
    if task.status != "paused" or not task.active_run_id:
        raise HTTPException(409, "当前任务不在暂停状态")
    run_id = task.active_run_id
    event = PAUSE_EVENTS.pop(run_id, None)
    if event is not None:
        event.clear()
    run = await db.get(GenerationRun, run_id)
    pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
    if run:
        run.status = "queued"
    if pipeline:
        pipeline.status = "queued"
    task.status = "queued"
    await db.commit()
    start_task_run(run_id)
    return {"task_id": task.id, "status": "resumed"}
