"""流水线暂停/恢复测试：Agent 边界 checkpoint + resume 续跑 + task_paused/resumed 事件。"""
import asyncio

import pytest
from sqlalchemy import select

from app.agent.pipeline import PipelinePaused, build_plan, run_agent_loop
from app.agent.registry import ToolContext
from app.agent.schemas import AgentSpec, PipelinePlan
from app.core.database import SessionLocal
from app.models.entities import GenerationEvent, PipelineRun
from app.services.ppt_pipeline_service import PAUSE_EVENTS


async def wait_for(client, headers, url, predicate, attempts=300):
    payload = None
    for _ in range(attempts):
        response = await client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        if predicate(payload):
            return payload
        await asyncio.sleep(0.02)
    return payload


async def _ready_course(client, headers):
    from agent_pipeline_helpers import ready_course as _ready
    return await _ready(client, headers, model_name="暂停 Mock", title="浮力原理")


@pytest.mark.asyncio
async def test_pipeline_pauses_at_agent_boundary_and_resumes(client, auth_headers):
    from app.agent.artifacts import PipelineArtifactManager
    from app.agent.context import ContextState
    from app.agent.events import PipelineEventEmitter
    from app.agent.pipeline import PipelineRuntime
    from app.models.entities import CourseProject, CourseTask, GenerationRun
    from app.renderers.presentation_builder import PresentationBuilder
    from app.services.course_task_service import _profile_provider
    from app.providers.llm.mock import MockProvider

    course_id = await _ready_course(client, auth_headers)
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        task = await db.scalar(select(CourseTask).where(CourseTask.course_id == course_id, CourseTask.task_type == "ppt"))
        blueprint = await db.scalar(select(_bp_model()).where(
            _bp_model().course_id == course_id, _bp_model().version == course.current_blueprint_version,
        ))
        profile, provider, config = await _profile_provider(db, course, task)
        gen_run = GenerationRun(course_id=course_id, course_task_id=task.id, thread_id=f"pause-{course_id}",
                                run_type="task", trigger_type="initial", status="running")
        db.add(gen_run)
        await db.flush()
        pr = PipelineRun(generation_run_id=gen_run.id, status="running")
        db.add(pr)
        await db.commit()
        await db.refresh(gen_run)
        await db.refresh(pr)
    from app.core.config import get_settings
    from pathlib import Path
    workspace = Path(get_settings().storage_root) / "generated" / course_id / "ppt_pipeline" / gen_run.id
    workspace.mkdir(parents=True, exist_ok=True)
    context = ContextState(blueprint=blueprint.content_json, profile=profile)
    context.template = {"id": "lessonforge_deck_academic", "palette": {}, "typography": {}}
    pause_event = asyncio.Event()
    runtime = PipelineRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=gen_run, pipeline_run=pr,
        profile=profile, provider=provider, config=config, knowledge_context={},
        source_versions={}, locks=[], preferred_template="lessonforge_deck_academic",
        trigger_type="initial", context=context, builder=PresentationBuilder(),
        artifacts=PipelineArtifactManager(pr, workspace),
        emitter=PipelineEventEmitter(pr.id, gen_run.id, course_id, task.id, "ppt"),
        workspace_root=workspace, pause_event=pause_event,
    )
    runtime.tool_context = ToolContext(
        ctx=context, builder=runtime.builder, workspace_root=workspace, course=course, task=task,
        generation_run_id=gen_run.id, pipeline_run_id=pr.id, provider=provider,
        artifacts=runtime.artifacts, emitter=runtime.emitter, runtime=runtime,
    )
    plan = build_plan(runtime, "initial")

    # 先请求暂停再启动流水线：第一个 Agent 边界必然暂停（确定性）
    runtime.request_pause()
    loop_task = asyncio.create_task(run_agent_loop(runtime, plan))
    with pytest.raises(PipelinePaused):
        await loop_task

    # checkpoint 已持久化，run 状态 paused
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, pr.id)
        assert row.status == "paused"
        assert "paused_agent" in row.checkpoint_json
        events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == gen_run.id,
            GenerationEvent.event_type.in_(["agent_started", "task_paused"]),
        )))
    assert runtime.pause_event.is_set()

    # 恢复：清暂停事件，继续跑完整流水线
    pause_event.clear()
    await run_agent_loop(runtime, plan)
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, pr.id)
        assert row.checkpoint_json.get("step_index", 0) >= 1
    assert runtime.builder is not None


def _bp_model():
    from app.models.entities import CourseBlueprint
    return CourseBlueprint


@pytest.mark.asyncio
async def test_pause_resume_api_endpoints(client, auth_headers):
    course_id = await _ready_course(client, auth_headers)
    # 无运行任务时 pause → 409；非暂停任务 resume → 409
    no_run = await client.post(f"/api/v1/courses/{course_id}/tasks/ppt/pause", headers=auth_headers)
    assert no_run.status_code == 409
    no_resume = await client.post(f"/api/v1/courses/{course_id}/tasks/ppt/resume", headers=auth_headers)
    assert no_resume.status_code == 409


@pytest.mark.asyncio
async def test_pause_request_persists_pausing_until_safe_boundary(client, auth_headers):
    from agent_pipeline_helpers import build_runtime
    from app.models.entities import CourseTask, GenerationRun
    from app.services.course_task_service import task_jobs

    course_id = await _ready_course(client, auth_headers)
    runtime = await build_runtime(course_id, trigger="initial")
    async with SessionLocal() as db:
        task = await db.get(CourseTask, runtime.task.id)
        task.active_run_id = runtime.generation_run.id
        task.status = "running"
        await db.commit()

    blocker = asyncio.create_task(asyncio.Event().wait())
    task_jobs[runtime.generation_run.id] = blocker
    response = await client.post(f"/api/v1/courses/{course_id}/tasks/ppt/pause", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "pausing"

    async with SessionLocal() as db:
        generation = await db.get(GenerationRun, runtime.generation_run.id)
        pipeline = await db.get(PipelineRun, runtime.pipeline_run.id)
        task = await db.get(CourseTask, runtime.task.id)
        assert generation.status == "pausing"
        assert pipeline.status == "pausing"
    assert task.status == "pausing"
    assert PAUSE_EVENTS[runtime.generation_run.id].is_set()
    PAUSE_EVENTS.pop(runtime.generation_run.id, None)
    task_jobs.pop(runtime.generation_run.id, None)
    blocker.cancel()


@pytest.mark.asyncio
async def test_pause_orphaned_run_becomes_paused_immediately(client, auth_headers):
    from agent_pipeline_helpers import build_runtime
    from app.models.entities import CourseTask

    course_id = await _ready_course(client, auth_headers)
    runtime = await build_runtime(course_id, trigger="initial")
    async with SessionLocal() as db:
        task = await db.get(CourseTask, runtime.task.id)
        task.active_run_id = runtime.generation_run.id
        task.status = "running"
        await db.commit()

    response = await client.post(f"/api/v1/courses/{course_id}/tasks/ppt/pause", headers=auth_headers)
    assert response.status_code == 202
    assert response.json()["status"] == "paused"
    async with SessionLocal() as db:
        pipeline = await db.get(PipelineRun, runtime.pipeline_run.id)
        assert pipeline.status == "paused"
    PAUSE_EVENTS.pop(runtime.generation_run.id, None)


@pytest.mark.asyncio
async def test_pause_preempts_blocked_pipeline_job(client, auth_headers, monkeypatch):
    from app.models.entities import CourseTask
    from app.services.course_task_service import create_task_run, start_task_run, task_jobs
    import app.services.ppt_pipeline_service as ppt_service

    course_id = await _ready_course(client, auth_headers)
    started = asyncio.Event()

    async def blocked_pipeline(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ppt_service, "run_ppt_pipeline", blocked_pipeline)
    async with SessionLocal() as db:
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "ppt",
        ))
        run = await create_task_run(db, task, "sync_context")
        db.add(PipelineRun(generation_run_id=run.id, status="running"))
        await db.commit()
        run_id = run.id
    start_task_run(run_id)
    await asyncio.wait_for(started.wait(), timeout=2)
    job = task_jobs[run_id]

    response = await client.post(f"/api/v1/courses/{course_id}/tasks/ppt/pause", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "pausing"
    await asyncio.wait_for(job, timeout=2)

    async with SessionLocal() as db:
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "ppt",
        ))
        pipeline = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
        assert task.status == "paused"
        assert task.active_run_id == run_id
        assert pipeline.status == "paused"
    PAUSE_EVENTS.pop(run_id, None)
