"""通用 Agent 顺序执行器。

从 app/agent/pipeline.py 的 run_agent_loop 骨架抽取领域无关部分：
- 工具轮次上限（默认 8）、总步数上限（40）、token 估算上限；
- 暂停安全边界（Agent 边界 / 决策前后 / 每次工具调用前）；
- handoff 归一化、artifact 持久化、checkpoint 落库、决策失败有限重试。

领域差异通过参数注入：
- agent_registry：{key -> Agent 实例}；
- call_agent：一次 Agent 决策调用（Mock 走 decide，LLM 走 stream_decision）；
- persist_artifact：completed 决策的 output 持久化（领域产物合并/作用域过滤）；
- retry_classifier：决定调用异常是否重试（默认全部不重试，直接抛错）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Awaitable, Callable
from uuid import uuid4

from sqlalchemy import select

from app.agent.context import estimate_tokens
from app.agent.core.error import AgentError
from app.agent.pipeline import PipelinePaused
from app.agent.core.state import AgentRuntimeState
from app.agent.registry import ToolContext, execute_tool, get_tool, summarize
from app.agent.schemas import AgentDecision, AgentSpec, PipelinePlan, ToolCall, ToolResult
from app.core.database import SessionLocal
from app.models.entities import GenerationStep, PipelineRun, PipelineToolCall

logger = logging.getLogger(__name__)

MAX_TOTAL_STEPS = 40
MAX_ESTIMATED_TOKENS = 60_000
RETRY_ATTEMPTS = 2


def normalize_handoff(
    value: str | None,
    valid_keys: set[str],
    aliases: dict[str, str] | None = None,
) -> str | None:
    """把模型使用的角色名/能力名转换为可执行 Agent key。"""
    if not value:
        return None
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    canonical = (aliases or {}).get(key, key)
    return canonical if canonical in valid_keys else None


async def _stream_agent_decision(
    runtime: AgentRuntimeState, agent_key: str, system: str, prompt: str,
) -> AgentDecision:
    """流式获取 AgentDecision：thought_delta → SSE；decision_ready → 返回。

    流式不可用时回退到阻塞式 structured()。
    """
    provider = getattr(runtime, "provider", None)
    if provider is None:
        raise AgentError("provider_missing", "运行时缺少 LLM Provider。", retryable=False)
    stream_method = getattr(provider, "stream_decision", None)
    if stream_method is None:
        return await provider.structured(system, prompt, AgentDecision)
    decision: AgentDecision | None = None
    try:
        async for kind, payload in stream_method(system, prompt, AgentDecision):
            if kind == "thought_delta" and runtime.emitter is not None and payload:
                await runtime.emitter.agent_status_delta(agent_key, str(payload))
                await runtime.emitter.agent_thought_chunk(agent_key, str(payload))
            elif kind == "decision_ready":
                decision = payload
    except Exception as exc:  # noqa: BLE001  流式异常回退阻塞式
        logger.warning("Agent %s 流式决策失败，回退 structured：%s", agent_key, exc)
    if decision is None:
        decision = await provider.structured(system, prompt, AgentDecision)
    return decision


def _tool_schemas_text(runtime: AgentRuntimeState, agent=None) -> str:
    from app.agent.registry import all_tool_schemas
    import json

    return json.dumps(all_tool_schemas(getattr(agent, "allowed_tools", None)), ensure_ascii=False)


async def _checkpoint_agent(
    runtime: AgentRuntimeState,
    agent_key: str,
    decision: AgentDecision,
    step_index: int,
    artifact_id: str | None,
):
    """Agent 完成时写入 checkpoint + generation_steps（单事务）。"""
    runtime.context.decisions.append({
        "agent": agent_key, "summary": decision.summary, "artifact_id": artifact_id,
    })
    pipeline_run = getattr(runtime, "pipeline_run", None)
    generation_run = getattr(runtime, "generation_run", None)
    if pipeline_run is not None:
        async with SessionLocal() as db:
            row = await db.get(PipelineRun, pipeline_run.id)
            if row:
                row.current_agent = agent_key
                row.current_step_index = step_index + 1
                row.status = "running"
                checkpoint = {
                    **(row.checkpoint_json or {}),
                    "step_index": step_index + 1,
                    "produced_artifact_ids": [artifact_id] if artifact_id else [],
                    "context_hash": runtime.context.context_hash(),
                    "user_instruction": runtime.context.user_instruction,
                    "revision_round": row.revision_round,
                    "locks": [getattr(lock, "json_path", "") for lock in runtime.locks] if getattr(runtime, "locks", None) else [],
                    "agents_done": [item["agent"] for item in runtime.context.decisions],
                }
                checkpoint_hook = getattr(runtime, "checkpoint_payload", None)
                if callable(checkpoint_hook):
                    checkpoint.update(checkpoint_hook())
                row.checkpoint_json = checkpoint
                row.token_usage_json = runtime.token_usage
                await db.commit()
    if generation_run is not None:
        async with SessionLocal() as db:
            db.add(GenerationStep(
                run_id=generation_run.id,
                node_name=agent_key,
                status="completed",
                output_ref=artifact_id,
                duration_ms=int(decision.__dict__.get("_duration_ms", 0) or 0),
            ))
            await db.commit()


async def _persist_paused(runtime: AgentRuntimeState, step_index: int, agent_key: str):
    pipeline_run = getattr(runtime, "pipeline_run", None)
    if pipeline_run is None:
        return
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, pipeline_run.id)
        if row:
            row.status = "paused"
            row.current_agent = agent_key
            row.current_step_index = step_index
            checkpoint = {**(row.checkpoint_json or {}), "step_index": step_index, "paused_agent": agent_key}
            checkpoint_hook = getattr(runtime, "checkpoint_payload", None)
            if callable(checkpoint_hook):
                checkpoint.update(checkpoint_hook())
            row.checkpoint_json = checkpoint
            await db.commit()


def _tool_call_row(runtime: AgentRuntimeState, agent_key: str, call: ToolCall, execution_id: str, status: str):
    pipeline_run = getattr(runtime, "pipeline_run", None)
    return PipelineToolCall(
        id=execution_id, model_call_id=call.id,
        pipeline_run_id=pipeline_run.id if pipeline_run else "",
        agent_key=agent_key, tool_name=call.tool_name,
        input_json=call.input, output_json={}, status=status,
    )


async def _execute_tool_call(
    runtime: AgentRuntimeState,
    agent_key: str,
    call: ToolCall,
    tool_context: ToolContext,
    *,
    allowed_tools: set[str] | None = None,
    forced_result: ToolResult | None = None,
) -> ToolResult:
    started = time.monotonic()
    execution_id = str(uuid4())
    if runtime.emitter is not None:
        await runtime.emitter.tool_call_started(
            agent_key, call.tool_name, execution_id,
            input_summary=summarize(call.input, 200), input_json=call.input,
            model_call_id=call.id,
        )
    pipeline_run = getattr(runtime, "pipeline_run", None)
    if pipeline_run is not None:
        async with SessionLocal() as db:
            db.add(_tool_call_row(runtime, agent_key, call, execution_id, status="started"))
            await db.commit()
    if forced_result is not None:
        result = forced_result
    elif allowed_tools is not None and call.tool_name not in allowed_tools:
        result = ToolResult(
            ok=False,
            error=f"Agent {agent_key} 无权调用工具 {call.tool_name}",
            error_code="tool_not_allowed",
            retryable=False,
        )
    else:
        # 暴露当前工具名，供领域工具构造 MutationReceipt 使用。
        if tool_context is not None:
            tool_context._current_tool_name = call.tool_name
        result = await execute_tool(call.tool_name, tool_context, call.input)
    duration_ms = int((time.monotonic() - started) * 1000)
    runtime.context.append_tool_result(
        execution_id, agent_key, call.tool_name, result.output, result.error,
        result.error_code, result.retryable,
    )
    if runtime.emitter is not None:
        await runtime.emitter.tool_call_completed(
            agent_key, call.tool_name, execution_id, result.ok,
            output_summary=summarize(result.output, 300), duration_ms=duration_ms,
            error=result.error, output_json=result.output, model_call_id=call.id,
            error_code=result.error_code, retryable=result.retryable,
        )
    if pipeline_run is not None:
        async with SessionLocal() as db:
            row = await db.scalar(select(PipelineToolCall).where(PipelineToolCall.id == execution_id))
            if row:
                row.status = "completed" if result.ok else "failed"
                row.output_json = result.output
                row.duration_ms = duration_ms
                row.error_json = {
                    "message": result.error, "code": result.error_code, "retryable": result.retryable,
                } if result.error else None
                await db.commit()
    failure_key = f"{agent_key}:{call.tool_name}"
    if result.ok:
        runtime.unresolved_tool_failures.pop(failure_key, None)
    else:
        runtime.unresolved_tool_failures[failure_key] = {
            "agent_key": agent_key,
            "tool_name": call.tool_name,
            "error_code": result.error_code,
            "message": result.error,
            "retryable": result.retryable,
        }
        # 致命工具错误（不可重试的契约/守卫错误）：
        # 允许 LLM 进行 1~2 次 Reflection 自愈，避免单次参数/路径小偏差导致直接硬中断
        fatal_codes = getattr(runtime, "fatal_tool_error_codes", frozenset()) or frozenset()
        if result.error_code in fatal_codes:
            consecutive_fatal = runtime.agent_stats.setdefault(agent_key, {}).get("consecutive_fatal_errors", 0) + 1
            runtime.agent_stats[agent_key]["consecutive_fatal_errors"] = consecutive_fatal
            allow_self_correction = getattr(runtime, "allow_fatal_self_correction", True)
            if not allow_self_correction or consecutive_fatal > 2:
                raise AgentError(
                    "fatal_tool_error",
                    _fatal_tool_error_message(agent_key, call.tool_name, result),
                    retryable=False,
                    details={
                        "agent_key": agent_key,
                        "tool_name": call.tool_name,
                        "error_code": result.error_code,
                        "requested_target": (result.output or {}).get("requested_target"),
                        "allowed_scope": (result.output or {}).get("allowed_scope"),
                        "suggestion": (result.output or {}).get("suggestion"),
                        "message": result.error,
                    },
                )
            else:
                runtime.context.add_note(
                    f"【操作契约提示】Agent {agent_key} 调用 {call.tool_name} 被限制（{result.error_code}）："
                    f"{result.error or '修改超出本轮契约允许范围'}。"
                    f"建议：{(result.output or {}).get('suggestion') or '请根据教学目标调整修改目标或调用其他工具进行自愈修复。'}"
                )
    return result


def _fatal_tool_error_message(agent_key: str, tool_name: str, result: ToolResult) -> str:
    """面向用户的清晰拒绝文案：目标/范围/建议，不再泛化为“无进展”。"""
    details = result.output or {}
    target = details.get("requested_target")
    scope = details.get("allowed_scope")
    suggestion = details.get("suggestion")
    parts = [
        f"Agent {agent_key} 调用 {tool_name} 被拒绝（{result.error_code}）："
        f"{result.error or '修改超出本轮修改契约允许范围'}。"
    ]
    if target:
        parts.append(f"请求目标：{target}。")
    if scope:
        parts.append(f"允许范围：{scope}。")
    if suggestion:
        parts.append(f"建议：{suggestion}。")
    parts.append("系统已停止重试，本轮修改未执行，原教学设计未改变。")
    return "".join(parts)


def _builder_state_fingerprint(tool_context: ToolContext) -> str:
    """Small stable fingerprint used by the idempotent-read no-progress guard."""
    builder = (tool_context.extra or {}).get("builder") if tool_context is not None else None
    if builder is None:
        builder = getattr(tool_context, "builder", None)
    if builder is None or not hasattr(builder, "to_content"):
        return ""
    try:
        raw = json.dumps(builder.to_content(), ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _repeat_signature(agent_key: str, call: ToolCall, tool_context: ToolContext) -> str:
    payload = json.dumps(call.input, ensure_ascii=False, sort_keys=True, default=str)
    return f"{agent_key}:{call.tool_name}:{payload}:{_builder_state_fingerprint(tool_context)}"


def _agent_stats(runtime: AgentRuntimeState, agent_key: str) -> dict[str, Any]:
    return runtime.agent_stats.setdefault(agent_key, {
        "decision_rounds": 0,
        "tool_calls": 0,
        "failed_tool_calls": 0,
        "repeated_tool_calls": 0,
        "cache_hits": 0,
        "no_progress_rounds": 0,
        "completed": False,
        "termination_reason": "",
    })


async def run_agent_loop(
    runtime: AgentRuntimeState,
    plan: PipelinePlan,
    *,
    agent_registry: dict[str, Any],
    call_agent: Callable[[AgentRuntimeState, str, Any, int], Awaitable[AgentDecision]],
    persist_artifact: Callable[[AgentRuntimeState, str, AgentDecision, int], Awaitable[str | None]],
    retry_classifier: Callable[[Exception], bool] | None = None,
    start_step: int | None = None,
) -> None:
    """顺序执行计划中的每个 Agent（每个 Agent 内部小循环：工具调用 → 完成）。"""
    tc = runtime.tool_context
    if start_step is None:
        start_step = runtime.checkpoint_start
    for step_index in range(start_step, len(plan.agents)):
        spec = plan.agents[step_index]
        if runtime.pause_requested():
            await _persist_paused(runtime, step_index, spec.key)
            raise PipelinePaused()
        agent = agent_registry[spec.key]
        stats = _agent_stats(runtime, spec.key)
        # A later repair pass is a new Agent execution; only consecutive
        # no-progress rounds inside this execution may trigger termination.
        runtime.no_progress_rounds[spec.key] = 0
        runtime.current_agent_key = spec.key
        if tc is not None and tc.ctx is not None:
            tc.ctx.current_agent = spec.key
        if runtime.emitter is not None:
            await runtime.emitter.agent_started(spec.key, agent.name, step_index, progress=10 + step_index * 5)
        step_started = time.monotonic()
        completed_artifact_id = None
        decision: AgentDecision | None = None
        tool_rounds = 0
        while tool_rounds < spec.max_steps:
            stats["decision_rounds"] += 1
            runtime._steps += 1
            if runtime._steps > MAX_TOTAL_STEPS:
                raise RuntimeError(f"流水线超过最大步骤数 {MAX_TOTAL_STEPS}")
            max_context_tokens = getattr(runtime, "max_context_tokens", MAX_ESTIMATED_TOKENS)
            if max_context_tokens and estimate_tokens(runtime.context.to_prompt(spec.key)) > max_context_tokens:
                runtime.termination_reason = "agent_context_budget_exceeded"
                stats["termination_reason"] = runtime.termination_reason
                raise AgentError("agent_context_budget_exceeded", "流水线上下文超过 token 估算上限", retryable=True)
            max_estimated_tokens = getattr(runtime, "max_estimated_tokens", MAX_ESTIMATED_TOKENS)
            if max_estimated_tokens and int(runtime.token_usage.get("tokens", 0) or 0) > max_estimated_tokens:
                runtime.termination_reason = "agent_token_budget_exceeded"
                stats["termination_reason"] = runtime.termination_reason
                raise AgentError("agent_token_budget_exceeded", "流水线累计 token 估算超过 60000", retryable=True)
            if runtime.pause_requested():
                await _persist_paused(runtime, step_index, spec.key)
                raise PipelinePaused()
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    decision = await call_agent(runtime, spec.key, agent, tool_rounds)
                    max_estimated_tokens = getattr(runtime, "max_estimated_tokens", MAX_ESTIMATED_TOKENS)
                    if max_estimated_tokens and int(runtime.token_usage.get("tokens", 0) or 0) > max_estimated_tokens:
                        runtime.termination_reason = "agent_token_budget_exceeded"
                        stats["termination_reason"] = runtime.termination_reason
                        raise AgentError("agent_token_budget_exceeded", "流水线累计 token 估算超过 60000", retryable=True)
                    break
                except Exception as exc:  # noqa: BLE001
                    retryable = retry_classifier(exc) if retry_classifier is not None else False
                    if not retryable or attempt == RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning("Agent %s 调用重试：%s", spec.key, exc)
            if decision is None:
                raise RuntimeError(f"Agent {spec.key} 调用失败")
            # 暂停可能在 LLM 请求期间到达；在执行任何 Tool 副作用前进入安全暂停点。
            if runtime.pause_requested():
                await _persist_paused(runtime, step_index, spec.key)
                raise PipelinePaused()
            decision.__dict__["_duration_ms"] = int((time.monotonic() - step_started) * 1000)
            if decision.tool_calls:
                batch_had_progress = False
                for call in decision.tool_calls:
                    if runtime.pause_requested():
                        await _persist_paused(runtime, step_index, spec.key)
                        raise PipelinePaused()
                    stats["tool_calls"] += 1
                    tool = get_tool(call.tool_name)
                    forced_result = None
                    signature = ""
                    cache_hit = False
                    if tool is not None and tool.idempotent:
                        signature = _repeat_signature(spec.key, call, tc)
                        repeat_count = runtime.repeated_tool_calls.get(signature, 0) + 1
                        runtime.repeated_tool_calls[signature] = repeat_count
                        cached = runtime.tool_result_cache.get(signature)
                        if cached is not None:
                            cache_hit = True
                            stats["repeated_tool_calls"] += 1
                            stats["cache_hits"] += 1
                            forced_result = cached.model_copy(deep=True)
                    result = await _execute_tool_call(
                        runtime,
                        spec.key,
                        call,
                        tc,
                        allowed_tools=set(getattr(agent, "allowed_tools", []) or []),
                        forced_result=forced_result,
                    )
                    if not result.ok:
                        stats["failed_tool_calls"] += 1
                        # 设置工具的结构化拒绝也必须回到领域 runtime，不能被当成无上下文失败。
                        if call.tool_name == "vs_set_video_generation_resolution":
                            mutation_hook = getattr(runtime, "record_tool_mutation", None)
                            if mutation_hook is not None:
                                await mutation_hook(spec.key, call, result)
                    elif cache_hit:
                        # 缓存命中会把既有成功结果重新回喂给模型，但不算新进展。
                        pass
                    else:
                        batch_had_progress = True
                        mutation_hook = getattr(runtime, "record_tool_mutation", None)
                        if mutation_hook is not None:
                            await mutation_hook(spec.key, call, result)
                        if tool is not None and tool.idempotent and signature:
                            runtime.tool_result_cache[signature] = result.model_copy(deep=True)
                if batch_had_progress:
                    runtime.no_progress_rounds[spec.key] = 0
                else:
                    streak = runtime.no_progress_rounds.get(spec.key, 0) + 1
                    runtime.no_progress_rounds[spec.key] = streak
                    stats["no_progress_rounds"] += 1
                    if streak <= 2:
                        runtime.context.add_note(
                            f"Agent {spec.key} 上一轮工具调用没有获得新信息；"
                            "请使用已有结果完成当前步骤，或调整参数调用能够产生新状态的工具。"
                        )
                    else:
                        runtime.termination_reason = "agent_no_progress"
                        stats["termination_reason"] = runtime.termination_reason
                        raise AgentError(
                            "agent_no_progress",
                            f"Agent {spec.key} 连续 {streak} 轮工具调用没有产生新信息或状态变化",
                            retryable=True,
                        )
                tool_rounds += 1
                continue
            if decision.completed:
                if decision.handoff:
                    valid_keys = set(agent_registry)
                    canonical_handoff = normalize_handoff(
                        decision.handoff, valid_keys,
                        getattr(runtime, "handoff_aliases", None),
                    )
                    if canonical_handoff:
                        runtime.requested_handoff = canonical_handoff
                    else:
                        runtime.context.add_note(f"忽略无法识别的 handoff：{decision.handoff}")
                        if runtime.emitter is not None:
                            await runtime.emitter.emit_domain(
                                "agent.handoff.ignored",
                                agent={"id": spec.key},
                                message=f"无法识别交接目标 {decision.handoff}，已继续当前计划",
                                payload={"requested": decision.handoff},
                            )
                completed_artifact_id = await persist_artifact(runtime, spec.key, decision, step_index)
                await _checkpoint_agent(runtime, spec.key, decision, step_index, completed_artifact_id)
                if runtime.emitter is not None:
                    await runtime.emitter.agent_completed(
                        spec.key, decision.summary,
                        duration_ms=int(decision.__dict__.get("_duration_ms", 0)),
                        artifact_id=completed_artifact_id,
                    )
                    await runtime.emitter.agent_status_completed(spec.key, decision.summary)
                stats["completed"] = True
                break
        # 工具轮次耗尽是运行失败，不能伪造 Agent 完成事件后继续发布。
        if not decision or not decision.completed:
            runtime.termination_reason = "agent_tool_round_exhausted"
            stats["termination_reason"] = runtime.termination_reason
            raise AgentError(
                "agent_tool_round_exhausted",
                f"Agent {spec.key} 已达到工具轮次上限 {spec.max_steps}，但没有产生完成结果",
                retryable=True,
            )
