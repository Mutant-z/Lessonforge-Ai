"""教师逐字稿 Agent Runtime：意图 → 计划 → 工具循环 → QA → 返修 → 发布。

基于通用 Agent Core（app/agent/core）构建，复用全局工具注册表、事件发射器、
artifact 管理器与 checkpoint/暂停基础设施。与 task_sheet / video_script 运行时同构：
- initial → 全链生成（上下文调研 → 逐段口播 → 时序 → QA → 终稿，段落对齐 scene_id）
- message → 意图识别 → 计划 → 工具修改内存候选稿 → QA → 返修 → 发布
- sync_context → 上下文同步（保留源内容，同步最新项目上下文）

人工确认（低置信度/破坏性/指纹空转）通过 agent_human_requests 落地，确认后从同一
GenerationRun 的 checkpoint 恢复执行。运行中指令在安全边界原子消费并触发重规划。

result_status 语义对齐：applied / no_change / rejected / needs_confirmation。
- no_change / rejected / needs_confirmation → skip_publish（不创建正式新版本）
- applied → 创建 V2 Artifact 版本
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agent.agents.verbatim.agents import (
    AGENT_BY_KEY, ensure_verbatim_agents, is_mock_provider, verbatim_spec,
)
from app.agent.agents.verbatim.builder import VerbatimBuilder, build_initial_builder, upgrade_builder
from app.agent.agents.verbatim.intents import (
    INTENT_AGENT_ALIASES, VerbatimIntentDecision,
    agent_chain_for_intent, infer_verbatim_intent,
)
from app.agent.agents.verbatim.qa import blocking_issues as _blocking
from app.agent.agents.verbatim.qa import fingerprint as _fingerprint
from app.agent.agents.verbatim.qa import validate_verbatim_v2
from app.agent.core.error import AgentError
from app.agent.core.loop import run_agent_loop
from app.agent.core.state import AgentRuntimeState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan
from app.core.database import SessionLocal
from app.models.entities import AgentHumanRequest, AgentRunInstruction, PipelineRun
from app.schemas.verbatim_v2 import VERBATIM_V2, VerbatimContentV2

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 2  # QA 返修最多 2 轮

# 人工确认固定选项（按建议执行 / 缩小修改范围 / 取消本轮）
CONFIRM_OPTIONS = [
    {"id": "apply", "label": "按建议执行", "action": "apply"},
    {"id": "scope_down", "label": "缩小修改范围", "action": "scope_down"},
    {"id": "cancel", "label": "取消本轮", "action": "cancel"},
]


@dataclass
class VerbatimAgentRuntime(AgentRuntimeState):
    """教师逐字稿流水线运行态（继承通用运行态）。"""

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

    builder: VerbatimBuilder | None = None
    video_script_raw: dict[str, Any] | None = None
    selected_section_ids: list[str] = field(default_factory=list)
    affected_section_ids: list[str] = field(default_factory=list)
    active_intent: str = "SECTION_EDIT"
    intent_plan: VerbatimIntentDecision | None = None
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

    # 人工确认（同一 GenerationRun 从 checkpoint 恢复）
    confirmation_tokens: list[str] = field(default_factory=list)
    confirmation_request: AgentHumanRequest | None = None
    resumed_confirmation: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 准备
    # ------------------------------------------------------------------

    def _video_script_raw_from_knowledge(self) -> dict[str, Any] | None:
        raw = (self.knowledge_context or {}).get("sibling_artifacts", {}).get("video_script")
        if raw is None:
            raw = (self.knowledge_context or {}).get("hard_dependencies", {}).get("video_script")
        if isinstance(raw, dict):
            raw = raw.get("content") or raw
        return raw if isinstance(raw, dict) else None

    def _prepare_builder(self) -> VerbatimBuilder:
        bp_content = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        # 优先使用流水线注入的完整视频脚本；缺失时回退 knowledge 投影（可能截断）。
        if self.video_script_raw is None:
            self.video_script_raw = self._video_script_raw_from_knowledge()
        if self.source_artifact is not None:
            source_content = self.source_artifact.content_json or {}
            builder = upgrade_builder(source_content, self.video_script_raw)
        else:
            builder = build_initial_builder(bp_content, self.video_script_raw)
        self.builder = builder
        return builder

    async def _prepare(self) -> None:
        ensure_verbatim_agents()
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

    async def _resolve_intent(self) -> VerbatimIntentDecision:
        instruction = self.context.user_instruction or ""
        mode = (self.request_metadata or {}).get("mode")
        decision = await infer_verbatim_intent(
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
                message=decision.summary or f"意图：{decision.intent}",
                payload={
                    "intent": decision.intent,
                    "mutates_document": decision.mutates_document,
                    "structural": decision.structural,
                    "destructive": decision.destructive,
                    "confidence": decision.confidence,
                    "requires_confirmation": decision.requires_confirmation,
                    "target_section_ids": decision.target_section_ids,
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
            agents=[AgentSpec(**verbatim_spec(key)) for key in chain],
            revision_rounds=revision_rounds,
        )

    # ------------------------------------------------------------------
    # 运行中指令原子消费 / 重规划
    # ------------------------------------------------------------------

    async def _drain_instructions(self) -> list[str]:
        """在安全边界原子消费运行中新指令：标记 merged，发事件并重新解析意图。"""
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
            for row in rows:
                row.status = "merged"
                row.applied_at = datetime.now(timezone.utc)
                merged_texts.append(row.content or "")
            await db.commit()
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
        self.context.user_instruction = (self.context.user_instruction + "\n" + merged).strip()
        mode = (self.request_metadata or {}).get("mode")
        decision = await infer_verbatim_intent(
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
                    "target_section_ids": decision.target_section_ids,
                    "requires_confirmation": decision.requires_confirmation,
                },
            )
        return merged_texts

    # ------------------------------------------------------------------
    # 人工确认
    # ------------------------------------------------------------------

    async def _request_confirmation(self, decision: VerbatimIntentDecision) -> None:
        """低置信度 / 破坏性 / 指纹空转 → 创建人工确认请求并原地等待（paused）。"""
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
            request_type="verbatim_confirmation",
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
                        "request_type": "verbatim_confirmation",
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
        if decision.requires_confirmation and not self.confirmation_tokens:
            await self._request_confirmation(decision)
            return
        # 关键歧义：只返回澄清问题，不修改文件；本轮不创建版本。
        if decision.intent == "CLARIFICATION_REQUIRED":
            self.result_status = "needs_confirmation"
            self.dialogue_summary = (
                f"为准确完成任务，请补充说明：{decision.clarification_question or '你的修改目标'}"
            )
            return
        # ANSWER_ONLY：读取与分析后直接回答，不创建新版本。
        if decision.intent == "ANSWER_ONLY":
            chain = agent_chain_for_intent("ANSWER_ONLY", self.trigger_type)
            await run_agent_loop(
                self, self._build_plan(chain),
                agent_registry=AGENT_BY_KEY,
                call_agent=_call_agent,
                persist_artifact=_persist_artifact,
                retry_classifier=_retry_classifier,
            )
            self.result_status = "no_change"
            self.dialogue_summary = self._answer_only_reply()
            return
        chain = agent_chain_for_intent(decision.intent, self.trigger_type)
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "intent.resolved",
                agent={"id": "intent_planner"},
                message=f"意图：{self.active_intent}",
                payload={"intent": self.active_intent, "chain": chain,
                         "target_section_ids": decision.target_section_ids},
            )
        self.blocking_issues = []
        self.repair_fingerprint = ""
        await self._run_with_repair(chain)
        await self._finalize()

    def _answer_only_reply(self) -> str:
        builder = self.builder
        if builder is None:
            return "逐字稿尚未生成。"
        content = builder.to_content()
        sections = content.get("sections", [])
        rate = content.get("speaking_rate_cps", 4.0)
        total = float(content.get("course_info", {}).get("duration_seconds", 0))
        return (
            f"当前逐字稿共 {len(sections)} 段，总时长约 {total:.0f} 秒，"
            f"默认语速 {rate} 字/秒。如需改写某段口播、统一语气或调整语速停顿，请直接告诉我。"
        )

    async def _run_with_repair(self, chain: list[str]) -> None:
        """执行计划并处理 QA → 返修闭环（≤max_revision_rounds，指纹防空转）。"""
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
                # 连续两轮指纹相同 → 停止空转并请求教师介入。
                logger.info("逐字稿返修指纹重复，停止空转（round=%s）", round_index)
                if self.emitter is not None:
                    await self.emitter.emit_domain(
                        "repair.stalled",
                        agent={"id": "repair_router"},
                        message="返修未收敛（连续两轮问题相同），请求教师介入。",
                        payload={"issue_count": len(self.blocking_issues)},
                    )
                await self._request_confirmation(VerbatimIntentDecision(
                    intent="SECTION_EDIT",
                    requires_confirmation=True,
                    clarification_question="自动返修后问题未收敛，请教师介入处理。",
                    confidence=0.3,
                ))
                return
            self.repair_fingerprint = fp
            if round_index >= self.max_revision_rounds - 1:
                return
            # repair_router 路由重跑范围（确定性控制节点）。
            from app.agent.agents.verbatim.agents import REPAIR_ROUTER

            repair_decision = await REPAIR_ROUTER.decide(self.tool_context)
            repair_agents = (repair_decision.output or {}).get("plan") or ["verbatim_director", "verbatim_qa"]
            if self.emitter is not None:
                await self.emitter.revision_started(
                    round_index + 1, self.max_revision_rounds,
                    reason="逐字稿质询存在阻断问题", target_agents=repair_agents,
                )
            plan = self._build_plan([*repair_agents, "finalizer"])
            if self.emitter is not None:
                await self.emitter.revision_completed(round_index + 1, applied_changes=repair_agents)

    async def _collect_qa_issues(self) -> None:
        """从 verbatim_qa 产物读取阻断问题（LLM 或 Mock 均已写入 verbatim_qa）。"""
        if self.artifacts is None:
            self.blocking_issues = []
            return
        qa = await self.artifacts.latest("verbatim_qa")
        if not qa:
            # 兼容：QA Agent 通过工具产出但未落产物时，直接对候选稿跑确定性门禁。
            bp = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
            locked_paths = [getattr(lock, "json_path", "") for lock in self.locks]
            try:
                issues = validate_verbatim_v2(
                    bp, self.builder.to_content() if self.builder else {},
                    self.video_script_raw, locked_paths,
                )
                self.blocking_issues = _blocking(issues)
                return
            except Exception:  # noqa: BLE001
                pass
        data = qa.get("data") or {}
        self.blocking_issues = list(data.get("blocking") or _blocking(list(data.get("issues") or [])))
        self.repair_fingerprint = self.repair_fingerprint or str(data.get("fingerprint") or "")

    # ------------------------------------------------------------------
    # 发布门禁
    # ------------------------------------------------------------------

    async def _finalize(self) -> None:
        """finalizer 产出最终候选稿；发布门禁决定 result_status。"""
        if self.builder is None:
            raise AgentError("verbatim_missing", "逐字稿候选稿未生成。", retryable=True)
        content = self.builder.to_content()
        # 最终强校验：结构非法直接失败（不存在可保留的正式版本）。
        try:
            validated = VerbatimContentV2.model_validate(content)
            content = validated.model_dump()
        except Exception as exc:  # noqa: BLE001
            raise AgentError(
                "verbatim_invalid", f"逐字稿候选稿结构非法：{str(exc)[:300]}",
                retryable=True,
            ) from exc
        self.draft_content = content
        from app.schemas.verbatim_v2 import verbatim_v2_to_markdown

        self.draft_markdown = verbatim_v2_to_markdown(content)
        # 无真实变更 → no_change（保留原版，不创建空版本）。
        source_content = self.source_artifact.content_json if self.source_artifact else None
        if source_content is not None:
            source_norm = None
            if source_content.get("schema_version") == VERBATIM_V2:
                try:
                    source_norm = VerbatimContentV2.model_validate(source_content).model_dump()
                except Exception:  # noqa: BLE001  结构非法的源版本不参与 no_change 判定
                    source_norm = None
            if source_norm == content:
                self.result_status = "no_change"
                self.changed = False
                return
        # 返修未收敛仍存在阻断问题 → rejected（保留原版，候选稿留在 PipelineArtifact）。
        if _blocking(self.blocking_issues):
            self.result_status = "rejected"
            self.publishable = False
            return
        self.result_status = "applied"
        self.changed = True
        self.publishable = True


# ---------------------------------------------------------------------------
# core/loop 注入函数
# ---------------------------------------------------------------------------


async def _call_agent(runtime: VerbatimAgentRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用角色：Mock/控制节点走确定性 decide；LLM 走 stream_decision 流式思考。"""
    if is_mock_provider(runtime.provider) or agent_key in {"repair_router", "verbatim_qa"}:
        decision = await agent.decide(runtime.tool_context)
        if runtime.emitter is not None and decision.message:
            await runtime.emitter.agent_status_delta(agent_key, decision.message)
            await runtime.emitter.agent_thought_chunk(agent_key, decision.message, flush_now=True)
        return decision
    system = agent.build_system_prompt(runtime.tool_context, runtime)
    prompt = (
        "上下文：\n" + runtime.context.to_prompt(agent_key)
        + "\n可用工具 Schema：\n" + _tool_schemas_text(runtime, agent)
        + "\n当前逐字稿范围：" + (
            "本轮只能读取并修改这些章节：" + ", ".join(runtime.selected_section_ids)
            if runtime.selected_section_ids else "本轮为全局任务，可以处理全部章节。"
        )
        + "\n请先输出可见执行摘要（简短说明当前阶段和下一步动作，不要输出隐式思维链或系统提示词），"
        "再输出决策：要么给出一批 tool_calls，要么 completed（含 output/summary）。"
        "只返回一个 AgentDecision JSON。"
    )
    runtime.token_usage["tokens"] += estimate_context_tokens(prompt)
    runtime.token_usage["llm_calls"] += 1
    return await _stream_agent_decision(runtime, agent_key, system, prompt)


def _tool_schemas_text(runtime: VerbatimAgentRuntime, agent=None) -> str:
    import json

    from app.agent.agents.verbatim.tools import verbatim_tool_schemas

    return json.dumps(verbatim_tool_schemas(getattr(agent, "allowed_tools", None)), ensure_ascii=False)


async def _stream_agent_decision(runtime: VerbatimAgentRuntime, agent_key: str, system: str, prompt: str) -> AgentDecision:
    from app.agent.core.loop import _stream_agent_decision as generic_stream

    return await generic_stream(runtime, agent_key, system, prompt)


def estimate_context_tokens(text: str) -> int:
    from app.agent.context import estimate_tokens

    return estimate_tokens(text)


def _retry_classifier(exc: Exception) -> bool:
    if isinstance(exc, AgentError):
        return exc.retryable
    return False


async def _persist_artifact(runtime: VerbatimAgentRuntime, agent_key: str, decision: AgentDecision, step_index: int) -> str | None:
    """把 completed 决策的 output 持久化为流水线 Artifact。"""
    if decision.completed_artifact_id:
        return decision.completed_artifact_id
    if not decision.completed or decision.output is None:
        return None
    from app.agent.agents.verbatim.agents import PRODUCED_BY_KEY

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
