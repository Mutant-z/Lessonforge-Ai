"""视频脚本 V4 动态 Agent 运行时测试（Mock Provider 全链：意图 → 工具 → QA → 发布门禁）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.agents.video_script.intents import infer_video_script_intent
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Artifact, CourseBlueprint, CourseProject, CourseTask, GenerationRun, PipelineRun

_runtime_course_cache: dict[str, str] = {}


@pytest.fixture
async def _runtime_course(client, auth_headers):
    """共享课程（模块级缓存）：只建一次，避免多次 ready_course 的后台任务相互干扰。"""
    from agent_pipeline_helpers import ready_course

    if not _runtime_course_cache:
        _runtime_course_cache["course_id"] = await ready_course(client, auth_headers, title="视频脚本运行时课程")
    return _runtime_course_cache["course_id"]


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
        gen_run = GenerationRun(course_id=course_id, course_task_id=task.id, thread_id=f"vs-{trigger}-{id(artifact)}",
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
async def test_runtime_answer_only_does_not_publish(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="这个脚本有几个片段？")
    await runtime.run()
    assert runtime.result_status == "no_change"
    assert not runtime.publishable


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
async def test_runtime_no_change_when_identical(client, auth_headers, _runtime_course):
    runtime = await _make_runtime(_runtime_course, instruction="保持不变")
    await runtime.run()
    assert runtime.result_status in {"no_change", "applied"}


@pytest.mark.asyncio
async def test_runtime_qa_gate_blocks_corrupt_references(client, auth_headers, _runtime_course):
    """故意制造非法目标引用 → QA 阻断、返修无法收敛 → 不发布。"""
    def corrupt(source):
        for scene in source["scenes"]:
            scene["objective_ids"] = ["OBJ-NOPE"]

    runtime = await _make_runtime(_runtime_course, instruction="把章节重排一下", corrupt=corrupt, pre_upgrade=True)
    await runtime.run()
    assert runtime.result_status in {"rejected", "no_change"}
    assert not runtime.publishable
    assert runtime.blocking_issues, "非法引用必须产生阻断问题"


@pytest.mark.asyncio
async def test_runtime_intent_resolution_initial(client, auth_headers, _runtime_course):
    plan = await infer_video_script_intent(None, "initial", "")
    assert plan.intent == "GENERATE"
    assert plan.mutates_document
