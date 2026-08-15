"""视频脚本 Agent Runtime：意图 → 计划 → 工具循环 → QA → 返修 → 发布。

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
from typing import Any

from app.agent.agents.video_script.agents import (
    AGENT_BY_KEY, FINALIZER, PRODUCTION_QA, REPAIR_ROUTER,
    ensure_video_script_agents, is_mock_provider, video_script_spec,
)
from app.agent.agents.video_script.builder import (
    VideoScriptBuilder, build_initial_builder, upgrade_builder,
)
from app.agent.agents.video_script.intents import (
    INTENT_AGENT_ALIASES, VideoScriptIntentDecision, agent_chain_for_intent,
    infer_video_script_intent,
)
from app.agent.agents.video_script.qa import blocking_issues as _blocking
from app.agent.agents.video_script.qa import fingerprint as _fingerprint
from app.agent.agents.video_script.qa import validate_video_script_v4
from app.agent.core.error import AgentError
from app.agent.core.loop import run_agent_loop
from app.agent.core.state import AgentRuntimeState
from app.agent.registry import ToolContext, execute_tool, summarize
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.video_script_v4 import VIDEO_SCRIPT_V4, SeedanceVideoScriptContentV4

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 2  # QA 返修最多 2 轮


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
            builder = build_initial_builder(bp_content, lesson_plan_raw)
        self.builder = builder
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

    # ------------------------------------------------------------------
    # 意图与计划
    # ------------------------------------------------------------------

    async def _resolve_intent(self) -> VideoScriptIntentDecision:
        instruction = self.context.user_instruction or ""
        mode = (self.request_metadata or {}).get("mode")
        decision = await infer_video_script_intent(
            self.provider, self.trigger_type, instruction,
            self.selected_section_ids or None, self.selected_scene_ids or None, mode,
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
                    "target_section_ids": decision.target_section_ids,
                    "target_scene_ids": decision.target_scene_ids,
                    "assumptions": decision.assumptions,
                    "plan_steps": decision.plan_steps,
                    "acceptance_criteria": decision.acceptance_criteria,
                    "visible_summary": decision.visible_summary,
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

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await self._prepare()
        if self.emitter is not None:
            await self.emitter.pipeline_started(self.trigger_type)
        intent_decision = await self._resolve_intent()
        # 关键歧义：只返回澄清问题，不修改文件；本轮不创建版本。
        if intent_decision.intent == "CLARIFICATION_REQUIRED":
            if self.emitter is not None:
                await self.emitter.emit_domain(
                    "intent.recognized",
                    agent={"id": "intent_planner"},
                    message="需要教师澄清后再继续",
                    payload={"intent": "CLARIFICATION_REQUIRED",
                             "clarification_question": intent_decision.clarification_question},
                )
            self.result_status = "needs_confirmation"
            self.dialogue_summary = (
                f"为准确完成任务，请补充说明：{intent_decision.clarification_question or '你的修改目标'}"
            )
            return
        # ANSWER_ONLY：读取与分析后直接回答，不创建新版本。
        if intent_decision.intent == "ANSWER_ONLY":
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
        self.repair_fingerprint = ""
        await self._run_with_repair(chain)
        await self._finalize()

    def _answer_only_reply(self) -> str:
        builder = self.builder
        if builder is None:
            return "视频脚本尚未生成。"
        content = builder.to_content()
        sections = content.get("outline", {}).get("sections", [])
        scenes = content.get("scenes", [])
        minutes = round(float(content.get("course_info", {}).get("duration_seconds", 0)) / 60, 1)
        return (
            f"当前视频脚本共 {len(sections)} 个动态章节、{len(scenes)} 个分镜，"
            f"总时长约 {minutes} 分钟。如需调整章节结构或分镜内容，请直接告诉我。"
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
                logger.info("视频脚本返修指纹重复，停止空转（round=%s）", round_index)
                return
            self.repair_fingerprint = fp
            if round_index >= self.max_revision_rounds - 1:
                return
            # repair_router 路由重跑范围（确定性控制节点）。
            repair_decision = await REPAIR_ROUTER.decide(self.tool_context)
            repair_agents = (repair_decision.output or {}).get("plan") or ["script_director", "production_qa"]
            if self.emitter is not None:
                await self.emitter.revision_started(
                    round_index + 1, self.max_revision_rounds,
                    reason="视频脚本质询存在阻断问题", target_agents=repair_agents,
                )
            plan = self._build_plan([*repair_agents, "finalizer"])
            if self.emitter is not None:
                await self.emitter.revision_completed(round_index + 1, applied_changes=repair_agents)

    async def _collect_qa_issues(self) -> None:
        """从 production_qa 产物读取阻断问题（LLM 或 Mock 均已写入 production_qa）。"""
        if self.artifacts is None:
            self.blocking_issues = []
            return
        qa = await self.artifacts.latest("video_script_qa")
        if not qa:
            # 兼容：QA Agent 通过工具产出但未落产物时，直接对候选稿跑确定性门禁。
            bp = self.blueprint.content_json if hasattr(self.blueprint, "content_json") else self.blueprint
            locked_paths = [getattr(lock, "json_path", "") for lock in self.locks]
            try:
                issues = validate_video_script_v4(
                    CourseBlueprintSchema.model_validate(bp),
                    self.builder.to_content() if self.builder else {},
                    self._lesson_plan_raw(), locked_paths,
                    max_scene_seconds=float((self.request_metadata or {}).get("renderer_max_scene_seconds") or 15),
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


async def _call_agent(runtime: VideoScriptAgentRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用角色：Mock/控制节点走确定性 decide；LLM 走 stream_decision 流式思考。"""
    if is_mock_provider(runtime.provider) or agent_key in {"repair_router", "production_qa"}:
        decision = await agent.decide(runtime.tool_context)
        if runtime.emitter is not None and decision.message:
            await runtime.emitter.agent_status_delta(agent_key, decision.message)
            await runtime.emitter.agent_thought_chunk(agent_key, decision.message, flush_now=True)
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
    from app.agent.core.loop import _stream_agent_decision as generic_stream

    return await generic_stream(runtime, agent_key, system, prompt)


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
