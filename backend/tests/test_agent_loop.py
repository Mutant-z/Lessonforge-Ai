"""Agent Loop 执行器单测：多次 LLM 调用、工具结果进入下一轮上下文、Checkpoint 写入。"""
import asyncio

import pytest
from sqlalchemy import select

from app.agent.pipeline import PipelineRuntime, build_plan, run_agent_loop
from app.agent.schemas import AgentDecision, ToolCall
from app.agent.artifacts import PipelineArtifactManager
from app.agent.events import PipelineEventEmitter
from app.agent.context import ContextState
from app.agent.registry import ToolContext
from app.core.database import SessionLocal
from app.models.entities import CourseProject, CourseTask, GenerationRun, PipelineRun
from app.renderers.presentation_builder import PresentationBuilder


class _ScriptedProvider:
    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.prompts = []
        self.calls = 0

    async def structured(self, system, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        return self._decisions.pop(0)


async def _create_course(client, headers):
    await client.post("/api/v1/settings/models", headers=headers, json={
        "name": "循环 Mock", "provider": "mock", "base_url": "mock://loop",
        "model_name": "mock-loop", "timeout_seconds": 30, "is_active": True,
    })
    session = (await client.post("/api/v1/course-intakes", headers=headers)).json()
    await client.post(f"/api/v1/course-intakes/{session['id']}/messages", headers=headers, json={
        "content": "为八年级学生制作一节10分钟的《勾股定理》数学微课，课堂讲解。",
        "expected_revision": 0,
    })
    for _ in range(100):
        ready = (await client.get(f"/api/v1/course-intakes/{session['id']}", headers=headers)).json()
        if ready["status"] == "ready":
            break
        await asyncio.sleep(0.02)
    confirmed = await client.post(f"/api/v1/course-intakes/{session['id']}/confirm", headers=headers, json={
        "expected_revision": ready["current_revision"], "idempotency_key": f"loop-{session['id']}",
    })
    return confirmed.json()["course_id"]


async def _ready_course(client, headers):
    """建课 + 蓝图审批 + Agent 初始化就绪 + 全部任务终态（避免后台任务泄漏导致 DB 锁）。"""
    from agent_pipeline_helpers import ready_course as _ready
    course_id = await _ready(client, headers, model_name="循环 Mock", title="勾股定理")
    response = await client.get(f"/api/v1/courses/{course_id}/project", headers=headers)
    return course_id, response.json()


async def _build_runtime(course_id, provider):
    from app.services.course_task_service import _latest_artifact, _profile_provider
    from app.core.database import SessionLocal
    from app.models.entities import CourseBlueprint
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        task = await db.scalar(select(CourseTask).where(CourseTask.course_id == course_id, CourseTask.task_type == "ppt"))
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        profile, _, config = await _profile_provider(db, course, task)
        gen_run = GenerationRun(course_id=course_id, course_task_id=task.id, thread_id=f"loop-{course_id}",
                                run_type="task", trigger_type="initial", status="running")
        db.add(gen_run)
        await db.flush()
        pr = PipelineRun(generation_run_id=gen_run.id, status="running")
        db.add(pr)
        await db.commit()
        await db.refresh(gen_run)
        await db.refresh(pr)
        gen_run_id, pr_id = gen_run.id, pr.id
    from app.core.config import get_settings
    from pathlib import Path
    workspace = Path(get_settings().storage_root) / "generated" / course_id / "ppt_pipeline" / gen_run_id
    workspace.mkdir(parents=True, exist_ok=True)
    from app.services.model_config_service import resolved_model_name
    context = ContextState(blueprint=blueprint.content_json, profile=profile)
    context.template = {"id": "lessonforge_deck_academic", "palette": {}, "typography": {}}
    runtime = PipelineRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=gen_run, pipeline_run=pr,
        profile=profile, provider=provider, config=config, knowledge_context={},
        source_versions={}, locks=[], preferred_template="lessonforge_deck_academic",
        trigger_type="initial", context=context, builder=PresentationBuilder(),
        artifacts=PipelineArtifactManager(pr, workspace),
        emitter=PipelineEventEmitter(pr.id, gen_run.id, course_id, task.id, "ppt"),
        workspace_root=workspace,
    )
    runtime.tool_context = ToolContext(
        ctx=context, builder=runtime.builder, workspace_root=workspace, course=course, task=task,
        generation_run_id=gen_run_id, pipeline_run_id=pr_id, provider=provider,
        artifacts=runtime.artifacts, emitter=runtime.emitter, runtime=runtime,
    )
    return runtime, gen_run_id


@pytest.mark.asyncio
async def test_loop_runs_multiple_llm_calls_and_forwards_tool_results(client, auth_headers, tmp_path):
    from app.models.entities import CourseProject
    course_id, _ = await _ready_course(client, auth_headers)
    provider = _ScriptedProvider([
        AgentDecision(tool_calls=[ToolCall(tool_name="get_template_catalog", input={})], message="读取模板"),
        AgentDecision(completed=True, output={"slides": [], "total_slides": 0}, summary="模板分析完成"),
    ])
    runtime, gen_run_id = await _build_runtime(course_id, provider)
    plan = build_plan(runtime, "initial")
    # 只跑一个 Agent：template_analysis 会被 LLM 脚本驱动（非 mock）
    from app.agent.schemas import AgentSpec
    plan.agents = [AgentSpec(key="template_analysis", role="模板分析")]
    await run_agent_loop(runtime, plan)

    assert provider.calls >= 2  # 多次 LLM 调用
    # 工具结果进入下一轮上下文
    assert any("tool_result" in prompt for prompt in provider.prompts[1:])
    # Checkpoint 已写入
    async with SessionLocal() as db:
        pr = await db.get(PipelineRun, runtime.pipeline_run.id)
        assert pr.checkpoint_json.get("step_index") == 1
        assert pr.checkpoint_json.get("agents_done") == ["template_analysis"]
        gen = await db.get(GenerationRun, gen_run_id)
        assert gen.status == "running"


class _StreamingProvider:
    """模拟支持 stream_decision 的 LLM：yield 思考增量 + 最终决策。"""

    def __init__(self, decision: AgentDecision):
        self._decision = decision
        self.calls = 0

    async def stream_decision(self, system, prompt, schema):
        self.calls += 1
        yield ("thought_delta", "先分析当前任务，")
        yield ("thought_delta", "再决定调用哪个工具。")
        yield ("decision_ready", self._decision)


@pytest.mark.asyncio
async def test_agent_call_streams_thoughts_and_returns_decision(client, auth_headers, tmp_path):
    from app.agent.agents.template_analysis import TEMPLATE_ANALYSIS_AGENT
    from app.agent.pipeline import _agent_call
    from app.models.entities import GenerationEvent

    course_id, _ = await _ready_course(client, auth_headers)
    provider = _StreamingProvider(AgentDecision(completed=True, output={"slides": []}, summary="模板分析完成"))
    runtime, gen_run_id = await _build_runtime(course_id, provider)

    decision = await _agent_call(runtime, "template_analysis", TEMPLATE_ANALYSIS_AGENT, 0)
    assert provider.calls == 1
    assert decision.completed is True
    assert decision.output == {"slides": []}

    # 思考增量已通过 agent_thought_chunk 事件写入 generation_events
    async with SessionLocal() as db:
        thought_rows = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == gen_run_id,
            GenerationEvent.event_type == "agent_thought_chunk",
        ).order_by(GenerationEvent.id)))
    assert thought_rows, "未写入 agent_thought_chunk 事件"
    joined = "".join(row.data_json.get("text", "") for row in thought_rows)
    assert "先分析当前任务" in joined and "调用哪个工具" in joined
