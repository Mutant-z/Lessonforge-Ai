"""工具注册表 + 执行器。

- Tool：name / description / input_schema(Pydantic) / handler
- ToolContext：向工具注入运行时上下文（ContextState、PresentationBuilder、工作目录、DB、事件等）
- execute_tool：入参校验，异常转 ToolResult(ok=False) 回喂 Agent 上下文
"""
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
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def schema_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
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


def all_tool_schemas() -> list[dict[str, Any]]:
    return [tool.schema_dict() for tool in _REGISTRY.values()]


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
        return ToolResult(ok=False, error=f"未知工具：{tool_name}")
    try:
        validated = tool.input_schema.model_validate(input_dict)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"工具入参校验失败：{str(exc)[:300]}")
    try:
        return await tool.handler(tc, validated)
    except Exception as exc:  # noqa: BLE001
        logger.exception("工具 %s 执行失败", tool_name)
        return ToolResult(ok=False, error=f"工具 {tool_name} 执行失败：{str(exc)[:500]}")
