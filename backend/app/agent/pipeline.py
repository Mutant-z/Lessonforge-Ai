"""PPT Agent 流水线编排器。

- build_plan：按触发类型构建执行计划（AgentSpec 序列）
- run_agent_loop：顺序执行每个 Agent（内部小循环：工具调用 → 完成）
- run_revision_loop：QA 发现 critical/major 问题 → 修订 Agent 路由 → 重跑受影响 Agent → 再 QA（≤max_rounds）
- finalize：把 builder 输出组装为合法 PPTContent（锁定还原 + 确定性修复）
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState, estimate_tokens
from app.agent.definitions import AGENT_BY_KEY, agent_specs_for_trigger
from app.agent.events import PipelineEventEmitter
from app.agent.registry import ToolContext, execute_tool, summarize
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan
from app.core.database import SessionLocal
from app.models.entities import GenerationRun, GenerationStep, PipelineRun
from app.providers.llm.mock import MockProvider

logger = logging.getLogger(__name__)

MAX_TOTAL_STEPS = 40
MAX_ESTIMATED_TOKENS = 60_000
RETRY_ATTEMPTS = 2


class PipelinePaused(Exception):
    """Agent 边界暂停信号（由 execute_task_run 捕获持久化为 paused）。"""


@dataclass
class PipelineRuntime:
    """一次流水线运行的全部共享状态。"""

    course: Any
    task: Any
    blueprint: Any
    generation_run: GenerationRun
    pipeline_run: PipelineRun
    profile: Any
    provider: Any
    config: Any
    knowledge_context: dict[str, Any]
    source_versions: dict[str, Any]
    locks: list[Any]
    source_artifact: Any = None
    user_message: Any = None
    preferred_template: str = "lessonforge_deck_academic"
    trigger_type: str = "initial"

    context: ContextState = field(default_factory=ContextState)
    builder: Any = None
    artifacts: PipelineArtifactManager | None = None
    emitter: PipelineEventEmitter | None = None
    tool_context: ToolContext | None = None
    workspace_root: Any = None
    pause_event: asyncio.Event | None = None
    token_usage: dict[str, Any] = field(default_factory=lambda: {"llm_calls": 0, "tokens": 0})
    _steps: int = 0
    current_agent_key: str = ""
    checkpoint_start: int = 0

    def request_pause(self):
        if self.pause_event is not None:
            self.pause_event.set()

    def pause_requested(self) -> bool:
        return self.pause_event is not None and self.pause_event.is_set()


def build_plan(runtime: PipelineRuntime, trigger: str) -> PipelinePlan:
    """构建执行计划（初始/同步 → 完整流水线；消息/同步上下文 → 精简）。"""
    from app.agent.definitions import agent_specs_for_trigger, spec_for
    keys = agent_specs_for_trigger(trigger)
    return PipelinePlan(agents=[AgentSpec(**spec_for(key)) for key in keys], revision_rounds=runtime.pipeline_run.max_revision_rounds)


def _mock_mode(runtime: PipelineRuntime) -> bool:
    return isinstance(runtime.provider, MockProvider)


async def _agent_call(runtime: PipelineRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用 Agent：Mock 走确定性 decide（合成思考增量），LLM 走 stream_decision（流式思考 → 决策）。"""
    tc = runtime.tool_context
    if _mock_mode(runtime):
        decision = await agent.decide(tc)
        if runtime.emitter is not None and decision.message:
            # 合成流式思考：把 mock Agent 的可见消息推送为一段思考文本（前端打字机负责逐字渲染）
            await runtime.emitter.agent_thought_chunk(agent_key, decision.message, flush_now=True)
        return decision
    system = agent.build_system_prompt(tc)
    prompt = (
        "上下文：\n" + runtime.context.to_prompt(agent_key)
        + "\n可用工具 Schema：\n" + _tool_schemas_text(runtime)
        + "\n请先输出 thinking 字段（一段 Markdown 思考过程，说明你如何分析任务、下一步要做什么），"
        "再输出决策：要么给出一批 tool_calls，要么 completed（含 output/summary）。"
        "只返回一个 AgentDecision JSON。"
    )
    runtime.token_usage["tokens"] += estimate_tokens(prompt)
    runtime.token_usage["llm_calls"] += 1
    decision = await _stream_agent_decision(runtime, agent_key, system, prompt)
    if runtime.emitter is not None:
        await runtime.emitter.flush_thought()
    return decision


async def _stream_agent_decision(runtime: PipelineRuntime, agent_key: str, system: str, prompt: str) -> AgentDecision:
    """流式获取 AgentDecision：监听 thought_delta → 推送 SSE；decision_ready → 返回决策。

    流式不可用时（旧 provider 无 stream_decision / 异常）回退到阻塞式 structured()。
    """
    stream_method = getattr(runtime.provider, "stream_decision", None)
    if stream_method is None:
        return await runtime.provider.structured(system, prompt, AgentDecision)
    decision: AgentDecision | None = None
    try:
        async for kind, payload in stream_method(system, prompt, AgentDecision):
            if kind == "thought_delta" and runtime.emitter is not None and payload:
                await runtime.emitter.agent_thought_chunk(agent_key, str(payload))
            elif kind == "decision_ready":
                decision = payload
    except Exception as exc:  # noqa: BLE001 流式异常回退阻塞式
        logger.warning("Agent %s 流式决策失败，回退 structured：%s", agent_key, exc)
    if decision is None:
        decision = await runtime.provider.structured(system, prompt, AgentDecision)
    return decision


def _tool_schemas_text(runtime: PipelineRuntime) -> str:
    from app.agent.registry import all_tool_schemas
    import json
    return json.dumps(all_tool_schemas(), ensure_ascii=False)


async def _checkpoint_agent(runtime: PipelineRuntime, agent_key: str, decision: AgentDecision, step_index: int, artifact_id: str | None):
    """Agent 完成时写入 checkpoint + generation_steps（单事务）。"""
    runtime.context.decisions.append({
        "agent": agent_key, "summary": decision.summary, "artifact_id": artifact_id,
    })
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, runtime.pipeline_run.id)
        if row:
            row.current_agent = agent_key
            row.current_step_index = step_index + 1
            row.status = "running"
            row.checkpoint_json = {
                "step_index": step_index + 1,
                "produced_artifact_ids": [artifact_id] if artifact_id else [],
                "context_hash": runtime.context.context_hash(),
                "user_instruction": runtime.context.user_instruction,
                "revision_round": row.revision_round,
                "locks": [getattr(lock, "json_path", "") for lock in runtime.locks],
                "agents_done": [item["agent"] for item in runtime.context.decisions],
            }
            row.token_usage_json = runtime.token_usage
            await db.commit()
        gen_step = GenerationStep(
            run_id=runtime.generation_run.id,
            node_name=agent_key,
            status="completed",
            output_ref=artifact_id,
            duration_ms=int(decision.__dict__.get("_duration_ms", 0) or 0),
        )
        db.add(gen_step)
        await db.commit()


async def _persist_decision_artifact(runtime: PipelineRuntime, agent_key: str, decision: AgentDecision, step_index: int) -> str | None:
    """把 completed 决策的 output 持久化为 Agent 产出的 Artifact。"""
    if not decision.completed or decision.output is None:
        return None
    produced = AGENT_BY_KEY[agent_key].produced_artifacts
    artifact_type = produced[0] if produced else "note"
    artifact = await runtime.artifacts.create(
        artifact_type, "default", decision.output,
        producer_agent=agent_key, step_index=step_index,
    )
    if runtime.emitter is not None:
        await runtime.emitter.artifact_created(artifact_type, artifact["id"], artifact["name"], artifact["version"], producer_agent=agent_key, file_path=artifact["file_path"])
    return artifact["id"]


async def _execute_tool_call(runtime: PipelineRuntime, agent_key: str, call, tool_context: ToolContext) -> None:
    started = time.monotonic()
    await runtime.emitter.tool_call_started(agent_key, call.tool_name, call.id, input_summary=summarize(call.input, 200))
    async with SessionLocal() as db:
        db.add(_tool_call_row(runtime, agent_key, call, status="started"))
        await db.commit()
    result = await execute_tool(call.tool_name, tool_context, call.input)
    duration_ms = int((time.monotonic() - started) * 1000)
    runtime.context.append_tool_result(call.id, agent_key, call.tool_name, result.output, result.error)
    await runtime.emitter.tool_call_completed(agent_key, call.tool_name, call.id, result.ok,
                                              output_summary=summarize(result.output, 300), duration_ms=duration_ms, error=result.error)
    async with SessionLocal() as db:
        row = await db.scalar(select(_tool_call_model()).where(_tool_call_model().id == call.id))
        if row:
            row.status = "completed" if result.ok else "failed"
            row.output_json = result.output
            row.duration_ms = duration_ms
            row.error_json = {"message": result.error} if result.error else None
            await db.commit()


def _tool_call_row(runtime: PipelineRuntime, agent_key: str, call, status: str):
    from app.models.entities import PipelineToolCall
    return PipelineToolCall(
        id=call.id, pipeline_run_id=runtime.pipeline_run.id, agent_key=agent_key,
        tool_name=call.tool_name, input_json=call.input, output_json={}, status=status,
    )


def _tool_call_model():
    from app.models.entities import PipelineToolCall
    return PipelineToolCall


async def run_agent_loop(runtime: PipelineRuntime, plan: PipelinePlan, start_step: int | None = None) -> None:
    """顺序执行计划中的每个 Agent（每个 Agent 内部小循环：工具调用 → 完成）。"""
    tc = runtime.tool_context
    if start_step is None:
        start_step = runtime.checkpoint_start
    for step_index in range(start_step, len(plan.agents)):
        spec = plan.agents[step_index]
        if runtime.pause_requested():
            await _persist_paused(runtime, step_index, spec.key)
            raise PipelinePaused()
        agent = AGENT_BY_KEY[spec.key]
        runtime.current_agent_key = spec.key
        if tc.ctx is not None:
            tc.ctx.current_agent = spec.key
        await runtime.emitter.agent_started(spec.key, agent.name, step_index, progress=10 + step_index * 5)
        step_started = time.monotonic()
        completed_artifact_id = None
        tool_rounds = 0
        while tool_rounds < spec.max_steps:
            runtime._steps += 1
            if runtime._steps > MAX_TOTAL_STEPS:
                raise RuntimeError(f"流水线超过最大步骤数 {MAX_TOTAL_STEPS}")
            if estimate_tokens(runtime.context.to_prompt(spec.key)) > MAX_ESTIMATED_TOKENS:
                raise RuntimeError("流水线上下文超过 token 估算上限")
            if runtime.pause_requested():
                await _persist_paused(runtime, step_index, spec.key)
                raise PipelinePaused()
            decision = None
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    decision = await _agent_call(runtime, spec.key, agent, tool_rounds)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning("Agent %s 调用重试：%s", spec.key, exc)
            if decision is None:
                raise RuntimeError(f"Agent {spec.key} 调用失败")
            decision.__dict__["_duration_ms"] = int((time.monotonic() - step_started) * 1000)
            if decision.tool_calls:
                for call in decision.tool_calls:
                    await _execute_tool_call(runtime, spec.key, call, tc)
                tool_rounds += 1
                continue
            if decision.completed:
                completed_artifact_id = await _persist_decision_artifact(runtime, spec.key, decision, step_index)
                await _checkpoint_agent(runtime, spec.key, decision, step_index, completed_artifact_id)
                await runtime.emitter.agent_completed(spec.key, decision.summary,
                                                      duration_ms=int(decision.__dict__.get("_duration_ms", 0)),
                                                      artifact_id=completed_artifact_id)
                break
        # while 结束但未 completed（超过 max_steps 且一直工具调用）→ 视为完成并持久化当前产物
        if not decision or not decision.completed:
            await runtime.emitter.agent_completed(spec.key, "已达工具轮次上限，跳过该 Agent 输出", artifact_id=completed_artifact_id)


async def _persist_paused(runtime: PipelineRuntime, step_index: int, agent_key: str):
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, runtime.pipeline_run.id)
        if row:
            row.status = "paused"
            row.current_agent = agent_key
            row.current_step_index = step_index
            row.checkpoint_json = {**row.checkpoint_json, "step_index": step_index, "paused_agent": agent_key}
            await db.commit()


async def run_revision_loop(runtime: PipelineRuntime, plan: PipelinePlan) -> None:
    """执行计划并处理 QA → 修订闭环（修订 Agent 路由，≤max_revision_rounds）。"""
    from app.agent.agents.revision import REVISION_AGENT
    from app.renderers.presentation_builder import PresentationBuilder
    max_rounds = plan.revision_rounds
    await run_agent_loop(runtime, plan)
    for round_index in range(1, max_rounds + 1):
        qa_artifact = await runtime.artifacts.latest("visual_qa") if runtime.artifacts else None
        if not qa_artifact:
            break
        issues = [item for item in (qa_artifact.get("data") or {}).get("issues", [])
                  if item.get("severity") in {"critical", "major"}]
        if not issues:
            break
        reason = "；".join(item.get("message", "")[:80] for item in issues[:3])
        revision_decision = await REVISION_AGENT.decide(runtime.tool_context)
        target_agents = list((revision_decision.output or {}).get("target_agents") or [])
        if not target_agents:
            break
        await runtime.emitter.revision_started(round_index, max_rounds, reason=reason, target_agents=target_agents)
        # 重建 builder，让受影响 Agent 从最新 Artifact 重跑并重建页面
        runtime.builder = PresentationBuilder(runtime.preferred_template)
        runtime.tool_context.builder = runtime.builder
        sub_plan = PipelinePlan(
            agents=[_spec(agent_key) for agent_key in [*target_agents, "ppt_editor", "visual_qa"]],
            revision_rounds=max_rounds,
        )
        await run_agent_loop(runtime, sub_plan, start_step=0)
        await runtime.emitter.revision_completed(round_index, applied_changes=[f"重跑 {key}" for key in target_agents])


def _spec(agent_key: str) -> AgentSpec:
    info = AGENT_BY_KEY[agent_key]
    return AgentSpec(key=agent_key, role=info.role, description=info.description, max_steps=8)


def finalize_content(runtime: PipelineRuntime) -> dict[str, Any]:
    """把 builder 输出组装为合法 PPTContent（锁定还原 + 确定性修复 + 主题固定）。"""
    from app.renderers.presentation_builder import PresentationBuilder
    content = runtime.builder.to_ppt_content() if runtime.builder is not None else {}
    if not content.get("slides"):
        # builder 未构建（例如仅修订路径）→ 回退 source 内容
        if runtime.source_artifact is not None:
            content = dict(getattr(runtime.source_artifact, "content_json", {}))
    content["theme"] = runtime.preferred_template
    # 锁定路径还原
    if runtime.locks:
        from app.services.course_task_service import _restore_locked_paths
        source = getattr(runtime.source_artifact, "content_json", {}) if runtime.source_artifact else {}
        content = _restore_locked_paths(content, source, runtime.locks)
    # 确定性修复（结构 + 知识规则）
    from app.services.course_task_service import _validate_and_repair_ppt
    repaired, _ = _validate_and_repair_ppt(content)
    return repaired if repaired is not None else content
