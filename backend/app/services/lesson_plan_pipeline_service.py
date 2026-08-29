"""教学设计 Agent V2 流水线服务：把 lesson_plan 任务运行分派进动态工具化流水线。

- initial → 全链生成（上下文调研 → 目录 → 内容 → QA → 终稿）
- message → 意图识别 → 计划 → 工具修改内存候选稿 → QA → 返修 → 发布
- sync_context → 上下文同步（保留源内容，同步最新项目上下文）

result_status 语义与 PPT 对齐：applied / no_change / needs_confirmation / rejected。
- no_change / rejected → skip_publish（不创建正式新版本，原版本保持不变）
- applied → 创建 V2 Artifact 版本
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from app.agent.artifacts import PipelineArtifactManager
from app.agent.agents.lesson_plan.runtime import LessonPlanAgentRuntime
from app.agent.context import ContextState
from app.agent.core.error import AgentError
from app.agent.core.loop import PipelinePaused
from app.agent.events import PipelineEventEmitter
from app.agent.registry import ToolContext
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AgentMessage, Artifact, ArtifactLock, GenerationRun, PipelineRun
from app.schemas.artifact import AgentArtifactRevisionPayload
from app.schemas.lesson_plan import LessonPlanContentV2, lesson_plan_to_markdown_v2
from app.services.ppt_pipeline_service import (
    PAUSE_EVENTS, PipelineRunResult, _get_or_create_pipeline_run, _latest_artifact,
)
from app.services.project_knowledge_service import build_project_knowledge_context
from app.services.chat_attachment_service import attachment_prompt, prepare_chat_attachments

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_TYPE = "lesson_plan_agent_pipeline"


def _workspace_root(course_id: str, generation_run_id: str) -> Path:
    root = Path(get_settings().storage_root) / "generated" / course_id / "lesson_plan_pipeline" / generation_run_id
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("analysis", "content", "plans", "assets", "drafts", "qa", "output"):
        (root / sub).mkdir(exist_ok=True)
    return root


async def _build_runtime(db, course, task, generation_run, blueprint, source, profile, provider, config,
                         knowledge_context, source_versions, locks, user_message) -> LessonPlanAgentRuntime:
    attachments, runtime_provider = await prepare_chat_attachments(db, course, user_message, provider)
    pipeline_run = await _get_or_create_pipeline_run(db, generation_run, max_rounds=3)
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
        upstream=knowledge_context.get("upstream") or {},
    )
    artifacts = PipelineArtifactManager(pipeline_run, workspace)
    emitter = await PipelineEventEmitter.for_run(generation_run, pipeline_run, task_type="lesson_plan")
    runtime = LessonPlanAgentRuntime(
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
    tool_context = ToolContext(
        ctx=context, workspace_root=workspace, course=course, task=task,
        generation_run_id=generation_run.id, pipeline_run_id=pipeline_run.id,
        provider=runtime_provider, artifacts=artifacts, emitter=emitter, runtime=runtime,
    )
    runtime.tool_context = tool_context
    checkpoint = pipeline_run.checkpoint_json or {}
    if checkpoint.get("step_index"):
        runtime.context.restore(checkpoint)
        runtime.checkpoint_start = int(checkpoint.get("step_index", 0))
    return runtime


def _runtime_plan_json(runtime: LessonPlanAgentRuntime) -> dict:
    return {
        "result_status": getattr(runtime, "result_status", "applied"),
        "active_intent": getattr(runtime, "active_intent", "GENERATE"),
        "repair_round": getattr(runtime, "repair_round", 0),
        "intent_gate": getattr(runtime, "intent_gate", {}),
        "diff_summary": getattr(runtime, "diff_summary", {}),
        "failed_tool_count": sum(
            int(item.get("failed_tool_calls", 0) or 0)
            for item in getattr(runtime, "agent_stats", {}).values()
        ),
        "agent_stats": getattr(runtime, "agent_stats", {}),
        "termination_reason": getattr(runtime, "termination_reason", ""),
        "current_agent": getattr(runtime, "current_agent_key", ""),
    }


async def _persist_pipeline_state(
    runtime: LessonPlanAgentRuntime,
    status: str,
    error_payload: dict | None = None,
) -> None:
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, runtime.pipeline_run.id)
        if row:
            row.status = status
            row.token_usage_json = runtime.token_usage
            row.error_json = error_payload
            row.plan_json = {
                **(row.plan_json or {}),
                **_runtime_plan_json(runtime),
            }
            row.current_agent = getattr(runtime, "current_agent_key", "")
            if status in {"completed", "failed", "cancelled"}:
                from app.models.entities import now

                row.finished_at = now()
            await db.commit()


async def _finish_pipeline(runtime: LessonPlanAgentRuntime, status: str, error: str | None = None, artifact_id: str | None = None):
    await _persist_pipeline_state(
        runtime, status, {"message": error} if error else None,
    )
    if runtime.emitter is not None:
        if status == "completed":
            # result_status=rejected：修改未应用，不能发出成功型 pipeline_completed；
            # 由 runtime 已发的 result.rejected 事件承载真实结果。
            result_status = getattr(runtime, "result_status", "applied")
            if result_status == "rejected":
                await runtime.emitter.agent_message_completed(
                    summary=runtime.dialogue_summary,
                    sub_agents=[
                        {"agent": item.get("agent", ""), "summary": item.get("summary", ""),
                         "artifact_id": item.get("artifact_id"), "status": "rejected"}
                        for item in runtime.context.decisions
                    ],
                    artifact_id=None,
                )
            else:
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


async def _run_runtime_with_failure_persistence(runtime: LessonPlanAgentRuntime) -> None:
    try:
        await runtime.run()
    except Exception as exc:
        if isinstance(exc, AgentError):
            error = {
                "code": exc.code,
                "message": exc.user_message,
                "retryable": exc.retryable,
            }
            if exc.details:
                error["details"] = exc.details
        else:
            error = {
                "code": "task_generation_failed",
                "message": str(exc)[:500],
                "retryable": True,
            }
        await _persist_pipeline_state(runtime, "failed", error)
        raise


async def _pause_at_safe_boundary(runtime: LessonPlanAgentRuntime, boundary: str) -> None:
    from app.agent.core.loop import _persist_paused

    if not runtime.pause_requested():
        return
    await _persist_paused(runtime, runtime.checkpoint_start, runtime.current_agent_key or boundary)
    raise PipelinePaused()


def _section_scope(message: AgentMessage, source: Artifact | None) -> list[str]:
    """把教师指令中的章节范围转换为稳定章节 ID。

    章节 ID 只在请求入口做一次别名规范化（reflection → SEC-REFLECTION 等），
    未知 ID 直接抛出结构化错误，不让非法 ID 进入工具执行层。
    """
    from app.agent.agents.lesson_plan.section_refs import (
        build_section_index,
        canonicalize_section_ids,
    )

    metadata = dict(getattr(message, "metadata_json", None) or {})
    structured = list(metadata.get("selected_section_ids") or metadata.get("target_section_ids") or [])
    raw_ids: list[str] = [str(value) for value in structured if str(value)]
    if source is not None:
        active_section_id = str(metadata.get("active_section_id") or "")
        if active_section_id:
            raw_ids.append(active_section_id)
    if not raw_ids:
        return []
    index = build_section_index((source.content_json or {}) if source else {})
    canonical, invalid = canonicalize_section_ids(raw_ids, index)
    if invalid:
        raise AgentError(
            "invalid_section_id",
            f"指令引用了不存在的章节 ID：{', '.join(invalid)}；"
            "已停止执行，原教学设计未改变。",
            retryable=False,
            details={"invalid_section_ids": invalid},
        )
    return canonical


async def _run_pipeline_full(runtime: LessonPlanAgentRuntime) -> dict:
    await _pause_at_safe_boundary(runtime, "orchestrator")
    await _run_runtime_with_failure_persistence(runtime)
    await _pause_at_safe_boundary(runtime, "finalize")
    content = dict(runtime.draft_content)
    outline_count = len((content.get("outline") or {}).get("sections", []))
    runtime.dialogue_summary = (
        f"教学设计已生成完成，共 {outline_count} 个章节。已完成目标、环节、活动与评价的"
        "一致设计，你可以在右侧预览，或继续输入指令调整目录与内容。"
    )
    return content


async def _run_pipeline_message(runtime: LessonPlanAgentRuntime, source: Artifact, message: AgentMessage) -> tuple[dict, AgentArtifactRevisionPayload]:
    emitter = runtime.emitter
    runtime.selected_section_ids = _section_scope(message, source)
    if emitter is not None:
        await emitter.agent_status_delta("orchestrator", "正在理解修改范围并创建动态执行计划。\n")
        await emitter.revision_started(1, runtime.pipeline_run.max_revision_rounds, reason=message.content[:200], target_agents=["orchestrator"])
        await emitter.emit_domain("repair.started", message="已开始创建教学设计新修订版本", payload={
            "revision": source.version + 1, "selected_section_ids": runtime.selected_section_ids,
        })
    await _run_runtime_with_failure_persistence(runtime)
    await _pause_at_safe_boundary(runtime, "revision")
    source_content = source.content_json or {}
    if runtime.result_status in {"no_change", "rejected", "needs_confirmation"}:
        content = dict(source_content)
        if runtime.result_status == "rejected":
            gate_code = str((runtime.intent_gate or {}).get("code") or "")
            if gate_code == "fatal_tool_error":
                target = (runtime.intent_gate or {}).get("requested_target")
                error_code = str((runtime.intent_gate or {}).get("error_code") or "")
                suggestion = (runtime.intent_gate or {}).get("suggestion")
                assistant_reply = (
                    "本轮修改未执行："
                    + (f"目标章节已规范化为 {target}，但" if target else "")
                    + f"当前工具不允许该修改（{error_code}）。"
                    + (f"建议：{suggestion}。" if suggestion else "")
                    + "系统已停止重试，原教学设计未改变。"
                )
            elif gate_code == "intent_unfulfilled":
                assistant_reply = "本轮修改没有完整满足教师指令，未应用修改；原教学设计保持不变。"
            elif gate_code == "required_artifact_missing":
                assistant_reply = "本轮 Agent 执行产物不完整，未应用修改；原教学设计保持不变。"
            elif gate_code == "unresolved_tool_failure":
                assistant_reply = "本轮存在未解决的工具执行错误，未应用修改；原教学设计保持不变。"
            elif gate_code == "content_regression":
                assistant_reply = "检测到正文异常减少或出现空章节，本轮修改未应用；原教学设计保持不变。"
            elif gate_code == "no_change_but_request_unfulfilled":
                assistant_reply = (
                    "本轮未检测到可应用的修改：请确认你要修改的部分是否在当前教学设计中存在，"
                    "或重新描述更具体的内容（例如明确指出要改的章节）。原教学设计保持不变。"
                )
            else:
                assistant_reply = "本轮修订未通过教学质询门禁，未应用修改；原教学设计保持不变。"
        elif runtime.result_status == "no_change" and runtime.active_intent == "ANSWER_ONLY":
            answer = getattr(runtime, "draft_answer", None) or {}
            answer_text = str(answer.get("answer") or "") if isinstance(answer, dict) else str(answer or "")
            assistant_reply = (
                answer_text
                if answer_text
                else "已回答教师问题；本轮未修改教学设计，未创建新版本。"
            )
        elif runtime.result_status == "no_change":
            assistant_reply = "当前设计已符合要求，本轮未创建空转版本；原教学设计保持不变。"
        else:
            assistant_reply = "修改范围或目标存在歧义，请确认后重试；本轮未创建新版本。"
    else:
        content = dict(runtime.draft_content)
        assistant_reply = f"已根据你的要求创建教学设计 V{source.version + 1}；原版本仍可在版本历史中恢复。"
    runtime.dialogue_summary = assistant_reply
    if emitter is not None:
        applied = runtime.result_status == "applied"
        answered = runtime.active_intent == "ANSWER_ONLY"
        if applied:
            # 修改已应用：修订完成 + 最终结果。
            await emitter.revision_completed(
                1,
                applied_changes=[f"教师指令：{message.content[:60]}"],
            )
            await emitter.emit_domain(
                "repair.completed",
                message="教学设计修订已完成",
                payload={
                    "revision": source.version + 1,
                    "applied": True,
                    "result_status": runtime.result_status,
                },
            )
            await emitter.emit_domain(
                "polish.result",
                message=assistant_reply,
                payload={
                    "result_status": runtime.result_status,
                    "active_intent": runtime.active_intent,
                    "changed_sections": list(runtime.affected_section_ids),
                    "intent_gate": dict(runtime.intent_gate or {}),
                    "diff_summary": dict(runtime.diff_summary or {}),
                },
            )
        else:
            # 未应用 / 已回答 / 待确认：不再发送“修订完成”或成功型 polish.result，
            # 避免与 runtime 已发送的 result.rejected / result.no_change（⛔/➖）
            # 互相矛盾。只发送“未应用，原版本已保留”的终结事件。
            await emitter.emit_domain(
                "repair.completed",
                message=(
                    "已回答教师问题（未修改教学设计）"
                    if answered
                    else "教学设计修订未应用，原版本已保留"
                ),
                payload={
                    "revision": source.version,
                    "applied": False,
                    "result_status": runtime.result_status,
                },
            )
        await emitter.agent_message_append(assistant_reply)
    return content, AgentArtifactRevisionPayload(content_json=content, assistant_reply=assistant_reply)


async def _run_pipeline_sync(runtime: LessonPlanAgentRuntime, source: Artifact) -> dict:
    await _pause_at_safe_boundary(runtime, "context_sync")
    await _run_runtime_with_failure_persistence(runtime)
    await _pause_at_safe_boundary(runtime, "context_sync")
    if runtime.result_status in {"no_change", "rejected", "needs_confirmation"}:
        content = dict(source.content_json or {})
        runtime.dialogue_summary = "未应用上下文同步修改，原教学设计保持不变。"
    else:
        content = dict(runtime.draft_content)
        runtime.dialogue_summary = "已依据最新项目上下文更新教学设计候选稿。"
    return content


async def complete_lesson_plan_pipeline_after_publish(runtime: LessonPlanAgentRuntime | None, artifact_id: str) -> None:
    """Publish the sole success terminal event after the domain Artifact commit."""
    if runtime is None:
        return
    try:
        await _finish_pipeline(runtime, "completed", artifact_id=artifact_id)
    except Exception:  # The already committed official Artifact remains authoritative.
        logger.exception(
            "lesson_plan pipeline terminal event failed after Artifact commit",
            extra={"generation_run_id": runtime.generation_run.id, "artifact_id": artifact_id},
        )


async def run_lesson_plan_pipeline(db, course, task, run: GenerationRun, blueprint) -> PipelineRunResult:
    """执行 lesson_plan 任务运行（动态工具化流水线），返回与下游 save 块兼容的结果。"""
    from app.services.course_task_service import _profile_provider
    from app.services.model_config_service import resolved_model_name

    source = await _latest_artifact(db, course.id, "lesson_plan")
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
        )
    if run.trigger_type == "sync_context":
        if not source:
            raise RuntimeError("任务文件尚未生成，无法同步项目上下文")
        content = await _run_pipeline_sync(runtime, source)
        return PipelineRunResult(
            content=content, model_name=model_name, profile=profile, provider=provider,
            locks=locks, source_versions=source_versions, change_summary="上下文同步生成",
            runtime=runtime,
            skip_publish=runtime.result_status in {"no_change", "rejected", "needs_confirmation"},
        )

    content = await _run_pipeline_full(runtime)
    return PipelineRunResult(
        content=content, model_name=model_name, profile=profile, provider=provider,
        locks=locks, source_versions=source_versions,
        change_summary="上下文同步生成" if run.trigger_type in {"sync_dependencies", "sync_context"} else "首次生成",
        runtime=runtime,
    )
