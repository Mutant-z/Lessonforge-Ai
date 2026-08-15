"""教学设计 Agent Runtime：意图 → 计划 → 工具循环 → QA → 返修 → 发布。

基于通用 Agent Core（app/agent/core）构建，复用全局工具注册表、事件发射器、
artifact 管理器与 checkpoint/暂停基础设施。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agent.agents.lesson_plan.agents import (
    AGENT_BY_KEY, FINALIZER, INTENT_PLANNER, PEDAGOGY_QA, REPAIR_ROUTER,
    ensure_lesson_plan_agents, is_mock_provider, lesson_plan_spec,
)
from app.agent.agents.lesson_plan.builder import (
    LessonPlanBuilder, build_initial_builder, upgrade_builder,
)
from app.agent.agents.lesson_plan.diff import diff_lesson_plans, distinct_top_level_fact_sections
from app.agent.agents.lesson_plan.formatting import strip_hardcoded_ordinals
from app.agent.agents.lesson_plan.intents import (
    INTENT_AGENT_ALIASES, LessonPlanIntentDecision, agent_chain_for_intent,
    infer_lesson_plan_intent,
)
from app.agent.agents.lesson_plan.qa import blocking_issues as _blocking
from app.agent.agents.lesson_plan.qa import (
    build_lesson_plan_verification_report,
    fingerprint as _fingerprint,
)
from app.agent.agents.lesson_plan.section_refs import (
    build_section_index,
    canonicalize_section_ids,
)
from app.agent.agents.lesson_plan.tools._common import MutationPolicy
from app.agent.core.error import AgentError
from app.agent.core.loop import run_agent_loop
from app.agent.core.state import AgentRuntimeState
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.lesson_plan import LessonPlanContentV2

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 3

#: 致命工具错误码：出现即终止当前修改链（rejected），不再空转重试。
#: 注意：source_view_forbidden 属于只读投影越权，工具没有修改 Builder，
#: 后续角色仍可完成产物，因此保持非致命（见 _NON_BLOCKING_READ_FAILURE_CODES）。
FATAL_TOOL_ERROR_CODES = frozenset({
    "invalid_section_id",
    "section_scope_violation",
    "tool_not_allowed",
    "structure_modification_forbidden",
    "core_field_unauthorized",
    "mutation_contract_error",
    "outline_replace_forbidden",
    "artifact_locked",
    "locked_path_conflict",
    "section_not_found",
    "section_already_exists",
})

# 这些失败表示模型请求了不适用于当前角色的只读投影。请求没有修改 Builder，
# 且后续角色仍可依靠已注入的角色上下文生成必需产物，因此不能把已经通过
# Schema、教学 QA 与意图门禁的候选稿误判为不可发布。错误仍保留在遥测中。
_NON_BLOCKING_READ_FAILURE_CODES = frozenset({"source_view_forbidden"})


@dataclass
class LessonPlanAgentRuntime(AgentRuntimeState):
    """教学设计流水线运行态（继承通用运行态）。"""

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

    builder: LessonPlanBuilder | None = None
    #: 用户原始请求范围（未规范化），与执行范围分离，绝不混用。
    requested_section_ids: list[str] = field(default_factory=list)
    #: 规范化后的执行范围（别名已在入口转换，见 section_refs.py）。
    selected_section_ids: list[str] = field(default_factory=list)
    affected_section_ids: list[str] = field(default_factory=list)
    #: 执行链前生成的不可变上下文快照（所有 Agent 共享同一快照）。
    context_snapshot: Any = None
    #: 致命工具错误（不可重试）：记录后整轮终止，rejected 发布。
    fatal_tool_error: dict[str, Any] | None = None
    active_intent: str = "GENERATE"
    resolved_intent: LessonPlanIntentDecision | None = None
    #: 统一任务规格（任何 Agent 启动前生成，后续 Agent 不得重新解释任务）。
    task_spec: Any = None
    #: 统一证据包（只读工具结果自动写入，下一轮不需要重新读取）。
    evidence_bundle: Any = None
    #: 统一验证报告（pedagogy_qa / 工具校验 / finalizer 消费同一份报告）。
    verification_report: dict[str, Any] = field(default_factory=dict)
    #: 是否已消费 QA 轮产出的统一验证报告（finalize 优先复用，避免覆盖手动注入）。
    _qa_report_ready: bool = False
    #: 写操作 MutationReceipt 记录（核心状态机事件来源）。
    mutation_receipts: list[Any] = field(default_factory=list)
    #: 全节点 LLM 化：单次运行会多次调用模型（意图 + 分析节点 + 内容节点），
    #: 去掉累计/单次 token 硬限额（0 = 不限制），避免“润色一次就爆 60000 token”。
    max_estimated_tokens: int = 0
    max_context_tokens: int = 0
    #: 分析节点 LLM 深度分析缓存（每节点最多一次深度分析；工具执行后不再二次调用）。
    _analysis_cache: dict[str, Any] = field(default_factory=dict)
    content_policy: str = "preserve"
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    repair_fingerprint: str = ""
    repair_round: int = 0
    max_revision_rounds: int = MAX_REVISION_ROUNDS
    publishable: bool = False
    draft_content: dict[str, Any] = field(default_factory=dict)
    draft_markdown: str = ""
    draft_answer: dict[str, Any] = field(default_factory=dict)
    baseline_content: dict[str, Any] = field(default_factory=dict)
    diff_summary: dict[str, Any] = field(default_factory=dict)
    intent_gate: dict[str, Any] = field(default_factory=dict)
    request_metadata: dict[str, Any] = field(default_factory=dict)
    handoff_aliases: dict[str, str] = field(default_factory=lambda: INTENT_AGENT_ALIASES)
    changed: bool = False
    executed_chain: list[str] = field(default_factory=list)
    mutation_policy: MutationPolicy | None = None
    #: 致命工具错误立即终止（覆盖通用基类空集，仅教学设计流水线生效）。
    fatal_tool_error_codes: frozenset[str] = FATAL_TOOL_ERROR_CODES

    # ------------------------------------------------------------------
    # 准备
    # ------------------------------------------------------------------

    def _prepare_builder(self) -> LessonPlanBuilder:
        bp_content = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        if self.source_artifact is not None:
            source_content = self.source_artifact.content_json or {}
            builder = upgrade_builder(source_content, bp_content)
        else:
            builder = build_initial_builder(bp_content)
        self.builder = builder
        return builder

    async def _prepare(self) -> None:
        ensure_lesson_plan_agents()
        # 幂等：重复调用（run() 内再次 _prepare）不重建 builder，避免工具
        # 修改的实例与最终读取的实例分裂。
        if self.builder is None:
            self.builder = self._prepare_builder()
        builder = self.builder
        if not self.baseline_content:
            self.baseline_content = builder.to_content()
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

    # ------------------------------------------------------------------
    # 意图与计划
    # ------------------------------------------------------------------

    async def _resolve_intent(self) -> LessonPlanIntentDecision:
        instruction = self.context.user_instruction or ""
        mode = (self.request_metadata or {}).get("mode")
        # 意图识别结合当前工作区内容：把当前教学设计大纲、项目材料与兄弟产物
        # 注入意图提取，先粗提取用户要修改哪个部分，再对目标部分做精确定位。
        # （粗提取 → 章节接地 → 只修改目标部分，其他部分保持不变。）
        content = self.builder.to_content() if self.builder else None
        decision = await infer_lesson_plan_intent(
            self.provider, self.trigger_type, instruction,
            self.selected_section_ids or None, mode,
            content=content,
            knowledge=self.knowledge_context or None,
            profile=getattr(getattr(self, "profile", None), "context_json", None) or None,
        )
        self.active_intent = decision.intent
        self.resolved_intent = decision
        # 章节 ID 规范化：入口统一把别名映射为规范 SEC-* ID。
        # - 用户选中章节（requested）：必须已存在，过滤索引外未知项并记入 ambiguity。
        # - 契约目标/解析范围（resolved_scope/target_section_ids）：可能包含计划新建的
        #   章节（拆分/新增），只做别名映射，不做索引存在性过滤；非法 ID 由工具层
        #   （section_not_found）作为致命错误拦截，避免把尚未创建的章节误判为无效。
        self.requested_section_ids = list(self.selected_section_ids)
        section_index = build_section_index(
            self.builder.to_content() if self.builder else {}
        )
        canonical_selected, invalid_selected = canonicalize_section_ids(
            self.requested_section_ids, section_index,
        )
        if invalid_selected:
            decision.ambiguity_reasons = list(decision.ambiguity_reasons or []) + [
                f"invalid_section_id:{raw}" for raw in invalid_selected
            ]
        self.selected_section_ids = canonical_selected
        resolved_scope, _ = canonicalize_section_ids(
            list(decision.resolved_scope or []), None,
        )
        decision.resolved_scope = resolved_scope or canonical_selected
        decision.affected_section_ids = list(decision.resolved_scope)
        target_ids, _ = canonicalize_section_ids(
            list(decision.target_section_ids or []), None,
        )
        decision.target_section_ids = target_ids or decision.resolved_scope
        required_kinds = set(decision.required_change_kinds or [])
        self.content_policy = (
            "preserve"
            if required_kinds == {"outline_structure"}
            else "edit"
        )
        # 注入本轮细粒度修改权限（MutationPolicy），工具层据此校验越权。
        from app.agent.agents.lesson_plan.intents import VALID_FACT_KEYS

        forbidden = set(decision.forbidden_change_kinds or [])
        # 收紧：只有契约显式要求 core_content 修改时才放开全部内核键；
        # 格式修正（SECTION_FORMAT_EDIT）绝不写内核（含契约点名的 target_fact_keys）；
        # 其余意图（含 SECTION_EDIT / 纯结构）一律只允许契约点名的 target_fact_keys，
        # 避免误调 lesson_update_core。
        if decision.intent == "SECTION_FORMAT_EDIT":
            allowed_core = set()
        elif "core_content" in required_kinds and "core_content" not in forbidden:
            allowed_core = set(VALID_FACT_KEYS)
        elif decision.target_fact_keys:
            allowed_core = set(decision.target_fact_keys)
        elif decision.intent == "TIMING_ADJUST":
            allowed_core = {"stages"}
        else:
            allowed_core = set()
        self.mutation_policy = MutationPolicy(
            allowed_section_ids=set(self.selected_section_ids) | set(decision.target_section_ids or []),
            allowed_core_keys=allowed_core,
            allow_structure_ops=decision.intent == "RESTRUCTURE" or decision.structural,
            allow_top_level_add=True,
        )
        return decision

    async def _ensure_task_spec(self) -> Any:
        """在执行链前生成不可变任务规格（TaskSpec）并发射 task.spec.created。"""
        from app.agent.agents.lesson_plan.intents import build_lesson_plan_task_spec

        instruction = self.context.user_instruction or ""
        snapshot_id = ""
        if self.resolved_intent is not None:
            snapshot_id = self.resolved_intent.context_snapshot_id
        spec = build_lesson_plan_task_spec(
            self.resolved_intent or LessonPlanIntentDecision(intent=self.active_intent),
            instruction,
            context_snapshot_id=snapshot_id,
        )
        self.task_spec = spec
        if self.emitter is not None:
            decision = self.resolved_intent
            await self.emitter.emit_domain(
                "task.spec.created",
                agent={"id": "intent_planner"},
                message=f"任务规格已生成：{spec.intent}",
                payload={
                    "spec_id": spec.spec_id,
                    "intent": spec.intent,
                    "expected_outcome": spec.expected_outcome,
                    "requested_section_ids": list(spec.requested_section_ids),
                    "target_section_ids": list(spec.target_section_ids),
                    "target_fact_keys": list(spec.target_fact_keys),
                    "allowed_change_kinds": list(spec.allowed_change_kinds),
                    "forbidden_change_kinds": list(spec.forbidden_change_kinds),
                    "success_conditions": list(spec.success_conditions),
                    "requires_teaching_reasoning": spec.requires_teaching_reasoning,
                    "requires_confirmation": spec.requires_confirmation,
                    "context_snapshot_id": spec.context_snapshot_id,
                    "classifier_version": getattr(decision, "classifier_version", ""),
                    "rule_match": getattr(decision, "rule_match", ""),
                },
            )
        return spec

    async def _ensure_evidence_bundle(self) -> Any:
        """执行链前生成统一证据包（EvidenceBundle）并发射 evidence.bundle.ready。"""
        from app.agent.agents.lesson_plan.context import build_lesson_plan_evidence_bundle

        content = self.builder.to_content() if self.builder else {}
        bp_content = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        source = getattr(self, "source_artifact", None)
        source_version = f"v{getattr(source, 'version', 1)}" if source is not None else ""
        decision = self.resolved_intent
        target_ids = list((decision.target_section_ids if decision else []) or self.selected_section_ids)
        fact_keys = list((decision.target_fact_keys if decision else []) or [])
        spec = self.task_spec
        requires_reasoning = bool(getattr(spec, "requires_teaching_reasoning", True))
        bundle = build_lesson_plan_evidence_bundle(
            content,
            blueprint=bp_content,
            profile=getattr(getattr(self, "profile", None), "context_json", None) or {},
            knowledge=self.knowledge_context or {},
            task_spec_id=getattr(spec, "spec_id", "") if spec else "",
            source_version=source_version,
            target_section_ids=target_ids,
            target_fact_keys=fact_keys,
            requires_teaching_reasoning=requires_reasoning,
        )
        self.evidence_bundle = bundle
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "evidence.bundle.ready",
                agent={"id": "context_researcher"},
                message=(
                    "证据包已就绪（格式/确定性任务不检索材料）"
                    if not requires_reasoning
                    else f"证据包已就绪（{bundle.sufficiency}）"
                ),
                payload={
                    "task_spec_id": bundle.task_spec_id,
                    "source_version": bundle.source_version,
                    "target_sections": [
                        {"section_id": item.section_id, "has_visible_text": item.has_visible_text}
                        for item in bundle.target_sections
                    ],
                    "material_evidence_count": len(bundle.material_evidence),
                    "fact_owner_map": dict(bundle.fact_owner_map),
                    "knowledge_gaps": list(bundle.knowledge_gaps),
                    "sufficiency": bundle.sufficiency,
                },
            )
        return bundle

    def execution_scope_ids(self) -> list[str]:
        """本轮执行范围：契约目标优先（意图识别接地结果），回退到用户选中范围。

        用户在前端选中的章节（selected_section_ids）与意图识别解析出的目标
        （target_section_ids / resolved_scope）必须统一：工具层 MutationPolicy
        只允许修改契约目标，LLM 提示词的范围也必须与之一致，否则 LLM 以为
        可以改全部章节，实际被守卫拒绝（fatal）或不知道改哪而空转。
        """
        if self.resolved_intent is not None:
            targets = list(self.resolved_intent.target_section_ids or [])
            if targets:
                return targets
            scope = list(self.resolved_intent.resolved_scope or [])
            if scope:
                return scope
        return list(self.selected_section_ids)

    def record_mutation(self, receipt: Any) -> None:
        """记录写操作的 MutationReceipt（由工具层调用，幂等）。"""
        if receipt is None:
            return
        self.mutation_receipts.append(receipt)
        if self.emitter is not None and getattr(receipt, "changed", False):
            # 核心状态机事件：写操作已应用。后台任务发送，失败不阻断工具结果。
            import asyncio

            asyncio.create_task(self._emit_patch_applied(receipt))

    async def _emit_patch_applied(self, receipt: Any) -> None:
        try:
            await self.emitter.emit_domain(
                "patch.operation.applied",
                agent={"id": getattr(receipt, "tool_name", "") or self.current_agent_key},
                message="修改操作已应用（写入候选稿）",
                payload={
                    "operation_id": getattr(receipt, "operation_id", ""),
                    "tool_name": getattr(receipt, "tool_name", ""),
                    "target_paths": list(getattr(receipt, "target_paths", []) or []),
                    "before_hash": getattr(receipt, "before_hash", ""),
                    "after_hash": getattr(receipt, "after_hash", ""),
                    "changed_section_ids": list(getattr(receipt, "changed_section_ids", []) or []),
                    "changed_core_keys": list(getattr(receipt, "changed_core_keys", []) or []),
                },
            )
        except Exception:  # noqa: BLE001  事件失败不影响修改结果
            logger.warning("patch.operation.applied 事件发送失败", exc_info=True)

    def content_mutable_section_ids(self, content: dict[str, Any] | None = None) -> set[str]:
        """Sections whose visible content may change during a structure-only run."""
        current = content or (self.builder.to_content() if self.builder else {})
        baseline = self.baseline_content or {}
        baseline_ids = {
            str(item.get("id") or "")
            for item in _walk_outline((baseline.get("outline") or {}).get("sections") or [])
        }
        mutable = set(self.selected_section_ids or [])
        mutable.update(
            str(item.get("id") or "")
            for item in _walk_outline((current.get("outline") or {}).get("sections") or [])
            if str(item.get("id") or "") not in baseline_ids
        )
        facts = set((self.resolved_intent.required_separate_facts if self.resolved_intent else []) or [])
        if facts:
            for source in (baseline, current):
                for item in _walk_outline((source.get("outline") or {}).get("sections") or []):
                    if facts.intersection(item.get("coverage_refs") or []):
                        mutable.add(str(item.get("id") or ""))
        return {item for item in mutable if item}

    def _build_plan(self, chain: list[str], revision_rounds: int = MAX_REVISION_ROUNDS) -> PipelinePlan:
        return PipelinePlan(
            agents=[AgentSpec(**lesson_plan_spec(key)) for key in chain],
            revision_rounds=revision_rounds,
        )

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await self._prepare()
        if self.emitter is not None:
            await self.emitter.pipeline_started(self.trigger_type)
        if self.trigger_type == "initial":
            # 首轮生成：确定性 GENERATE 计划（上下文调研 → 目录 → 内容 → QA → 终稿）。
            intent_decision = await self._resolve_intent()
            chain = agent_chain_for_intent(intent_decision.intent, self.trigger_type)
        else:
            intent_decision = await self._resolve_intent()
            if intent_decision.intent == "QA_ONLY":
                chain = agent_chain_for_intent("QA_ONLY", self.trigger_type)
            elif self.trigger_type == "sync_context":
                chain = agent_chain_for_intent("SYNC_CONTEXT", self.trigger_type)
            else:
                # 结构意图若涉及正文迁移/内核写入，按契约变更类型补入 lesson_designer。
                chain = agent_chain_for_intent(
                    intent_decision.intent, self.trigger_type,
                    intent_decision.required_change_kinds,
                )
        # 执行链前创建不可变上下文快照：resolved 取规范化契约，不依赖执行后
        # 才计算的 affected_section_ids；所有 Agent 共享同一快照。
        await self._ensure_context_snapshot()
        # 执行链前生成不可变任务规格与统一证据包：后续 Agent 不得重新解释任务，
        # 只读工具结果自动写入证据包。
        await self._ensure_task_spec()
        await self._ensure_evidence_bundle()
        if self.emitter is not None:
            decision = self.resolved_intent
            await self.emitter.emit_domain(
                "intent.resolved",
                agent={"id": "intent_planner"},
                message=f"意图：{self.active_intent}",
                payload={
                    "intent": self.active_intent,
                    "chain": chain,
                    "affected_section_ids": list(getattr(decision, "affected_section_ids", None) or self.selected_section_ids),
                    "requested_scope": list(getattr(decision, "requested_scope", None) or []),
                    "resolved_scope": list(getattr(decision, "resolved_scope", None) or []),
                    "target_section_ids": list(getattr(decision, "target_section_ids", None) or []),
                    "allowed_change_kinds": list(getattr(decision, "allowed_change_kinds", None) or []),
                    "forbidden_change_kinds": list(getattr(decision, "forbidden_change_kinds", None) or []),
                    "required_invariants": list(getattr(decision, "required_invariants", None) or []),
                    "rule_match": getattr(decision, "rule_match", ""),
                    "classifier_version": getattr(decision, "classifier_version", ""),
                },
            )
        self.blocking_issues = []
        self.repair_fingerprint = ""
        self.fatal_tool_error = None
        self.verification_report = {}
        self._qa_report_ready = False
        self._analyst_attempted = False
        self._analysis_cache = {}
        self.mutation_receipts = []
        self.executed_chain = list(chain)
        await self._run_with_repair(chain)
        await self._apply_deterministic_fixes()
        # 确定性修复无效（目标无实际变化）但用户明确要求修改时，升级一次 LLM
        # 分析师轮次：让模型读取源文档、渲染预览与指令上下文，理解并落实修改。
        await self._maybe_run_analyst_round()
        await self._finalize()

    async def _ensure_context_snapshot(self) -> None:
        """在执行链前生成不可变上下文快照，并写回契约的快照标识。

        ``resolved_section_ids`` 取自规范化后的契约（与用户原始请求分离），
        ``preserved_section_ids`` 为快照时点下现有章节中不在执行范围内的章节。
        """
        from app.agent.agents.lesson_plan.context import build_lesson_plan_context_snapshot

        content = self.builder.to_content() if self.builder else {}
        bp_content = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        resolved = list((self.resolved_intent.resolved_scope or []) if self.resolved_intent else self.selected_section_ids)
        requested = list(self.requested_section_ids or self.selected_section_ids)
        source = getattr(self, "source_artifact", None)
        source_content = getattr(source, "content_json", None) or {}
        source_version = f"v{getattr(source, 'version', 1)}" if source is not None else ""
        from app.agent.agents.lesson_plan.context import _calc_hash

        snapshot = build_lesson_plan_context_snapshot(
            content,
            blueprint=bp_content,
            artifact_id=getattr(source, "id", ""),
            requested_section_ids=requested,
            resolved_section_ids=resolved,
            locked_paths=[getattr(lock, "json_path", "") for lock in self.locks],
            profile=getattr(getattr(self, "profile", None), "context_json", None) or {},
            siblings=self.knowledge_context.get("sibling_artifacts") or {},
            source_version=source_version,
            source_hash=_calc_hash(source_content) if source_content else "",
        )
        self.context_snapshot = snapshot
        if self.resolved_intent is not None:
            self.resolved_intent.context_snapshot_id = snapshot.snapshot_id
            self.resolved_intent.context_snapshot_hash = snapshot.snapshot_hash
        if self.emitter is not None:
            await self.emitter.emit_domain(
                "context.snapshot.created",
                agent={"id": "orchestrator"},
                message="已创建执行前上下文快照（目标章节与保护范围已固定）",
                payload={
                    "snapshot_id": snapshot.snapshot_id,
                    "source_version": source_version,
                    "target_section_ids": resolved,
                    "preserved_section_ids": list(snapshot.preserved_section_ids),
                    "fact_owners": dict(snapshot.fact_owner_map),
                    "snapshot_hash": snapshot.snapshot_hash,
                },
            )

    async def _run_with_repair(self, chain: list[str]) -> None:
        """执行计划并处理 QA → 返修闭环（≤max_revision_rounds，指纹防空转）。"""
        plan = self._build_plan(chain)
        for round_index in range(self.max_revision_rounds + 1):
            self.repair_round = round_index
            try:
                await run_agent_loop(
                    self, plan,
                    agent_registry=AGENT_BY_KEY,
                    call_agent=_call_agent,
                    persist_artifact=_persist_artifact,
                    retry_classifier=_retry_classifier,
                )
            except AgentError as exc:
                if exc.code == "fatal_tool_error":
                    # 不可重试的契约/守卫错误：立即终止整轮修改链，不进入返修，
                    # 也不伪装成 agent_no_progress。
                    self.fatal_tool_error = dict(exc.details or {})
                    if self.emitter is not None:
                        await self.emitter.emit_domain(
                            "result.rejected",
                            agent={"id": "orchestrator"},
                            message=exc.user_message,
                            payload={
                                "result_status": "rejected",
                                "error_code": str((self.fatal_tool_error or {}).get("error_code") or exc.code),
                                "requested_target": (self.fatal_tool_error or {}).get("requested_target"),
                                "allowed_scope": (self.fatal_tool_error or {}).get("allowed_scope"),
                                "suggestion": (self.fatal_tool_error or {}).get("suggestion"),
                            },
                        )
                    return
                raise
            await self._collect_qa_issues()
            if not _blocking(self.blocking_issues):
                return
            fp = _fingerprint(self.blocking_issues)
            if fp and fp == self.repair_fingerprint:
                logger.info("教学设计返修指纹重复，停止空转（round=%s）", round_index)
                return
            self.repair_fingerprint = fp
            if round_index >= self.max_revision_rounds - 1:
                return
            # repair_router 路由重跑范围（确定性控制节点）。
            repair_decision = await REPAIR_ROUTER.decide(self.tool_context)
            repair_agents = (repair_decision.output or {}).get("plan") or ["lesson_designer", "pedagogy_qa"]
            if self.emitter is not None:
                await self.emitter.revision_started(
                    round_index + 1, self.max_revision_rounds,
                    reason="教学质询存在阻断问题", target_agents=repair_agents,
                )
            plan = self._build_plan([*repair_agents, "finalizer"])
            if self.emitter is not None:
                await self.emitter.revision_completed(round_index + 1, applied_changes=repair_agents)

    async def _apply_deterministic_fixes(self) -> None:
        """应用确定性内容修复（不依赖模型行为即可保证的用户诉求落地）。

        仅在用户明确要求格式修正（SECTION_FORMAT_EDIT）时执行：对目标章节正文
        确定性去除硬编码的旧序号标记（一、/二、/（一）/1. 等）与【教学评价】式
        包装前缀，章节序号一律由渲染器按树结构动态生成。

        注意：普通内容修改（SECTION_EDIT / CONTENT_ENRICH 等）**不**做强制清理——
        正文中的「一、二、」可能是内容固有的结构排版（如板书设计的分板块、大纲式
        列表），属于作者意图，模型写入什么就保留什么，避免“润色板书却把板块结构
        改坏”。
        """
        decision = self.resolved_intent
        if self.builder is None or decision is None:
            return
        if decision.intent != "SECTION_FORMAT_EDIT":
            return
        if not getattr(decision, "strip_hardcoded_numbering", False):
            return
        targets = list(decision.target_section_ids or decision.affected_section_ids or [])
        content = self.builder.to_content()
        fixed = strip_hardcoded_ordinals(content, targets)
        if fixed != content:
            self.builder.replace_content(fixed)
            # 确定性写操作同样登记 MutationReceipt 并触发 patch.operation.applied。
            from app.agent.agents.lesson_plan.tools._common import build_mutation_receipt

            build_mutation_receipt(
                self.tool_context,
                tool_name="format_normalizer",
                change_paths=[f"$.outline.sections[{sid}]" for sid in targets],
                before_content=content,
                after_content=fixed,
                section_ids=targets,
            )

    async def _collect_qa_issues(self) -> None:
        """从 pedagogy_qa 产物读取统一验证报告（LLM 或 Mock 均已写入 lesson_qa）。

        校验与 Finalizer 消费同一份 verification_report，不允许再出现
        「QA 100 分、Finalizer 又认为失败」的矛盾。
        """
        report: dict[str, Any] | None = None
        if self.artifacts is not None:
            qa = await self.artifacts.latest("lesson_qa")
            if qa:
                data = qa.get("data") or {}
                report = data.get("verification_report") if isinstance(data, dict) else None
                if not report:
                    report = self._fallback_verification_report()
                if report and isinstance(report, dict):
                    self.verification_report = report
                    self._qa_report_ready = True
        if report is None:
            report = self._fallback_verification_report() or {}
            self.verification_report = report
            self._qa_report_ready = bool(report)
        self.blocking_issues = list(report.get("blocking_issues") or [])
        await self._emit_verification_completed()

    async def _maybe_run_analyst_round(self) -> None:
        """确定性修复无效时升级一次 LLM 分析师轮次。

        场景：用户明确要求修改（格式/内容/时长/结构），但确定性修复与契约目标
        均未对候选稿产生任何实际变化。此时必须让模型读取源文档、渲染预览与指令
        上下文，理解用户真正要改的内容——而不是零 LLM 地直接判定“未检测到可应用
        的修改”。

        规则：
        - 只在真实 Provider 下触发（Mock 走确定性行为，保持测试稳定）；
        - 只对内容定位型意图触发（格式/普通内容/丰富/时长/结构）；
        - 每次运行最多一次（_analyst_attempted 防循环）；
        - 分析师（lesson_designer）仍受 MutationPolicy 范围约束，只改契约目标。
        """
        if self._analyst_attempted or self.builder is None:
            return
        if is_mock_provider(self.provider) or self.provider is None:
            return
        decision = self.resolved_intent
        intent = (decision.intent if decision else None) or self.active_intent
        if intent not in {
            "SECTION_EDIT", "SECTION_FORMAT_EDIT", "CONTENT_ENRICH",
            "TIMING_ADJUST", "RESTRUCTURE",
        }:
            return
        if self.fatal_tool_error is not None:
            return
        # 只有当前候选稿相对源没有任何实际变化时才升级（否则主链已生效）。
        baseline = self.baseline_content or (
            dict(getattr(self.source_artifact, "content_json", None) or {}) if self.source_artifact is not None else None
        )
        if baseline is not None:
            current = self.builder.to_content()
            diff = diff_lesson_plans(baseline, current)
            if diff.get("changed"):
                return
        # 确认需要升级后置位防循环标记。
        self._analyst_attempted = True
        # 追加分析师轮次：lesson_designer（LLM 分析并修改）→ finalizer（确定性组装）。
        if "lesson_designer" not in self.executed_chain:
            self.executed_chain.append("lesson_designer")
        if self.emitter is not None:
            await self.emitter.revision_started(
                self.repair_round + 1, self.max_revision_rounds,
                reason="确定性修复未产生实际变化，升级模型分析用户要求", target_agents=["lesson_designer"],
            )
        plan = self._build_plan(["lesson_designer", "finalizer"])
        try:
            await run_agent_loop(
                self, plan,
                agent_registry=AGENT_BY_KEY,
                call_agent=_call_agent,
                persist_artifact=_persist_artifact,
                retry_classifier=_retry_classifier,
            )
        except AgentError as exc:
            # 分析师工具的契约守卫错误：记录但不阻断（由最终门禁判定发布）。
            if exc.code == "fatal_tool_error":
                self.fatal_tool_error = dict(exc.details or {})
                if self.emitter is not None:
                    await self.emitter.emit_domain(
                        "result.rejected",
                        agent={"id": "orchestrator"},
                        message=exc.user_message,
                        payload={
                            "result_status": "rejected",
                            "error_code": str((self.fatal_tool_error or {}).get("error_code") or exc.code),
                            "requested_target": (self.fatal_tool_error or {}).get("requested_target"),
                            "allowed_scope": (self.fatal_tool_error or {}).get("allowed_scope"),
                            "suggestion": (self.fatal_tool_error or {}).get("suggestion"),
                        },
                    )
                return
            raise
        # 分析师可能修改了候选稿：重新收集统一验证报告，最终门禁在 _finalize 判定。
        if self.artifacts is not None:
            qa = await self.artifacts.latest("lesson_qa")
            if qa is not None:
                await self._collect_qa_issues()
            else:
                self.verification_report = {}
                self.blocking_issues = []
                self._qa_report_ready = False
        if self.emitter is not None:
            await self.emitter.revision_completed(
                self.repair_round + 1, applied_changes=["lesson_designer"],
            )

    def _fallback_verification_report(self) -> dict[str, Any] | None:
        if self.builder is None:
            return None
        bp = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
        locked_paths = [getattr(lock, "json_path", "") for lock in self.locks]
        baseline = self.baseline_content or (
            dict(getattr(self.source_artifact, "content_json", None) or {}) if self.source_artifact is not None else None
        )
        decision = self.resolved_intent
        target_ids = list((decision.target_section_ids if decision else []) or self.selected_section_ids)
        numbering_blocking = bool(decision and decision.intent == "SECTION_FORMAT_EDIT")
        try:
            return build_lesson_plan_verification_report(
                CourseBlueprintSchema.model_validate(bp),
                baseline,
                self.builder.to_content(),
                locked_paths=locked_paths,
                target_section_ids=target_ids,
                numbering_blocking=numbering_blocking,
            )
        except Exception:  # noqa: BLE001
            return None

    async def _emit_verification_completed(self) -> None:
        """发射 verification.completed（状态机核心事件，每轮返修一次）。"""
        if self.emitter is None:
            return
        report = self.verification_report or {}
        blocking = list(report.get("blocking_issues") or [])
        await self.emitter.emit_domain(
            "verification.completed",
            agent={"id": "pedagogy_qa"},
            message=(
                "确定性验证完成：全部通过"
                if not blocking
                else f"确定性验证完成：发现 {len(blocking)} 个阻断问题"
            ),
            payload={
                "passed": bool(report.get("passed")),
                "task_completed": bool(report.get("task_completed")),
                "target_checks": len(report.get("target_checks") or []),
                "scope_checks": len(report.get("scope_checks") or []),
                "pedagogical_checks": len(report.get("pedagogical_checks") or []),
                "baseline_warnings": len(report.get("baseline_warnings") or []),
                "blocking_issues": blocking[:12],
                "target_section_ids": list(report.get("target_section_ids") or []),
                "repair_round": self.repair_round,
            },
        )

    # ------------------------------------------------------------------
    # 发布门禁
    # ------------------------------------------------------------------

    async def _emit_result_status_event(self) -> None:
        """发射最终结果事件（result.applied / result.no_change / result.rejected）。

        rejected 的文案按实际原因区分：致命工具越权 vs 未检测到可应用修改，
        避免与后续 polish.result 的具体文案互相矛盾。
        """
        if self.emitter is None:
            return
        status = self.result_status
        if status == "applied":
            event_type, message = "result.applied", "修改已应用，新版本已生成"
        elif status == "no_change":
            event_type, message = "result.no_change", "未发现需要修改的内容，未创建新版本"
        elif status == "needs_confirmation":
            event_type, message = "result.no_change", "修改范围存在歧义，需要教师确认"
        else:
            event_type = "result.rejected"
            gate_code = str((self.intent_gate or {}).get("code") or "")
            if gate_code == "no_change_but_request_unfulfilled":
                message = "未检测到可应用的修改，本轮修改未落实"
            elif gate_code == "fatal_tool_error":
                message = "修改被安全拒绝，原教学设计未改变"
            elif gate_code == "intent_unfulfilled":
                message = "本轮修改未满足教师指令，未应用修改"
            else:
                message = "本轮修改未通过门禁，未应用修改；原教学设计保持不变"
        await self.emitter.emit_domain(
            event_type,
            agent={"id": "orchestrator"},
            message=message,
            payload={
                "result_status": status,
                "intent": self.active_intent,
                "intent_gate": dict(self.intent_gate or {}),
                "diff_summary": dict(self.diff_summary or {}),
                "changed_sections": list(self.affected_section_ids or []),
                "verification_passed": bool((self.verification_report or {}).get("passed")),
                "target_section_ids": list((self.resolved_intent.target_section_ids if self.resolved_intent else []) or []),
            },
        )

    async def _finalize(self) -> None:
        """finalizer 产出最终候选稿；发布门禁决定 result_status。"""
        if self.builder is None:
            raise AgentError("lesson_plan_missing", "教学设计候选稿未生成。", retryable=True)
        # 最终确定性验证：基于最终候选稿重新生成统一验证报告（含确定性修复后的
        # 结果）。QA 产物已携带统一报告时直接复用（验证与 Finalizer 消费同一份）；
        # 已存在验证状态（QA 轮报告或手动注入的阻断问题）时不做覆盖重算。
        if not self._qa_report_ready and not self.verification_report and not self.blocking_issues:
            final_report = self._fallback_verification_report() or {}
            if final_report:
                self.verification_report = final_report
                self.blocking_issues = list(final_report.get("blocking_issues") or [])
                await self._emit_verification_completed()
        # 致命工具错误（不可重试）：整轮修改终止，rejected，原教学设计保持不变。
        if self.fatal_tool_error:
            self.result_status = "rejected"
            self.publishable = False
            self.changed = False
            self.intent_gate = {
                "passed": False,
                "code": "fatal_tool_error",
                **self.fatal_tool_error,
            }
            await self._emit_result_status_event()
            return
        # ANSWER_ONLY：独立完成协议。不生成教学设计版本、不校验产物、不要求
        # lesson_content；结果一律 no_change（仅回答未修改）。
        if self.active_intent == "ANSWER_ONLY":
            self.result_status = "no_change"
            self.changed = False
            self.draft_answer = await self._read_answer()
            await self._emit_result_status_event()
            return
        content = self.builder.to_content()
        # 最终强校验：结构非法直接失败（不存在可保留的正式版本）。
        try:
            validated = LessonPlanContentV2.model_validate(content)
            content = validated.model_dump()
        except Exception as exc:  # noqa: BLE001
            raise AgentError(
                "lesson_plan_invalid", f"教学设计候选稿结构非法：{str(exc)[:300]}",
                retryable=True,
            ) from exc
        self.draft_content = content
        from app.schemas.lesson_plan import lesson_plan_to_markdown_v2

        self.draft_markdown = lesson_plan_to_markdown_v2(content)
        baseline = self.baseline_content
        if not baseline and self.source_artifact is not None:
            baseline = dict(getattr(self.source_artifact, "content_json", None) or {})
        pure_structure = bool(
            self.resolved_intent
            and set(self.resolved_intent.required_change_kinds or []) == {"outline_structure"}
        )
        mutable_section_ids = self.content_mutable_section_ids(content) if pure_structure else None
        self.diff_summary = diff_lesson_plans(
            baseline or content,
            content,
            mutable_section_ids=mutable_section_ids,
        )
        self.affected_section_ids = list(self.diff_summary.get("changed_sections") or [])
        self.intent_gate = self._evaluate_intent_gate(content, self.diff_summary)

        content_regressions: list[str] = []
        if baseline and self.source_artifact is not None:
            if self.diff_summary.get("emptied_sections"):
                content_regressions.append("existing_sections_emptied")
            if pure_structure and self.diff_summary.get("unexpected_content_changes"):
                content_regressions.append("unexpected_content_changes")
            if pure_structure and float(self.diff_summary.get("content_loss_ratio") or 0) > 0.05:
                content_regressions.append("visible_content_loss_exceeds_5_percent")
        from app.agent.agents.lesson_plan.diff import empty_leaf_section_ids, section_visible_text

        empty_leaf_ids = empty_leaf_section_ids(content)
        if empty_leaf_ids:
            content_regressions.append("empty_leaf_sections")
        fact_owners = dict(self.intent_gate.get("fact_owners") or {})
        empty_fact_owners = []
        for fact, section_id in fact_owners.items():
            section = self.builder.find_section(section_id) if self.builder else None
            if not section or not section_visible_text(section):
                empty_fact_owners.append(fact)
        if empty_fact_owners:
            content_regressions.append("required_fact_sections_empty")
        if content_regressions:
            self.intent_gate = {
                **self.intent_gate,
                "passed": False,
                "code": "content_regression",
                "content_regressions": content_regressions,
                "empty_leaf_sections": empty_leaf_ids,
                "empty_required_facts": empty_fact_owners,
            }

        missing_artifacts = await self._missing_required_artifacts()
        if missing_artifacts:
            self.intent_gate = {
                **self.intent_gate,
                "passed": False,
                "code": "required_artifact_missing",
                "missing_artifacts": missing_artifacts,
            }

        # 范围完整性门禁：保留章节（非目标、非新建、非结构变更范围内）的正文必须逐字不变。
        if baseline and self.source_artifact is not None:
            scope_failures = self._evaluate_scope_gate(baseline, content)
            if scope_failures:
                self.intent_gate = {
                    **self.intent_gate,
                    "passed": False,
                    "code": "scope_gate_failed",
                    "scope_failures": scope_failures,
                }
        blocking_tool_failures = [
            failure
            for failure in self.unresolved_tool_failures.values()
            if str(failure.get("error_code") or "") not in _NON_BLOCKING_READ_FAILURE_CODES
        ]
        if blocking_tool_failures:
            self.intent_gate = {
                **self.intent_gate,
                "passed": False,
                "code": "unresolved_tool_failure",
                "unresolved_tool_failures": blocking_tool_failures,
            }
        # 无真实变更 → no_change（保留原版，不创建空版本）。
        # 源版本与候选稿都经过同一 schema 规范化（补默认字段）后再比较，避免
        # Pydantic model_dump 填充默认值导致的假阳性差异。
        # 返修未收敛仍存在阻断问题优先于 no_change；不能用“没有变化”掩盖
        # 一个已知不可发布的候选稿。
        if _blocking(self.blocking_issues):
            self.result_status = "rejected"
            self.publishable = False
            await self._emit_result_status_event()
            return
        if self.active_intent == "QA_ONLY":
            self.result_status = "no_change"
            self.changed = False
            await self._emit_result_status_event()
            return
        if not self.intent_gate.get("passed", True):
            if self.source_artifact is None:
                raise AgentError(
                    str(self.intent_gate.get("code") or "lesson_plan_gate_failed"),
                    "教学设计流水线缺少必需产物或未通过意图完成度门禁。",
                    retryable=True,
                    details=self.intent_gate,
                )
            self.result_status = "rejected"
            self.publishable = False
            self.changed = False
            await self._emit_result_status_event()
            return
        # 无真实变更 → 判定已符合要求。
        # 注意：格式/内容类修改（SECTION_FORMAT_EDIT / SECTION_EDIT / TIMING_ADJUST /
        # RESTRUCTURE / CONTENT_ENRICH）没有任何变更时，绝不能伪装成 no_change
        # （“当前设计已符合要求，本轮未创建空转版本”会让用户以为要求已满足）——
        # 必须进入 intent_gate 判定：如果该要求本就不可能从结构上满足（例如目标章节
        # 在文档中不存在、或指令要求的部分无法定位），标记 rejected 并给出原因。
        if not self.diff_summary.get("changed") and self.source_artifact is not None:
            if self.active_intent not in {"ANSWER_ONLY", "QA_ONLY"}:
                self.intent_gate = {
                    **self.intent_gate,
                    "passed": False,
                    "code": "no_change_but_request_unfulfilled",
                    "failures": list(self.intent_gate.get("failures") or []) + ["required_change_missing"],
                    "message": "本轮未对候选稿产生任何变更，但用户要求的修改未落实；"
                               "请检查目标章节是否存在于当前文档、指令所述部分是否可定位。",
                }
                self.result_status = "rejected"
                self.publishable = False
                self.changed = False
                await self._emit_result_status_event()
                return
            self.result_status = "no_change"
            self.changed = False
            await self._emit_result_status_event()
            return
        self.result_status = "applied"
        self.changed = True
        self.publishable = True
        await self._emit_result_status_event()

    def _evaluate_intent_gate(self, content: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
        decision = self.resolved_intent
        if self.trigger_type == "initial" or decision is None:
            return {"passed": True, "code": "initial_generation"}
        failures: list[str] = []
        kinds = list(decision.required_change_kinds or [])
        for kind in kinds:
            if kind == "qa_only":
                continue
            key = {
                "outline_structure": "outline_structure_changed",
                "section_content": "section_content_changed",
                "core_content": "core_content_changed",
                "timing": "timing_changed",
            }.get(kind)
            if key and not diff.get(key):
                failures.append(f"required_change_missing:{kind}")
        fact_owners: dict[str, str] = {}
        if decision.required_separate_facts:
            if decision.must_be_distinct_top_level:
                fact_owners = distinct_top_level_fact_sections(content, decision.required_separate_facts)
                if not fact_owners:
                    failures.append("required_facts_not_in_distinct_top_level_sections")
        if "timing" in kinds:
            stages = (content.get("pedagogical_core") or {}).get("stages") or []
            target = float((content.get("course_info") or {}).get("duration_minutes") or 0)
            total = sum(float(item.get("duration_minutes") or 0) for item in stages)
            if abs(total - target) > 0.5:
                failures.append("timing_not_conserved")
        return {
            "passed": not failures,
            "code": "passed" if not failures else "intent_unfulfilled",
            "required_change_kinds": kinds,
            "required_separate_facts": list(decision.required_separate_facts or []),
            "fact_owners": fact_owners,
            "failures": failures,
        }

    def _evaluate_scope_gate(self, baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
        """范围完整性门禁：目标/新建章节之外的保留章节正文必须逐字不变。

        - 契约 target_section_ids 与 resolved_scope 之外的所有现有章节；
        - 本轮新建章节（不在 baseline 中）不受保留约束；
        - 结构意图（RESTRUCTURE）允许移动/重命名保留章节，但其 blocks/summary 不得变化。
        """
        decision = self.resolved_intent
        if decision is None:
            return []
        from app.agent.agents.lesson_plan.context import walk_sections_recursive

        baseline_nodes = {
            str(node.get("id") or ""): node
            for node, _parent, _order, _depth in walk_sections_recursive(
                (baseline.get("outline") or {}).get("sections") or []
            )
        }
        candidate_nodes = {
            str(node.get("id") or ""): node
            for node, _parent, _order, _depth in walk_sections_recursive(
                (candidate.get("outline") or {}).get("sections") or []
            )
        }
        allowed = set(decision.target_section_ids or []) | set(decision.resolved_scope or [])
        failures: list[str] = []
        for section_id, source_node in baseline_nodes.items():
            if section_id in allowed:
                continue
            target_node = candidate_nodes.get(section_id)
            if target_node is None:
                failures.append(f"preserved_section_removed:{section_id}")
                continue
            if source_node.get("blocks") != target_node.get("blocks") or source_node.get("summary") != target_node.get("summary"):
                failures.append(f"preserved_section_content_changed:{section_id}")
        return failures

    async def _missing_required_artifacts(self) -> list[str]:
        if self.artifacts is None:
            return []
        if self.trigger_type == "initial":
            required = ["lesson_research", "lesson_outline", "lesson_content", "lesson_qa", "lesson_plan_draft"]
        elif self.active_intent == "ANSWER_ONLY":
            # 独立完成协议：纯问答不要求任何教学设计产物，只要求答复产物。
            required = ["lesson_answer"]
        elif self.active_intent == "QA_ONLY":
            required = ["lesson_qa", "lesson_plan_draft"]
        elif self.active_intent == "CLARIFICATION_REQUIRED":
            return []
        else:
            # 按本轮实际执行的 Agent 链推导必需产物：未被调用的角色不要求其产物。
            chain = list(self.executed_chain or [])
            if not chain:
                chain = agent_chain_for_intent(self.active_intent, self.trigger_type)
            from app.agent.agents.lesson_plan.agents import PRODUCED_BY_KEY

            produced_by = dict(PRODUCED_BY_KEY)
            required: list[str] = []
            for agent_key in chain:
                for artifact_type in produced_by.get(agent_key, []):
                    if artifact_type not in required:
                        required.append(artifact_type)
            if "lesson_plan_draft" not in required:
                required.append("lesson_plan_draft")
            required = list(dict.fromkeys(required))
        missing = []
        for artifact_type in required:
            if not await self.artifacts.latest(artifact_type):
                missing.append(artifact_type)
        return missing

    async def _read_answer(self) -> dict[str, Any]:
        """读取 answer_finalizer 的 lesson_answer 产物（ANSWER_ONLY 独立完成协议）。"""
        if self.artifacts is None:
            return {}
        answer = await self.artifacts.latest("lesson_answer")
        if not answer:
            return {}
        data = answer.get("data") or {}
        if isinstance(data, dict):
            return data
        return {"answer": str(data)}


# ---------------------------------------------------------------------------
# core/loop 注入函数
# ---------------------------------------------------------------------------

#: 先跑确定性产物、再把 LLM 深度分析附加到产物上的节点（门禁/组装必须真实，
#: 校验与发布裁决始终由确定性逻辑承担，模型不做自我评价与发布决定）。
_LLM_ANALYSIS_NODES = frozenset({
    "intent_planner", "context_researcher", "format_normalizer",
    "pedagogy_qa", "repair_router", "finalizer",
})


def _merge_llm_analysis(base: AgentDecision, llm: AgentDecision | None) -> AgentDecision:
    """把 LLM 深度分析附加到确定性产物（校验/路由/组装/验证报告仍由确定性裁决）。"""
    if llm is not None and llm.completed and llm.output is not None:
        base.output = {**dict(base.output or {}), "llm_analysis": llm.output}
        if llm.summary:
            base.summary = llm.summary
        if llm.message:
            base.message = llm.message
    return base


async def _call_agent(runtime: LessonPlanAgentRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用角色：Mock/无 Provider 走确定性 decide；真实 Provider 全部节点深度 LLM 分析。

    - outline_architect / lesson_designer：LLM 驱动（多轮工具循环）；
    - intent_planner / context_researcher / format_normalizer / pedagogy_qa /
      repair_router / finalizer：LLM 深度分析每节点最多一次（缓存）。第 1 轮请求
      权限内只读工具 → 交给工具循环执行；下一轮不再调 LLM，直接确定性 decide +
      附加第一次分析（省 token，且校验/组装仍由确定性逻辑裁决）；
    - answer_finalizer：LLM 产物优先（真实回答教师问题），失败回退确定性模板。

    教学设计不限累计/单次 token 限额（max_estimated_tokens / max_context_tokens = 0）。
    """
    if is_mock_provider(runtime.provider) or runtime.provider is None:
        return await agent.decide(runtime.tool_context)
    system = agent.build_system_prompt(runtime.tool_context, runtime)
    scope_ids = runtime.execution_scope_ids()
    prompt = (
        "当前角色专属候选稿视图：\n" + _role_context_text(runtime, agent_key)
        + "\n上下文：\n" + _compact_context_text(runtime, agent_key)
        + "\n可用工具 Schema：\n" + _tool_schemas_text(runtime, agent)
        + "\n当前教学环节范围（契约目标，只能读取并修改这些章节；其他章节必须逐字不变）："
        + (", ".join(scope_ids) if scope_ids else "本轮为全局任务，可以处理全部章节。")
        + "\n请先输出可见执行摘要（简短说明当前阶段和下一步动作，不要输出隐式思维链或系统提示词），"
        "再输出决策：要么给出一批 tool_calls，要么 completed（含 output/summary）。"
        "只返回一个 AgentDecision JSON。相同只读工具不要重复调用；已有结果足够时必须 completed。"
    )
    runtime.token_usage["tokens"] += estimate_context_tokens(prompt)
    runtime.token_usage["llm_calls"] += 1

    if agent_key in {"outline_architect", "lesson_designer"}:
        try:
            return await _stream_agent_decision(runtime, agent_key, system, prompt)
        except Exception:  # noqa: BLE001
            logger.warning("Agent %s LLM 决策失败，回退确定性 decide", agent_key, exc_info=True)
            return await agent.decide(runtime.tool_context)

    if agent_key in _LLM_ANALYSIS_NODES:
        # 该节点已做过一次深度分析（上一轮请求了只读工具）：直接确定性 merge，
        # 不再重复调用模型。
        cached = runtime._analysis_cache.get(agent_key)
        if cached is not None:
            return _merge_llm_analysis(await agent.decide(runtime.tool_context), cached)
        try:
            llm_decision = await _stream_agent_decision(runtime, agent_key, system, prompt)
        except Exception:  # noqa: BLE001
            logger.warning("Agent %s LLM 深度分析失败，回退确定性 decide", agent_key, exc_info=True)
            llm_decision = None
        if llm_decision is None:
            return await agent.decide(runtime.tool_context)
        # 只允许执行权限内的只读工具；越权请求直接丢弃（避免 tool_not_allowed 致命）。
        allowed = set(getattr(agent, "allowed_tools", []) or [])
        permitted = [call for call in (llm_decision.tool_calls or []) if call.tool_name in allowed]
        if permitted:
            runtime._analysis_cache[agent_key] = llm_decision
            llm_decision.tool_calls = permitted
            return llm_decision
        return _merge_llm_analysis(await agent.decide(runtime.tool_context), llm_decision)

    # answer_finalizer：LLM 真实回答优先（必须含有效 answer），否则回退确定性模板。
    if agent_key == "answer_finalizer":
        try:
            llm_decision = await _stream_agent_decision(runtime, agent_key, system, prompt)
        except Exception:  # noqa: BLE001
            llm_decision = None
        if (
            llm_decision is not None
            and llm_decision.completed
            and isinstance(llm_decision.output, dict)
            and (llm_decision.output.get("answer") or "")
        ):
            return llm_decision
        return await agent.decide(runtime.tool_context)


def _tool_schemas_text(runtime: LessonPlanAgentRuntime, agent=None) -> str:
    import json

    from app.agent.agents.lesson_plan.tools import lesson_plan_tool_schemas

    return json.dumps(
        lesson_plan_tool_schemas(
            getattr(agent, "allowed_tools", None),
            agent_key=getattr(agent, "key", None),
        ),
        ensure_ascii=False,
    )


def _role_context_text(runtime: LessonPlanAgentRuntime, agent_key: str) -> str:
    content = runtime.builder.to_content() if runtime.builder else {}
    outline = (content.get("outline") or {}).get("sections") or []
    core = content.get("pedagogical_core") or {}
    payload: dict[str, Any] = {
        "intent": runtime.resolved_intent.model_dump() if runtime.resolved_intent else {"intent": runtime.active_intent},
        "selected_section_ids": list(runtime.selected_section_ids),
        "execution_scope_ids": list(runtime.execution_scope_ids()),
    }
    snapshot = getattr(runtime, "context_snapshot", None)
    if snapshot is not None:
        payload["context_snapshot"] = {
            "snapshot_id": getattr(snapshot, "snapshot_id", ""),
            "snapshot_hash": getattr(snapshot, "snapshot_hash", ""),
            "source_version": getattr(snapshot, "source_version", ""),
            "requested_section_ids": list(getattr(snapshot, "requested_section_ids", []) or []),
            "resolved_section_ids": list(getattr(snapshot, "resolved_section_ids", []) or []),
            "preserved_section_ids": list(getattr(snapshot, "preserved_section_ids", []) or []),
            "fact_owner_map": dict(getattr(snapshot, "fact_owner_map", {}) or {}),
            "fact_to_section_ids": dict(getattr(snapshot, "fact_to_section_ids", {}) or {}),
            "all_section_ids": list(getattr(snapshot, "all_section_ids", []) or []),
        }
    if agent_key == "outline_architect":
        payload["outline"] = _outline_projection(outline)
    elif agent_key == "lesson_designer":
        payload["course_info"] = content.get("course_info") or {}
        payload["pedagogical_core"] = core
        visible_section_ids = set(runtime.execution_scope_ids())
        if runtime.content_policy == "preserve":
            visible_section_ids.update(runtime.content_mutable_section_ids(content))
            payload["content_policy"] = (
                "结构调整任务：未列入 mutable_sections 的已有章节正文必须逐字保留，"
                "不得修改 pedagogical_core。新增叶子章节完成前必须写入可见 blocks。"
            )
            payload["mutable_section_ids"] = sorted(visible_section_ids)
        if visible_section_ids:
            payload["selected_sections"] = [
                runtime.builder.find_section(section_id)
                for section_id in visible_section_ids
                if runtime.builder.find_section(section_id) is not None
            ]
    elif agent_key == "finalizer":
        payload["outline_summary"] = [
            {"id": item.get("id"), "title": item.get("title"), "coverage_refs": item.get("coverage_refs", [])}
            for item in outline
        ]
        payload["blocking_issues"] = list(runtime.blocking_issues)
        payload["diff_summary"] = diff_lesson_plans(runtime.baseline_content or content, content)
    else:
        payload["outline_summary"] = [
            {"id": item.get("id"), "title": item.get("title"), "coverage_refs": item.get("coverage_refs", [])}
            for item in outline
        ]
    return _bounded_json(payload, 14_000)


def _outline_projection(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "coverage_refs": list(item.get("coverage_refs") or []),
            "children": _outline_projection(list(item.get("children") or [])),
        }
        for item in sections
    ]


def _walk_outline(sections: list[dict[str, Any]]):
    for item in sections:
        yield item
        yield from _walk_outline(list(item.get("children") or []))


def _compact_json_value(
    value: Any, *, string_limit: int = 600, list_limit: int = 12, dict_limit: int = 24,
) -> Any:
    if isinstance(value, str):
        return value if len(value) <= string_limit else value[: string_limit - 1] + "…"
    if isinstance(value, list):
        return [
            _compact_json_value(
                item, string_limit=string_limit, list_limit=list_limit, dict_limit=dict_limit,
            )
            for item in value[:list_limit]
        ]
    if isinstance(value, dict):
        return {
            str(key): _compact_json_value(
                child, string_limit=string_limit, list_limit=list_limit, dict_limit=dict_limit,
            )
            for key, child in list(value.items())[:dict_limit]
        }
    return value


def _bounded_json(payload: dict[str, Any], limit: int) -> str:
    """Return valid JSON within a character budget; never slice serialized JSON."""
    import json

    for string_limit, list_limit in ((1200, 24), (600, 12), (300, 8), (120, 4)):
        compacted = _compact_json_value(
            payload, string_limit=string_limit, list_limit=list_limit,
        )
        text = json.dumps(compacted, ensure_ascii=False, default=str)
        if len(text) <= limit:
            return text
    fallback = {
        "truncated": True,
        "available_keys": list(payload)[:20],
        "summary": str(payload)[: max(0, limit - 200)],
    }
    text = json.dumps(fallback, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return json.dumps({"truncated": True}, ensure_ascii=False)


def _priority_json(fields: list[tuple[str, Any]], limit: int) -> str:
    """Admit already-compacted fields in priority order while keeping valid JSON."""
    import json

    accepted: dict[str, Any] = {}
    omitted: list[str] = []
    for key, value in fields:
        candidate = {**accepted, key: value}
        if len(json.dumps(candidate, ensure_ascii=False, default=str)) <= limit:
            accepted[key] = value
        else:
            omitted.append(key)
    if omitted:
        candidate = {**accepted, "omitted_low_priority_fields": omitted}
        if len(json.dumps(candidate, ensure_ascii=False, default=str)) <= limit:
            accepted = candidate
    return json.dumps(accepted, ensure_ascii=False, default=str)


def _knowledge_records_summary(value: Any) -> Any:
    """Reduce material/sibling payloads to identity and a bounded summary."""
    if isinstance(value, list):
        return [_knowledge_records_summary(item) for item in value[:8]]
    if isinstance(value, dict):
        identity = {
            key: value.get(key)
            for key in ("id", "type", "artifact_type", "title", "name", "version", "summary")
            if value.get(key) not in (None, "")
        }
        if identity:
            return _compact_json_value(identity, string_limit=300, list_limit=6)
        return {
            str(key): _knowledge_records_summary(child)
            for key, child in list(value.items())[:8]
        }
    return _compact_json_value(value, string_limit=300, list_limit=6)


def _compact_context_text(runtime: LessonPlanAgentRuntime, agent_key: str) -> str:
    """Build priority-ordered, valid JSON without starving recent tool results."""

    bp = runtime.context.blueprint if runtime.context is not None else {}
    bp = bp.model_dump() if hasattr(bp, "model_dump") else (bp or {})
    blueprint_summary = {
        "course_identity": bp.get("course_identity", {}),
        "objectives": [
            {"id": item.get("id"), "behavior": item.get("behavior", "")}
            for item in bp.get("objectives", [])
        ],
        "knowledge_points": [
            {"id": item.get("id"), "name": item.get("name", "")}
            for item in bp.get("knowledge_points", [])
        ],
        "timeline": [
            {"segment_id": item.get("segment_id"), "name": item.get("name"), "duration_minutes": item.get("duration_minutes")}
            for item in bp.get("timeline", [])
        ],
    }
    results = []
    successful_tools: list[str] = []
    for block in runtime.context.tool_results[-6:]:
        if block.agent_key not in {"", agent_key}:
            continue
        if isinstance(block.payload, dict) and block.payload.get("ok") is True:
            successful_tools.append(block.tool_name)
        results.append({
            "tool": block.tool_name,
            "result_json": _bounded_json({"result": block.payload}, 900),
        })
    successful_tools = list(dict.fromkeys(successful_tools))
    profile = getattr(getattr(runtime, "profile", None), "context_json", None) or {}
    knowledge = runtime.knowledge_context or {}
    knowledge_summary = {
        "materials": _knowledge_records_summary(knowledge.get("materials") or []),
        "siblings": _knowledge_records_summary(
            knowledge.get("sibling_artifacts") or knowledge.get("upstream") or {}
        ),
        "hard_dependencies": _knowledge_records_summary(knowledge.get("hard_dependencies") or {}),
    }
    fields = [
        ("user_instruction", _compact_json_value(runtime.context.user_instruction, string_limit=3000)),
        ("intent", _compact_json_value(
            runtime.resolved_intent.model_dump() if runtime.resolved_intent else {"intent": runtime.active_intent},
            string_limit=500, list_limit=12,
        )),
        ("recent_tool_results", results),
        ("successfully_obtained_tools", successful_tools),
        ("runtime_notes", [_compact_json_value(note, string_limit=500) for note in runtime.context.extra_notes[-4:]]),
        ("blueprint", _compact_json_value(blueprint_summary, string_limit=500, list_limit=16)),
        ("profile_summary", _compact_json_value(profile, string_limit=300, list_limit=8)),
        ("locked_paths", [getattr(lock, "json_path", "") for lock in runtime.locks]),
        ("knowledge_summary", knowledge_summary),
    ]
    return _priority_json(fields, 12_000)


async def _stream_agent_decision(runtime: LessonPlanAgentRuntime, agent_key: str, system: str, prompt: str) -> AgentDecision:
    from app.agent.core.loop import _stream_agent_decision as generic_stream

    return await generic_stream(runtime, agent_key, system, prompt)


def estimate_context_tokens(text: str) -> int:
    from app.agent.context import estimate_tokens

    return estimate_tokens(text)


def _retry_classifier(exc: Exception) -> bool:
    if isinstance(exc, AgentError):
        return exc.retryable
    return False


async def _persist_artifact(runtime: LessonPlanAgentRuntime, agent_key: str, decision: AgentDecision, step_index: int) -> str | None:
    """把 completed 决策的 output 持久化为流水线 Artifact。"""
    if decision.completed_artifact_id:
        return decision.completed_artifact_id
    if not decision.completed or decision.output is None:
        return None
    produced = None
    from app.agent.agents.lesson_plan.agents import PRODUCED_BY_KEY

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
