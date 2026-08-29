"""课后练习 Agent Runtime：意图 → 计划 → 工具循环 → QA 返修 → 发布。

基于通用 Agent Core（app/agent/core）构建，复用全局工具注册表、事件发射器、
artifact 管理器与 checkpoint/暂停基础设施。与 task_sheet 运行时同构但独立：

- 意图协议为强类型 ExerciseIntentDecision（目标题目/分区 ID）。
- 角色为 9 个：intent_planner / context_researcher / exercise_architect /
  question_designer / scoring_guard / visual_specifier / exercise_qa /
  repair_router / finalizer；每角色最多 6 次工具决策（core/loop 预算）。
- 运行中指令在安全边界原子消费并触发重规划（run.instruction.merged + plan.revised）。
- 人工确认（低置信度/破坏性/指纹空转）通过 agent_human_requests 落地，
  确认后从同一 GenerationRun 的 checkpoint 恢复执行。

result_status 语义与 PPT/lesson_plan 对齐：applied / no_change / rejected / needs_confirmation。
- no_change / rejected / needs_confirmation → skip_publish（不创建正式新版本）
- applied → 创建 V2 Artifact 版本
"""

from __future__ import annotations

import logging
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agent.agents.exercise.agents import (
    AGENT_BY_KEY, ensure_exercise_agents, is_mock_provider, exercise_spec,
)
from app.agent.agents.exercise.builder import (
    ExerciseBuilder, build_initial_builder, upgrade_builder,
)
from app.agent.agents.exercise.intents import (
    INTENT_AGENT_ALIASES, ExerciseIntentDecision,
    agent_chain_for_intent, infer_exercise_intent,
)
from app.agent.agents.exercise.qa import blocking_issues as _blocking
from app.agent.agents.exercise.qa import fingerprint as _fingerprint
from app.agent.core.error import AgentError
from app.agent.core.gates import gates_active
from app.agent.core.loop import run_agent_loop
from app.agent.core.state import AgentRuntimeState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan, ToolCall
from app.core.database import SessionLocal
from app.models.entities import AgentHumanRequest, AgentRunInstruction, PipelineRun
from app.schemas.artifact import ExerciseContent
from app.services.chat_attachment_service import apply_runtime_attachments

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 3  # 最多 3 轮 QA 返修

# 人工确认固定选项（按建议执行 / 缩小修改范围 / 取消本轮）
CONFIRM_OPTIONS = [
    {"id": "apply", "label": "按建议执行", "action": "apply"},
    {"id": "scope_down", "label": "缩小修改范围", "action": "scope_down"},
    {"id": "cancel", "label": "取消本轮", "action": "cancel"},
]


@dataclass
class ExerciseAgentRuntime(AgentRuntimeState):
    """课后练习流水线运行态（继承通用运行态）。"""

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

    builder: ExerciseBuilder | None = None
    selected_section_ids: list[str] = field(default_factory=list)
    affected_section_ids: list[str] = field(default_factory=list)
    active_intent: str = "QUESTION_EDIT"
    intent_plan: ExerciseIntentDecision | None = None
    content_policy: str = "preserve"
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    repair_fingerprint: str = ""
    repair_round: int = 0
    max_revision_rounds: int = MAX_REVISION_ROUNDS
    #: 深度 LLM 化：QA 教学质询与返修轮次每轮都会调用模型，不限累计/单次 token
    #: 估算预算（core/loop 对 0 表示不限制）。
    max_estimated_tokens: int = 0
    max_context_tokens: int = 0
    #: 组装类节点（finalizer）每轮最多一次 LLM 深度分析的缓存。
    _analysis_cache: dict[str, Any] = field(default_factory=dict)
    publishable: bool = False
    draft_content: dict[str, Any] = field(default_factory=dict)
    draft_markdown: str = ""
    request_metadata: dict[str, Any] = field(default_factory=dict)
    handoff_aliases: dict[str, str] = field(default_factory=lambda: INTENT_AGENT_ALIASES)
    changed: bool = False

    # 人工确认（同一 GenerationRun 从 checkpoint 恢复）
    confirmation_tokens: list[str] = field(default_factory=list)
    confirmation_request: AgentHumanRequest | None = None
    resumed_confirmation: dict[str, Any] = field(default_factory=dict)

    # 协议统计（PipelineRun 记录实际使用的协议）
    tool_protocol: str = "structured"   # native | structured
    tool_call_count: int = 0
    protocol_fallbacks: int = 0
    before_type_counts: dict[str, int] = field(default_factory=dict)
    after_type_counts: dict[str, int] = field(default_factory=dict)
    requested_delta: int = 0
    actual_delta: int = 0
    baseline_content: dict[str, Any] = field(default_factory=dict)
    # ExerciseBuilder is not persisted in the generic checkpoint.  A process
    # restart therefore replays safely from the formal source instead of
    # applying a stale orchestration step index to a fresh Builder.
    restarted_from_source: bool = False

    # ------------------------------------------------------------------
    # 准备
    # ------------------------------------------------------------------

    def _prepare_builder(self) -> ExerciseBuilder:
        bp_content = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        task_sheet_raw = (self.knowledge_context or {}).get("sibling_artifacts", {}).get("task_sheet")
        if task_sheet_raw is None:
            task_sheet_raw = (self.knowledge_context or {}).get("hard_dependencies", {}).get("task_sheet")
        if isinstance(task_sheet_raw, dict):
            task_sheet_raw = task_sheet_raw.get("content") or task_sheet_raw
        if self.source_artifact is not None:
            source_content = self.source_artifact.content_json or {}
            builder = upgrade_builder(source_content, bp_content, task_sheet_raw)
        else:
            builder = build_initial_builder(bp_content, task_sheet_raw)
        self.builder = builder
        return builder

    async def _prepare(self) -> None:
        ensure_exercise_agents()
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
        self.before_type_counts = builder.question_type_counts()
        await self._restore_confirmation_state()

    async def _restore_confirmation_state(self) -> None:
        """从 checkpoint 恢复人工确认令牌与确认信息（同一 GenerationRun 恢复）。"""
        if self.pipeline_run is None:
            return
        checkpoint = self.pipeline_run.checkpoint_json or {}
        pending = checkpoint.get("pending_confirmation") or {}
        if pending.get("token"):
            self.confirmation_tokens = [str(pending["token"])]
            self.resumed_confirmation = dict(pending)
        checkpoint_intent = checkpoint.get("active_intent")
        if checkpoint_intent:
            self.active_intent = str(checkpoint_intent)

    # ------------------------------------------------------------------
    # 意图与计划
    # ------------------------------------------------------------------

    async def _resolve_intent(self) -> ExerciseIntentDecision:
        instruction = self.context.user_instruction or ""
        mode = (self.request_metadata or {}).get("mode")
        available = self.builder.all_question_ids() if self.builder is not None else None
        decision = await infer_exercise_intent(
            self.provider, self.trigger_type, instruction,
            self.selected_section_ids or None, mode,
            available_question_ids=available or None,
            current_type_counts=self.builder.question_type_counts() if self.builder else None,
        )
        self._configure_count_intent(decision)
        self.intent_plan = decision
        self.active_intent = decision.intent
        self.selected_section_ids = list(self.selected_section_ids or [])
        self.content_policy = "edit" if decision.mutates_document else "preserve"
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "intent.recognized",
                agent={"id": "intent_planner"},
                message=f"意图：{decision.intent}",
                payload={
                    "intent": decision.intent,
                    "mutates_document": decision.mutates_document,
                    "structural": decision.structural,
                    "destructive": decision.destructive,
                    "confidence": decision.confidence,
                    "requires_confirmation": decision.requires_confirmation,
                    "target_question_ids": decision.target_question_ids,
                    "target_section_ids": decision.target_section_ids,
                    "affected_json_paths": decision.affected_json_paths,
                    "assumptions": decision.assumptions,
                    "plan_steps": decision.plan_steps,
                    "acceptance_criteria": decision.acceptance_criteria,
                    "clarification_question": decision.clarification_question,
                },
            )
            if decision.plan_steps:
                await self.emitter.emit_domain(
                    "plan.created",
                    agent={"id": "intent_planner"},
                    message="已创建执行计划",
                    payload={"intent": decision.intent, "steps": decision.plan_steps},
                )
        return decision

    def _configure_count_intent(self, decision: ExerciseIntentDecision) -> None:
        """Resolve a safe insertion section and observable delta for count contracts."""
        if decision.operation != "ensure_question_type_count" or self.builder is None:
            return
        question_type = str(decision.question_type or "")
        current = self.builder.question_type_counts().get(question_type, 0)
        decision.current_count = current
        decision.requested_delta = int(decision.target_count or 0) - current
        if decision.requested_delta < 0 and self.confirmation_tokens:
            # A prior generic exact-count request was confirmed by the teacher;
            # turn that confirmation into an executable bounded deletion.
            decision.mutation_mode = "delete_excess"
            decision.requires_confirmation = False
            decision.destructive = True
        self.requested_delta = decision.requested_delta
        if decision.delete_position == "last":
            matching = [
                item for item in self.builder.question_snapshot()
                if item.get("question_type") == question_type
            ]
            if matching:
                target = matching[-1]
                decision.delete_question_ids = [str(target.get("id") or "")]
                decision.allowed_section_ids = [str(target.get("section_id") or "")]
        if not decision.allowed_section_ids:
            if self.selected_section_ids:
                decision.allowed_section_ids = list(self.selected_section_ids)
            elif decision.target_section_ids:
                valid_sections = {item.get("id") for item in self.builder.sections}
                decision.allowed_section_ids = [
                    item for item in decision.target_section_ids if item in valid_sections
                ]
        if not decision.allowed_section_ids:
            per_section: dict[str, int] = {}
            for item in self.builder.question_snapshot():
                if item.get("question_type") == question_type:
                    section_id = str(item.get("section_id") or "")
                    per_section[section_id] = per_section.get(section_id, 0) + 1
            if per_section and decision.mutation_mode == "delete_excess":
                decision.allowed_section_ids = sorted(per_section)
            elif per_section:
                decision.allowed_section_ids = [max(
                    per_section,
                    key=lambda key: (per_section[key], key == "understanding_application"),
                )]
            else:
                decision.allowed_section_ids = ["understanding_application"]
        decision.target_section_ids = list(decision.allowed_section_ids)

    def _build_plan(self, chain: list[str], revision_rounds: int = MAX_REVISION_ROUNDS) -> PipelinePlan:
        specs = []
        for key in chain:
            spec = exercise_spec(key)
            if self.intent_plan and self.intent_plan.operation == "ensure_question_type_count":
                if key == "question_designer":
                    spec["max_steps"] = 2
                elif key == "finalizer":
                    spec["max_steps"] = 1
            specs.append(AgentSpec(**spec))
        return PipelinePlan(
            agents=specs,
            revision_rounds=revision_rounds,
        )

    # ------------------------------------------------------------------
    # 运行中指令原子消费 / 合并 / 重规划
    # ------------------------------------------------------------------

    async def _drain_instructions(self) -> list[str]:
        """在安全边界原子消费运行中新指令：标记 merged，发事件并重新解析意图。

        返回本次消费的新指令文本列表；空表示无新指令。
        """
        if self.pipeline_run is None or self.trigger_type != "message":
            return []
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(AgentRunInstruction).where(
                AgentRunInstruction.pipeline_run_id == self.pipeline_run.id,
                AgentRunInstruction.status == "queued",
            ).order_by(AgentRunInstruction.created_at)))
            if not rows:
                return []
            merged_texts: list[str] = []
            attachment_metadata: list[dict[str, Any]] = []
            for row in rows:
                row.status = "merged"
                row.applied_at = datetime.now(timezone.utc)
                merged_texts.append(row.content or "")
                attachment_metadata.extend((row.metadata_json or {}).get("attachments") or [])
            await db.commit()
            if attachment_metadata:
                await apply_runtime_attachments(
                    db, self.course, self, {"attachments": attachment_metadata},
                )
        if not merged_texts:
            return []
        merged = "\n".join(merged_texts)
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "run.instruction.merged",
                agent={"id": "intent_planner"},
                message=f"已合并运行中指令：{merged[:120]}",
                payload={"instruction_count": len(merged_texts), "content": merged_texts},
            )
        # 合并到当前目标后重新执行意图识别
        self.context.user_instruction = (self.context.user_instruction + "\n" + merged).strip()
        mode = (self.request_metadata or {}).get("mode")
        available = self.builder.all_question_ids() if self.builder is not None else None
        decision = await infer_exercise_intent(
            self.provider, "message", self.context.user_instruction,
            self.selected_section_ids or None, mode,
            available_question_ids=available or None,
            current_type_counts=self.builder.question_type_counts() if self.builder else None,
        )
        self._configure_count_intent(decision)
        self.intent_plan = decision
        self.active_intent = decision.intent
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "plan.revised",
                agent={"id": "intent_planner"},
                message=f"已根据新指令重新规划：{decision.intent}",
                payload={
                    "intent": decision.intent,
                    "target_question_ids": decision.target_question_ids,
                    "target_section_ids": decision.target_section_ids,
                    "requires_confirmation": decision.requires_confirmation,
                },
            )
        return merged_texts

    # ------------------------------------------------------------------
    # 人工确认
    # ------------------------------------------------------------------

    async def _request_confirmation(self, decision: ExerciseIntentDecision) -> None:
        """低置信度 / 破坏性 / 指纹空转 → 创建人工确认请求并原地等待（paused）。"""
        async with SessionLocal() as db:
            existing = await db.scalar(select(AgentHumanRequest).where(
                AgentHumanRequest.pipeline_run_id == self.pipeline_run.id,
                AgentHumanRequest.request_type == "exercise_confirmation",
                AgentHumanRequest.status == "pending",
            ).order_by(AgentHumanRequest.created_at.desc()))
        if existing is not None:
            self.confirmation_request = existing
            self.result_status = "needs_confirmation"
            self.dialogue_summary = existing.prompt or decision.clarification_question or "需要教师确认后继续。"
            return
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "human.required",
                agent={"id": "intent_planner"},
                message=decision.clarification_question or "需要教师确认后才能继续",
                payload={
                    "intent": decision.intent,
                    "clarification_question": decision.clarification_question,
                    "destructive": decision.destructive,
                    "confidence": decision.confidence,
                },
            )
        request = AgentHumanRequest(
            pipeline_run_id=self.pipeline_run.id,
            request_type="exercise_confirmation",
            prompt=decision.clarification_question or "请确认本次修改的执行范围。",
            options_json=CONFIRM_OPTIONS,
            status="pending",
        )
        async with SessionLocal() as db:
            db.add(request)
            await db.flush()
            request_id = request.id
            row = await db.get(PipelineRun, self.pipeline_run.id)
            if row:
                row.status = "paused"
                row.checkpoint_json = {
                    **(row.checkpoint_json or {}),
                    "pending_confirmation": {
                        "request_id": request_id,
                        "request_type": "exercise_confirmation",
                        "intent": decision.intent,
                        "requires_confirmation": True,
                    },
                }
                row.plan_json = {
                    **(row.plan_json or {}),
                    "result_status": "needs_confirmation",
                    "active_intent": decision.intent,
                }
            await db.commit()
        self.confirmation_request = request
        self.result_status = "needs_confirmation"
        self.dialogue_summary = decision.clarification_question or "需要教师确认后继续。"

    async def _mark_confirmation_resolved(self) -> None:
        """确认恢复后发 human.resolved 事件。"""
        info = self.resumed_confirmation or {}
        if not info:
            return
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "human.resolved",
                agent={"id": "intent_planner"},
                message="教师已确认，继续执行。",
                payload={
                    "request_id": info.get("request_id"),
                    "choice": info.get("choice"),
                    "intent": info.get("intent"),
                },
            )

    async def _clear_obsolete_confirmations(self) -> None:
        """Resolve stale confirmation cards after deterministic replanning made them unnecessary."""
        if self.pipeline_run is None:
            return
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(AgentHumanRequest).where(
                AgentHumanRequest.pipeline_run_id == self.pipeline_run.id,
                AgentHumanRequest.request_type == "exercise_confirmation",
                AgentHumanRequest.status == "pending",
            )))
            resolved_at = datetime.now(timezone.utc)
            for row in rows:
                row.status = "resolved"
                row.resolved_at = resolved_at
                row.response_json = {
                    **dict(row.response_json or {}),
                    "resolution": "superseded",
                    "reason": "deterministic_intent_no_longer_requires_confirmation",
                }
            pipeline = await db.get(PipelineRun, self.pipeline_run.id)
            if pipeline:
                checkpoint = dict(pipeline.checkpoint_json or {})
                checkpoint.pop("pending_confirmation", None)
                pipeline.checkpoint_json = checkpoint
            await db.commit()

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await self._prepare()
        if self.emitter is not None:
            await self.emitter.pipeline_started(self.trigger_type)
            if self.restarted_from_source:
                await self.emitter.emit_domain(
                    "run.restarted_from_source",
                    agent={"id": "orchestrator"},
                    message="检测到未持久化的旧候选稿进度，已从当前正式版本安全重跑。",
                    payload={
                        "reason": "exercise_builder_not_checkpointed",
                        "checkpoint_start": 0,
                    },
                )
        if self.resumed_confirmation:
            await self._mark_confirmation_resolved()
        decision = await self._resolve_intent()
        if not decision.requires_confirmation:
            await self._clear_obsolete_confirmations()
        # 已确认恢复：清除 checkpoint 标记后继续执行当前意图。
        if self.resumed_confirmation:
            async with SessionLocal() as db:
                row = await db.get(PipelineRun, self.pipeline_run.id)
                if row:
                    checkpoint = dict(row.checkpoint_json or {})
                    checkpoint.pop("pending_confirmation", None)
                    row.checkpoint_json = checkpoint
                    row.status = "running"
                    await db.commit()
        # 需要人工确认且尚未确认 → 创建确认请求，原地暂停。
        # relaxed 门禁模式：低置信度/破坏性关键词不再拦截，按当前意图直接执行。
        if gates_active() and decision.requires_confirmation and not self.confirmation_tokens:
            await self._request_confirmation(decision)
            return
        if (
            decision.operation == "ensure_question_type_count"
            and decision.current_count == decision.target_count
        ):
            self.result_status = "no_change"
            self.changed = False
            self.publishable = False
            self.draft_content = self.builder.to_content() if self.builder else {}
            self.after_type_counts = dict(self.before_type_counts)
            snapshot = self.builder.question_snapshot() if self.builder else []
            matching_ids = [
                str(item.get("id")) for item in snapshot
                if item.get("question_type") == decision.question_type
            ]
            semantic_mismatches: list[str] = []
            for item in snapshot:
                correct_count = len(item.get("correct_option_ids") or [])
                declared = item.get("question_type")
                if declared == "single_choice" and correct_count > 1:
                    semantic_mismatches.append(f"{item.get('id')}:单选字段但有{correct_count}个正确项")
                if declared == "multiple_choice" and correct_count < 2:
                    semantic_mismatches.append(f"{item.get('id')}:多选字段但正确项不足2个")
            choice_by_section: dict[str, dict[str, int]] = {}
            for item in snapshot:
                if item.get("question_type") not in {"single_choice", "multiple_choice"}:
                    continue
                section_id = str(item.get("section_id") or "")
                bucket = choice_by_section.setdefault(section_id, {"single_choice": 0, "multiple_choice": 0})
                bucket[str(item.get("question_type"))] += 1
            self.dialogue_summary = (
                f"已按题型字段、正确选项数量和题目 ID 完成核验：当前共有 "
                f"{decision.target_count} 道多选题（{', '.join(matching_ids)}）。"
                f"各分区选择题构成为 {choice_by_section}；单选题不计入多选题数量。"
                f"题型语义异常：{semantic_mismatches or '无'}。"
                "因此本轮无需删题，也未创建新版本。"
            )
            return
        if decision.operation == "move_question" and self.builder is not None:
            question_id = next(iter(decision.target_question_ids), "")
            _, current_section, _ = self.builder.find_question(question_id)
            if current_section is not None and current_section.get("id") == decision.destination_section_id:
                self.result_status = "no_change"
                self.changed = False
                self.publishable = False
                self.draft_content = self.builder.to_content()
                self.dialogue_summary = (
                    f"核验完成：{question_id} 已位于目标分区 {decision.destination_section_id}，"
                    "因此未创建新版本。"
                )
                return
        chain = agent_chain_for_intent(decision.intent, self.trigger_type)
        if decision.operation == "ensure_question_type_count":
            chain = ["question_designer", "finalizer"]
        elif decision.operation == "move_question":
            chain = ["question_designer", "finalizer"]
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "intent.resolved",
                agent={"id": "intent_planner"},
                message=f"意图：{self.active_intent}",
                payload={"intent": self.active_intent, "chain": chain,
                         "target_question_ids": decision.target_question_ids,
                         "target_section_ids": decision.target_section_ids},
            )
        self.blocking_issues = []
        self.repair_fingerprint = ""
        await self._run_with_repair(chain)
        await self._finalize()

    async def _run_with_repair(self, chain: list[str]) -> None:
        """执行计划并处理 QA → 返修闭环（≤3 轮，指纹防空转）。"""
        plan = self._build_plan(chain)
        attempt_count = 2 if self.intent_plan and self.intent_plan.operation == "ensure_question_type_count" else self.max_revision_rounds
        for round_index in range(attempt_count):
            self.repair_round = round_index
            await run_agent_loop(
                self, plan,
                agent_registry=AGENT_BY_KEY,
                call_agent=_call_agent,
                persist_artifact=_persist_artifact,
                retry_classifier=_retry_classifier,
            )
            await self._collect_qa_issues()
            if not _blocking(self.blocking_issues):
                return
            fp = _fingerprint(self.blocking_issues)
            if fp and fp == self.repair_fingerprint:
                # 连续两轮指纹相同 → 停止空转并请求教师介入。
                logger.info("练习返修指纹重复，停止空转（round=%s）", round_index)
                if self.emitter is not None:
                    await self.emitter.emit_domain(
                        "repair.stalled",
                        agent={"id": "repair_router"},
                        message="返修未收敛（连续两轮问题相同），请求教师介入。",
                        payload={"issue_count": len(self.blocking_issues)},
                    )
                await self._request_confirmation(ExerciseIntentDecision(
                    intent="QUESTION_EDIT",
                    requires_confirmation=True,
                    clarification_question="自动返修三轮后问题未收敛，请教师介入处理。",
                    confidence=0.3,
                ))
                return
            self.repair_fingerprint = fp
            if round_index >= attempt_count - 1:
                return
            # repair_router 路由重跑范围（确定性控制节点）。
            from app.agent.agents.exercise.agents import REPAIR_ROUTER

            repair_decision = await REPAIR_ROUTER.decide(self.tool_context)
            repair_agents = (repair_decision.output or {}).get("plan") or ["question_designer", "exercise_qa"]
            if self.emitter is not None:
                await self.emitter.revision_started(
                    round_index + 1, attempt_count - 1,
                    reason="练习质询存在阻断问题", target_agents=repair_agents,
                )
            plan = self._build_plan([*repair_agents, "finalizer"])
            if self.emitter is not None:
                await self.emitter.revision_completed(round_index + 1, applied_changes=repair_agents)

    async def _collect_qa_issues(self) -> None:
        """运行 exercise_qa 角色收集阻断问题（LLM 质询 + 确定性门禁合并）。

        relaxed 门禁模式：QA 结果只作为 qa.issues 事件提示，不进入返修/阻断。
        """
        from app.agent.agents.exercise.agents import EXERCISE_QA

        self.blocking_issues = []
        if self.builder is None:
            return
        decision = await EXERCISE_QA.decide(self.tool_context)
        output = decision.output or {}
        if not gates_active():
            if self.emitter is not None and output.get("issues"):
                await self.emitter.emit_domain(
                    "qa.issues",
                    agent={"id": "exercise_qa"},
                    message=decision.summary,
                    payload={
                        "issues": output.get("issues"),
                        "blocking": [],
                        "fingerprint": output.get("fingerprint"),
                        "source": output.get("source"),
                    },
                )
            return
        self.blocking_issues = list(output.get("issues") or [])
        if self.emitter is not None and output.get("issues"):
            await self.emitter.emit_domain(
                "qa.issues",
                agent={"id": "exercise_qa"},
                message=decision.summary,
                payload={
                    "issues": output.get("issues"),
                    "blocking": output.get("blocking"),
                    "fingerprint": output.get("fingerprint"),
                    "source": output.get("source"),
                },
            )

    # ------------------------------------------------------------------
    # 发布门禁（Schema / 确定性规则 / LLM QA / 锁定检查全通过才发布）
    # ------------------------------------------------------------------

    async def _finalize(self) -> None:
        if self.builder is None:
            raise AgentError("exercise_missing", "课后练习候选稿未生成。", retryable=True)
        # QA_ONLY：仅质量检查/回答，不创建新版本。
        if self.active_intent == "QA_ONLY":
            self.result_status = "no_change"
            self.changed = False
            self.publishable = False
            return
        try:
            validated = ExerciseContent.model_validate(self.builder.to_content())
            content = validated.model_dump()
        except Exception as exc:  # noqa: BLE001
            raise AgentError(
                "exercise_invalid", f"课后练习候选稿结构非法：{str(exc)[:300]}",
                retryable=True,
            ) from exc
        # 发布门禁通过（QA blocking 为空）→ 回填 review_summary 终态，供学生卷/教师卷导出展示。
        summary = content.setdefault("review_summary", {})
        summary["rules_status"] = "passed"
        if summary.get("text_review_status") == "pending":
            summary["text_review_status"] = "passed"
        content["review_summary"] = summary
        self.draft_content = content
        self.after_type_counts = self.builder.question_type_counts()
        self.actual_delta = sum(self.after_type_counts.values()) - sum(self.before_type_counts.values())
        contract_failures = self._enforce_intent_contract(content)
        # relaxed 门禁模式：意图契约降级为 diagnostics，不再拒绝发布。
        if contract_failures and gates_active():
            self.result_status = "rejected"
            self.changed = False
            self.publishable = False
            self.blocking_issues = [
                {
                    "severity": "critical",
                    "dimension": "intent",
                    "description": failure,
                    "target_role": "question_designer",
                }
                for failure in contract_failures
            ]
            return
        try:
            from app.agents.generators import to_markdown

            self.draft_markdown = to_markdown("exercise", validated)
        except Exception:  # noqa: BLE001  markdown 非必需
            self.draft_markdown = ""
        # 无真实变更 → no_change（保留原版，不创建空版本）。
        source_content = self.source_artifact.content_json if self.source_artifact else None
        if source_content is not None:
            source_norm = None
            if source_content.get("schema_version") == "2.0":
                try:
                    source_norm = ExerciseContent.model_validate(source_content).model_dump()
                except Exception:  # noqa: BLE001  结构非法的源版本不参与 no_change 判定
                    source_norm = None
            if source_norm == content:
                self.result_status = "no_change"
                self.changed = False
                return
        self.result_status = "applied"
        self.changed = True
        self.publishable = True

    def _enforce_intent_contract(self, content: dict[str, Any]) -> list[str]:
        """Reject candidates that are valid documents but do not fulfill the teacher request."""
        decision = self.intent_plan
        if decision is not None and decision.operation == "move_question":
            question_id = next(iter(decision.target_question_ids), "")
            baseline_builder = ExerciseBuilder(self.baseline_content)
            candidate_builder = ExerciseBuilder(content)
            baseline_question, _, _ = baseline_builder.find_question(question_id)
            candidate_question, candidate_section, _ = candidate_builder.find_question(question_id)
            failures: list[str] = []
            if candidate_question is None or candidate_section is None:
                failures.append(f"moved_question_missing:{question_id}")
            elif candidate_section.get("id") != decision.destination_section_id:
                failures.append(
                    f"question_destination:{candidate_section.get('id')}!={decision.destination_section_id}"
                )
            if baseline_question != candidate_question:
                failures.append(f"moved_question_content_changed:{question_id}")
            baseline_locations = {
                item["id"]: item["section_id"]
                for item in baseline_builder.question_snapshot()
                if item["id"] != question_id
            }
            candidate_locations = {
                item["id"]: item["section_id"]
                for item in candidate_builder.question_snapshot()
                if item["id"] != question_id
            }
            if baseline_locations != candidate_locations:
                failures.append("non_target_question_moved")
            return failures
        if decision is None or decision.operation != "ensure_question_type_count":
            return []
        question_type = str(decision.question_type or "")
        expected = int(decision.target_count or 0)
        actual = int(self.after_type_counts.get(question_type, 0))
        failures: list[str] = []
        if actual != expected:
            failures.append(f"{question_type}_count:{actual}!={expected}")
        if self.actual_delta != int(decision.requested_delta or 0):
            failures.append(f"question_delta:{self.actual_delta}!={decision.requested_delta}")

        baseline_questions = {
            item["id"]: item for item in ExerciseBuilder(self.baseline_content).question_snapshot()
        }
        candidate_questions = {
            item["id"]: item for item in ExerciseBuilder(content).question_snapshot()
        }
        allowed_removed_ids: set[str] = set()
        for question_id, baseline in baseline_questions.items():
            candidate = candidate_questions.get(question_id)
            if candidate is None:
                if (
                    decision.mutation_mode == "delete_excess"
                    and baseline.get("question_type") == question_type
                    and baseline.get("section_id") in set(decision.allowed_section_ids or [])
                ):
                    allowed_removed_ids.add(question_id)
                else:
                    failures.append(f"existing_question_deleted:{question_id}")
                continue
            if candidate.get("question_type") != baseline.get("question_type"):
                failures.append(f"existing_question_type_changed:{question_id}")
            if candidate.get("section_id") != baseline.get("section_id"):
                failures.append(f"existing_question_moved:{question_id}")
            if (
                candidate.get("score") != baseline.get("score")
                and candidate.get("section_id") not in set(decision.allowed_section_ids or [])
            ):
                failures.append(f"score_changed_outside_allowed_section:{question_id}")

        baseline_sections = {
            item.get("id"): (item.get("title"), item.get("score"))
            for item in self.baseline_content.get("sections", [])
        }
        candidate_sections = {
            item.get("id"): (item.get("title"), item.get("score"))
            for item in content.get("sections", [])
        }
        if decision.preserve_section_scores and candidate_sections != baseline_sections:
            failures.append("section_titles_or_scores_changed")
        expected_removed = max(0, -int(decision.requested_delta or 0))
        if decision.mutation_mode == "delete_excess" and len(allowed_removed_ids) != expected_removed:
            failures.append(f"removed_question_count:{len(allowed_removed_ids)}!={expected_removed}")
        normalized_baseline = copy.deepcopy(self.baseline_content)
        if allowed_removed_ids:
            baseline_builder = ExerciseBuilder(normalized_baseline)
            for question_id in allowed_removed_ids:
                baseline_builder.delete_block(question_id)
            normalized_baseline = baseline_builder.to_content()
        if self._normalized_count_edit_content(normalized_baseline) != self._normalized_count_edit_content(
            content, baseline=self.baseline_content,
        ):
            failures.append("non_target_content_changed")
        return failures

    @staticmethod
    def _normalized_count_edit_content(
        content: dict[str, Any],
        *,
        baseline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Normalize allowed additions/score changes so remaining diff means scope drift."""
        normalized = copy.deepcopy(content)
        normalized.pop("review_summary", None)
        reference = baseline or content

        def _question_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
            result: dict[str, dict[str, Any]] = {}
            for section in raw.get("sections", []):
                for block in section.get("blocks", []):
                    questions = block.get("sub_questions", []) if block.get("kind") == "question_group" else [block]
                    for question in questions:
                        result[str(question.get("id") or "")] = question
            return result

        reference_questions = _question_map(reference)
        for section in normalized.get("sections", []):
            kept_blocks = []
            for block in section.get("blocks", []):
                if block.get("kind") == "question":
                    question_id = str(block.get("id") or "")
                    if question_id not in reference_questions:
                        continue
                    block["score"] = reference_questions[question_id].get("score")
                    block["scoring_points"] = copy.deepcopy(reference_questions[question_id].get("scoring_points", []))
                    kept_blocks.append(block)
                elif block.get("kind") == "question_group":
                    block["sub_questions"] = [
                        question for question in block.get("sub_questions", [])
                        if str(question.get("id") or "") in reference_questions
                    ]
                    for question in block["sub_questions"]:
                        ref = reference_questions[str(question.get("id") or "")]
                        question["score"] = ref.get("score")
                        question["scoring_points"] = copy.deepcopy(ref.get("scoring_points", []))
                    kept_blocks.append(block)
            section["blocks"] = kept_blocks
        return normalized


# ---------------------------------------------------------------------------
# core/loop 注入函数
# ---------------------------------------------------------------------------


async def _call_agent(runtime: ExerciseAgentRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用角色：Mock/控制节点走确定性 decide；LLM 走原生 tool calling，
    不可用时回退流式结构化决策。

    每次决策前先原子消费运行中新指令（安全边界）。
    """
    await runtime._drain_instructions()
    if (
        agent_key == "question_designer"
        and runtime.intent_plan
        and runtime.intent_plan.delete_question_ids
    ):
        return _positional_delete_decision(runtime)
    if (
        agent_key == "question_designer"
        and runtime.intent_plan
        and runtime.intent_plan.operation == "move_question"
    ):
        plan = runtime.intent_plan
        question_id = next(iter(plan.target_question_ids), "")
        _, section, _ = runtime.builder.find_question(question_id) if runtime.builder else (None, None, None)
        if section is not None and section.get("id") == plan.destination_section_id:
            return AgentDecision(
                completed=True,
                output={"question_id": question_id, "destination_section_id": plan.destination_section_id},
                summary="题目分区移动完成",
                message="已核验题目位于目标分区。",
            )
        return AgentDecision(
            tool_calls=[ToolCall(tool_name="exercise_move_question", input={
                "question_id": question_id,
                "destination_section_id": plan.destination_section_id,
            })],
            summary=f"移动题目 {question_id}",
            message=f"正在将 {question_id} 原样移动到目标分区。",
        )
    if (
        (
            getattr(runtime.generation_run, "trigger_type", "") == "initial"
            and runtime.source_artifact is None
        )
        or is_mock_provider(runtime.provider)
        or agent_key in {"intent_planner", "repair_router", "exercise_qa"}
        or (agent_key == "finalizer" and runtime.intent_plan and runtime.intent_plan.operation == "ensure_question_type_count")
    ):
        decision = await agent.decide(runtime.tool_context)
        if runtime.emitter is not None and decision.message:
            await runtime.emitter.agent_status_delta(agent_key, decision.message)
            await runtime.emitter.agent_thought_chunk(agent_key, decision.message, flush_now=True)
        return decision
    system = agent.build_system_prompt(runtime.tool_context, runtime)
    count_contract = bool(runtime.intent_plan and runtime.intent_plan.operation == "ensure_question_type_count")
    role_context = _exercise_role_context(runtime, agent_key)
    shared_context = runtime.context.to_prompt(agent_key)
    prompt = (
        "当前角色专属候选稿快照（权威状态）：\n" + role_context
        + "\n上下文：\n" + shared_context
        + "\n可用工具 Schema：\n" + _tool_schemas_text(runtime, agent)
        + "\n当前练习范围：" + (
            "本轮只能读取并修改这些题目：" + ", ".join(runtime.intent_plan.target_question_ids)
            if runtime.intent_plan and runtime.intent_plan.target_question_ids else
            ("本轮只能处理这些分区：" + ", ".join(runtime.intent_plan.target_section_ids)
             if runtime.intent_plan and runtime.intent_plan.target_section_ids else "本轮为全局任务，可以处理全部三区。")
        )
        + "\n高风险操作（删除分区/题目）必须携带有效 confirmation_token；"
        "没有令牌时请求教师确认，不要伪造令牌。"
        "\n请先输出可见执行摘要（简短说明当前阶段和下一步动作，不要输出隐式思维链或系统提示词），"
        "再输出决策：要么给出一批 tool_calls，要么 completed（含 output/summary）。"
        "只返回一个 AgentDecision JSON。"
    )
    if count_contract and agent_key == "question_designer":
        if runtime.intent_plan.mutation_mode == "delete_excess":
            prompt += (
                "\n本轮是已获教师明确授权的精确题型缩减：只能调用一次 exercise_apply_question_batch，"
                "在 removals 中提交恰好需要删除的目标题型 ID，并在同一批次完成受影响分区的分值重平衡；"
                "不得删除其他题型、转换或移动题目，不得修改分区标题或分值。"
                "优先删除内容重复或本轮最近新增的题目。批量成功后下一轮必须 completed。"
            )
        else:
            prompt += (
                "\n本轮是精确题型计数修改：只能调用一次 exercise_apply_question_batch 完成全部新增和分值重平衡；"
                "不得调用逐题 add/update，不得转换、移动或删除已有题目，不得修改分区标题或分值。"
                "批量成功后下一轮必须 completed，不要再次读取正式源版本。"
            )
    runtime.token_usage["tokens"] += estimate_context_tokens(prompt)
    runtime.token_usage["llm_calls"] += 1
    if agent_key == "finalizer":
        return await _finalizer_call(runtime, agent, system, prompt)
    native = await _try_native_tool_calling(runtime, agent_key, system, prompt, agent)
    if native is not None:
        return _validate_count_tool_decision(runtime, agent_key, native)
    decision = await _stream_agent_decision(runtime, agent_key, system, prompt)
    return _validate_count_tool_decision(runtime, agent_key, decision)


def _positional_delete_decision(runtime: ExerciseAgentRuntime) -> AgentDecision:
    """Build one deterministic atomic batch for an explicitly targeted deletion."""
    builder = runtime.builder
    plan = runtime.intent_plan
    if builder is None or plan is None:
        return AgentDecision(completed=True, summary="没有可删除的候选题目")
    delete_ids = [item for item in plan.delete_question_ids if builder.find_question(item)[0] is not None]
    if not delete_ids:
        return AgentDecision(
            completed=True,
            output={"deleted_question_ids": plan.delete_question_ids},
            summary="指定的最后一道题已删除",
            message="已完成指定题目删除与分值重平衡。",
        )

    delete_set = set(delete_ids)
    score_updates: list[dict[str, Any]] = []
    affected_sections = set(plan.allowed_section_ids or [])
    content = builder.to_content()
    for section in content.get("sections", []):
        if section.get("id") not in affected_sections:
            continue
        questions: list[dict[str, Any]] = []
        for block in section.get("blocks", []):
            questions.extend(block.get("sub_questions", []) if block.get("kind") == "question_group" else [block])
        survivors = [item for item in questions if str(item.get("id") or "") not in delete_set]
        if not survivors:
            continue
        deficit = int(section.get("score") or 0) - sum(int(item.get("score") or 0) for item in survivors)
        quotient, remainder = divmod(max(0, deficit), len(survivors))
        for index, item in enumerate(survivors):
            increment = quotient + (1 if index < remainder else 0)
            if increment <= 0:
                continue
            new_score = int(item.get("score") or 0) + increment
            update: dict[str, Any] = {"question_id": item.get("id"), "score": new_score}
            points = copy.deepcopy(item.get("scoring_points") or [])
            if points:
                points[-1]["points"] = int(points[-1].get("points") or 0) + increment
                update["scoring_points"] = points
            score_updates.append(update)

    return AgentDecision(
        tool_calls=[ToolCall(
            tool_name="exercise_apply_question_batch",
            input={
                "base_revision": builder.revision,
                "removals": delete_ids,
                "score_updates": score_updates,
                "expected_question_type": plan.question_type,
                "expected_type_count": plan.target_count,
                "expected_total_delta": plan.requested_delta,
                "allowed_section_ids": list(plan.allowed_section_ids or []),
            },
        )],
        summary=f"删除指定题目：{', '.join(delete_ids)}",
        message=f"正在删除最后一道目标题型（{', '.join(delete_ids)}）并重平衡分值。",
    )


def _exercise_role_context(runtime: ExerciseAgentRuntime, agent_key: str) -> str:
    import json

    builder = runtime.builder
    if builder is None:
        return "{}"
    decision = runtime.intent_plan
    content = builder.to_content()
    allowed = set(getattr(decision, "allowed_section_ids", None) or [])
    payload: dict[str, Any] = {
        "intent_contract": decision.model_dump() if decision else {"intent": runtime.active_intent},
        "builder_revision": builder.revision,
        "question_type_counts": builder.question_type_counts(),
        "question_count": len(builder.all_question_ids()),
        "question_snapshot": builder.question_snapshot(),
        "section_scores": [
            {"id": item.get("id"), "title": item.get("title"), "score": item.get("score")}
            for item in builder.sections
        ],
    }
    if decision and decision.operation == "ensure_question_type_count":
        payload["allowed_sections"] = [
            item for item in content.get("sections", []) if item.get("id") in allowed
        ]
        bp = runtime.context.blueprint if runtime.context is not None else {}
        if hasattr(bp, "model_dump"):
            bp = bp.model_dump()
        payload["blueprint_facts"] = {
            "objectives": (bp or {}).get("objectives", []),
            "knowledge_points": (bp or {}).get("knowledge_points", []),
            "timeline": (bp or {}).get("timeline", []),
        }
        payload["instruction"] = runtime.context.user_instruction
    return json.dumps(payload, ensure_ascii=False, default=str)


def _validate_count_tool_decision(
    runtime: ExerciseAgentRuntime, agent_key: str, decision: AgentDecision,
) -> AgentDecision:
    if not (
        runtime.intent_plan
        and runtime.intent_plan.operation == "ensure_question_type_count"
        and agent_key == "question_designer"
        and decision.tool_calls
    ):
        return decision
    illegal = [call.tool_name for call in decision.tool_calls if call.tool_name != "exercise_apply_question_batch"]
    if illegal:
        raise AgentError(
            "count_edit_requires_batch",
            f"精确题型计数修改只能使用原子批量工具，拒绝调用：{', '.join(illegal)}",
            retryable=True,
        )
    if len(decision.tool_calls) != 1:
        raise AgentError(
            "count_edit_requires_single_batch",
            "精确题型计数修改必须在一个原子批次中完成",
            retryable=True,
        )
    return decision


def _merge_llm_analysis(base: AgentDecision, llm: AgentDecision | None) -> AgentDecision:
    """把 LLM 深度分析附加到确定性产物（组装/校验仍由确定性逻辑承担）。"""
    if llm is None:
        return base
    if llm.summary:
        base.summary = llm.summary
    if llm.message:
        base.message = llm.message
    if llm.completed and llm.output is not None:
        base.output = {**dict(base.output or {}), "llm_analysis": llm.output}
    return base


async def _finalizer_call(
    runtime: ExerciseAgentRuntime, agent, system: str, prompt: str,
) -> AgentDecision:
    """finalizer（组装类节点）：每轮最多一次 LLM 深度分析，组装产物始终由确定性 decide 产出。"""
    cached = runtime._analysis_cache.get("finalizer")
    if cached is not None:
        decision = _merge_llm_analysis(await agent.decide(runtime.tool_context), cached)
        if runtime.emitter is not None and decision.message:
            await runtime.emitter.agent_status_delta("finalizer", decision.message)
            await runtime.emitter.agent_thought_chunk("finalizer", decision.message, flush_now=True)
        return decision
    llm_decision: AgentDecision | None = None
    try:
        llm_decision = await _try_native_tool_calling(runtime, "finalizer", system, prompt, agent)
    except Exception:  # noqa: BLE001
        llm_decision = None
    if llm_decision is None:
        try:
            llm_decision = await _stream_agent_decision(runtime, "finalizer", system, prompt)
        except Exception:  # noqa: BLE001
            llm_decision = None
    if llm_decision is None or not llm_decision.completed:
        if llm_decision is not None and llm_decision.tool_calls:
            from app.agent.agents.exercise.agents import FINALIZER_TOOLS

            allowed = set(FINALIZER_TOOLS)
            permitted = [call for call in llm_decision.tool_calls if call.tool_name in allowed]
            if permitted:
                runtime._analysis_cache["finalizer"] = llm_decision
                llm_decision.tool_calls = permitted
                return llm_decision
        return await agent.decide(runtime.tool_context)
    return _merge_llm_analysis(await agent.decide(runtime.tool_context), llm_decision)


async def _try_native_tool_calling(
    runtime: ExerciseAgentRuntime, agent_key: str, system: str, prompt: str, agent,
) -> AgentDecision | None:
    """尝试原生 tool calling；协议不可用/错误时发 fallback 事件并返回 None。"""
    provider = getattr(runtime, "provider", None)
    native_method = getattr(provider, "native_agent_decision", None)
    if not native_method or not getattr(provider, "supports_native_tools", False):
        return None
    from app.agent.agents.exercise.tools import exercise_tool_schemas

    try:
        allowed_tools = getattr(agent, "allowed_tools", None)
        if (
            runtime.intent_plan
            and runtime.intent_plan.operation == "ensure_question_type_count"
            and agent_key == "question_designer"
        ):
            allowed_tools = ["exercise_apply_question_batch"]
        decision = await native_method(
            system, prompt,
            exercise_tool_schemas(allowed_tools),
        )
    except Exception:  # noqa: BLE001  协议错误回退
        decision = None
    if decision is None:
        runtime.tool_protocol = "structured"
        runtime.protocol_fallbacks += 1
        if runtime.emitter is not None:
            await runtime.emitter.emit_domain(
                "provider.tool_protocol_fallback",
                agent={"id": agent_key},
                message="原生 tool calling 不可用，已回退结构化 AgentDecision 协议",
                payload={"provider": getattr(provider, "name", "")},
            )
        return None
    runtime.tool_protocol = "native"
    if decision.tool_calls:
        runtime.tool_call_count += len(decision.tool_calls)
    if runtime.emitter is not None and decision.message:
        await runtime.emitter.agent_status_delta(agent_key, decision.message)
        await runtime.emitter.agent_thought_chunk(agent_key, decision.message, flush_now=True)
    return decision


def _tool_schemas_text(runtime: ExerciseAgentRuntime, agent=None) -> str:
    import json

    from app.agent.agents.exercise.tools import exercise_tool_schemas

    allowed = getattr(agent, "allowed_tools", None)
    if (
        runtime.intent_plan
        and runtime.intent_plan.operation == "ensure_question_type_count"
        and getattr(agent, "key", "") == "question_designer"
    ):
        allowed = ["exercise_apply_question_batch"]
    return json.dumps(exercise_tool_schemas(allowed), ensure_ascii=False)


async def _stream_agent_decision(runtime: ExerciseAgentRuntime, agent_key: str, system: str, prompt: str) -> AgentDecision:
    from app.agent.core.loop import _stream_agent_decision as generic_stream

    return await generic_stream(runtime, agent_key, system, prompt)


def estimate_context_tokens(text: str) -> int:
    from app.agent.context import estimate_tokens

    return estimate_tokens(text)


def _retry_classifier(exc: Exception) -> bool:
    if isinstance(exc, AgentError):
        return exc.retryable
    return False


async def _persist_artifact(runtime: ExerciseAgentRuntime, agent_key: str, decision: AgentDecision, step_index: int) -> str | None:
    """把 completed 决策的 output 持久化为流水线 Artifact。"""
    if decision.completed_artifact_id:
        return decision.completed_artifact_id
    if not decision.completed or decision.output is None:
        return None
    from app.agent.agents.exercise.agents import PRODUCED_BY_KEY

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
