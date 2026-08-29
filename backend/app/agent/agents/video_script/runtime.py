"""视频脚本 Agent Runtime：意图 → 计划 → 工具编辑 → 发布前校验 → 发布。

基于通用 Agent Core（app/agent/core）构建，复用全局工具注册表、事件发射器、
artifact 管理器与 checkpoint/暂停基础设施。与 lesson_plan / task_sheet 运行时同构：
- initial → 全链生成（上下文调研 → 章节 → 分镜 → QA → 终稿，目录由 AI 动态规划）
- message → 意图识别 → 计划 → 工具修改内存候选稿 → QA → 返修 → 发布
- sync_context → 上下文同步（保留源内容，同步最新项目上下文）

result_status 语义与 PPT/lesson_plan/task_sheet 对齐：applied / no_change / rejected。
- no_change / rejected → skip_publish（不创建正式新版本）
- applied → 创建 V4 Artifact 版本
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agent.agents.video_script.agents import (
    AGENT_BY_KEY,
    ensure_video_script_agents, is_mock_provider, video_script_spec,
)
from app.agent.agents.video_script.builder import (
    VideoScriptBuilder, build_empty_builder, build_initial_builder, upgrade_builder,
)
from app.agent.agents.video_script.intents import (
    INTENT_AGENT_ALIASES, VideoScriptIntentDecision, agent_chain_for_intent,
    infer_video_script_intent,
)
from app.agent.agents.video_script.qa import blocking_issues as _blocking
from app.agent.agents.video_script.qa import fingerprint as _fingerprint
from app.agent.agents.video_script.qa import validate_video_script_v4
from app.agent.core.error import AgentError
from app.agent.core.gates import gates_active
from app.agent.core.loop import PipelinePaused, run_agent_loop
from app.agent.core.state import AgentRuntimeState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan, ToolCall, ToolResult
from app.core.database import SessionLocal
from app.models.entities import AgentHumanRequest, AgentRunInstruction, PipelineRun
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.video_script_v4 import VIDEO_SCRIPT_V4, SeedanceVideoScriptContentV4
from app.services.video_generation_settings_service import (
    VideoGenerationSettingsPatch,
    VideoGenerationSettingsUpdate,
    normalize_native_video_resolution,
    preferred_video_resolution,
)
from app.services.chat_attachment_service import apply_runtime_attachments

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 1  # 仅允许一次面向阻断约束的定向修复

CONFIRM_OPTIONS = [
    {"id": "apply", "label": "按当前范围执行", "action": "apply"},
    {"id": "scope_down", "label": "缩小修改范围", "action": "scope_down"},
    {"id": "cancel", "label": "取消本轮", "action": "cancel"},
]


@dataclass
class VideoScriptAgentRuntime(AgentRuntimeState):
    """视频脚本流水线运行态（继承通用运行态）。"""

    course: Any = None
    task: Any = None
    blueprint: Any = None
    generation_run: Any = None
    pipeline_run: Any = None
    profile: Any = None
    provider: Any = None
    config: Any = None
    knowledge_context: dict[str, Any] = field(default_factory=dict)
    source_versions: dict[str, Any] = field(default_factory=dict)
    locks: list[Any] = field(default_factory=list)
    source_artifact: Any = None
    user_message: Any = None
    trigger_type: str = "initial"
    workspace_root: Any = None

    builder: VideoScriptBuilder | None = None
    selected_section_ids: list[str] = field(default_factory=list)
    selected_scene_ids: list[str] = field(default_factory=list)
    affected_section_ids: list[str] = field(default_factory=list)
    affected_scene_ids: list[str] = field(default_factory=list)
    active_intent: str = "GENERATE"
    intent_plan: VideoScriptIntentDecision | None = None
    content_policy: str = "preserve"
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    repair_fingerprint: str = ""
    repair_round: int = 0
    max_revision_rounds: int = MAX_REVISION_ROUNDS
    publishable: bool = False
    draft_content: dict[str, Any] = field(default_factory=dict)
    draft_markdown: str = ""
    request_metadata: dict[str, Any] = field(default_factory=dict)
    handoff_aliases: dict[str, str] = field(default_factory=lambda: INTENT_AGENT_ALIASES)
    changed: bool = False
    baseline_content: dict[str, Any] = field(default_factory=dict)
    draft_revision: int = 0
    confirmation_tokens: list[str] = field(default_factory=list)
    confirmation_request: AgentHumanRequest | None = None
    resumed_confirmation: dict[str, Any] = field(default_factory=dict)
    #: 视频脚本多节点会多次调用模型；关闭应用层 60k 累计/上下文估算硬限额。
    #: 模型真实上下文窗口、步骤上限、超时和暂停/取消保护仍由原链路负责。
    max_estimated_tokens: int = 0
    max_context_tokens: int = 0
    #: 复合指令的分辨率更新延迟到脚本成功发布/安全 no-change 时提交。
    pending_video_settings: VideoGenerationSettingsPatch | None = None
    #: 由任务事务写入并在 commit 后用于构造权威事件与最终回复。
    video_resolution_update: VideoGenerationSettingsUpdate | None = None
    settings_tool_result: dict[str, Any] | None = None

    @property
    def pending_video_resolution(self) -> str | None:
        """兼容流水线旧调用；实际待提交副作用使用强类型 settings patch。"""
        return self.pending_video_settings.preferred_resolution if self.pending_video_settings else None

    @pending_video_resolution.setter
    def pending_video_resolution(self, value: str | None) -> None:
        self.pending_video_settings = (
            VideoGenerationSettingsPatch(
                preferred_resolution=normalize_native_video_resolution(value)
            )
            if value
            else None
        )

    # ------------------------------------------------------------------
    # 准备
    # ------------------------------------------------------------------

    def _lesson_plan_raw(self) -> dict[str, Any] | None:
        raw = (self.knowledge_context or {}).get("sibling_artifacts", {}).get("lesson_plan")
        if raw is None:
            raw = (self.knowledge_context or {}).get("hard_dependencies", {}).get("lesson_plan")
        if isinstance(raw, dict):
            raw = raw.get("content") or raw
        return raw if isinstance(raw, dict) else None

    def _prepare_builder(self) -> VideoScriptBuilder:
        bp_content = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        lesson_plan_raw = self._lesson_plan_raw()
        if self.source_artifact is not None:
            source_content = self.source_artifact.content_json or {}
            if source_content.get("schema_version") in {"3.0", "4.0"}:
                builder = upgrade_builder(source_content, bp_content, lesson_plan_raw)
            else:
                # V1/V2 历史脚本：保持只读，首次编辑/同步时确定性重建 V4 候选
                # （与 legacy 路径 V2→V3 行为一致，不读取 PPT）。
                builder = build_initial_builder(bp_content, lesson_plan_raw)
        else:
            # Mock 保持可重复的合法夹具；真实模型从事实骨架开始，章节与分镜由 LLM 工具生成。
            builder = (
                build_initial_builder(bp_content, lesson_plan_raw)
                if is_mock_provider(self.provider)
                else build_empty_builder(bp_content)
            )
        self.builder = builder
        builder.configure_renderer_limit(
            float((self.request_metadata or {}).get("renderer_max_scene_seconds") or 15)
        )
        return builder

    async def _prepare(self) -> None:
        ensure_video_script_agents()
        builder = self._prepare_builder()
        if self.tool_context is None:
            self.tool_context = ToolContext(
                ctx=self.context, workspace_root=self.workspace_root,
                course=self.course, task=self.task,
                generation_run_id=self.generation_run.id if self.generation_run else "",
                pipeline_run_id=self.pipeline_run.id if self.pipeline_run else "",
                provider=self.provider, artifacts=self.artifacts, emitter=self.emitter,
                runtime=self, extra={"builder": builder},
            )
        elif self.tool_context.extra.get("builder") is None:
            self.tool_context.extra["builder"] = builder
            self.tool_context.runtime = self
            self.tool_context.emitter = self.emitter
            self.tool_context.artifacts = self.artifacts
        self.baseline_content = builder.to_content()
        checkpoint = dict(getattr(self.pipeline_run, "checkpoint_json", None) or {})
        pending = checkpoint.get("pending_confirmation") or {}
        if pending.get("token"):
            self.confirmation_tokens = [str(pending["token"])]
            self.resumed_confirmation = dict(pending)
        pending_settings = checkpoint.get("pending_video_settings") or {}
        if isinstance(pending_settings, dict) and pending_settings.get("preferred_resolution"):
            self.pending_video_settings = VideoGenerationSettingsPatch(
                preferred_resolution=normalize_native_video_resolution(pending_settings["preferred_resolution"])
            )
        snapshot = checkpoint.get("draft_snapshot")
        if isinstance(snapshot, dict) and checkpoint.get("draft_revision") is not None:
            builder.restore(snapshot, int(checkpoint.get("draft_revision") or 0))
            self.draft_revision = builder.revision

    async def _emit_initial_snapshot(self) -> None:
        if self.builder is None:
            return
        content = self.builder.to_content()
        self.draft_revision = self.builder.revision
        async with SessionLocal() as db:
            row = await db.get(PipelineRun, self.pipeline_run.id)
            if row:
                row.checkpoint_json = {
                    **(row.checkpoint_json or {}),
                    "draft_snapshot": content,
                    "draft_revision": self.draft_revision,
                    "base_artifact_id": getattr(self.source_artifact, "id", None),
                    "base_version": getattr(self.source_artifact, "version", 0) or 0,
                }
                await db.commit()
        if self.emitter is not None:
            await self.emitter.artifact_started(
                "video_script", f"draft:{self.generation_run.id}", producer_agent="orchestrator",
            )
            await self.emitter.artifact_patch(
                f"draft:{self.generation_run.id}", "video_script",
                [{"op": "replace", "path": "", "value": content}],
                summary="已载入视频脚本候选稿",
                operation_id=f"snapshot-{self.draft_revision}", base_revision=self.draft_revision,
                draft_revision=self.draft_revision,
                affected_section_ids=[], affected_scene_ids=[], snapshot=True,
            )

    async def record_tool_mutation(self, agent_key: str, call: ToolCall, result: ToolResult) -> None:
        """把脚本编辑和课程设置工具结果分别记录到运行态。"""
        if call.tool_name == "vs_set_video_generation_resolution":
            self.settings_tool_result = {
                **dict(result.output or {}),
                "message": result.error or "视频生成分辨率设置已暂存。",
                "error_code": result.error_code,
                "ok": result.ok,
            }
            if result.ok:
                async with SessionLocal() as db:
                    row = await db.get(PipelineRun, self.pipeline_run.id)
                    if row:
                        row.checkpoint_json = {
                            **(row.checkpoint_json or {}),
                            "pending_video_settings": dict(result.output or {}),
                        }
                        await db.commit()
            return
        output = dict(result.output or {})
        patches = list(output.get("patch") or [])
        if not patches or self.builder is None:
            return
        revision = int(output.get("revision") or self.builder.revision)
        base_revision = self.draft_revision
        if revision <= base_revision:
            return
        self.draft_revision = revision
        affected_sections = [str(item) for item in output.get("affected_section_ids") or []]
        affected_scenes = [str(item) for item in output.get("affected_scene_ids") or []]
        self.affected_section_ids = sorted(set([*self.affected_section_ids, *affected_sections]))
        self.affected_scene_ids = sorted(set([*self.affected_scene_ids, *affected_scenes]))
        snapshot = self.builder.to_content()
        if call.tool_name in {"vs_apply_outline_ops", "vs_apply_scene_ops"}:
            patches.append({"op": "replace", "path": "", "value": snapshot})
        async with SessionLocal() as db:
            row = await db.get(PipelineRun, self.pipeline_run.id)
            if row:
                row.checkpoint_json = {
                    **(row.checkpoint_json or {}),
                    "draft_snapshot": snapshot,
                    "draft_revision": revision,
                }
                await db.commit()
        if self.emitter is not None:
            await self.emitter.artifact_patch(
                f"draft:{self.generation_run.id}", "video_script", patches,
                summary=str(output.get("summary") or call.tool_name),
                operation_id=call.id, base_revision=base_revision, draft_revision=revision,
                affected_section_ids=affected_sections, affected_scene_ids=affected_scenes,
                producer_agent=agent_key,
            )

    # ------------------------------------------------------------------
    # 意图与计划
    # ------------------------------------------------------------------

    async def _resolve_intent(self) -> VideoScriptIntentDecision:
        instruction = self.context.user_instruction or ""
        mode = (self.request_metadata or {}).get("mode")
        available_scenes = self.builder.all_scene_ids() if self.builder else []
        if self.builder and self.selected_section_ids:
            section_scope = set(self.selected_section_ids)
            available_scenes = [scene.id for scene in self.builder.scenes if scene.section_id in section_scope]
        decision = await infer_video_script_intent(
            self.provider, self.trigger_type, instruction,
            self.selected_section_ids or None, self.selected_scene_ids or None, mode,
            available_section_ids=self.builder.all_section_ids() if self.builder else None,
            available_scene_ids=available_scenes,
        )
        self.intent_plan = decision
        self.active_intent = decision.intent
        self.selected_section_ids = list(decision.target_section_ids or self.selected_section_ids)
        self.selected_scene_ids = list(decision.target_scene_ids or self.selected_scene_ids)
        self.content_policy = "edit" if decision.mutates_document else "preserve"
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "intent.recognized",
                agent={"id": "intent_planner"},
                message=decision.visible_summary or f"意图：{decision.intent}",
                payload={
                    "intent": decision.intent,
                    "mutates_document": decision.mutates_document,
                    "structural": decision.structural,
                    "destructive": decision.destructive,
                    "confidence": decision.confidence,
                    "requires_confirmation": decision.requires_confirmation,
                    "operation": decision.operation,
                    "target_section_ids": decision.target_section_ids,
                    "target_scene_ids": decision.target_scene_ids,
                    "affected_json_paths": decision.affected_json_paths,
                    "preserve_constraints": decision.preserve_constraints,
                    "assumptions": decision.assumptions,
                    "plan_steps": decision.plan_steps,
                    "acceptance_criteria": decision.acceptance_criteria,
                    "visible_summary": decision.visible_summary,
                    "clarification_question": decision.clarification_question,
                    "resolution_requested": decision.resolution_requested,
                    "resolution_preference": decision.resolution_preference,
                    "resolution_setting_only": decision.resolution_setting_only,
                    "resolution_error": decision.resolution_error,
                },
            )
            if decision.plan_steps:
                await self.emitter.emit_domain(
                    "plan.created",
                    agent={"id": "intent_planner"},
                    message="已创建执行计划",
                    payload={"intent": decision.intent, "steps": decision.plan_steps},
                )
            if decision.clarification_question:
                await self.emitter.emit_domain(
                    "agent.clarification.required",
                    agent={"id": "intent_planner"},
                    message=decision.clarification_question,
                    payload={"question": decision.clarification_question},
                )
        return decision

    def _build_plan(self, chain: list[str], revision_rounds: int = MAX_REVISION_ROUNDS) -> PipelinePlan:
        return PipelinePlan(
            agents=[AgentSpec(**video_script_spec(key)) for key in chain],
            revision_rounds=revision_rounds,
        )

    async def _drain_instructions(self) -> list[str]:
        """在安全边界合并运行中指令，并基于当前候选稿重新识别范围。"""
        if self.pipeline_run is None:
            return []
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(AgentRunInstruction).where(
                AgentRunInstruction.pipeline_run_id == self.pipeline_run.id,
                AgentRunInstruction.status == "queued",
            ).order_by(AgentRunInstruction.created_at)))
            if not rows:
                return []
            texts: list[str] = []
            setting_rows: list[AgentRunInstruction] = []
            attachment_metadata: list[dict[str, Any]] = []
            selected_sections: list[str] = []
            selected_scenes: list[str] = []
            latest_mode = (self.request_metadata or {}).get("mode") or "auto"
            for row in rows:
                metadata = dict(row.metadata_json or {})
                attachment_metadata.extend(metadata.get("attachments") or [])
                setting_hint = str(metadata.get("mode") or "") in {"resolution", "video_generation_settings"}
                if setting_hint or "分辨率" in (row.content or ""):
                    row.status = "settings_queued"
                    setting_rows.append(row)
                    continue
                row.status = "script_merged"
                row.applied_at = datetime.now(timezone.utc)
                texts.append(row.content or "")
                selected_sections.extend(str(item) for item in metadata.get("selected_section_ids") or [])
                selected_scenes.extend(str(item) for item in metadata.get("selected_scene_ids") or [])
                latest_mode = str(metadata.get("mode") or latest_mode)
            await db.commit()
            if attachment_metadata:
                await apply_runtime_attachments(
                    db, self.course, self, {"attachments": attachment_metadata},
                )
        # 设置类追加指令不进入脚本上下文；在同一安全边界通过独立设置 Agent 处理。
        for setting_row in setting_rows:
            decision = await infer_video_script_intent(
                self.provider, "message", setting_row.content or "",
                mode=str((setting_row.metadata_json or {}).get("mode") or "auto"),
                available_section_ids=self.builder.all_section_ids() if self.builder else None,
                available_scene_ids=self.builder.all_scene_ids() if self.builder else None,
            )
            self.intent_plan = decision
            self.settings_tool_result = None
            self.pending_video_settings = None
            await run_agent_loop(
                self, self._build_plan(["project_settings"]),
                agent_registry=AGENT_BY_KEY, call_agent=_call_agent,
                persist_artifact=_persist_artifact, retry_classifier=_retry_classifier,
            )
            setting_status = "settings_applied" if self.pending_video_settings else "settings_rejected"
            async with SessionLocal() as db:
                queued = await db.get(AgentRunInstruction, setting_row.id)
                if queued:
                    queued.status = setting_status
                    queued.applied_at = datetime.now(timezone.utc)
                    await db.commit()
        if setting_rows and self.emitter is not None:
            await self.emitter.emit_domain(
                "run.instruction.queued",
                agent={"id": "project_settings"},
                message=f"已隔离 {len(setting_rows)} 条视频生成设置指令，等待设置 Agent 处理",
                payload={"instruction_count": len(setting_rows), "settings_only": True},
            )
        if not texts:
            return []
        self.context.user_instruction = "\n".join([self.context.user_instruction, *texts]).strip()
        self.selected_section_ids = list(dict.fromkeys(selected_sections or self.selected_section_ids))
        self.selected_scene_ids = list(dict.fromkeys(selected_scenes or self.selected_scene_ids))
        self.request_metadata["mode"] = latest_mode
        decision = await infer_video_script_intent(
            self.provider, "message", self.context.user_instruction,
            self.selected_section_ids or None, self.selected_scene_ids or None, latest_mode,
            available_section_ids=self.builder.all_section_ids() if self.builder else None,
            available_scene_ids=self.builder.all_scene_ids() if self.builder else None,
        )
        self.intent_plan = decision
        self.active_intent = decision.intent
        self.selected_section_ids = list(decision.target_section_ids)
        self.selected_scene_ids = list(decision.target_scene_ids)
        # 新合并指令必须重新经过确认门，不能复用此前意图的一次性令牌。
        self.confirmation_tokens = []
        self.resumed_confirmation = {}
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "run.instruction.merged", agent={"id": "intent_planner"},
                message=f"已合并 {len(texts)} 条新要求",
                payload={"instruction_count": len(texts), "content": texts},
            )
            await self.emitter.emit_domain(
                "plan.revised", agent={"id": "intent_planner"},
                message=decision.visible_summary or f"已重新规划：{decision.intent}",
                payload={
                    "intent": decision.intent, "operation": decision.operation,
                    "target_section_ids": decision.target_section_ids,
                    "target_scene_ids": decision.target_scene_ids,
                    "requires_confirmation": decision.requires_confirmation,
                    "resolution_requested": decision.resolution_requested,
                    "resolution_preference": decision.resolution_preference,
                    "resolution_error": decision.resolution_error,
                },
            )
        return texts

    async def _request_confirmation(self, decision: VideoScriptIntentDecision) -> None:
        async with SessionLocal() as db:
            existing = await db.scalar(select(AgentHumanRequest).where(
                AgentHumanRequest.pipeline_run_id == self.pipeline_run.id,
                AgentHumanRequest.request_type == "video_script_confirmation",
                AgentHumanRequest.status == "pending",
            ).order_by(AgentHumanRequest.created_at.desc()))
            if existing is not None:
                self.confirmation_request = existing
                self.result_status = "needs_confirmation"
                self.dialogue_summary = existing.prompt
                return
        prompt = decision.clarification_question or "请确认本次视频脚本修改范围。"
        request = AgentHumanRequest(
            pipeline_run_id=self.pipeline_run.id, request_type="video_script_confirmation",
            prompt=prompt, options_json=CONFIRM_OPTIONS, status="pending",
        )
        async with SessionLocal() as db:
            db.add(request)
            await db.flush()
            row = await db.get(PipelineRun, self.pipeline_run.id)
            if row:
                row.status = "paused"
                row.checkpoint_json = {
                    **(row.checkpoint_json or {}),
                    "pending_confirmation": {
                        "request_id": request.id, "request_type": "video_script_confirmation",
                        "intent": decision.intent, "requires_confirmation": True,
                    },
                }
                row.plan_json = {**(row.plan_json or {}), "result_status": "needs_confirmation"}
            await db.commit()
        self.confirmation_request = request
        self.result_status = "needs_confirmation"
        self.dialogue_summary = prompt
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "human.required", agent={"id": "intent_planner"}, message=prompt,
                payload={
                    "request_id": request.id, "intent": decision.intent,
                    "destructive": decision.destructive, "confidence": decision.confidence,
                    "options": CONFIRM_OPTIONS,
                },
            )

    async def _clear_confirmation_checkpoint(self) -> None:
        if not self.resumed_confirmation:
            return
        async with SessionLocal() as db:
            row = await db.get(PipelineRun, self.pipeline_run.id)
            if row:
                checkpoint = dict(row.checkpoint_json or {})
                checkpoint.pop("pending_confirmation", None)
                row.checkpoint_json = checkpoint
                row.status = "running"
                await db.commit()

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await self._prepare()
        if self.emitter is not None:
            await self.emitter.pipeline_started(self.trigger_type)
        await self._emit_initial_snapshot()
        await self._clear_confirmation_checkpoint()
        intent_decision = await self._resolve_intent()
        # 破坏性/低置信度修改必须在任何设置落库或编辑工具调用之前暂停确认。
        # relaxed 门禁模式：直接按当前意图执行，不再等待确认。
        if gates_active() and intent_decision.requires_confirmation and not self.confirmation_tokens:
            await self._request_confirmation(intent_decision)
            return
        # 下游视频生成设置走独立控制 Agent + typed tool，不运行脚本 Builder。
        # 能力拒绝也必须经过设置工具，不能被当作脚本修改错误。
        if intent_decision.intent == "VIDEO_GENERATION_SETTINGS_UPDATE" or intent_decision.resolution_setting_only or intent_decision.resolution_error:
            if intent_decision.settings_operation == "query_video_resolution":
                self.result_status = "settings_unchanged"
                self.dialogue_summary = "当前视频生成分辨率由模型能力决定；请在报价前选择可用的 720p 或 480p。"
                return
            await run_agent_loop(
                self,
                self._build_plan(["project_settings"]),
                agent_registry=AGENT_BY_KEY,
                call_agent=_call_agent,
                persist_artifact=_persist_artifact,
                retry_classifier=_retry_classifier,
            )
            if self.settings_tool_result and (
                self.settings_tool_result.get("error_code") == "video_resolution_unsupported"
                or self.settings_tool_result.get("ok") is False
            ):
                self.result_status = "settings_rejected"
                result = self.settings_tool_result
                supported = "、".join(str(item) for item in result.get("supported") or [])
                self.dialogue_summary = (
                    str(result.get("message") or "当前视频生成设置未应用。")
                    + (f" 可用分辨率：{supported}。" if supported else "")
                )
            elif self.pending_video_settings is not None:
                self.result_status = "settings_applied" if self.pending_video_settings else "settings_unchanged"
                self.dialogue_summary = (
                    f"视频生成分辨率 {self.pending_video_settings.preferred_resolution} 已暂存，等待事务确认。"
                )
            else:
                self.result_status = "settings_rejected"
                self.dialogue_summary = "未能生成有效的视频生成设置修改。"
            return
        if intent_decision.resolution_preference:
            self.pending_video_resolution = intent_decision.resolution_preference
        if self.emitter is not None:
            await self.emitter.agent_message_append(
                (intent_decision.visible_summary or f"已识别为 {intent_decision.intent}") + "\n"
            )
        if intent_decision.intent in {"ANSWER_ONLY", "QA_ONLY"}:
            chain = agent_chain_for_intent(intent_decision.intent, self.trigger_type)
            await run_agent_loop(
                self, self._build_plan(chain),
                agent_registry=AGENT_BY_KEY,
                call_agent=_call_agent,
                persist_artifact=_persist_artifact,
                retry_classifier=_retry_classifier,
            )
            self.result_status = "no_change"
            self.dialogue_summary = await self._answer_only_reply(intent_decision.intent)
            return
        chain = agent_chain_for_intent(intent_decision.intent, self.trigger_type)
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "intent.resolved",
                agent={"id": "intent_planner"},
                message=f"意图：{self.active_intent}",
                payload={"intent": self.active_intent, "chain": chain,
                         "affected_section_ids": self.selected_section_ids,
                         "affected_scene_ids": self.selected_scene_ids},
            )
        self.blocking_issues = []
        await self._run_once(chain)
        late_instructions = await self._drain_instructions()
        if late_instructions:
            if gates_active() and self.intent_plan and self.intent_plan.requires_confirmation and not self.confirmation_tokens:
                await self._request_confirmation(self.intent_plan)
                raise PipelinePaused()
            if self.intent_plan and self.intent_plan.resolution_error:
                self.result_status = "no_change"
                self.pending_video_resolution = None
                self.dialogue_summary = self.intent_plan.resolution_error
                return
            self.pending_video_resolution = (
                self.intent_plan.resolution_preference if self.intent_plan else None
            )
            updated_chain = agent_chain_for_intent(self.active_intent, self.trigger_type)
            await self._run_once(updated_chain)
        await self._finalize()
        if self.result_status in {"applied", "no_change"} and self.pending_video_resolution:
            self.dialogue_summary = (
                f"{self.dialogue_summary or ''}\n"
                f"视频生成分辨率已更新为 {self.pending_video_resolution}；"
                "该设置将在后续视频报价与生成中使用。"
            ).strip()
        elif self.result_status == "rejected":
            self.pending_video_resolution = None

    async def _answer_only_reply(self, intent: str) -> str:
        if self.intent_plan and self.intent_plan.resolution_error:
            return self.intent_plan.resolution_error + " 本轮未修改视频脚本或视频生成设置。"
        if self.intent_plan and self.intent_plan.rationale == "video-generation-setting-question":
            current = preferred_video_resolution(self.course) if self.course else None
            return (
                f"当前视频生成分辨率为 {current or '1280x720（默认）'}。系统支持 1280x720（720p）和 "
                "854x480（480p）；本轮未修改设置或视频脚本。"
            )
        if self.intent_plan and self.intent_plan.rationale == "video-generation-setting":
            if self.intent_plan.resolution_preference:
                return (
                    f"已记录视频生成分辨率偏好：{self.intent_plan.resolution_preference}。"
                    "视频脚本内容保持不变；前往视频生成环节报价时将以该分辨率生成。"
                )
            return "分辨率属于视频生成环节，当前视频脚本内容未修改。请在视频生成设置中选择系统支持的分辨率。"
        if self.artifacts is not None:
            artifact = await self.artifacts.latest("video_script_answer")
            answer = str(((artifact or {}).get("data") or {}).get("answer") or "").strip()
            if answer:
                return answer
        builder = self.builder
        if builder is None:
            return "视频脚本尚未生成。"
        content = builder.to_content()
        sections = content.get("outline", {}).get("sections", [])
        scenes = content.get("scenes", [])
        minutes = round(float(content.get("course_info", {}).get("duration_seconds", 0)) / 60, 1)
        base = (
            f"当前视频脚本共 {len(sections)} 个动态章节、{len(scenes)} 个分镜，"
            f"总时长约 {minutes} 分钟。"
        )
        if intent == "QA_ONLY":
            return base + "内容质量自动检验已关闭；本轮未执行术语、数字、语速或表达门禁。"
        return base

    async def _run_once(self, chain: list[str]) -> None:
        """顺序执行一次主计划。不再运行发布前阻断检测与定向返修轮：
        结构合法性由发布时的 V4 Schema 强校验兜底，内容质量由 Agent 依据
        用户意图直接产出。仅 QA_ONLY 意图单独执行检查。"""
        plan = self._build_plan(chain)
        await run_agent_loop(
            self, plan, agent_registry=AGENT_BY_KEY, call_agent=_call_agent,
            persist_artifact=_persist_artifact, retry_classifier=_retry_classifier,
        )

    async def _collect_validation_issues(self) -> None:
        """合并 LLM 语义问题与确定性硬门禁；任何路径都不计算质量分。"""
        semantic_issues: list[dict[str, Any]] = []
        validation = await self.artifacts.latest("video_script_validation") if self.artifacts is not None else None
        if validation:
            data = validation.get("data") or {}
            semantic_issues = list(data.get("issues") or [])
            self.repair_fingerprint = self.repair_fingerprint or str(data.get("fingerprint") or "")
        bp = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        locked_paths = [getattr(lock, "json_path", "") for lock in self.locks]
        try:
            hard_issues = validate_video_script_v4(
                CourseBlueprintSchema.model_validate(bp),
                self.builder.to_content() if self.builder else {},
                self._lesson_plan_raw(), locked_paths,
                max_scene_seconds=float((self.request_metadata or {}).get("renderer_max_scene_seconds") or 15),
            )
        except Exception:  # noqa: BLE001
            hard_issues = [{
                "severity": "critical", "dimension": "structure", "location": "$",
                "description": "候选稿无法完成发布前结构校验", "suggestion": "检查脚本结构后重试",
            }]
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for issue in [*hard_issues, *semantic_issues]:
            key = (
                str(issue.get("dimension") or "semantic"),
                str(issue.get("location") or "$"),
                str(issue.get("description") or issue.get("message") or ""),
            )
            if key not in seen:
                seen.add(key)
                merged.append(issue)
        self.blocking_issues = _blocking(merged)
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "validation.completed", agent={"id": "validation"},
                message=("发布前约束已检查" if not self.blocking_issues else f"仍有 {len(self.blocking_issues)} 个阻断问题"),
                payload={"passed": not self.blocking_issues, "blocking_count": len(self.blocking_issues)},
            )

    # ------------------------------------------------------------------
    # 发布门禁
    # ------------------------------------------------------------------

    def _scope_violations(self, candidate: dict[str, Any]) -> list[str]:
        """确保 LLM 修改没有越过教师显式选择的章节/分镜范围。

        只做范围守护：用户显式选中的章节/分镜之外的改动视为越界。
        不再做字段级白名单约束——具体修改内容交给意图识别与 QA 门禁判断，
        避免"修改被内部约束拒绝、结果不落库"。
        """
        if self.trigger_type != "message" or not self.intent_plan:
            return []
        baseline = self.baseline_content or {}
        base_sections = {str(item.get("id")): item for item in (baseline.get("outline") or {}).get("sections", [])}
        next_sections = {str(item.get("id")): item for item in (candidate.get("outline") or {}).get("sections", [])}
        base_scenes = {str(item.get("id")): item for item in baseline.get("scenes", [])}
        next_scenes = {str(item.get("id")): item for item in candidate.get("scenes", [])}
        changed_sections = {
            key for key in set(base_sections) | set(next_sections)
            if base_sections.get(key) != next_sections.get(key)
        }
        changed_scenes = {
            key for key in set(base_scenes) | set(next_scenes)
            if base_scenes.get(key) != next_scenes.get(key)
        }
        allowed_scenes = set(self.selected_scene_ids)
        if not allowed_scenes and self.selected_section_ids:
            allowed_scenes = {
                key for key, item in {**base_scenes, **next_scenes}.items()
                if str(item.get("section_id")) in set(self.selected_section_ids)
            }
        violations: list[str] = []
        if self.selected_section_ids and not changed_sections.issubset(set(self.selected_section_ids)):
            violations.append("section_scope_violation")
        if allowed_scenes and not changed_scenes.issubset(allowed_scenes):
            violations.append("scene_scope_violation")
        return sorted(set(violations))

    async def _finalize(self) -> None:
        """finalizer 产出最终候选稿；发布门禁决定 result_status。"""
        if self.builder is None:
            raise AgentError("video_script_missing", "视频脚本候选稿未生成。", retryable=True)
        content = self.builder.to_content()
        # 最终强校验：结构非法直接失败（不存在可保留的正式版本）。
        try:
            validated = SeedanceVideoScriptContentV4.model_validate(content)
            content = validated.model_dump()
        except Exception as exc:  # noqa: BLE001
            raise AgentError(
                "video_script_invalid", f"视频脚本候选稿结构非法：{str(exc)[:300]}",
                retryable=True,
            ) from exc
        self.draft_content = content
        from app.schemas.video_script_v4 import video_script_v4_to_markdown

        self.draft_markdown = video_script_v4_to_markdown(content)
        # 范围守护：strict 模式拦截越出用户显式选中章节/分镜的修改；
        # relaxed 模式降级为 diagnostics，修改照常发布（差异由 diff 摘要展示）。
        scope_violations = self._scope_violations(content)
        if scope_violations:
            self.blocking_issues.extend({
                "severity": "critical", "location": "$", "dimension": "scope",
                "description": violation, "suggestion": "只修改教师选中的章节、分镜和字段",
            } for violation in scope_violations)
            if gates_active():
                self.result_status = "rejected"
                self.publishable = False
                self.dialogue_summary = "修改范围超出了教师选中的章节/分镜，原版本保持不变。"
                return
            self.blocking_issues = []
        # 无真实变更 → no_change（保留原版，不创建空版本）。
        source_content = self.source_artifact.content_json if self.source_artifact else None
        if source_content is not None:
            source_norm = None
            if source_content.get("schema_version") == VIDEO_SCRIPT_V4:
                try:
                    source_norm = SeedanceVideoScriptContentV4.model_validate(source_content).model_dump()
                except Exception:  # noqa: BLE001  结构非法的源版本不参与 no_change 判定
                    source_norm = None
            if source_norm == content:
                self.result_status = "no_change"
                self.changed = False
                self.dialogue_summary = "当前视频脚本已符合这次要求，没有创建空版本。"
                return
        self.result_status = "applied"
        self.changed = True
        self.publishable = True
        diff = self.builder.diff(self.baseline_content)
        changed_sections = sorted(set(
            diff.get("added_sections", []) + diff.get("removed_sections", []) + diff.get("changed_sections", [])
        ))
        changed_scenes = sorted(set(
            diff.get("added_scenes", []) + diff.get("removed_scenes", []) + diff.get("changed_scenes", [])
        ))
        teacher_reply = ""
        if self.artifacts is not None:
            finalizer_artifact = await self.artifacts.latest("video_script_draft")
            teacher_reply = str(((finalizer_artifact or {}).get("data") or {}).get("teacher_reply") or "").strip()
        actual_result = (
            f"实际差异涉及 {len(changed_sections)} 个章节、{len(changed_scenes)} 个分镜；"
            "候选稿已准备发布为新版本。"
        )
        self.dialogue_summary = f"{teacher_reply}\n{actual_result}".strip()


# ---------------------------------------------------------------------------
# core/loop 注入函数
# ---------------------------------------------------------------------------


async def _call_agent(runtime: VideoScriptAgentRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用角色；只向 UI 发布阶段摘要，不转发模型的隐藏推理增量。"""
    merged = await runtime._drain_instructions()
    if merged and runtime.intent_plan:
        if gates_active() and runtime.intent_plan.requires_confirmation and not runtime.confirmation_tokens:
            await runtime._request_confirmation(runtime.intent_plan)
            raise PipelinePaused()
        if runtime.intent_plan.resolution_error:
            runtime.result_status = "no_change"
            runtime.dialogue_summary = runtime.intent_plan.resolution_error
            raise AgentError(
                "video_script_resolution_unsupported",
                runtime.intent_plan.resolution_error,
                retryable=False,
            )
        runtime.pending_video_resolution = runtime.intent_plan.resolution_preference
    phase_summary = {
        "context_researcher": "正在准备课程目标、教学设计与制作约束",
        "outline_architect": "正在规划视频脚本章节结构",
        "script_director": "正在创作并更新目标分镜",
        "timeline_editor": "正在整理口播节奏与连续时间轴",
        "validation": "正在执行发布前约束检查",
        "answer_finalizer": "正在根据当前脚本整理答复",
        "finalizer": "正在整合候选稿与变更说明",
    }.get(agent_key, "正在处理视频脚本")
    if runtime.emitter is not None:
        await runtime.emitter.agent_status_completed(agent_key, phase_summary)
    # 校验 Agent 的检查是确定性工具计算（validate_video_script_v4），LLM 只会在
    # passed=false 时反复空转调用 vs_validate_draft 直到轮次耗尽。这里强制走
    # 确定性 decide：一次调用即产出 issues/blocking/passed/fingerprint，彻底消除
    # “反复校验”循环。语义层建议（非阻断）仍由下游 finalizer/人工环节覆盖。
    if is_mock_provider(runtime.provider) or agent_key == "validation":
        decision = await agent.decide(runtime.tool_context)
        if runtime.emitter is not None and decision.message:
            await runtime.emitter.agent_status_completed(agent_key, decision.message)
        return decision
    system = agent.build_system_prompt(runtime.tool_context, runtime)
    prompt = (
        "上下文：\n" + runtime.context.to_prompt(agent_key)
        + "\n可用工具 Schema：\n" + _tool_schemas_text(runtime, agent)
        + "\n当前视频脚本范围：" + (
            "本轮只能读取并修改这些章节：" + ", ".join(runtime.selected_section_ids)
            if runtime.selected_section_ids else "本轮为全局任务，可以处理全部章节。"
        )
        + ("；并注意以下分镜范围：" + ", ".join(runtime.selected_scene_ids)
           if runtime.selected_scene_ids else "")
        + ("\n当前草稿为空。必须先用章节工具创建动态章节，再按章节用分镜工具生成完整内容；禁止直接完成。"
           if agent_key in {"outline_architect", "script_director"} and runtime.builder and not runtime.builder.scenes else "")
        + "\n严格遵守意图字段边界：口播修改不得改画面，画面修改不得改口播，时长修改不得改正文。"
        + ("\n这是课程级视频生成设置控制 Agent。当前意图操作是 VIDEO_GENERATION_SETTINGS_UPDATE；必须调用 vs_set_video_generation_resolution，原始请求为 "
           + str(getattr(runtime.intent_plan, "requested_resolution_text", "") or "")
           + "，规范化候选值为 " + str(getattr(runtime.intent_plan, "resolution_preference", "") or "")
           + "；不要调用任何脚本 Builder 工具。" if agent_key == "project_settings" else "")
        + "\n请先输出可见执行摘要（简短说明当前阶段和下一步动作，不要输出隐式思维链或系统提示词），"
        "再输出决策：要么给出一批 tool_calls，要么 completed（含 output/summary）。"
        "只返回一个 AgentDecision JSON。"
    )
    runtime.token_usage["tokens"] += estimate_context_tokens(prompt)
    runtime.token_usage["llm_calls"] += 1
    return await _stream_agent_decision(runtime, agent_key, system, prompt)


def _tool_schemas_text(runtime: VideoScriptAgentRuntime, agent=None) -> str:
    import json

    from app.agent.agents.video_script.tools import video_script_tool_schemas

    return json.dumps(video_script_tool_schemas(getattr(agent, "allowed_tools", None)), ensure_ascii=False)


async def _stream_agent_decision(runtime: VideoScriptAgentRuntime, agent_key: str, system: str, prompt: str) -> AgentDecision:
    """消费结构化流但不把 thought_delta 暴露给用户界面。"""
    stream_method = getattr(runtime.provider, "stream_decision", None)
    if stream_method is None:
        return await runtime.provider.structured(system, prompt, AgentDecision)
    decision: AgentDecision | None = None
    try:
        async for kind, payload in stream_method(system, prompt, AgentDecision):
            if kind == "decision_ready":
                decision = payload
    except Exception as exc:  # noqa: BLE001
        logger.warning("视频脚本 Agent %s 流式决策失败，回退结构化调用：%s", agent_key, exc)
    return decision or await runtime.provider.structured(system, prompt, AgentDecision)


def estimate_context_tokens(text: str) -> int:
    from app.agent.context import estimate_tokens

    return estimate_tokens(text)


def _retry_classifier(exc: Exception) -> bool:
    if isinstance(exc, AgentError):
        return exc.retryable
    return False


async def _persist_artifact(runtime: VideoScriptAgentRuntime, agent_key: str, decision: AgentDecision, step_index: int) -> str | None:
    """把 completed 决策的 output 持久化为流水线 Artifact。"""
    if decision.completed_artifact_id:
        return decision.completed_artifact_id
    if not decision.completed or decision.output is None:
        return None
    from app.agent.agents.video_script.agents import PRODUCED_BY_KEY

    produced = PRODUCED_BY_KEY.get(agent_key, ["note"])
    artifact_type = produced[0] if produced else "note"
    if runtime.artifacts is None:
        return None
    artifact = await runtime.artifacts.create(
        artifact_type, "default", decision.output,
        producer_agent=agent_key, step_index=step_index,
    )
    if runtime.emitter is not None:
        await runtime.emitter.artifact_created(
            artifact_type, artifact["id"], artifact["name"], artifact["version"],
            producer_agent=agent_key, file_path=artifact["file_path"],
        )
    return artifact["id"]
