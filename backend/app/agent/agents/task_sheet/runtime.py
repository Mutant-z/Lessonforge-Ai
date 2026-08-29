"""学习任务单 Agent Runtime（方案 §2）：意图 → 计划 → 工具循环 → QA → 返修 → 发布。

基于通用 Agent Core（app/agent/core）构建，复用全局工具注册表、事件发射器、
artifact 管理器与 checkpoint/暂停基础设施。与 lesson_plan 运行时同构但独立：

- 意图协议为强类型 TaskSheetIntentDecision（新枚举 + target_task_ids/target_phases）。
- 角色为 7 个：intent_planner / context_researcher / task_architect / task_designer /
  task_sheet_qa / repair_router / finalizer；每角色最多 6 次工具决策（core/loop 预算）。
- 运行中指令在安全边界原子消费并触发重规划（run.instruction.merged + plan.revised）。
- 人工确认（低置信度/破坏性/指纹空转）通过 agent_human_requests 落地，
  确认后从同一 GenerationRun 的 checkpoint 恢复执行。

result_status 语义与 PPT/lesson_plan 对齐：applied / no_change / rejected / needs_confirmation。
- no_change / rejected / needs_confirmation → skip_publish（不创建正式新版本）
- applied → 创建 V3 Artifact 版本
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agent.agents.task_sheet.agents import (
    AGENT_BY_KEY, ensure_task_sheet_agents, is_mock_provider, task_sheet_spec,
)
from app.agent.agents.task_sheet.builder import TaskSheetBuilder, build_initial_builder, upgrade_builder
from app.agent.agents.task_sheet.intents import (
    INTENT_AGENT_ALIASES, TaskSheetIntentDecision,
    agent_chain_for_intent, infer_task_sheet_intent,
)
from app.agent.agents.task_sheet.qa import blocking_issues as _blocking
from app.agent.agents.task_sheet.qa import fingerprint as _fingerprint
from app.agent.core.error import AgentError
from app.agent.core.gates import gates_active
from app.agent.core.loop import run_agent_loop
from app.agent.core.state import AgentRuntimeState
from app.agent.pipeline import PipelinePaused
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan, ToolCall
from app.core.database import SessionLocal
from app.models.entities import AgentHumanRequest, AgentRunInstruction, PipelineRun
from app.schemas.task_sheet import TASK_SHEET_V3, TaskSheetContentV3
from app.services.chat_attachment_service import apply_runtime_attachments

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 3  # 方案 §1：最多 3 轮 QA 返修

# 人工确认固定选项（方案 §3.3：按建议执行 / 缩小修改范围 / 取消本轮）
CONFIRM_OPTIONS = [
    {"id": "apply", "label": "按建议执行", "action": "apply"},
    {"id": "scope_down", "label": "缩小修改范围", "action": "scope_down"},
    {"id": "cancel", "label": "取消本轮", "action": "cancel"},
]


@dataclass
class TaskSheetAgentRuntime(AgentRuntimeState):
    """学习任务单流水线运行态（继承通用运行态）。"""

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

    builder: TaskSheetBuilder | None = None
    selected_section_ids: list[str] = field(default_factory=list)
    affected_section_ids: list[str] = field(default_factory=list)
    active_intent: str = "TASK_EDIT"
    intent_plan: TaskSheetIntentDecision | None = None
    content_policy: str = "preserve"
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    repair_fingerprint: str = ""
    repair_round: int = 0
    max_revision_rounds: int = MAX_REVISION_ROUNDS
    #: 深度 LLM 化：QA 教学质询与返修轮次每轮都会调用模型，不限累计/单次 token
    #: 估算预算（与 lesson_plan 全节点 LLM 化对齐；core/loop 对 0 表示不限制）。
    max_estimated_tokens: int = 0
    max_context_tokens: int = 0
    #: 组装类节点（finalizer）每轮最多一次 LLM 深度分析的缓存：同一节点请求过
    #: 只读工具后，下一轮直接确定性产出 + 附加已缓存分析（省 token、防空转）。
    _analysis_cache: dict[str, Any] = field(default_factory=dict)
    publishable: bool = False
    draft_content: dict[str, Any] = field(default_factory=dict)
    draft_markdown: str = ""
    request_metadata: dict[str, Any] = field(default_factory=dict)
    handoff_aliases: dict[str, str] = field(default_factory=lambda: INTENT_AGENT_ALIASES)
    changed: bool = False

    # 人工确认（方案 §3.3：同一 GenerationRun 从 checkpoint 恢复）
    confirmation_tokens: list[str] = field(default_factory=list)
    confirmation_request: AgentHumanRequest | None = None
    resumed_confirmation: dict[str, Any] = field(default_factory=dict)
    # 工具在候选稿上命中高风险守卫时，保存精确调用；教师确认后可以从
    # 同一候选稿和同一工具参数继续，而不是让模型重新猜一遍完整对象。
    pending_tool_confirmation: dict[str, Any] = field(default_factory=dict)
    confirmation_replay_used: bool = False

    # 协议统计（方案 §3.1：PipelineRun 记录实际使用的协议）
    tool_protocol: str = "structured"   # native | structured
    tool_call_count: int = 0
    protocol_fallbacks: int = 0

    # ------------------------------------------------------------------
    # 准备
    # ------------------------------------------------------------------

    def checkpoint_payload(self) -> dict[str, Any]:
        """保存可恢复的候选稿与工具上下文，避免暂停后从正式版本重建。"""
        payload: dict[str, Any] = {
            "context_snapshot": self.context.snapshot(),
            "active_intent": self.active_intent,
            "selected_section_ids": list(self.selected_section_ids),
            "source_artifact_id": getattr(self.source_artifact, "id", None),
            "source_version": getattr(self.source_artifact, "version", None),
            "base_artifact_id": getattr(self.source_artifact, "id", None),
            "base_version": getattr(self.source_artifact, "version", None),
        }
        if self.builder is not None:
            payload["draft_snapshot"] = self.builder.to_content()
            payload["draft_revision"] = self.builder.revision
        # 始终写入该键，确认恢复后清空时可以覆盖旧 checkpoint 中的调用记录。
        payload["pending_tool_confirmation"] = copy.deepcopy(self.pending_tool_confirmation)
        return payload

    def _prepare_builder(self) -> TaskSheetBuilder:
        checkpoint = (self.pipeline_run.checkpoint_json or {}) if self.pipeline_run is not None else {}
        draft_snapshot = checkpoint.get("draft_snapshot")
        checkpoint_source_id = checkpoint.get("base_artifact_id")
        checkpoint_source_version = checkpoint.get("base_version")
        current_source_id = getattr(self.source_artifact, "id", None)
        current_source_version = getattr(self.source_artifact, "version", None)
        can_restore_draft = (
            isinstance(draft_snapshot, dict)
            and draft_snapshot.get("schema_version") == TASK_SHEET_V3
            and checkpoint_source_id == current_source_id
            and checkpoint_source_version == current_source_version
        )
        if can_restore_draft:
            builder = TaskSheetBuilder(draft_snapshot)
            builder._revision = int(checkpoint.get("draft_revision") or 0)
            self.builder = builder
            return builder
        bp_content = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        lesson_plan_raw = (self.knowledge_context or {}).get("sibling_artifacts", {}).get("lesson_plan")
        if lesson_plan_raw is None:
            lesson_plan_raw = (self.knowledge_context or {}).get("hard_dependencies", {}).get("lesson_plan")
        if isinstance(lesson_plan_raw, dict):
            lesson_plan_raw = lesson_plan_raw.get("content") or lesson_plan_raw
        if self.source_artifact is not None:
            source_content = self.source_artifact.content_json or {}
            builder = upgrade_builder(source_content, bp_content, lesson_plan_raw)
        else:
            builder = build_initial_builder(bp_content, lesson_plan_raw)
        self.builder = builder
        return builder

    async def _prepare(self) -> None:
        ensure_task_sheet_agents()
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
        await self._restore_confirmation_state()

    async def _restore_confirmation_state(self) -> None:
        """从 checkpoint 恢复人工确认令牌与确认信息（同一 GenerationRun 恢复）。"""
        if self.pipeline_run is None:
            return
        checkpoint = self.pipeline_run.checkpoint_json or {}
        context_snapshot = checkpoint.get("context_snapshot")
        if isinstance(context_snapshot, dict):
            self.context.restore(context_snapshot)
        pending = checkpoint.get("pending_confirmation") or {}
        pending_tool = checkpoint.get("pending_tool_confirmation")
        if isinstance(pending_tool, dict):
            self.pending_tool_confirmation = copy.deepcopy(pending_tool)
        if pending.get("token"):
            self.confirmation_tokens = [str(pending["token"])]
            self.resumed_confirmation = dict(pending)
        checkpoint_intent = checkpoint.get("active_intent")
        if checkpoint_intent:
            self.active_intent = str(checkpoint_intent)
        selected = checkpoint.get("selected_section_ids")
        if not self.selected_section_ids and isinstance(selected, list):
            self.selected_section_ids = [str(item) for item in selected if str(item)]

    # ------------------------------------------------------------------
    # 意图与计划
    # ------------------------------------------------------------------

    async def _resolve_intent(self) -> TaskSheetIntentDecision:
        instruction = self.context.user_instruction or ""
        mode = (self.request_metadata or {}).get("mode")
        decision = await infer_task_sheet_intent(
            self.provider, self.trigger_type, instruction,
            self.selected_section_ids or None, mode,
        )
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
                    "target_task_ids": decision.target_task_ids,
                    "target_phases": decision.target_phases,
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

    def _build_plan(self, chain: list[str], revision_rounds: int = MAX_REVISION_ROUNDS) -> PipelinePlan:
        return PipelinePlan(
            agents=[AgentSpec(**task_sheet_spec(key)) for key in chain],
            revision_rounds=revision_rounds,
        )

    # ------------------------------------------------------------------
    # 运行中指令原子消费 / 合并 / 重规划（方案 §3.2）
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
        # 合并到当前目标后重新执行意图识别（方案 §3.2：从当前候选稿生成剩余计划）
        self.context.user_instruction = (self.context.user_instruction + "\n" + merged).strip()
        mode = (self.request_metadata or {}).get("mode")
        decision = await infer_task_sheet_intent(
            self.provider, "message", self.context.user_instruction,
            self.selected_section_ids or None, mode,
        )
        self.intent_plan = decision
        self.active_intent = decision.intent
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "plan.revised",
                agent={"id": "intent_planner"},
                message=f"已根据新指令重新规划：{decision.intent}",
                payload={
                    "intent": decision.intent,
                    "target_task_ids": decision.target_task_ids,
                    "target_phases": decision.target_phases,
                    "requires_confirmation": decision.requires_confirmation,
                },
            )
        return merged_texts

    # ------------------------------------------------------------------
    # 人工确认
    # ------------------------------------------------------------------

    async def _request_confirmation(self, decision: TaskSheetIntentDecision) -> None:
        """低置信度 / 破坏性 / 指纹空转 → 创建人工确认请求并原地等待（paused）。"""
        existing_request: AgentHumanRequest | None = None
        if self.pipeline_run is not None:
            async with SessionLocal() as db:
                existing_request = await db.scalar(select(AgentHumanRequest).where(
                    AgentHumanRequest.pipeline_run_id == self.pipeline_run.id,
                    AgentHumanRequest.request_type == "task_sheet_confirmation",
                    AgentHumanRequest.status == "pending",
                ).order_by(AgentHumanRequest.created_at.desc()))
        if self.emitter is not None and existing_request is None:
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
        request = existing_request or AgentHumanRequest(
            pipeline_run_id=self.pipeline_run.id,
            request_type="task_sheet_confirmation",
            prompt=decision.clarification_question or "请确认本次修改的执行范围。",
            options_json=CONFIRM_OPTIONS,
            status="pending",
        )
        async with SessionLocal() as db:
            if existing_request is None:
                db.add(request)
                await db.flush()
            request_id = request.id
            row = await db.get(PipelineRun, self.pipeline_run.id)
            if row:
                row.status = "paused"
                pending_confirmation = {
                    **((row.checkpoint_json or {}).get("pending_confirmation") or {}),
                    "request_id": request_id,
                    "request_type": "task_sheet_confirmation",
                    "intent": decision.intent,
                    "requires_confirmation": True,
                }
                row.checkpoint_json = {
                    **(row.checkpoint_json or {}),
                    **self.checkpoint_payload(),
                    "pending_confirmation": pending_confirmation,
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

    async def handle_tool_failure(self, agent_key: str, call: ToolCall, result: Any) -> None:
        """把高风险工具拒绝转换成一次可恢复的教师确认，而不是工具空转。"""
        if getattr(result, "error_code", None) != "confirmation_required":
            return
        self.pending_tool_confirmation = {
            "agent_key": agent_key,
            "tool_name": call.tool_name,
            "input": copy.deepcopy(call.input),
        }
        intent = self.active_intent if self.active_intent in {
            "TASK_EDIT", "STRUCTURE_EDIT", "TIMING_ADJUST", "ALIGNMENT_REPAIR",
            "SCAFFOLD_EDIT", "RECORDING_EDIT", "SYNC_CONTEXT",
        } else "TASK_EDIT"
        question = (
            f"{result.error or '本次修改涉及高风险目标或结构变更。'}\n"
            "请确认是否按当前建议继续执行；如需缩小范围，请选择“缩小修改范围”。"
        )
        await self._request_confirmation(TaskSheetIntentDecision(
            intent=intent, destructive=True, confidence=1.0,
            requires_confirmation=True, clarification_question=question,
            assumptions=["工具检测到目标解绑或其他高风险变更"],
            plan_steps=["等待教师确认", "恢复候选稿并继续执行被拦截的工具调用"],
            acceptance_criteria=["高风险工具调用已获得教师确认"],
        ))
        raise PipelinePaused()

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

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await self._prepare()
        if self.emitter is not None:
            await self.emitter.pipeline_started(self.trigger_type)
        if self.resumed_confirmation:
            await self._mark_confirmation_resolved()
        decision = await self._resolve_intent()
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
        chain = agent_chain_for_intent(decision.intent, self.trigger_type)
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "intent.resolved",
                agent={"id": "intent_planner"},
                message=f"意图：{self.active_intent}",
                payload={"intent": self.active_intent, "chain": chain,
                         "target_task_ids": decision.target_task_ids,
                         "target_phases": decision.target_phases},
            )
        self.blocking_issues = []
        self.repair_fingerprint = ""
        await self._run_with_repair(chain)
        await self._finalize()

    async def _run_with_repair(self, chain: list[str]) -> None:
        """执行计划并处理 QA → 返修闭环（≤3 轮，指纹防空转）。"""
        plan = self._build_plan(chain)
        for round_index in range(self.max_revision_rounds + 1):
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
                # 连续两轮指纹相同 → 停止空转并请求教师介入（方案 §1）。
                logger.info("任务单返修指纹重复，停止空转（round=%s）", round_index)
                if self.emitter is not None:
                    await self.emitter.emit_domain(
                        "repair.stalled",
                        agent={"id": "repair_router"},
                        message="返修未收敛（连续两轮问题相同），请求教师介入。",
                        payload={"issue_count": len(self.blocking_issues)},
                    )
                await self._request_confirmation(TaskSheetIntentDecision(
                    intent="TASK_EDIT",
                    requires_confirmation=True,
                    clarification_question="自动返修三轮后问题未收敛，请教师介入处理。",
                    confidence=0.3,
                ))
                return
            self.repair_fingerprint = fp
            if round_index >= self.max_revision_rounds - 1:
                return
            # repair_router 路由重跑范围（确定性控制节点）。
            from app.agent.agents.task_sheet.agents import REPAIR_ROUTER

            repair_decision = await REPAIR_ROUTER.decide(self.tool_context)
            repair_agents = (repair_decision.output or {}).get("plan") or ["task_designer", "task_sheet_qa"]
            if self.emitter is not None:
                await self.emitter.revision_started(
                    round_index + 1, self.max_revision_rounds,
                    reason="任务单质询存在阻断问题", target_agents=repair_agents,
                )
            plan = self._build_plan([*repair_agents, "finalizer"])
            if self.emitter is not None:
                await self.emitter.revision_completed(round_index + 1, applied_changes=repair_agents)

    async def _collect_qa_issues(self) -> None:
        """教学质询门禁已移除：QA 角色不再运行，阻断问题恒为空。

        保留方法签名与调用点（_run_with_repair 第一轮后 _blocking([]) 为空，
        返修闭环自动退出）。结构安全校验仍由 _finalize 的
        TaskSheetContentV3.model_validate 承担。
        """
        self.blocking_issues = []
        self.repair_fingerprint = ""

    # ------------------------------------------------------------------
    # 发布门禁（方案 §2.3：Schema / 确定性规则 / LLM QA / 锁定检查全通过才发布）
    # ------------------------------------------------------------------

    async def _finalize(self) -> None:
        if self.builder is None:
            raise AgentError("task_sheet_missing", "任务单候选稿未生成。", retryable=True)
        # QA_ONLY：仅质量检查/回答，不创建新版本（方案 §2.1）。
        if self.active_intent == "QA_ONLY":
            self.result_status = "no_change"
            self.changed = False
            self.publishable = False
            return
        content = self.builder.to_content()
        try:
            validated = TaskSheetContentV3.model_validate(content)
            content = validated.model_dump()
        except Exception as exc:  # noqa: BLE001
            raise AgentError(
                "task_sheet_invalid", f"任务单候选稿结构非法：{str(exc)[:300]}",
                retryable=True,
            ) from exc
        self.draft_content = content
        from app.schemas.task_sheet import task_sheet_v3_to_markdown

        self.draft_markdown = task_sheet_v3_to_markdown(content)
        # 无真实变更 → no_change（保留原版，不创建空版本）。
        source_content = self.source_artifact.content_json if self.source_artifact else None
        if source_content is not None:
            source_norm = None
            if source_content.get("schema_version") == TASK_SHEET_V3:
                try:
                    source_norm = TaskSheetContentV3.model_validate(source_content).model_dump()
                except Exception:  # noqa: BLE001  结构非法的源版本不参与 no_change 判定
                    source_norm = None
            if source_norm == content:
                self.result_status = "no_change"
                self.changed = False
                return
        # 结构安全校验：候选稿结构非法时保留原版（防损坏文档的底线）。
        # 教学质询门禁已移除，不再有 blocked/rejected 分支，结构合法即发布。
        self.result_status = "applied"
        self.changed = True
        self.publishable = True


# ---------------------------------------------------------------------------
# core/loop 注入函数
# ---------------------------------------------------------------------------


async def _call_agent(runtime: TaskSheetAgentRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用角色：Mock/控制节点走确定性 decide；LLM 走原生 tool calling，
    不可用时回退流式结构化决策（方案 §3.1）。

    每次决策前先原子消费运行中新指令（安全边界，方案 §3.2）。
    """
    await runtime._drain_instructions()
    replay = runtime.pending_tool_confirmation
    if (
        replay
        and runtime.resumed_confirmation.get("choice") == "apply"
        and runtime.confirmation_tokens
        and not runtime.confirmation_replay_used
        and replay.get("agent_key") == agent_key
    ):
        runtime.confirmation_replay_used = True
        replay_input = copy.deepcopy(replay.get("input") or {})
        replay_input["confirmation_token"] = runtime.confirmation_tokens[0]
        runtime.pending_tool_confirmation = {}
        return AgentDecision(
            tool_calls=[ToolCall(tool_name=str(replay.get("tool_name") or ""), input=replay_input)],
            message="已获得教师确认，继续执行刚才被拦截的修改。",
        )
    # The initial builder is already a complete blueprint-derived V3 document.
    # Running it through edit tools made the model try to add the same chapters
    # again and incorrectly hit the destructive-edit confirmation gate.  LLM
    # tool loops are for later teacher edits; initialization uses the safe,
    # deterministic Agent decisions and still runs the normal QA/finalizer path.
    if (
        (
            getattr(runtime.generation_run, "trigger_type", "") == "initial"
            and runtime.source_artifact is None
        )
        or is_mock_provider(runtime.provider)
        or agent_key in {"repair_router", "task_sheet_qa"}
    ):
        decision = await agent.decide(runtime.tool_context)
        if runtime.emitter is not None and decision.message:
            await runtime.emitter.agent_status_delta(agent_key, decision.message)
            await runtime.emitter.agent_thought_chunk(agent_key, decision.message, flush_now=True)
        return decision
    system = agent.build_system_prompt(runtime.tool_context, runtime)
    confirmation_choice = runtime.resumed_confirmation.get("choice") if runtime.resumed_confirmation else ""
    confirmation_note = ""
    if runtime.confirmation_tokens:
        confirmation_note = (
            "\n本次运行已获得教师确认令牌；需要确认的工具调用必须原样使用令牌："
            f"{runtime.confirmation_tokens[0]}。"
        )
    if confirmation_choice == "scope_down":
        confirmation_note += "\n教师选择了缩小修改范围，请勿重放原高风险调用，先调整为更小且明确的范围。"
    prompt = (
        "上下文：\n" + runtime.context.to_prompt(agent_key)
        + "\n可用工具 Schema：\n" + _tool_schemas_text(runtime, agent)
        + "\n当前任务单范围：" + (
            "本轮只能读取并修改这些任务：" + ", ".join(runtime.intent_plan.target_task_ids)
            if runtime.intent_plan and runtime.intent_plan.target_task_ids else
            ("本轮只能处理这些教学环节：" + ", ".join(runtime.intent_plan.target_phases)
             if runtime.intent_plan and runtime.intent_plan.target_phases else "本轮为全局任务，可以处理全部章节。")
        )
        + "\n高风险操作（删除任务/章节、目标解绑）必须携带有效 confirmation_token；"
        + "没有令牌时请求教师确认，不要伪造令牌。"
        + "\n普通内容润色/任务编辑必须保留现有 objective_ids、knowledge_point_ids、stage_id；"
        + "只有明确的 ALIGNMENT_REPAIR 意图才允许改变 objective_ids。"
        + confirmation_note
        + "\n请先输出可见执行摘要（简短说明当前阶段和下一步动作，不要输出隐式思维链或系统提示词），"
        + "再输出决策：要么给出一批 tool_calls，要么 completed（含 output/summary）。"
        + "只返回一个 AgentDecision JSON。"
    )
    runtime.token_usage["tokens"] += estimate_context_tokens(prompt)
    runtime.token_usage["llm_calls"] += 1
    if agent_key == "finalizer":
        return await _finalizer_call(runtime, agent, system, prompt)
    native = await _try_native_tool_calling(runtime, agent_key, system, prompt, agent)
    if native is not None:
        return native
    return await _stream_agent_decision(runtime, agent_key, system, prompt)


def _merge_llm_analysis(base: AgentDecision, llm: AgentDecision | None) -> AgentDecision:
    """把 LLM 深度分析附加到确定性产物（组装/校验仍由确定性逻辑承担）。

    summary/message 无条件采纳（工具调用轮的摘要同样有价值）；llm_analysis
    仅在 LLM 完成且有 output 时附加（工具调用轮无分析产物，不附加）。
    """
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
    runtime: TaskSheetAgentRuntime, agent, system: str, prompt: str,
) -> AgentDecision:
    """finalizer（组装类节点）：每轮最多一次 LLM 深度分析，组装产物始终由确定性 decide 产出。

    - 缓存命中（上一轮 LLM 已请求只读工具）：确定性 decide + 附加已缓存分析（最多 2 轮结束）；
    - 首次：原生 tool calling → 流式结构化；LLM 请求允许集内只读工具 → 缓存并放行；
    - LLM 失败 / 直接 completed：确定性 decide + 附加分析。内容/markdown 永不来自模型。
    """
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
            from app.agent.agents.task_sheet.agents import FINALIZER_TOOLS

            allowed = set(FINALIZER_TOOLS)
            permitted = [call for call in llm_decision.tool_calls if call.tool_name in allowed]
            if permitted:
                runtime._analysis_cache["finalizer"] = llm_decision
                llm_decision.tool_calls = permitted
                return llm_decision
        return await agent.decide(runtime.tool_context)
    return _merge_llm_analysis(await agent.decide(runtime.tool_context), llm_decision)


async def _try_native_tool_calling(
    runtime: TaskSheetAgentRuntime, agent_key: str, system: str, prompt: str, agent,
) -> AgentDecision | None:
    """尝试原生 tool calling；协议不可用/错误时发 fallback 事件并返回 None。"""
    provider = getattr(runtime, "provider", None)
    native_method = getattr(provider, "native_agent_decision", None)
    if not native_method or not getattr(provider, "supports_native_tools", False):
        return None
    from app.agent.agents.task_sheet.tools import task_sheet_tool_schemas

    try:
        decision = await native_method(
            system, prompt,
            task_sheet_tool_schemas(getattr(agent, "allowed_tools", None)),
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


def _tool_schemas_text(runtime: TaskSheetAgentRuntime, agent=None) -> str:
    import json

    from app.agent.agents.task_sheet.tools import task_sheet_tool_schemas

    return json.dumps(task_sheet_tool_schemas(getattr(agent, "allowed_tools", None)), ensure_ascii=False)


async def _stream_agent_decision(runtime: TaskSheetAgentRuntime, agent_key: str, system: str, prompt: str) -> AgentDecision:
    from app.agent.core.loop import _stream_agent_decision as generic_stream

    return await generic_stream(runtime, agent_key, system, prompt)


def estimate_context_tokens(text: str) -> int:
    from app.agent.context import estimate_tokens

    return estimate_tokens(text)


def _retry_classifier(exc: Exception) -> bool:
    if isinstance(exc, AgentError):
        return exc.retryable
    return False


async def _persist_artifact(runtime: TaskSheetAgentRuntime, agent_key: str, decision: AgentDecision, step_index: int) -> str | None:
    """把 completed 决策的 output 持久化为流水线 Artifact。"""
    if decision.completed_artifact_id:
        return decision.completed_artifact_id
    if not decision.completed or decision.output is None:
        return None
    from app.agent.agents.task_sheet.agents import PRODUCED_BY_KEY

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
