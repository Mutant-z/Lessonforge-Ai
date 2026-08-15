"""教学设计工具包：导入即注册全部 lesson_* 工具。"""

from copy import deepcopy

from app.agent.agents.lesson_plan.tools import check_tools, edit_tools, read_tools  # noqa: F401
from app.agent.registry import all_tool_schemas, get_tool

__all__ = ["register_lesson_plan_tools", "lesson_plan_tool_schemas", "get_lesson_plan_tool"]

_loaded = False

# ``lesson_get_source`` 是一个共享工具，但不同角色只应看到自己能读取的投影。
# 这里收紧的是提供给模型的 JSON Schema；handler 中的服务端校验仍保留，形成
# “模型不规划越权参数 + 后端不执行越权参数”的双层保护。
_SOURCE_VIEWS_BY_AGENT: dict[str, tuple[str, ...]] = {
    "outline_architect": ("summary", "outline"),
    "lesson_designer": ("summary", "core", "section"),
    "context_researcher": ("summary", "outline", "core", "section"),
    "format_normalizer": ("summary", "section"),
    "answer_finalizer": ("summary", "section"),
    "pedagogy_qa": ("summary", "outline", "core", "section"),
    "repair_router": ("summary", "outline", "core", "section"),
    "finalizer": ("summary", "outline", "core", "section", "full"),
}


def register_lesson_plan_tools() -> None:
    """幂等注册教学设计全部工具（重复调用不报错）。"""
    global _loaded
    if _loaded:
        return
    read_tools._register_read_tools()
    edit_tools._register_edit_tools()
    check_tools._register_check_tools()
    _loaded = True


def lesson_plan_tool_schemas(
    allowed_names: list[str] | None = None,
    *,
    agent_key: str | None = None,
) -> list[dict]:
    """返回教学设计工具 Schema，并按角色裁剪候选稿读取视图。"""
    register_lesson_plan_tools()
    schemas = all_tool_schemas(allowed_names)
    allowed_views = _SOURCE_VIEWS_BY_AGENT.get(str(agent_key or ""))
    if allowed_views is None:
        return schemas

    projected = deepcopy(schemas)
    for schema in projected:
        if schema.get("name") != "lesson_get_source":
            continue
        view_schema = (
            (schema.get("input_schema") or {}).get("properties") or {}
        ).get("view")
        if not isinstance(view_schema, dict):
            continue
        view_schema["enum"] = list(allowed_views)
        if view_schema.get("default") not in allowed_views:
            view_schema["default"] = allowed_views[0]
        view_schema["description"] = (
            f"当前角色可读取的候选稿投影：{', '.join(allowed_views)}。"
            "不要请求列表之外的视图。"
        )
    return projected


def get_lesson_plan_tool(name: str):
    register_lesson_plan_tools()
    return get_tool(name)
