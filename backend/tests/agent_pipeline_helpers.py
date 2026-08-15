"""Agent 流水线测试共享工具：建课就绪 + 运行时构建。"""
import asyncio
from pathlib import Path

from sqlalchemy import select

from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState
from app.agent.events import PipelineEventEmitter
from app.agent.pipeline import PipelineRuntime
from app.agent.registry import ToolContext
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import CourseBlueprint, CourseProject, CourseTask, GenerationRun, PipelineRun
from app.renderers.presentation_builder import PresentationBuilder
from app.services.course_task_service import _profile_provider


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


async def wait_tasks_terminal(client, headers, course_id, attempts=600):
    """等待内容任务终态、手动视频任务可生成，避免后台任务泄漏到测试后。"""
    project = await wait_for(client, headers, f"/api/v1/courses/{course_id}/project",
                             lambda item: all(task["status"] in {"review", "stale", "failed", "cancelled", "approved", "ready_to_generate", "waiting_dependency"}
                                              for task in item["tasks"]),
                             attempts=attempts)
    return project


async def ready_course(client, headers, model_name="流水线 Mock", title="勾股定理"):
    """建课 + 蓝图审批 + Agent 初始化就绪 + 全部任务终态（不泄漏后台任务）。"""
    await client.post("/api/v1/settings/models", headers=headers, json={
        "name": model_name, "provider": "mock", "base_url": "mock://pipe",
        "model_name": model_name.lower(), "timeout_seconds": 30, "is_active": True,
    })
    course = (await client.post("/api/v1/courses", headers=headers, json={
        "title": title, "subject": "初中数学", "grade_level": "八年级",
        "audience": "已学习基础概念的学生", "duration_minutes": 10,
        "scenario": "课堂讲解", "course_task": "理解并应用核心概念",
    })).json()
    blueprint = (await client.post(f"/api/v1/courses/{course['id']}/blueprint/generate", headers=headers)).json()
    await client.post(f"/api/v1/blueprints/{blueprint['id']}/approve", headers=headers)
    await wait_for(client, headers, f"/api/v1/courses/{course['id']}/project",
                   lambda item: item["agent_initialization"]["status"] == "ready")
    await wait_tasks_terminal(client, headers, course["id"])
    return course["id"]


async def build_runtime(course_id: str, provider=None, trigger: str = "initial") -> PipelineRuntime:
    """构建一个可独立运行的 PipelineRuntime（含真实 DB 行）。"""
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        task = await db.scalar(select(CourseTask).where(CourseTask.course_id == course_id, CourseTask.task_type == "ppt"))
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        profile, resolved_provider, config = await _profile_provider(db, course, task)
        provider = provider or resolved_provider
        gen_run = GenerationRun(course_id=course_id, course_task_id=task.id, thread_id=f"h-{course_id}-{trigger}",
                                run_type="task", trigger_type=trigger, status="running")
        db.add(gen_run)
        await db.flush()
        pr = PipelineRun(generation_run_id=gen_run.id, status="running")
        db.add(pr)
        await db.commit()
        await db.refresh(gen_run)
        await db.refresh(pr)
    workspace = Path(get_settings().storage_root) / "generated" / course_id / "ppt_pipeline" / gen_run.id
    workspace.mkdir(parents=True, exist_ok=True)
    context = ContextState(blueprint=blueprint.content_json, profile=profile)
    context.template = {"id": "lessonforge_deck_academic", "palette": {}, "typography": {}}
    runtime = PipelineRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=gen_run, pipeline_run=pr,
        profile=profile, provider=provider, config=config, knowledge_context={},
        source_versions={}, locks=[], preferred_template="lessonforge_deck_academic",
        trigger_type=trigger, context=context, builder=PresentationBuilder(),
        artifacts=PipelineArtifactManager(pr, workspace),
        emitter=PipelineEventEmitter(pr.id, gen_run.id, course_id, task.id, "ppt"),
        workspace_root=workspace,
    )
    runtime.tool_context = ToolContext(
        ctx=context, builder=runtime.builder, workspace_root=workspace, course=course, task=task,
        generation_run_id=gen_run.id, pipeline_run_id=pr.id, provider=provider,
        artifacts=runtime.artifacts, emitter=runtime.emitter, runtime=runtime,
    )
    return runtime
