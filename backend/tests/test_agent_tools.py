"""工具注册表与工具行为单测：入参校验、path-traversal 防护、图表/占位图、几何 QA。"""
from pathlib import Path

import pytest

from app.agent.registry import ToolContext, ensure_loaded, execute_tool, get_tool
from app.agent.schemas import ToolResult
from app.renderers.presentation_builder import PresentationBuilder
from PIL import Image


def _tc(tmp_path: Path) -> ToolContext:
    ensure_loaded()
    builder = PresentationBuilder("lessonforge_deck_academic")
    return ToolContext(builder=builder, workspace_root=tmp_path)


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(tmp_path):
    result = await execute_tool("no_such_tool", _tc(tmp_path), {})
    assert result.ok is False
    assert "未知工具" in result.error


@pytest.mark.asyncio
async def test_editing_tool_creates_element(tmp_path):
    tc = _tc(tmp_path)
    result = await execute_tool("create_slide", tc, {"page_type": "cover", "title": "标题"})
    assert result.ok and result.output["slide_id"]
    slide_id = result.output["slide_id"]
    result = await execute_tool("add_textbox", tc, {"slide_id": slide_id, "text": "内容", "x": 0.7, "y": 1.8, "width": 5, "height": 1})
    assert result.ok and result.output["element_id"]


@pytest.mark.asyncio
async def test_workspace_read_blocks_path_traversal(tmp_path):
    (tmp_path / "safe.txt").write_text("ok", encoding="utf-8")
    tc = _tc(tmp_path)
    result = await execute_tool("read_workspace_file", tc, {"path": "safe.txt"})
    assert result.ok and result.output["content"] == "ok"
    result = await execute_tool("read_workspace_file", tc, {"path": "../../../../etc/passwd"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_generate_image_placeholder_writes_png(tmp_path):
    tc = _tc(tmp_path)
    result = await execute_tool("generate_image", tc, {
        "prompt": "主体居右留白左侧", "slide_id": "S04", "asset_name": "v", "size": "640x480",
    })
    assert result.ok
    path = Path(tmp_path) / result.output["file_path"]
    assert path.is_file()
    with Image.open(path) as image:
        assert image.size == (640, 480)


@pytest.mark.asyncio
async def test_generate_chart_png_creates_file(tmp_path):
    tc = _tc(tmp_path)
    result = await execute_tool("generate_chart_png", tc, {
        "chart_type": "bar",
        "data": {"categories": ["目标", "现状"], "series": [{"name": "对比", "values": [80, 45]}]},
        "width": 480, "height": 320,
    })
    assert result.ok
    path = Path(tmp_path) / result.output["file_path"]
    assert path.is_file()
    with Image.open(path) as image:
        assert image.size == (480, 320)


@pytest.mark.asyncio
async def test_run_qa_flags_out_of_bounds_element(tmp_path):
    tc = _tc(tmp_path)
    builder = tc.builder
    slide_id = builder.create_slide("concept", "标题", "bullet")
    builder.add_textbox(slide_id, "正常文本", 0.7, 1.8, 5.0, 1.0, style={"size": 18, "color": "text"})
    builder.add_shape(slide_id, "rect", 12.0, 7.0, 2.0, 2.0, fill="primary")  # 越界
    result = await execute_tool("run_qa", tc, {})
    assert result.ok
    issues = result.output["issues"]
    assert any(item["rule_id"] == "geometry.out_of_bounds" for item in issues)
