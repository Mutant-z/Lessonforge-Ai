"""视频脚本 Agent V4 流水线服务：把 video_script 任务运行分派进动态工具化流水线。

- initial → 全链生成（上下文调研 → 章节 → 分镜 → QA → 终稿，目录由 AI 动态规划）
- message → 意图识别 → 计划 → 工具修改内存候选稿 → QA → 返修 → 发布
- sync_context → 上下文同步（保留源内容，同步最新项目上下文）

result_status 语义与 PPT / lesson_plan / task_sheet 对齐：applied / no_change / rejected / needs_confirmation。
- no_change / rejected / needs_confirmation → skip_publish（不创建正式新版本，原版本保持不变）
- applied → 创建 V4 Artifact 版本
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from app.agent.agents.video_script.runtime import VideoScriptAgentRuntime
from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState
from app.agent.core.loop import PipelinePaused
from app.agent.events import PipelineEventEmitter
from app.agent.registry import ToolContext
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AgentChatSession, AgentMessage, Artifact, ArtifactLock, GenerationRun, ModelConfig, PipelineRun
from app.schemas.artifact import AgentArtifactRevisionPayload
from app.services.ppt_pipeline_service import (
    PAUSE_EVENTS, PipelineRunResult, _get_or_create_pipeline_run, _latest_artifact,
)
from app.services.project_knowledge_service import build_project_knowledge_context

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_TYPE = "video_script_agent_pipeline"


def _workspace_root(course_id: str, generation_run_id: str) -> Path:
    root = Path(get_settings().storage_root) / "generated" / course_id / "video_script_pipeline" / generation_run_id
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("analysis", "content", "plans", "assets", "drafts", "qa", "output"):
        (root / sub).mkdir(exist_ok=True)
    return root


async def _build_runtime(db, course, task, generation_run, blueprint, source, profile, provider, config,
                         knowledge_context, source_versions, locks, user_message) -> VideoScriptAgentRuntime:
    pipeline_run = await _get_or_create_pipeline_run(db, generation_run, max_rounds=2)
    pipeline_run.pipeline_type = DEFAULT_PIPELINE_TYPE
    await db.commit()
    await db.refresh(pipeline_run)
    workspace = _workspace_root(course.id, generation_run.id)
    context = ContextState(
        course=course,
        blueprint=blueprint.content_json,
        profile=profile,
        knowledge=knowledge_context,
        source_artifact=source,
        user_instruction=user_message.content if user_message else "",
        locks=locks,
        upstream=knowledge_context.get("upstream") or knowledge_context.get("sibling_artifacts") or {},
    )
    artifacts = PipelineArtifactManager(pipeline_run, workspace)
    emitter = await PipelineEventEmitter.for_run(generation_run, pipeline_run, task_type="video_script")
    request_metadata = dict(getattr(user_message, "metadata_json", None) or {})
    video_session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == "video_generation",
    ))
    renderer = await db.get(ModelConfig, video_session.video_model_config_id) if video_session and video_session.video_model_config_id else None
    if renderer:
        request_metadata["renderer_api_mode"] = renderer.api_mode
        request_metadata["renderer_max_scene_seconds"] = 10 if renderer.api_mode == "gemini_interactions_video" else 15
    runtime = VideoScriptAgentRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=generation_run,
        pipeline_run=pipeline_run, profile=profile, provider=provider, config=config,
        knowledge_context=knowledge_context, source_versions=source_versions,
        locks=locks, source_artifact=source, user_message=user_message,
        trigger_type=generation_run.trigger_type,
        context=context, artifacts=artifacts, emitter=emitter,
        workspace_root=workspace, pause_event=PAUSE_EVENTS.setdefault(generation_run.id, asyncio.Event()),
        request_metadata=request_metadata,
    )
    tool_context = ToolContext(
        ctx=context, workspace_root=workspace, course=course, task=task,
        generation_run_id=generation_run.id, pipeline_run_id=pipeline_run.id,
        provider=provider, artifacts=artifacts, emitter=emitter, runtime=runtime,
    )
    runtime.tool_context = tool_context
    checkpoint = pipeline_run.checkpoint_json or {}
    if checkpoint.get("step_index"):
        runtime.context.restore(checkpoint)
        runtime.checkpoint_start = int(checkpoint.get("step_index", 0))
    return runtime


async def _finish_pipeline(runtime: VideoScriptAgentRuntime, status: str, error: str | None = None, artifact_id: str | None = None):
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, runtime.pipeline_run.id)
        if row:
            row.status = status
            row.token_usage_json = runtime.token_usage
            row.error_json = {"message": error} if error else None
            row.plan_json = {
                **(row.plan_json or {}),
                "result_status": getattr(runtime, "result_status", "applied"),
                "active_intent": getattr(runtime, "active_intent", "GENERATE"),
                "repair_round": getattr(runtime, "repair_round", 0),
            }
            if status in {"completed", "failed", "cancelled"}:
                from app.models.entities import now

                row.finished_at = now()
            await db.commit()
    if runtime.emitter is not None:
        if status == "completed":
            await runtime.emitter.pipeline_completed(
                artifact_id=artifact_id,
                llm_calls=runtime.token_usage.get("llm_calls", 0),
                tokens=runtime.token_usage.get("tokens", 0),
            )
            sub_agents = [
                {"agent": item.get("agent", ""), "summary": item.get("summary", ""),
                 "artifact_id": item.get("artifact_id"), "status": "completed"}
                for item in runtime.context.decisions
            ]
            await runtime.emitter.agent_message_completed(
                summary=runtime.dialogue_summary, sub_agents=sub_agents, artifact_id=artifact_id,
            )
        elif error:
            await runtime.emitter.pipeline_failed(error=error)
            await runtime.emitter.agent_message_failed(message=error)
        else:
            await runtime.emitter.agent_message_failed(message="")


async def _pause_at_safe_boundary(runtime: VideoScriptAgentRuntime, boundary: str) -> None:
    from app.agent.core.loop import _persist_paused

    if not runtime.pause_requested():
        return
    await _persist_paused(runtime, runtime.checkpoint_start, runtime.current_agent_key or boundary)
    raise PipelinePaused()


def _scene_scope(message: AgentMessage, source: Artifact | None) -> list[str]:
    metadata = dict(getattr(message, "metadata_json", None) or {})
    structured = list(metadata.get("selected_scene_ids") or metadata.get("target_scene_ids") or [])
    if structured:
        return [str(value) for value in structured if str(value)]
    return []


def _section_scope(message: AgentMessage, source: Artifact | None) -> list[str]:
    """把教师指令中的章节范围转换为稳定章节 ID。"""
    metadata = dict(getattr(message, "metadata_json", None) or {})
    structured = list(metadata.get("selected_section_ids") or metadata.get("target_section_ids") or [])
    if structured:
        return [str(value) for value in structured if str(value)]
    if source is None:
        return []
    source_sections = {
        str(item.get("id")) for item in (source.content_json or {}).get("outline", {}).get("sections", [])
    }
    active_section_id = str(metadata.get("active_section_id") or "")
    if active_section_id in source_sections:
        return [active_section_id]
    return []


async def _run_pipeline_full(runtime: VideoScriptAgentRuntime) -> dict:
    await _pause_at_safe_boundary(runtime, "orchestrator")
    await runtime.run()
    await _pause_at_safe_boundary(runtime, "finalize")
    content = dict(runtime.draft_content)
    section_count = len((content.get("outline") or {}).get("sections", []))
    scene_count = len(content.get("scenes", []))
    runtime.dialogue_summary = (
        f"视频脚本已生成完成，共 {section_count} 个动态章节、{scene_count} 个分镜。"
        "章节由 AI 根据课程内容动态规划，你可以在右侧预览，或继续输入指令调整结构与内容。"
    )
    return content


async def _run_pipeline_message(runtime: VideoScriptAgentRuntime, source: Artifact, message: AgentMessage) -> tuple[dict, AgentArtifactRevisionPayload]:
    emitter = runtime.emitter
    runtime.selected_section_ids = _section_scope(message, source)
    runtime.selected_scene_ids = _scene_scope(message, source)
    if emitter is not None:
        await emitter.agent_status_delta("orchestrator", "正在理解修改范围并创建动态执行计划。\n")
        await emitter.revision_started(1, runtime.pipeline_run.max_revision_rounds, reason=message.content[:200], target_agents=["orchestrator"])
        await emitter.emit_domain("repair.started", message="已开始创建视频脚本新修订版本", payload={
            "revision": source.version + 1, "selected_section_ids": runtime.selected_section_ids,
            "selected_scene_ids": runtime.selected_scene_ids,
        })
    await runtime.run()
    await _pause_at_safe_boundary(runtime, "revision")
    source_content = source.content_json or {}
    if runtime.result_status in {"no_change", "rejected", "needs_confirmation"}:
        content = dict(source_content)
        if runtime.result_status == "rejected":
            assistant_reply = "本轮修订未通过视频脚本质询门禁，未创建新版本；原视频脚本保持不变。"
        elif runtime.result_status == "no_change":
            assistant_reply = "当前视频脚本已符合要求，本轮未创建空转版本；原视频脚本保持不变。"
        else:
            assistant_reply = runtime.dialogue_summary or "修改范围或目标存在歧义，请确认后重试；本轮未创建新版本。"
    else:
        content = dict(runtime.draft_content)
        assistant_reply = f"已根据你的要求创建视频脚本 V{source.version + 1}；原版本仍可在版本历史中恢复。"
    runtime.dialogue_summary = assistant_reply
    if emitter is not None:
        await emitter.revision_completed(1, applied_changes=[f"教师指令：{message.content[:60]}"])
        await emitter.emit_domain("repair.completed", message="视频脚本修订已完成", payload={"revision": source.version + 1})
        await emitter.emit_domain(
            "polish.result",
            message=assistant_reply,
            payload={
                "result_status": runtime.result_status,
                "active_intent": runtime.active_intent,
                "changed_sections": list(runtime.affected_section_ids),
                "changed_scenes": list(runtime.affected_scene_ids),
            },
        )
        await emitter.agent_message_append(assistant_reply)
    return content, AgentArtifactRevisionPayload(content_json=content, assistant_reply=assistant_reply)


async def _run_pipeline_sync(runtime: VideoScriptAgentRuntime, source: Artifact) -> dict:
    await _pause_at_safe_boundary(runtime, "context_sync")
    await runtime.run()
    await _pause_at_safe_boundary(runtime, "context_sync")
    if runtime.result_status == "no_change":
        content = dict(source.content_json or {})
        runtime.dialogue_summary = "已同步最新项目上下文，文件内容保持不变。"
    else:
        content = dict(runtime.draft_content)
        runtime.dialogue_summary = "已依据最新项目上下文更新视频脚本候选稿。"
    return content


async def complete_video_script_pipeline_after_publish(runtime: VideoScriptAgentRuntime | None, artifact_id: str) -> None:
    """Publish the sole success terminal event after the domain Artifact commit."""
    if runtime is None:
        return
    try:
        await _finish_pipeline(runtime, "completed", artifact_id=artifact_id)
    except Exception:  # The already committed official Artifact remains authoritative.
        logger.exception(
            "video_script pipeline terminal event failed after Artifact commit",
            extra={"generation_run_id": runtime.generation_run.id, "artifact_id": artifact_id},
        )


async def run_video_script_pipeline(db, course, task, run: GenerationRun, blueprint) -> PipelineRunResult:
    """执行 video_script 任务运行（动态工具化流水线），返回与下游 save 块兼容的结果。"""
    from app.services.course_task_service import _profile_provider
    from app.services.model_config_service import resolved_model_name

    source = await _latest_artifact(db, course.id, "video_script")
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
    await runtime.emitter.agent_message_started("教学 Agent", mirror_status=False)

    if run.trigger_type == "message":
        if not source:
            raise RuntimeError("任务文件尚未生成")
        content, revision_payload = await _run_pipeline_message(runtime, source, user_message)
        return PipelineRunResult(
            content=content, revision=revision_payload, user_message=user_message,
            model_name=model_name, profile=profile, provider=provider, locks=locks,
            source_versions=source_versions,
            change_summary=f"Agent 对话修改：{user_message.content[:80]}",
            runtime=runtime,
            skip_publish=runtime.result_status in {"no_change", "needs_confirmation", "rejected"},
        )
    if run.trigger_type == "sync_context":
        if not source:
            raise RuntimeError("任务文件尚未生成，无法同步项目上下文")
        content = await _run_pipeline_sync(runtime, source)
        return PipelineRunResult(
            content=content, model_name=model_name, profile=profile, provider=provider,
            locks=locks, source_versions=source_versions, change_summary="上下文同步生成",
            runtime=runtime,
            skip_publish=runtime.result_status == "no_change",
        )

    content = await _run_pipeline_full(runtime)
    return PipelineRunResult(
        content=content, model_name=model_name, profile=profile, provider=provider,
        locks=locks, source_versions=source_versions,
        change_summary="上下文同步生成" if run.trigger_type in {"sync_dependencies", "sync_context"} else "首次生成",
        runtime=runtime,
    )
