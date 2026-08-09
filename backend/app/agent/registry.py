"""工具注册表 + 执行器。

- Tool：name / description / input_schema(Pydantic) / handler
- ToolContext：向工具注入运行时上下文（ContextState、PresentationBuilder、工作目录、DB、事件等）
- execute_tool：入参校验，异常转 ToolResult(ok=False) 回喂 Agent 上下文
"""
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from app.agent.schemas import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """一次流水线运行时向工具提供的共享上下文。"""

    ctx: Any = None                     # ContextState
    builder: Any = None                 # PresentationBuilder（可编辑 PPT 模型）
    workspace_root: Path | None = None  # storage/generated/{course_id}/ppt_pipeline/{run_id}
    course: Any = None
    task: Any = None
    generation_run_id: str = ""
    pipeline_run_id: str = ""
    provider: Any = None
    artifacts: Any = None               # PipelineArtifactManager
    emitter: Any = None                 # PipelineEventEmitter
    runtime: Any = None                 # PipelineRuntime（供工具读取配置/暂停等）
    extra: dict[str, Any] = field(default_factory=dict)


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        input_schema: type[BaseModel],
        handler: Callable[[ToolContext, BaseModel], Awaitable[ToolResult]],
        output_schema: type[BaseModel] | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 0,
        idempotent: bool = False,
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler
        self.output_schema = output_schema
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.idempotent = idempotent

    def schema_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
            "output_schema": self.output_schema.model_json_schema() if self.output_schema else ToolResult.model_json_schema(),
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": {"max_retries": self.max_retries},
            "idempotent": self.idempotent,
        }


_REGISTRY: dict[str, Tool] = {}


def register_tool(tool: Tool) -> Tool:
    if tool.name in _REGISTRY:
        raise ValueError(f"工具重复注册：{tool.name}")
    _REGISTRY[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def all_tool_schemas(allowed_names: list[str] | None = None) -> list[dict[str, Any]]:
    ensure_loaded()
    allowed = set(allowed_names or [])
    return [tool.schema_dict() for tool in _REGISTRY.values() if not allowed or tool.name in allowed]


_loaded = False


def ensure_loaded():
    """惰性导入工具模块（避免与 registry 循环导入）。"""
    global _loaded
    if _loaded:
        return
    from app.agent import tools  # noqa: F401  触发 tools/__init__ 注册全部工具
    _loaded = True


def summarize(value: Any, limit: int = 400) -> str:
    """把工具结果压缩为面向用户的摘要。"""
    try:
        import json
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def execute_tool(tool_name: str, tc: ToolContext, input_dict: dict[str, Any]) -> ToolResult:
    """校验入参并执行工具；异常转 ok=False，回喂 Agent 上下文自修复。"""
    ensure_loaded()
    tool = get_tool(tool_name)
    if tool is None:
        return ToolResult(ok=False, error=f"未知工具：{tool_name}", error_code="tool_not_found", retryable=False)
    try:
        validated = tool.input_schema.model_validate(input_dict)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"工具入参校验失败：{str(exc)[:300]}", error_code="tool_input_invalid", retryable=False)
    attempts = 1 + max(0, tool.max_retries)
    for attempt in range(1, attempts + 1):
        try:
            runtime = getattr(tc, "runtime", None)
            if runtime is not None and getattr(runtime, "cancel_requested", lambda: False)():
                return ToolResult(ok=False, error=f"工具 {tool_name} 已取消", error_code="tool_cancelled", retryable=True)
            async with asyncio.timeout(tool.timeout_seconds):
                result = await tool.handler(tc, validated)
            if tool.output_schema is not None and result.ok:
                tool.output_schema.model_validate(result.output)
            return result
        except TimeoutError:
            error = f"工具 {tool_name} 超时（{tool.timeout_seconds:g}s）"
            error_code = "tool_timeout"
        except Exception as exc:  # noqa: BLE001
            logger.exception("工具 %s 执行失败（%s/%s）", tool_name, attempt, attempts)
            error = f"工具 {tool_name} 执行失败：{str(exc)[:500]}"
            error_code = "tool_execution_failed"
        if attempt == attempts:
            return ToolResult(ok=False, error=error, error_code=error_code, retryable=True)
    return ToolResult(ok=False, error=f"工具 {tool_name} 执行失败", error_code="tool_execution_failed", retryable=True)
