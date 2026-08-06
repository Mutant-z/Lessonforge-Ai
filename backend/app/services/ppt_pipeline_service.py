"""PPT Agent 流水线服务：把 ppt 课程任务运行分派进多 Agent 流水线。

- initial / sync_dependencies → 完整流水线（叙事→模板→内容→视觉规划→布局→媒体→编辑→QA→修订闭环）
- message → 修订 Agent（复用 _generate_ppt_revision 的验证/修复机制）
- sync_context → 复用 _generate_context_sync（保留源文件、同步最新上下文）
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState
from app.agent.events import PipelineEventEmitter
from app.agent.pipeline import PipelineRuntime, build_plan, finalize_content, run_revision_loop
from app.agent.registry import ToolContext
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AgentMessage, Artifact, ArtifactLock, GenerationRun, PipelineRun
from app.providers.llm.mock import MockProvider
from app.renderers.presentation_builder import PresentationBuilder, design_system_for
from app.schemas.artifact import AgentArtifactRevisionPayload, PPTContent
from app.services.ppt_template_service import resolve_ppt_template

logger = logging.getLogger(__name__)

# generation_run_id -> asyncio.Event（pause 端点设置，loop 在 Agent 边界检查）
PAUSE_EVENTS: dict[str, asyncio.Event] = {}


@dataclass
class PipelineRunResult:
    """返回给 execute_task_run 下游（validate→save→事件→stale→质量刷新）的产物。"""

    content: dict
    revision: AgentArtifactRevisionPayload | None = None
    user_message: AgentMessage | None = None
    model_name: str = "mock"
    profile: object | None = None
    provider: object | None = None
    locks: list = field(default_factory=list)
    source_versions: dict = field(default_factory=dict)
    change_summary: str = "首次生成"


async def _latest_artifact(db, course_id: str, kind: str) -> Artifact | None:
    return await db.scalar(select(Artifact).where(
        Artifact.course_id == course_id, Artifact.artifact_type == kind,
    ).order_by(Artifact.version.desc()))


def _workspace_root(course_id: str, generation_run_id: str) -> Path:
    root = Path(get_settings().storage_root) / "generated" / course_id / "ppt_pipeline" / generation_run_id
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("analysis", "content", "plans", "assets", "drafts", "renders", "qa", "logs", "output"):
        (root / sub).mkdir(exist_ok=True)
    return root


async def _get_or_create_pipeline_run(db, generation_run: GenerationRun, max_rounds: int) -> PipelineRun:
    row = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == generation_run.id))
    if row is None:
        row = PipelineRun(generation_run_id=generation_run.id, status="running", max_revision_rounds=max_rounds)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    else:
        row.status = "running"
        row.error_json = None
        await db.commit()
        await db.refresh(row)
    return row


async def _build_runtime(db, course, task, generation_run, blueprint, source, profile, provider, config,
                         knowledge_context, source_versions, locks, user_message) -> PipelineRuntime:
    pipeline_run = await _get_or_create_pipeline_run(db, generation_run, max_rounds=3)
    workspace = _workspace_root(course.id, generation_run.id)
    preferred_template = resolve_ppt_template(
        (config.preferences_json or {}).get("default_ppt_template") if config else None,
    )["id"]
    context = ContextState(
        course=course,
        blueprint=blueprint.content_json,
        profile=profile,
        knowledge=knowledge_context.get("ppt_design_knowledge") or knowledge_context,
        source_artifact=source,
        user_instruction=user_message.content if user_message else "",
        locks=locks,
        upstream={},
    )
    context.upstream = knowledge_context.get("upstream") or {}
    context.template = design_system_for(resolve_ppt_template(preferred_template))
    builder = PresentationBuilder(preferred_template)
    artifacts = PipelineArtifactManager(pipeline_run, workspace)
    emitter = await PipelineEventEmitter.for_run(generation_run, pipeline_run)
    runtime = PipelineRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=generation_run,
        pipeline_run=pipeline_run, profile=profile, provider=provider, config=config,
        knowledge_context=knowledge_context, source_versions=source_versions,
        locks=locks, source_artifact=source, user_message=user_message,
        preferred_template=preferred_template, trigger_type=generation_run.trigger_type,
        context=context, builder=builder, artifacts=artifacts, emitter=emitter,
        workspace_root=workspace, pause_event=PAUSE_EVENTS.get(generation_run.id),
    )
    checkpoint = pipeline_run.checkpoint_json or {}
    if checkpoint.get("step_index"):
        runtime.context.restore(checkpoint)
        runtime.checkpoint_start = int(checkpoint.get("step_index", 0))
    tool_context = ToolContext(
        ctx=context, builder=builder, workspace_root=workspace, course=course, task=task,
        generation_run_id=generation_run.id, pipeline_run_id=pipeline_run.id,
        provider=provider, artifacts=artifacts, emitter=emitter, runtime=runtime,
    )
    runtime.tool_context = tool_context
    return runtime


async def _finish_pipeline(runtime: PipelineRuntime, status: str, error: str | None = None):
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, runtime.pipeline_run.id)
        if row:
            row.status = status
            row.token_usage_json = runtime.token_usage
            row.error_json = {"message": error} if error else None
            if status in {"completed", "failed", "cancelled"}:
                from app.models.entities import now
                row.finished_at = now()
            await db.commit()
    if runtime.emitter is not None:
        if status == "completed":
            await runtime.emitter.pipeline_completed(llm_calls=runtime.token_usage.get("llm_calls", 0),
                                                     tokens=runtime.token_usage.get("tokens", 0))
        elif error:
            await runtime.emitter.pipeline_failed(error=error)


# ---------- 各触发路径 ----------

async def _write_final_pptx(runtime: PipelineRuntime, content: dict) -> str | None:
    """把 builder 动态渲染为最终 PPTX（导出优先使用）；仅完整流水线（builder 已构建）。"""
    if runtime.builder is None or not runtime.builder.slides:
        return None
    from sqlalchemy import func
    async with SessionLocal() as db:
        next_version = (await db.scalar(select(func.max(Artifact.version)).where(
            Artifact.course_id == runtime.course.id, Artifact.artifact_type == "ppt",
        )) or 0) + 1
    out_dir = Path(get_settings().storage_root) / "generated" / runtime.course.id / "ppt"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{next_version}.pptx"
    runtime.builder.render(output)
    return str(output)


async def _run_pipeline_full(runtime: PipelineRuntime, blueprint) -> dict:
    plan = build_plan(runtime, runtime.trigger_type)
    await run_revision_loop(runtime, plan)
    content = finalize_content(runtime)
    await _write_final_pptx(runtime, content)
    await _finish_pipeline(runtime, "completed")
    return content


async def _run_pipeline_message(runtime: PipelineRuntime, source: Artifact, message: AgentMessage, version: int) -> tuple[dict, AgentArtifactRevisionPayload]:
    emitter = runtime.emitter
    await emitter.agent_started("revision", "修订 Agent", 0)
    if isinstance(runtime.provider, MockProvider):
        content = dict(source.content_json)
        assistant_reply = f"已根据你的要求创建PPT V{version}，原版本仍可在版本历史中恢复。"
    else:
        from app.services.course_task_service import _generate_ppt_revision, _ppt_template_instruction
        async with SessionLocal() as db:
            history = list(await db.scalars(select(AgentMessage).where(
                AgentMessage.course_id == runtime.course.id,
                AgentMessage.module_type == runtime.task.task_type,
            ).order_by(AgentMessage.created_at.desc()).limit(12)))
        schema = PPTContent
        base_instruction = (
            "最近对话：\n" + json.dumps([{"role": x.role, "content": x.content} for x in reversed(history)], ensure_ascii=False)
            + "\n锁定路径：\n" + json.dumps([x.json_path for x in runtime.locks], ensure_ascii=False)
            + "\n教师指令：\n" + message.content
            + "\ncontent_json 必须符合：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        ) + _ppt_template_instruction((source.content_json or {}).get("theme"))
        revision = await _generate_ppt_revision(
            runtime.provider, runtime.profile, runtime.knowledge_context, base_instruction, source, runtime.locks,
        )
        content = revision.content_json
        assistant_reply = revision.assistant_reply
    await emitter.revision_started(1, runtime.pipeline_run.max_revision_rounds, reason=message.content[:200], target_agents=["slide_content", "ppt_editor"])
    await emitter.artifact_created("revision_note", runtime.pipeline_run.id + "-rev", f"message-{version}", version,
                                   producer_agent="revision")
    await emitter.revision_completed(1, applied_changes=[f"教师指令：{message.content[:60]}"])
    await emitter.agent_completed("revision", "修订完成", artifact_id="revision_note")
    revision_payload = AgentArtifactRevisionPayload(content_json=content, assistant_reply=assistant_reply)
    await _finish_pipeline(runtime, "completed")
    return content, revision_payload


async def _run_pipeline_sync(db, runtime: PipelineRuntime, source: Artifact, blueprint, task) -> tuple[dict, object, object, dict, list]:
    from app.services.course_task_service import _generate_context_sync
    value, model_name, profile, source_versions, locks = await _generate_context_sync(
        db, runtime.course, task, source, blueprint,
    )
    content = value.model_dump()
    await _finish_pipeline(runtime, "completed")
    return content, model_name, profile, source_versions, locks


async def run_ppt_pipeline(db, course, task, run: GenerationRun, blueprint) -> PipelineRunResult:
    """执行 ppt 任务运行（Agent 流水线），返回与下游 save 块兼容的结果。"""
    from app.services.course_task_service import _latest_artifact as _latest, _profile_provider
    from app.services.model_config_service import resolved_model_name
    from app.services.project_knowledge_service import build_project_knowledge_context

    source = await _latest(db, course.id, "ppt")
    profile, provider, config = await _profile_provider(db, course, task)
    knowledge_context, source_versions = await build_project_knowledge_context(
        db, task, blueprint.content_json, blueprint.version, profile.context_json,
        config.context_window_tokens if config else None,
    )
    locks: list[ArtifactLock] = []
    if source:
        locks = list(await db.scalars(select(ArtifactLock).where(ArtifactLock.artifact_id == source.id)))
        if any(lock.json_path in {"", "$"} for lock in locks):
            raise RuntimeError("当前任务文件已整体锁定")

    user_message = None
    if run.trigger_type == "message":
        user_message = await db.scalar(select(AgentMessage).where(
            AgentMessage.run_id == run.id, AgentMessage.role == "user",
        ).order_by(AgentMessage.created_at.desc()))
        if not user_message:
            raise RuntimeError("未找到本次教师修改指令")

    runtime = await _build_runtime(
        db, course, task, run, blueprint, source, profile, provider, config,
        knowledge_context, source_versions, locks, user_message,
    )
    model_name = resolved_model_name(provider, config)

    if run.trigger_type == "message":
        if not source:
            raise RuntimeError("任务文件尚未生成")
        content, revision_payload = await _run_pipeline_message(runtime, source, user_message, source.version + 1)
        return PipelineRunResult(
            content=content, revision=revision_payload, user_message=user_message,
            model_name=model_name, profile=profile, provider=provider, locks=locks,
            source_versions=source_versions, change_summary=f"Agent 对话修改：{user_message.content[:80]}",
        )
    if run.trigger_type == "sync_context":
        if not source:
            raise RuntimeError("任务文件尚未生成，无法同步项目上下文")
        content, model_name, profile, source_versions, locks = await _run_pipeline_sync(db, runtime, source, blueprint, task)
        return PipelineRunResult(
            content=content, model_name=model_name, profile=profile, provider=provider,
            locks=locks, source_versions=source_versions, change_summary="上下文同步生成",
        )

    content = await _run_pipeline_full(runtime, blueprint)
    return PipelineRunResult(
        content=content, model_name=model_name, profile=profile, provider=provider,
        locks=locks, source_versions=source_versions,
        change_summary="上下文同步生成" if run.trigger_type in {"sync_dependencies", "sync_context"} else "首次生成",
    )
