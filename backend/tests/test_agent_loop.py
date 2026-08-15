"""Agent Loop 执行器单测：多次 LLM 调用、工具结果进入下一轮上下文、Checkpoint 写入。"""
import asyncio

import pytest
from sqlalchemy import select

from app.agent.pipeline import PipelineRuntime, _agent_call, build_plan, run_agent_loop
from app.agent.agents.layout import LayoutAgent
from app.agent.layouts.engine import compile_layout
from app.agent.schemas import AgentDecision, PPTAgentError, SlideLayoutArtifact, ToolCall
from app.agent.artifacts import PipelineArtifactManager
from app.agent.events import PipelineEventEmitter
from app.agent.context import ContextState
from app.agent.registry import ToolContext
from app.agent.registry import execute_tool
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
        result = self._decisions.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
async def test_confirmed_layout_candidate_bypasses_provider_and_clears_second_confirmation():
    source = {
        "id": "slide_03", "page_type": "objectives", "title": "预习目标",
        "body": ["理解浮力本质", "澄清深度误区", "推导核心原理"],
        "blocks": [{
            "kind": "steps", "steps": [
                {"title": "任务一", "detail": "分析上下表面压力差"},
                {"title": "任务二", "detail": "辨析完全浸没后的浮力"},
                {"title": "任务三", "detail": "归纳阿基米德原理"},
            ],
        }],
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title",
             "text": "预习目标", "x": 2.45, "y": 0.55, "w": 9.5, "h": 0.8,
             "style": {"size": 28}},
            *[
                {"kind": "textbox", "role": "body", "content_ref": f"body.{index}",
                 "text": text, "x": 2.45 + index * 2.7, "y": 1.7,
                 "w": 2.3, "h": 0.6, "style": {"size": 14}}
                for index, text in enumerate(("理解浮力本质", "澄清深度误区", "推导核心原理"))
            ],
        ],
    }
    candidate = compile_layout(
        "lessonforge_deck_smart_ai", source,
        {
            "slide_id": "slide_03", "layout_type": "steps_horizontal",
            "style": {"font_tier": "spacious", "font_scale": 1.04, "gap_scale": 1.3},
            "objectives": [
                {"metric": "font_size", "direction": "increase", "hard_requirement": True},
                {"metric": "vertical_utilization", "direction": "increase", "hard_requirement": True},
            ],
            "quality_mode": "polish_v2",
        },
    )
    candidate_id = str(candidate["selected_candidate_id"])
    candidate["requires_candidate_confirmation"] = True
    candidate["candidate_rankings"] = [{"candidate_id": "must-not-render-again"}]
    runtime = type("ConfirmedRuntime", (), {})()
    runtime.provider = object()  # No provider methods: any LLM call would fail this test.
    runtime.layout_engine_params = {
        "confirmed_candidate": candidate,
        "confirmed_candidate_id": candidate_id,
        "quality_mode": "polish_v2",
    }
    runtime.repair_mode = ""
    runtime.emitter = None
    runtime.selected_slide_ids = ["slide_03"]
    runtime.baseline_slides = [source]
    runtime.content_policy = "preserve"
    runtime.artifacts = None
    runtime.preferred_template = "lessonforge_deck_smart_ai"
    runtime.active_intent = "LAYOUT_ONLY"
    runtime.layout_compile_results = []
    runtime.tool_context = ToolContext(runtime=runtime)

    decision = await _agent_call(runtime, "layout", LayoutAgent(), 0)

    applied = decision.output["slides"][0]
    assert [
        (item["kind"], item.get("content_ref"), item["x"], item["y"], item["w"], item["h"], item.get("style") or {})
        for item in applied["elements"]
    ] == [
        (item["kind"], item.get("content_ref"), item["x"], item["y"], item["w"], item["h"], item.get("style") or {})
        for item in candidate["elements"]
    ]
    assert applied["selected_candidate_id"] == candidate_id
    assert applied["requires_candidate_confirmation"] is False
    assert applied["candidate_rankings"] == []
    assert runtime.layout_compile_results[0]["selected_candidate_id"] == candidate_id
    assert runtime.layout_compile_results[0]["requires_candidate_confirmation"] is False
    assert runtime.layout_compile_results[0]["candidate_rankings"] == []


@pytest.mark.asyncio
async def test_agent_loop_preserves_original_exception_without_shadowing_ppt_error(monkeypatch):
    """Regression for b2ae2c7b: local imports must not cause UnboundLocalError."""
    from types import SimpleNamespace

    from app.agent import pipeline as pipeline_module
    from app.agent.schemas import AgentSpec, PipelinePlan

    async def fail_agent_call(*_args, **_kwargs):
        raise ValueError("layout compiler sentinel")

    class Emitter:
        async def agent_started(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(pipeline_module, "_agent_call", fail_agent_call)
    runtime = SimpleNamespace(
        tool_context=SimpleNamespace(ctx=None), pause_requested=lambda: False,
        current_agent_key="", context=SimpleNamespace(
            current_agent="", to_prompt=lambda _key: "",
        ),
        emitter=Emitter(), _steps=0,
    )
    plan = PipelinePlan(agents=[AgentSpec(key="layout", role="layout", max_steps=1)])

    with pytest.raises(ValueError, match="layout compiler sentinel"):
        await run_agent_loop(runtime, plan, start_step=0)


@pytest.mark.asyncio
async def test_agent_loop_does_not_retry_deterministic_layout_compile_error(monkeypatch):
    """A local layout failure must not be reported as a retryable model error."""
    from types import SimpleNamespace

    from app.agent import pipeline as pipeline_module
    from app.agent.layouts.engine import LayoutCompileError
    from app.agent.schemas import AgentSpec, PipelinePlan

    calls = 0

    async def fail_agent_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise LayoutCompileError(
            [], ["purpose"], True,
            attempts=[{"layout_type": "bullet_flow", "missing_refs": ["purpose"]}],
        )

    class Emitter:
        async def agent_started(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(pipeline_module, "_agent_call", fail_agent_call)
    runtime = SimpleNamespace(
        tool_context=SimpleNamespace(ctx=None), pause_requested=lambda: False,
        current_agent_key="", context=SimpleNamespace(
            current_agent="", to_prompt=lambda _key: "",
        ),
        emitter=Emitter(), _steps=0,
    )
    plan = PipelinePlan(agents=[AgentSpec(key="layout", role="layout", max_steps=1)])

    with pytest.raises(PPTAgentError) as caught:
        await run_agent_loop(runtime, plan, start_step=0)

    assert calls == 1
    assert caught.value.code == "layout_compile_failed"
    assert caught.value.retryable is False
    assert caught.value.details["missing_refs"] == ["purpose"]


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


@pytest.mark.asyncio
async def test_slide_content_completed_without_slides_gets_one_protocol_correction(client, auth_headers):
    from app.agent.agents.slide_content import SLIDE_CONTENT_AGENT
    from app.agent.pipeline import _agent_call
    from app.models.entities import Artifact

    course_id, _ = await _ready_course(client, auth_headers)
    async with SessionLocal() as db:
        source = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id, Artifact.artifact_type == "ppt",
        ).order_by(Artifact.version.desc()))
    target = source.content_json["slides"][1]
    provider = _ScriptedProvider([
        AgentDecision(completed=True, output={}, summary="已完成"),
        AgentDecision(completed=True, output={"slides": [{
            "id": target["id"], "changed_fields": ["title"], "title": "结构纠正后的标题",
        }]}, summary="结构已纠正"),
    ])
    runtime, _ = await _build_runtime(course_id, provider)
    runtime.source_artifact = source
    runtime.context.source_artifact = source
    runtime.selected_slide_ids = [target["id"]]
    runtime.content_policy = "edit"

    decision = await _agent_call(runtime, "slide_content", SLIDE_CONTENT_AGENT, 0)

    assert provider.calls == 2
    assert decision.output["slides"][0]["title"] == "结构纠正后的标题"
    assert decision.output["slides"][0]["body"] == target["body"]


@pytest.mark.asyncio
async def test_restore_protocol_correction_falls_back_to_authoritative_revision(client, auth_headers):
    from app.agent.agents.slide_content import SLIDE_CONTENT_AGENT
    from app.agent.pipeline import _agent_call
    from app.models.entities import Artifact

    course_id, _ = await _ready_course(client, auth_headers)
    async with SessionLocal() as db:
        source = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id, Artifact.artifact_type == "ppt",
        ).order_by(Artifact.version.desc()))
    target = source.content_json["slides"][1]
    provider = _ScriptedProvider([
        AgentDecision(completed=True, output={}, summary="已完成"),
        AgentDecision(completed=True, output={}, summary="仍缺少 slides"),
    ])
    runtime, _ = await _build_runtime(course_id, provider)
    runtime.source_artifact = source
    runtime.context.source_artifact = source
    runtime.selected_slide_ids = [target["id"]]
    runtime.content_policy = "restore"

    decision = await _agent_call(runtime, "slide_content", SLIDE_CONTENT_AGENT, 0)

    assert provider.calls == 2
    assert decision.output == {"slides": [target]}


@pytest.mark.asyncio
async def test_reused_model_tool_call_ids_get_unique_persisted_invocations(client, auth_headers):
    from app.agent.pipeline import _execute_tool_call
    from app.models.entities import PipelineToolCall

    course_id, _ = await _ready_course(client, auth_headers)
    runtime, _ = await _build_runtime(course_id, _ScriptedProvider([]))
    call = ToolCall(id="call_01", tool_name="get_template_catalog", input={})

    await _execute_tool_call(runtime, "template_analysis", call, runtime.tool_context)
    await _execute_tool_call(runtime, "template_analysis", call, runtime.tool_context)

    async with SessionLocal() as db:
        rows = list(await db.scalars(select(PipelineToolCall).where(
            PipelineToolCall.pipeline_run_id == runtime.pipeline_run.id,
            PipelineToolCall.model_call_id == "call_01",
        )))
    assert len(rows) == 2
    assert len({row.id for row in rows}) == 2


@pytest.mark.asyncio
async def test_locked_image_layout_tool_failure_aborts_instead_of_reaching_qa(client, auth_headers):
    from app.agent.pipeline import _execute_tool_call

    course_id, _ = await _ready_course(client, auth_headers)
    runtime, _ = await _build_runtime(course_id, _ScriptedProvider([]))
    runtime.active_intent = "IMAGE_UPDATE"
    runtime.content_policy = "preserve"
    runtime.selected_slide_ids = ["slide_04"]
    runtime.builder.from_ppt_content({
        "theme": "lessonforge_deck_academic",
        "slides": [{
            "id": "slide_04", "page_type": "concept", "title": "原始标题",
            "purpose": "", "body": ["原始正文"], "blocks": [],
            "speaker_notes": "原始备注", "duration_seconds": 60,
        }],
    })
    runtime.tool_context.builder = runtime.builder
    before = runtime.builder.to_ppt_content()
    call = ToolCall(tool_name="layout_slide_batch", input={"layouts": [{
        "slide_id": "slide_04", "render_mode": "absolute", "elements": [{
            "kind": "textbox", "content_ref": "blocks.99.text", "text": "模型伪造文字",
            "x": 1, "y": 1, "w": 5, "h": 1,
        }],
    }]})

    with pytest.raises(PPTAgentError) as caught:
        await _execute_tool_call(runtime, "ppt_editor", call, runtime.tool_context)

    assert caught.value.code == "layout_incomplete"
    assert runtime.builder.to_ppt_content() == before

    # The same failure in a normal layout run used to reference a function-
    # local PPTAgentError import that was only assigned in IMAGE_UPDATE.
    runtime.active_intent = "LAYOUT_ONLY"
    with pytest.raises(PPTAgentError) as caught:
        await _execute_tool_call(runtime, "ppt_editor", call, runtime.tool_context)
    assert caught.value.code == "layout_incomplete"


@pytest.mark.asyncio
async def test_local_edit_tools_and_qa_cannot_escape_selected_slide(client, auth_headers):
    course_id, _ = await _ready_course(client, auth_headers)
    runtime, _ = await _build_runtime(course_id, _ScriptedProvider([]))
    runtime.selected_slide_ids = ["slide_01"]
    runtime.builder.from_ppt_content({
        "theme": "lessonforge_deck_academic",
        "slides": [
            {"id": "slide_01", "page_type": "cover", "title": "旧首页", "purpose": "p", "body": ["a"],
             "layout": "cover", "visual_suggestion": "old visual", "speaker_notes": "note", "duration_seconds": 10},
            {"id": "slide_02", "page_type": "scenario", "title": "第二页不应修改", "purpose": "p",
             "body": [str(i) for i in range(8)], "layout": "bullet", "visual_suggestion": "old visual",
             "speaker_notes": "note", "duration_seconds": 10},
        ],
    })
    runtime.tool_context.builder = runtime.builder

    write = await execute_tool("write_slide_batch", runtime.tool_context, {"slides": [
        {"id": "slide_01", "page_type": "cover", "title": "LLM 新首页", "purpose": "p", "body": ["a"],
         "layout": "cover", "visual_suggestion": "new visual", "speaker_notes": "note", "duration_seconds": 10},
        {"id": "slide_02", "page_type": "scenario", "title": "越权修改", "purpose": "p", "body": ["x"],
         "layout": "bullet", "visual_suggestion": "new visual", "speaker_notes": "note", "duration_seconds": 10},
    ]})
    assert write.ok is True
    assert write.output["slide_ids"] == ["slide_01"]
    assert write.output["rejected_slide_ids"] == ["slide_02"]
    assert runtime.builder.get_slide("slide_01")["title"] == "LLM 新首页"
    assert runtime.builder.get_slide("slide_02")["title"] == "第二页不应修改"

    layout = await execute_tool("layout_slide_batch", runtime.tool_context, {"layouts": [
        {"slide_id": "slide_01", "layout_type": "hero", "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title",
             "text": "LLM 新首页", "x": 0.8, "y": 1.2, "w": 5.0, "h": 1.2},
            {"kind": "textbox", "role": "body", "content_ref": "body",
             "text": "a", "x": 0.8, "y": 2.6, "w": 5.0, "h": 0.8},
            {"kind": "textbox", "role": "purpose", "content_ref": "purpose",
             "text": "p", "x": 0.8, "y": 3.6, "w": 5.0, "h": 0.8},
        ]},
        {"slide_id": "slide_02", "layout_type": "bad", "elements": [
            {"kind": "textbox", "role": "title", "text": "越权", "x": 0.8, "y": 1.2, "w": 5.0, "h": 1.2},
        ]},
    ]})
    assert layout.ok is True
    assert layout.output["rejected_slide_ids"] == ["slide_02"]
    assert runtime.builder.get_slide("slide_01")["elements"]
    assert runtime.builder.get_slide("slide_02")["elements"] == []

    qa = await execute_tool("run_content_qa", runtime.tool_context, {})
    assert qa.ok is True
    assert qa.output["coverage"] == {"slides_checked": 1}
    assert not any(issue["slide_id"] == "slide_02" for issue in qa.output["issues"])

    persisted = runtime.builder.to_ppt_content()
    assert persisted["slides"][0]["elements"], "LLM 布局几何必须进入最终 Artifact"


@pytest.mark.asyncio
async def test_real_provider_layout_is_recomputed_as_executable_geometry(client, auth_headers):
    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _agent_call

    course_id, _ = await _ready_course(client, auth_headers)
    provider = _ScriptedProvider([
        AgentDecision(completed=True, output=SlideLayoutArtifact.model_validate({"slides": [{
            "slide_id": "slide_01", "layout_type": "split_hero", "designRationale": "强化视觉重心与留白",
            "elements": [
                {"kind": "textbox", "role": "title", "text": "新首页", "x": 0.8, "y": 1.2, "w": 5.0, "h": 1.2,
                 "style": {"size": 34, "bold": True, "color": "primary"}},
                {"kind": "shape", "role": "visual", "x": 6.2, "y": 1.0, "w": 6.2, "h": 5.3,
                 "fill": "surface"},
            ],
        }]}).model_dump(), summary="已分析首页并生成可执行坐标"),
    ])
    runtime, _ = await _build_runtime(course_id, provider)
    runtime.selected_slide_ids = ["slide_01"]
    runtime.builder.from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [{
        "id": "slide_01", "page_type": "cover", "title": "旧首页", "purpose": "p",
        "body": ["八年级物理微课", "核心问题"], "layout": "cover",
        "visual_suggestion": "old visual", "speaker_notes": "note", "duration_seconds": 10,
    }]})
    runtime.tool_context.builder = runtime.builder
    await runtime.artifacts.create("slide_content", "default", {"slides": [{
        "id": "slide_01", "page_type": "cover", "title": "旧首页", "body": ["副标题"],
    }]}, producer_agent="slide_content")

    decision = await _agent_call(runtime, "layout", LAYOUT_AGENT, 0)

    assert provider.calls == 1
    assert decision.output["slides"][0]["slide_id"] == "slide_01"
    elements = decision.output["slides"][0]["elements"]
    semantic_elements = [item for item in elements if item.get("content_ref")]
    assert {item["content_ref"] for item in semantic_elements} == {"title", "body", "purpose"}
    assert all(float(item["x"]) >= 2.2 for item in semantic_elements)


@pytest.mark.asyncio
async def test_layout_schema_incompatibility_compiles_llm_analysis_instead_of_failing(client, auth_headers):
    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _agent_call

    course_id, _ = await _ready_course(client, auth_headers)
    provider = _ScriptedProvider([
        AgentDecision(
            completed=True,
            output={"slides": [{
                "id": "slide_01", "page_type": "cover", "title": "LLM 分析后的首页",
                "body": ["八年级物理微课", "潜水艇越深，浮力越大吗？"],
                "visual_suggestion": "采用左侧学术引导区与右侧高对比度主视觉区，强化留白和视觉重心",
            }]},
            summary="已完成首页审美分析",
        ),
    ])
    runtime, _ = await _build_runtime(course_id, provider)
    runtime.selected_slide_ids = ["slide_01"]
    runtime.builder.from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [{
        "id": "slide_01", "page_type": "cover", "title": "旧首页", "purpose": "p",
        "body": ["八年级物理微课", "核心问题"], "layout": "cover",
        "visual_suggestion": "old visual", "speaker_notes": "note", "duration_seconds": 10,
    }]})
    runtime.tool_context.builder = runtime.builder
    await runtime.artifacts.create("slide_content", "default", {"slides": [{
        "id": "slide_01", "page_type": "cover", "title": "旧首页",
        "body": ["八年级物理微课", "核心问题"],
    }]}, producer_agent="slide_content")

    decision = await _agent_call(runtime, "layout", LAYOUT_AGENT, 0)

    assert provider.calls == 1, "自然语言审美结果应本地编译，不能再次请求不兼容的嵌套 Schema"
    layout = decision.output["slides"][0]
    assert layout["slide_id"] == "slide_01"
    assert layout["layout_type"] == "academic_split_hero"
    assert len(layout["elements"]) >= 5
    applied = await execute_tool("layout_slide_batch", runtime.tool_context, {"layouts": [layout]})
    assert applied.ok is True
    assert applied.output["placed"] >= 5
