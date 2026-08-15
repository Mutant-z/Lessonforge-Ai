"""学习任务单工具集入口：注册全部 ts_* 工具（幂等，进程内只注册一次）。"""

from __future__ import annotations

from app.agent.agents.task_sheet.tools.check_tools import _register_check_tools
from app.agent.agents.task_sheet.tools.edit_tools import _register_edit_tools
from app.agent.agents.task_sheet.tools.read_tools import _register_read_tools

_ts_tools_registered = False


def register_task_sheet_tools() -> None:
    global _ts_tools_registered
    if _ts_tools_registered:
        return
    _ts_tools_registered = True
    _register_read_tools()
    _register_edit_tools()
    _register_check_tools()


def task_sheet_tool_schemas(allowed_names: list[str] | None = None) -> list[dict]:
    from app.agent.registry import all_tool_schemas

    return all_tool_schemas(allowed_names)
