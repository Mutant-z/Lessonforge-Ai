"""PPT Agent 流水线服务：把 ppt 课程任务运行分派进多 Agent 流水线。

- initial / sync_dependencies → 完整流水线（叙事→模板→内容→视觉规划→布局→媒体→编辑→QA→修订闭环）
- message → 修订 Agent（复用 _generate_ppt_revision 的验证/修复机制）
- sync_context → 复用 _generate_context_sync（保留源文件、同步最新上下文）
"""
import asyncio
import json
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState
from app.agent.events import PipelineEventEmitter
from app.agent.pipeline import (
    PipelinePaused, PipelineRuntime, _persist_paused, build_plan, finalize_content,
    run_revision_loop,
)
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


_CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                   "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _page_number(value: str) -> int | None:
    """解析阿拉伯数字及常见中文页码（当前课件页数通常远小于一百）。"""
    value = value.strip()
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if "十" in value:
        tens, ones = value.split("十", 1)
        tens_value = _CHINESE_DIGITS.get(tens, 1) if tens else 1
        ones_value = _CHINESE_DIGITS.get(ones, 0) if ones else 0
        return tens_value * 10 + ones_value
    digits = [_CHINESE_DIGITS.get(char) for char in value]
    if digits and all(item is not None for item in digits):
        return int("".join(str(item) for item in digits))
    return None


def _resolve_message_slide_ids(content: str, source_slides: list[dict]) -> list[str]:
    """把教师自然语言中的页面范围转换为稳定 slide ID。"""
    selected: list[str] = []
    if content.startswith("[目标页面:"):
        scope = content.split("]", 1)[0].removeprefix("[目标页面:")
        selected = [item.strip() for item in scope.split(",") if item.strip()]
    if selected:
        return selected

    page_number = 1 if any(token in content for token in ("首页", "封面", "首张")) else None
    if page_number is None:
        match = re.search(r"第\s*([0-9零〇一二两三四五六七八九十]+)\s*(?:页(?:面)?|张)", content)
        if match:
            page_number = _page_number(match.group(1))
    if page_number and 1 <= page_number <= len(source_slides):
        return [str(source_slides[page_number - 1].get("id") or f"S{page_number:02d}")]
    return []


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
    runtime: PipelineRuntime | None = None


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
    if generation_run.trigger_type == "message" and source is not None:
        preferred_template = resolve_ppt_template((source.content_json or {}).get("theme") or preferred_template)["id"]
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
    if generation_run.trigger_type == "message" and source is not None:
        builder.from_ppt_content(source.content_json or {})
    artifacts = PipelineArtifactManager(pipeline_run, workspace)
    emitter = await PipelineEventEmitter.for_run(generation_run, pipeline_run)
    runtime = PipelineRuntime(
        course=course, task=task, blueprint=blueprint, generation_run=generation_run,
        pipeline_run=pipeline_run, profile=profile, provider=provider, config=config,
        knowledge_context=knowledge_context, source_versions=source_versions,
        locks=locks, source_artifact=source, user_message=user_message,
        preferred_template=preferred_template, trigger_type=generation_run.trigger_type,
        context=context, builder=builder, artifacts=artifacts, emitter=emitter,
        workspace_root=workspace, pause_event=PAUSE_EVENTS.setdefault(generation_run.id, asyncio.Event()),
    )
    await emitter.pipeline_started(generation_run.trigger_type or "")
    # Codex 式消息语义：执行状态只进入 trace，assistant 正文只承载最终答复。
    # 暂停/恢复仍按 run_id 复用同一条 streaming 消息。
    await emitter.agent_message_started("教学 Agent", mirror_status=False)
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


async def _finish_pipeline(
    runtime: PipelineRuntime, status: str, error: str | None = None, artifact_id: str | None = None,
):
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
            await runtime.emitter.pipeline_completed(artifact_id=artifact_id, llm_calls=runtime.token_usage.get("llm_calls", 0),
                                                     tokens=runtime.token_usage.get("tokens", 0))
            sub_agents = [
                {"agent": item.get("agent", ""), "summary": item.get("summary", ""),
                 "artifact_id": item.get("artifact_id"), "status": "completed"}
                for item in runtime.context.decisions
            ]
            await runtime.emitter.agent_message_completed(
                summary=runtime.dialogue_summary, sub_agents=sub_agents, artifact_id=artifact_id)
        elif error:
            await runtime.emitter.pipeline_failed(error=error)
            await runtime.emitter.agent_message_failed(message=error)
        else:
            # cancelled（无错误信息）也把对话消息置为 failed，避免前端永久 streaming
            await runtime.emitter.agent_message_failed(message="")


# ---------- 各触发路径 ----------

async def _write_final_pptx(runtime: PipelineRuntime, content: dict, *, version: int | None = None) -> str | None:
    """把 builder 动态渲染为最终 PPTX（导出优先使用）；仅完整流水线（builder 已构建）。"""
    if runtime.builder is None or not runtime.builder.slides:
        return None
    from sqlalchemy import func
    if version is None:
        async with SessionLocal() as db:
            version = (await db.scalar(select(func.max(Artifact.version)).where(
                Artifact.course_id == runtime.course.id, Artifact.artifact_type == "ppt",
            )) or 0) + 1
    out_dir = Path(get_settings().storage_root) / "generated" / runtime.course.id / "ppt"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{version}.pptx"
    PresentationBuilder(runtime.preferred_template).from_ppt_content(content).render(output)
    return str(output)


async def _pause_at_safe_boundary(runtime: PipelineRuntime, boundary: str) -> None:
    """在完成写文件等副作用前兑现 pausing 请求。"""
    if not runtime.pause_requested():
        return
    await _persist_paused(runtime, runtime.checkpoint_start, runtime.current_agent_key or boundary)
    raise PipelinePaused()


async def _run_pipeline_full(runtime: PipelineRuntime, blueprint) -> dict:
    await _pause_at_safe_boundary(runtime, "orchestrator")
    if get_settings().ppt_agent_runtime_enabled:
        from app.agent.runtime import PPTAgentRuntime
        await PPTAgentRuntime(runtime).run()
    else:
        plan = build_plan(runtime, runtime.trigger_type)
        await run_revision_loop(runtime, plan)
    await _pause_at_safe_boundary(runtime, "finalize")
    content = finalize_content(runtime)
    await _write_final_pptx(runtime, content)
    await _pause_at_safe_boundary(runtime, "finalize")
    slide_count = len(content.get("slides") or [])
    runtime.dialogue_summary = (
        f"PPT 已生成完成，共 {slide_count} 页。已完成内容规划、页面构建与质量检查，"
        "你可以在右侧逐页预览，或继续输入指令修改指定页面。"
    )
    return content


async def _run_pipeline_message_agentic(runtime: PipelineRuntime, message: AgentMessage, version: int) -> tuple[dict, AgentArtifactRevisionPayload]:
    from app.agent.runtime import PPTAgentRuntime
    from app.services.ppt_template_service import list_ppt_templates
    emitter = runtime.emitter
    for candidate in list_ppt_templates():
        if candidate["id"] in message.content:
            runtime.preferred_template = candidate["id"]
            runtime.builder.apply_template(candidate["id"])
            runtime.context.template = design_system_for(candidate)
            break
    source_slides = list((getattr(runtime.source_artifact, "content_json", {}) or {}).get("slides") or [])
    selected_slide_ids = _resolve_message_slide_ids(message.content, source_slides)
    await emitter.agent_status_delta("orchestrator", "正在理解修改范围并创建动态执行计划。\n")
    await emitter.revision_started(1, runtime.pipeline_run.max_revision_rounds, reason=message.content[:200], target_agents=["orchestrator"])
    await emitter.emit_domain("repair.started", message="已开始创建 PPT 新修订版本", payload={"revision": version, "selected_slide_ids": selected_slide_ids})
    await PPTAgentRuntime(runtime).run(selected_slide_ids=selected_slide_ids)
    await _pause_at_safe_boundary(runtime, "revision")
    content = finalize_content(runtime)
    await _write_final_pptx(runtime, content, version=version)
    assistant_reply = f"已根据你的要求创建 PPT V{version}；原版本和页面级修改记录可在版本历史中恢复。"
    runtime.dialogue_summary = assistant_reply
    revision_payload = AgentArtifactRevisionPayload(content_json=content, assistant_reply=assistant_reply)
    await emitter.revision_completed(1, applied_changes=[f"教师指令：{message.content[:60]}"])
    await emitter.emit_domain("repair.completed", message="PPT 修订已完成", payload={"revision": version})
    await runtime.emitter.agent_message_append(assistant_reply)
    return content, revision_payload


async def _run_pipeline_message(runtime: PipelineRuntime, source: Artifact, message: AgentMessage, version: int) -> tuple[dict, AgentArtifactRevisionPayload]:
    emitter = runtime.emitter
    if get_settings().ppt_agent_runtime_enabled:
        return await _run_pipeline_message_agentic(runtime, message, version)

    # Feature-flagged legacy rollback path.
    await emitter.agent_started("revision", "修订 Agent", 0)
    await emitter.agent_status_delta("revision", "已读取当前课件，正在定位需要修改的页面。\n")

    async def publish_revision_progress() -> None:
        """Keep the execution console alive while a structured revision is pending.

        The PPT schema response cannot be applied until it is complete and validated, but
        this is still an active, observable operation. These messages describe known
        execution phases rather than exposing model reasoning.
        """
        updates = (
            "正在分析教师指令与现有页面结构。\n",
            "正在生成修订草稿，并保留锁定内容。\n",
            "正在检查页面文字、版式和视觉约束。\n",
            "模型仍在生成结构化修订稿，请稍候。\n",
        )
        index = 0
        try:
            while True:
                await asyncio.sleep(1.2)
                await emitter.agent_status_delta("revision", updates[index % len(updates)])
                index += 1
        except asyncio.CancelledError:
            raise

    progress_task = asyncio.create_task(publish_revision_progress())
    if isinstance(runtime.provider, MockProvider):
        try:
            content = dict(source.content_json)
            assistant_reply = f"已根据你的要求创建PPT V{version}，原版本仍可在版本历史中恢复。"
        finally:
            progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await progress_task
    else:
        try:
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
        finally:
            progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await progress_task
    await _pause_at_safe_boundary(runtime, "revision")
    await emitter.agent_status_delta("revision", "修订草稿已生成，正在写入并校验最终版本。\n")
    await emitter.revision_started(1, runtime.pipeline_run.max_revision_rounds, reason=message.content[:200], target_agents=["slide_content", "ppt_editor"])
    await emitter.artifact_created("revision_note", runtime.pipeline_run.id + "-rev", f"message-{version}", version,
                                   producer_agent="revision")
    await emitter.revision_completed(1, applied_changes=[f"教师指令：{message.content[:60]}"])
    await emitter.agent_completed("revision", "修订完成", artifact_id="revision_note")
    revision_payload = AgentArtifactRevisionPayload(content_json=content, assistant_reply=assistant_reply)
    # 对话正文 = 最终回复（以非 reset delta 流式推送，不镜像推演过程）
    await runtime.emitter.agent_message_append(assistant_reply)
    return content, revision_payload


async def _run_pipeline_sync(db, runtime: PipelineRuntime, source: Artifact, blueprint, task) -> tuple[dict, object, object, dict, list]:
    from app.services.course_task_service import _generate_context_sync
    await _pause_at_safe_boundary(runtime, "context_sync")
    value, model_name, profile, source_versions, locks = await _generate_context_sync(
        db, runtime.course, task, source, blueprint,
    )
    await _pause_at_safe_boundary(runtime, "context_sync")
    content = value.model_dump()
    runtime.dialogue_summary = "已同步最新项目上下文，文件内容保持不变。"
    return content, model_name, profile, source_versions, locks


async def complete_ppt_pipeline_after_publish(runtime: PipelineRuntime | None, artifact_id: str) -> None:
    """Publish the sole success terminal event after the domain Artifact commit."""
    if runtime is None:
        return
    try:
        await _finish_pipeline(runtime, "completed", artifact_id=artifact_id)
    except Exception:  # The already committed official Artifact remains authoritative.
        logger.exception(
            "PPT pipeline terminal event failed after Artifact commit",
            extra={"generation_run_id": runtime.generation_run.id, "artifact_id": artifact_id},
        )


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
            runtime=runtime,
        )
    if run.trigger_type == "sync_context":
        if not source:
            raise RuntimeError("任务文件尚未生成，无法同步项目上下文")
        content, model_name, profile, source_versions, locks = await _run_pipeline_sync(db, runtime, source, blueprint, task)
        return PipelineRunResult(
            content=content, model_name=model_name, profile=profile, provider=provider,
            locks=locks, source_versions=source_versions, change_summary="上下文同步生成", runtime=runtime,
        )

    content = await _run_pipeline_full(runtime, blueprint)
    return PipelineRunResult(
        content=content, model_name=model_name, profile=profile, provider=provider,
        locks=locks, source_versions=source_versions,
        change_summary="上下文同步生成" if run.trigger_type in {"sync_dependencies", "sync_context"} else "首次生成",
        runtime=runtime,
    )
