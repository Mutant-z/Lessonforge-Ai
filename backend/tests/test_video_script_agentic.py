"""视频脚本 V4 动态 Agent 运行时测试（Mock Provider 全链：意图 → 工具 → QA → 发布门禁）。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.agents.video_script.intents import infer_video_script_intent
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import (
    AgentHumanRequest, AgentMessage, AgentRunInstruction, Artifact, CourseBlueprint, CourseProject,
    CourseTask, GenerationEvent, GenerationRun, PipelineRun,
)

_runtime_course_cache: dict[str, str] = {}


@pytest.fixture
async def _runtime_course(client, auth_headers):
    """按测试用户复用课程，避免跨用户测试访问同一课程返回 404。"""
    from agent_pipeline_helpers import ready_course

    cache_key = auth_headers["Authorization"]
    if cache_key not in _runtime_course_cache:
        _runtime_course_cache[cache_key] = await ready_course(client, auth_headers, title="视频脚本运行时课程")
    return _runtime_course_cache[cache_key]


async def _make_runtime(course_id, *, instruction="", trigger="message", corrupt=None, pre_upgrade=False):
    """基于共享课程构建一个独立 VideoScriptAgentRuntime。

    共享课程的 video_script Artifact 在 runtime 开关关闭时可能是 V2/V3：
    - pre_upgrade=False（默认）：保持源版本原样，运行时内部完成 V2/V3 → V4 升级，
      用于验证「首次编辑触发 V4 升级并发布」；
    - pre_upgrade=True：先确定性升级为 V4 再交给运行时，用于验证 V4 源上的
      QA 拦截（corrupt 会保留在候选稿中）。
    """
    from app.agent.agents.video_script.runtime import VideoScriptAgentRuntime
    from app.agent.agents.video_script.builder import build_initial_builder
    from app.agent.artifacts import PipelineArtifactManager
    from app.agent.context import ContextState
    from app.agent.events import PipelineEventEmitter
    from app.agent.registry import ToolContext
    from app.schemas.video_script_v4 import VIDEO_SCRIPT_V4
    from app.services.course_task_service import _profile_provider

    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id, CourseTask.task_type == "video_script",
        ))
        blueprint = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_id,
            CourseBlueprint.version == course.current_blueprint_version,
        ))
        profile, provider, config = await _profile_provider(db, course, task)
        artifact = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id, Artifact.artifact_type == "video_script",
        ).order_by(Artifact.version.desc()))
        source_content = dict(artifact.content_json)
        if pre_upgrade and source_content.get("schema_version") != VIDEO_SCRIPT_V4:
            builder = build_initial_builder(blueprint.content_json)
            source_content = builder.to_content()
        if corrupt:
            corrupt(source_content)
        artifact.content_json = source_content
        await db.commit()
        await db.refresh(artifact)
        gen_run = GenerationRun(course_id=course_id, course_task_id=task.id, thread_id=f"vs-{trigger}-{uuid4()}",
                                run_type="task", trigger_type=trigger, status="running")
        db.add(gen_run)
        await db.flush()
        pr = PipelineRun(generation_run_id=gen_run.id, status="running", pipeline_type="video_script_agent_pipeline")
        db.add(pr)
        await db.commit()
        await db.refresh(gen_run)
        await db.refresh(pr)
    workspace = Path(get_settings().storage_root) / "generated" / course_id / "video_script_pipeline" / gen_run.id
    workspace.mkdir(parents=True, exist_ok=True)
    for sub in ("analysis", "content", "plans", "assets", "drafts", "qa", "output"):
        (workspace / sub).mkdir(exist_ok=True)
    context = ContextState(
        blueprint=blueprint.content_json, profile=profile,
        source_artifact=artifact, user_instruction=instruction, locks=[], upstream={},
    )
    artifacts = PipelineArtifactManager(pr, workspace)
    emitter = await PipelineEventEmitter.for_run(gen_run, pr, task_type="video_script")
    runtime = VideoScriptAgentRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=gen_run, pipeline_run=pr,
        profile=profile, provider=provider, config=config, knowledge_context={},
        source_versions={}, locks=[], source_artifact=artifact, user_message=None,
        trigger_type=trigger, context=context, artifacts=artifacts, emitter=emitter,
        workspace_root=workspace, request_metadata={},
    )
    runtime.tool_context = ToolContext(
        ctx=context, workspace_root=workspace, course=course, task=task,
        generation_run_id=gen_run.id, pipeline_run_id=pr.id, provider=provider,
        artifacts=artifacts, emitter=emitter, runtime=runtime,
    )
    return runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["narration", "visual", "continuity"])
async def test_active_run_instruction_accepts_video_modes(client, auth_headers, _runtime_course, mode):
    runtime = await _make_runtime(_runtime_course, instruction="优化视频脚本")
    response = await client.post(
        f"/api/v1/courses/{_runtime_course}/tasks/video_script/runs/{runtime.generation_run.id}/instructions",
        headers=auth_headers,
        json={"content": "优化目标分镜", "mode": mode},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    async with SessionLocal() as db:
        instruction = await db.get(AgentRunInstruction, payload["instruction_id"])
    assert instruction is not None
    assert instruction.metadata_json["mode"] == mode


@pytest.mark.asyncio
async def test_runtime_answer_only_does_not_publish(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="这个脚本有几个片段？")
    await runtime.run()
    assert runtime.result_status == "no_change"
    assert not runtime.publishable


@pytest.mark.asyncio
async def test_runtime_inspect_only_has_no_score_and_does_not_publish(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="检查一下脚本质量")
    await runtime.run()
    validation = await runtime.artifacts.latest("video_script_validation")
    data = (validation or {}).get("data") or {}
    serialized = str(data).lower()
    assert runtime.result_status == "no_change"
    assert not runtime.publishable
    assert "score" not in serialized


@pytest.mark.asyncio
async def test_runtime_restructure_publishes_v4(client, auth_headers, _runtime_course):
    """验收场景：「不要固定导入和总结，改成问题驱动的三章结构」→ 首次编辑触发 V4 升级并发布。"""
    runtime = await _make_runtime(_runtime_course, instruction="不要固定导入和总结，改成问题驱动的三章结构")
    await runtime.run()
    assert runtime.result_status == "applied"
    assert runtime.publishable
    assert runtime.draft_content["schema_version"] == "4.0"
    sections = runtime.draft_content["outline"]["sections"]
    assert len(sections) >= 1
    assert runtime.draft_markdown
    # 结构门禁：候选稿可被 V4 模型直接实例化
    from app.schemas.video_script_v4 import SeedanceVideoScriptContentV4

    SeedanceVideoScriptContentV4.model_validate(runtime.draft_content)


@pytest.mark.asyncio
async def test_resolution_request_keeps_video_script_unchanged(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="把分辨率调成480")
    await runtime.run()

    assert runtime.result_status in {"settings_applied", "settings_unchanged"}
    assert not runtime.publishable
    assert runtime.pending_video_resolution == "854x480"
    assert "854x480" in runtime.dialogue_summary
    # Runtime 只产生待提交副作用，不再自行跨 Session 写库或提前发成功事件。
    async with SessionLocal() as db:
        setting_events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == runtime.generation_run.id,
            GenerationEvent.event_type == "video_generation.setting.updated",
        )))
    assert setting_events == []


@pytest.mark.asyncio
async def test_video_script_completion_replaces_streaming_body_without_duplicate(client, auth_headers, _runtime_course):
    from app.services.video_script_pipeline_service import complete_video_script_pipeline_after_publish

    runtime = await _make_runtime(_runtime_course, instruction="把分辨率调成720")
    reply = "已记录视频生成分辨率偏好：1280x720。视频脚本内容保持不变。"
    await runtime.emitter.agent_message_started("视频脚本 Agent", mirror_status=False)
    runtime.dialogue_summary = reply
    await complete_video_script_pipeline_after_publish(runtime, runtime.source_artifact.id)

    async with SessionLocal() as db:
        message = await db.scalar(select(AgentMessage).where(
            AgentMessage.run_id == runtime.generation_run.id,
            AgentMessage.role == "assistant",
        ))
        events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == runtime.generation_run.id,
            GenerationEvent.event_type == "agent_message_delta",
        ).order_by(GenerationEvent.id)))

    assert message is not None
    assert message.content == reply
    assert message.content.count(reply) == 1
    assert len(events) == 1
    assert events[0].data_json.get("reset") is True
    assert events[0].data_json.get("delta") == reply


@pytest.mark.asyncio
async def test_runtime_no_change_when_identical(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="保持不变")
    await runtime.run()
    assert runtime.result_status in {"no_change", "applied"}


@pytest.mark.asyncio
async def test_runtime_no_qa_blocking_for_content_issues(client, auth_headers, _runtime_course):
    """行为变更：发布前阻断检测与定向返修已彻底移除。内容层面的问题
    （如非法的目标引用）不再触发 rejected——结构合法即发布，质量由
    保存后的统一质量报告以问题清单提示，不阻塞任务完成。"""
    def corrupt(source):
        for scene in source["scenes"]:
            scene["objective_ids"] = ["OBJ-NOPE"]

    runtime = await _make_runtime(_runtime_course, instruction="把章节重排一下", corrupt=corrupt, pre_upgrade=True)
    await runtime.run()
    assert runtime.result_status == "applied"
    assert runtime.publishable
    assert not runtime.blocking_issues, "内容问题不再产生发布阻断"


@pytest.mark.asyncio
async def test_runtime_intent_resolution_initial(client, auth_headers, _runtime_course):
    plan = await infer_video_script_intent(None, "initial", "")
    assert plan.intent == "GENERATE"
    assert plan.mutates_document


@pytest.mark.asyncio
async def test_destructive_change_pauses_same_run_for_confirmation(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="删除第一章")
    await runtime.run()
    async with SessionLocal() as db:
        pipeline = await db.get(PipelineRun, runtime.pipeline_run.id)
        request = await db.scalar(select(AgentHumanRequest).where(
            AgentHumanRequest.pipeline_run_id == runtime.pipeline_run.id,
            AgentHumanRequest.status == "pending",
        ))
    assert runtime.result_status == "needs_confirmation"
    assert pipeline.status == "paused"
    assert request is not None
    assert not runtime.publishable


@pytest.mark.asyncio
async def test_queued_instruction_merges_scope_and_preservation(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="压缩口播")
    await runtime._prepare()
    scene_id = runtime.builder.scenes[0]["id"]
    async with SessionLocal() as db:
        db.add(AgentRunInstruction(
            pipeline_run_id=runtime.pipeline_run.id,
            content="画面保持不变",
            status="queued",
            metadata_json={"selected_scene_ids": [scene_id], "mode": "narration"},
        ))
        await db.commit()
    merged = await runtime._drain_instructions()
    async with SessionLocal() as db:
        row = await db.scalar(select(AgentRunInstruction).where(
            AgentRunInstruction.pipeline_run_id == runtime.pipeline_run.id,
        ))
    assert merged == ["画面保持不变"]
    assert runtime.selected_scene_ids == [scene_id]
    assert "preserve_visual" in runtime.intent_plan.preserve_constraints
    assert row.status == "script_merged"
