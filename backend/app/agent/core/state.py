"""通用 Agent 运行时状态基类。

只承载通用运行态；领域状态（教学设计 builder、PPT 布局引擎参数等）由
领域 Runtime 子类扩展，core/loop 只通过通用字段与方法交互。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState
from app.agent.events import PipelineEventEmitter
from app.agent.registry import ToolContext


@dataclass
class AgentRuntimeState:
    """一次通用 Agent 流水线运行的全部共享状态。"""

    context: ContextState = field(default_factory=ContextState)
    artifacts: PipelineArtifactManager | None = None
    emitter: PipelineEventEmitter | None = None
    tool_context: ToolContext | None = None
    token_usage: dict[str, Any] = field(default_factory=lambda: {"llm_calls": 0, "tokens": 0})
    _steps: int = 0
    current_agent_key: str = ""
    checkpoint_start: int = 0
    requested_handoff: str | None = None
    result_status: str = "applied"
    pause_event: asyncio.Event | None = None
    cancel_event: asyncio.Event | None = None
    dialogue_summary: str | None = None
    agent_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    unresolved_tool_failures: dict[str, dict[str, Any]] = field(default_factory=dict)
    repeated_tool_calls: dict[str, int] = field(default_factory=dict)
    tool_result_cache: dict[str, Any] = field(default_factory=dict)
    no_progress_rounds: dict[str, int] = field(default_factory=dict)
    termination_reason: str = ""
    #: 不可重试的致命工具错误码：工具返回这些错误时，core/loop 立即终止当前
    #: Agent（不再空转重试）。默认空集（PPT/任务单等流水线行为不变）；
    #: 教学设计等强调范围安全的流水线自行覆盖为契约/守卫类错误码。
    fatal_tool_error_codes: frozenset[str] = frozenset()
    #: 累计 token 估算预算（0 = 不限制）。默认 60k；教学设计等全节点 LLM 化的
    #: 任务可覆盖为 0，避免单次运行多次调用模型即触发硬失败。
    max_estimated_tokens: int = 60_000
    #: 单次上下文 token 估算预算（0 = 不限制）。默认 60k。
    max_context_tokens: int = 60_000

    def request_pause(self):
        if self.pause_event is not None:
            self.pause_event.set()

    def pause_requested(self) -> bool:
        return self.pause_event is not None and self.pause_event.is_set()

    def cancel_requested(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()
