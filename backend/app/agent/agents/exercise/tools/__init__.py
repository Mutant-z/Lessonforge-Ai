"""课后练习工具集入口：注册全部 exercise_* 工具（幂等，进程内只注册一次）。"""

from __future__ import annotations

from app.agent.agents.exercise.tools.check_tools import _register_check_tools
from app.agent.agents.exercise.tools.edit_tools import _register_edit_tools
from app.agent.agents.exercise.tools.read_tools import _register_read_tools
from app.agent.agents.exercise.tools.visual_tools import _register_visual_tools

_exercise_tools_registered = False


def register_exercise_tools() -> None:
    global _exercise_tools_registered
    if _exercise_tools_registered:
        return
    _exercise_tools_registered = True
    _register_read_tools()
    _register_edit_tools()
    _register_check_tools()
    _register_visual_tools()


def exercise_tool_schemas(allowed_names: list[str] | None = None) -> list[dict]:
    from app.agent.registry import all_tool_schemas

    return all_tool_schemas(allowed_names)
