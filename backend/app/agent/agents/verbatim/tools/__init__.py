"""教师逐字稿工具集入口：幂等注册全部 vb_* 工具。"""

from __future__ import annotations

from app.agent.agents.verbatim.tools.check_tools import _register_check_tools
from app.agent.agents.verbatim.tools.edit_tools import _register_edit_tools
from app.agent.agents.verbatim.tools.metadata_tools import _register_metadata_tools
from app.agent.agents.verbatim.tools.read_tools import _register_read_tools

_loaded = False


def register_verbatim_tools() -> None:
    """幂等注册逐字稿全部工具（重复调用不报错）。"""
    global _loaded
    if _loaded:
        return
    _register_read_tools()
    _register_edit_tools()
    _register_metadata_tools()
    _register_check_tools()
    _loaded = True


def verbatim_tool_schemas(allowed_names: list[str] | None = None) -> list[dict]:
    from app.agent.registry import all_tool_schemas

    register_verbatim_tools()
    return all_tool_schemas(allowed_names)
