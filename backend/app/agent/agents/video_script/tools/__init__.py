"""视频脚本工具集入口：注册全部 vs_* 工具（幂等）。"""

from __future__ import annotations

from app.agent.agents.video_script.tools.check_tools import _register_check_tools
from app.agent.agents.video_script.tools.outline_tools import _register_outline_tools
from app.agent.agents.video_script.tools.read_tools import _register_read_tools
from app.agent.agents.video_script.tools.scene_tools import _register_scene_tools
from app.agent.agents.video_script.tools.project_settings_tools import _register_project_settings_tools

_loaded = False


def register_video_script_tools() -> None:
    """幂等注册视频脚本全部工具（重复调用不报错）。"""
    global _loaded
    if _loaded:
        return
    _register_read_tools()
    _register_outline_tools()
    _register_scene_tools()
    _register_project_settings_tools()
    _register_check_tools()
    _loaded = True


def video_script_tool_schemas(allowed_names: list[str] | None = None) -> list[dict]:
    from app.agent.registry import all_tool_schemas

    register_video_script_tools()
    return all_tool_schemas(allowed_names)
