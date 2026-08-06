"""工作区文件工具：读写流水线工作目录（path-traversal 防护）。"""
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult

MAX_FILE_BYTES = 2 * 1024 * 1024


def _safe_path(tc: ToolContext, relative: str) -> Path:
    root = (tc.workspace_root or Path("/tmp")).resolve()
    candidate = (root / relative.lstrip("/")).resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError(f"路径越界被拒绝：{relative}")
    return candidate


class ListWorkspaceFilesInput(BaseModel):
    prefix: str = ""


async def _list_workspace_files(tc: ToolContext, payload: ListWorkspaceFilesInput) -> ToolResult:
    root = (tc.workspace_root or Path("/tmp")).resolve()
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files.append(str(path.relative_to(root)))
    if payload.prefix:
        files = [item for item in files if item.startswith(payload.prefix)]
    return ToolResult(ok=True, output={"files": files})


class ReadWorkspaceFileInput(BaseModel):
    path: str


async def _read_workspace_file(tc: ToolContext, payload: ReadWorkspaceFileInput) -> ToolResult:
    target = _safe_path(tc, payload.path)
    if not target.is_file():
        return ToolResult(ok=False, error=f"文件不存在：{payload.path}")
    if target.stat().st_size > MAX_FILE_BYTES:
        return ToolResult(ok=False, error="文件过大，拒绝读取")
    return ToolResult(ok=True, output={"content": target.read_text(encoding="utf-8")})


class WriteWorkspaceFileInput(BaseModel):
    path: str
    content: str
    mime_type: str = "application/json"


async def _write_workspace_file(tc: ToolContext, payload: WriteWorkspaceFileInput) -> ToolResult:
    target = _safe_path(tc, payload.path)
    if len(payload.content.encode("utf-8")) > MAX_FILE_BYTES:
        return ToolResult(ok=False, error="写入内容过大")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content, encoding="utf-8")
    return ToolResult(ok=True, output={"path": payload.path, "mime_type": payload.mime_type})


def register_workspace_tools():
    register_tool(Tool("list_workspace_files", "列出工作目录文件", ListWorkspaceFilesInput, _list_workspace_files))
    register_tool(Tool("read_workspace_file", "读取工作目录文件（防路径穿越）", ReadWorkspaceFileInput, _read_workspace_file))
    register_tool(Tool("write_workspace_file", "写入工作目录文件", WriteWorkspaceFileInput, _write_workspace_file))


register_workspace_tools()
