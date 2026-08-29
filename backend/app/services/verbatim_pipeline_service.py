"""教师逐字稿 Agent V2 流水线服务：把 verbatim 任务运行分派进动态工具化流水线。

- initial → 全链生成（上下文调研 → 逐段口播 → 时序 → QA → 终稿，段落对齐 scene_id）
- message → 意图识别 → 计划 → 工具修改内存候选稿 → QA → 返修 → 发布
- sync_context → 上下文同步（保留源内容，同步最新项目上下文）

result_status 语义与 PPT / lesson_plan / task_sheet 对齐：applied / no_change /
rejected / needs_confirmation。
- no_change / rejected / needs_confirmation → skip_publish（不创建正式新版本）
- applied → 创建 V2 Artifact 版本
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agent.agents.verbatim.runtime import VerbatimAgentRuntime
from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState
from app.agent.core.loop import PipelinePaused
from app.agent.events import PipelineEventEmitter
from app.agent.registry import ToolContext
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AgentMessage, Artifact, ArtifactLock, GenerationRun, PipelineRun
from app.schemas.artifact import AgentArtifactRevisionPayload
from app.services.ppt_pipeline_service import (
    PAUSE_EVENTS, PipelineRunResult, _get_or_create_pipeline_run, _latest_artifact,
)
from app.services.project_knowledge_service import build_project_knowledge_context
from app.services.chat_attachment_service import attachment_prompt, prepare_chat_attachments

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_TYPE = "verbatim_agent_pipeline"


def _workspace_root(course_id: str, generation_run_id: str) -> Path:
    root = Path(get_settings().storage_root) / "generated" / course_id / "verbatim_pipeline" / generation_run_id
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("analysis", "content", "plans", "assets", "drafts", "qa", "output"):
        (root / sub).mkdir(exist_ok=True)
    return root


async def _build_runtime(db, course, task, generation_run, blueprint, source, profile, provider, config,
                         knowledge_context, source_versions, locks, user_message) -> VerbatimAgentRuntime:
    attachments, runtime_provider = await prepare_chat_attachments(db, course, user_message, provider)
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
    emitter = await PipelineEventEmitter.for_run(generation_run, pipeline_run, task_type="verbatim")
    runtime = VerbatimAgentRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=generation_run,
        pipeline_run=pipeline_run, profile=profile, provider=runtime_provider, config=config,
        knowledge_context=knowledge_context, source_versions=source_versions,
        locks=locks, source_artifact=source, user_message=user_message,
        trigger_type=generation_run.trigger_type,
        context=context, artifacts=artifacts, emitter=emitter,
        workspace_root=workspace, pause_event=PAUSE_EVENTS.setdefault(generation_run.id, asyncio.Event()),
        request_metadata=dict(getattr(user_message, "metadata_json", None) or {}),
    )
    if attachments:
        context.add_note(attachment_prompt(attachments))
    if user_message is not None:
        recent = list(await db.scalars(
            select(AgentMessage).where(
                AgentMessage.course_id == course.id,
                AgentMessage.task_id == task.id,
                AgentMessage.module_type == "verbatim",
            ).order_by(AgentMessage.created_at.desc()).limit(8)
        ))
        runtime.dialogue_context = [
            {"role": row.role, "content": row.content, "metadata": row.metadata_json or {}}
            for row in reversed(recent)
            if row.id != user_message.id
        ]
        runtime.context.dialogue_context = runtime.dialogue_context
        pending = next(
            (item.get("metadata", {}).get("clarification") for item in reversed(runtime.dialogue_context)
             if item.get("role") == "assistant" and item.get("metadata", {}).get("clarification")),
            None,
        )
        if isinstance(pending, dict):
            source_id = pending.get("source_artifact_id")
            source_version = pending.get("source_version")
            if (not source_id or source_id == getattr(source, "id", None)) and (
                source_version is None or source_version == getattr(source, "version", None)
            ):
                runtime.pending_clarification = pending

    tool_context = ToolContext(
        ctx=context, workspace_root=workspace, course=course, task=task,
        generation_run_id=generation_run.id, pipeline_run_id=pipeline_run.id,
        provider=runtime_provider, artifacts=artifacts, emitter=emitter, runtime=runtime,
    )
    runtime.tool_context = tool_context
    # 注入完整视频脚本（knowledge 投影可能因超长被截断，首稿与事实门禁需要完整 scenes）。
    video_script_artifact = await _latest_artifact(db, course.id, "video_script")
    if video_script_artifact:
        runtime.video_script_raw = video_script_artifact.content_json
    checkpoint = pipeline_run.checkpoint_json or {}
    if checkpoint.get("context_snapshot"):
        runtime.context.restore(checkpoint.get("context_snapshot"))
    if isinstance(checkpoint.get("pending_clarification"), dict):
        runtime.pending_clarification = dict(checkpoint["pending_clarification"])
    runtime.selected_section_ids = list(checkpoint.get("selected_section_ids") or runtime.selected_section_ids)
    draft_snapshot = checkpoint.get("draft_snapshot")
    checkpoint_source_id = checkpoint.get("source_artifact_id")
    if isinstance(draft_snapshot, dict) and checkpoint_source_id == getattr(source, "id", None):
        runtime.builder = VerbatimBuilder(draft_snapshot)
        runtime.builder._revision = int(checkpoint.get("draft_revision", 0) or 0)
        runtime.tool_context.extra["builder"] = runtime.builder
        runtime.pending_course_title = checkpoint.get("pending_course_title")
    if checkpoint.get("step_index") and (not draft_snapshot or checkpoint_source_id == getattr(source, "id", None)):
        runtime.checkpoint_start = int(checkpoint.get("step_index", 0))
    return runtime


async def _finish_pipeline(runtime: VerbatimAgentRuntime, status: str, error: str | None = None, artifact_id: str | None = None):
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
                metadata=(
                    {"clarification": runtime.pending_clarification}
                    if runtime.pending_clarification
                    else {"intent": runtime.active_intent, "mutation_domain": getattr(runtime.intent_plan, "mutation_domain", "none")}
                ),
            )
        elif error:
            await runtime.emitter.pipeline_failed(error=error)
            await runtime.emitter.agent_message_failed(message=error)
        else:
            await runtime.emitter.agent_message_failed(message="")


async def _pause_at_safe_boundary(runtime: VerbatimAgentRuntime, boundary: str) -> None:
    from app.agent.core.loop import _persist_paused

    if not runtime.pause_requested():
        return
    await _persist_paused(runtime, runtime.checkpoint_start, runtime.current_agent_key or boundary)
    raise PipelinePaused()


def _section_scope(message: AgentMessage, source: Artifact | None) -> list[str]:
    """把教师指令中的章节范围转换为稳定章节 ID。"""
    metadata = dict(getattr(message, "metadata_json", None) or {})
    structured = list(metadata.get("selected_section_ids") or metadata.get("target_section_ids") or [])
    if source is None:
        return [str(value) for value in structured if str(value)]
    source_content = source.content_json or {}
    source_sections = list(source_content.get("sections", []) or [])
    known_ids = {str(item.get("id")) for item in source_sections if item.get("id")}

    def canonical(value: Any) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw in known_ids:
            return raw
        import re
        match = re.search(r"(\d+)", raw)
        if match:
            candidate = f"VB-{int(match.group(1)):02d}"
            if candidate in known_ids:
                return candidate
            index = int(match.group(1)) - 1
            if 0 <= index < len(source_sections):
                return str(source_sections[index].get("id") or "") or None
        return None

    if structured:
        return list(dict.fromkeys(item for value in structured if (item := canonical(value))))
    active_section_id = canonical(metadata.get("active_section_id"))
    return [active_section_id] if active_section_id else []


async def _run_pipeline_full(runtime: VerbatimAgentRuntime) -> dict:
    await _pause_at_safe_boundary(runtime, "orchestrator")
    await runtime.run()
    await _pause_at_safe_boundary(runtime, "finalize")
    content = dict(runtime.draft_content)
    section_count = len(content.get("sections", []))
    rate = float(content.get("speaking_rate_cps") or 4.0)
    runtime.dialogue_summary = (
        f"教师逐字稿已生成完成，共 {section_count} 段，默认语速 {rate} 字/秒。"
        "每段已对齐视频场景，你可以在右侧预览，或继续输入指令调整口播、语气与停顿。"
    )
    return content


async def _run_pipeline_message(runtime: VerbatimAgentRuntime, source: Artifact, message: AgentMessage) -> tuple[dict, AgentArtifactRevisionPayload]:
    emitter = runtime.emitter
    runtime.selected_section_ids = _section_scope(message, source)
    if emitter is not None:
        await emitter.agent_status_delta("orchestrator", "正在理解修改范围并创建执行计划。\n")
        await emitter.revision_started(1, runtime.pipeline_run.max_revision_rounds, reason=message.content[:200], target_agents=["orchestrator"])
        await emitter.emit_domain("repair.started", message="已开始创建逐字稿新修订版本", payload={
            "revision": source.version + 1, "selected_section_ids": runtime.selected_section_ids,
        })
    await runtime.run()
    await _pause_at_safe_boundary(runtime, "revision")
    source_content = source.content_json or {}
    if runtime.result_status in {"no_change", "rejected", "needs_confirmation"}:
        content = dict(source_content)
        if runtime.result_status == "rejected":
            assistant_reply = "本轮修订未通过逐字稿质询门禁，未创建新版本；原逐字稿保持不变。"
        elif runtime.result_status == "no_change":
            assistant_reply = "当前逐字稿已符合要求，本轮未创建空转版本；原逐字稿保持不变。"
        else:
            assistant_reply = runtime.dialogue_summary or "修改范围或目标存在歧义，请确认后重试；本轮未创建新版本。"
    else:
        content = dict(runtime.draft_content)
        assistant_reply = runtime.dialogue_summary or f"已根据你的要求创建教师逐字稿 V{source.version + 1}；原版本仍可在版本历史中恢复。"
    runtime.dialogue_summary = assistant_reply
    if emitter is not None:
        await emitter.revision_completed(1, applied_changes=[f"教师指令：{message.content[:60]}"])
        await emitter.emit_domain("repair.completed", message="逐字稿修订已完成", payload={"revision": source.version + 1})
        await emitter.emit_domain(
            "polish.result",
            message=assistant_reply,
            payload={
                "result_status": runtime.result_status,
                "active_intent": runtime.active_intent,
                "changed_sections": list(runtime.affected_section_ids),
            },
        )
        await emitter.agent_message_append(assistant_reply)
    return content, AgentArtifactRevisionPayload(content_json=content, assistant_reply=assistant_reply)


async def _run_pipeline_sync(runtime: VerbatimAgentRuntime, source: Artifact) -> dict:
    await _pause_at_safe_boundary(runtime, "context_sync")
    await runtime.run()
    await _pause_at_safe_boundary(runtime, "context_sync")
    if runtime.result_status == "no_change":
        content = dict(source.content_json or {})
        runtime.dialogue_summary = "已同步最新项目上下文，文件内容保持不变。"
    else:
        content = dict(runtime.draft_content)
        runtime.dialogue_summary = "已依据最新项目上下文更新逐字稿候选稿。"
    return content


async def complete_verbatim_pipeline_after_publish(runtime: VerbatimAgentRuntime | None, artifact_id: str) -> None:
    """Publish the sole success terminal event after the domain Artifact commit."""
    if runtime is None:
        return
    try:
        update = getattr(runtime, "course_title_update", None)
        if update is not None and update.changed and runtime.emitter is not None:
            await runtime.emitter.emit_domain(
                "course.metadata.updated",
                agent={"id": "course_metadata"},
                message=f"课程名称已更新为“{update.title}”",
                payload={
                    "field": "title",
                    "title": update.title,
                    "previous_title": update.previous_title,
                    "changed": True,
                },
            )
        await _finish_pipeline(runtime, "completed", artifact_id=artifact_id)
    except Exception:  # The already committed official Artifact remains authoritative.
        logger.exception(
            "verbatim pipeline terminal event failed after Artifact commit",
            extra={"generation_run_id": runtime.generation_run.id, "artifact_id": artifact_id},
        )


async def run_verbatim_pipeline(db, course, task, run: GenerationRun, blueprint) -> PipelineRunResult:
    """执行 verbatim 任务运行（动态工具化流水线），返回与下游 save 块兼容的结果。"""
    from app.services.course_task_service import _profile_provider
    from app.services.model_config_service import resolved_model_name

    source = await _latest_artifact(db, course.id, "verbatim")
    profile, provider, config = await _profile_provider(db, course, task)
    knowledge_context, source_versions = await build_project_knowledge_context(
        db, task, blueprint.content_json, blueprint.version, profile.context_json,
        config.context_window_tokens if config else None, run=run,
    provider=provider,
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
            keep_paused=runtime.result_status == "needs_confirmation",
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
