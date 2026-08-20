"""教师逐字稿课程级元数据工具。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.agents.verbatim.tools._common import _builder
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool


class UpdateCourseTitleInput(BaseModel):
    course_title: str = Field(min_length=1, max_length=200)


async def _vb_update_course_title(tc: ToolContext, inp: UpdateCourseTitleInput) -> ToolResult:
    """只更新候选稿页眉，并把课程主数据改名暂存到运行态。"""
    runtime = tc.runtime
    plan = getattr(runtime, "intent_plan", None) if runtime else None
    planned_title = str(getattr(plan, "course_title", "") or "").strip()
    title = inp.course_title.strip()
    if not planned_title or title != planned_title:
        return ToolResult(
            ok=False,
            error="课程名称必须与意图规划器解析出的目标名称一致",
            error_code="course_title_contract_violation",
            retryable=False,
            output={"requested_title": title, "planned_title": planned_title},
        )
    builder = _builder(tc)
    previous = str((builder.to_content().get("course_info") or {}).get("course_title") or "")
    try:
        builder.update_course_title(title)
    except ValueError as exc:
        return ToolResult(ok=False, error=str(exc), error_code="course_title_invalid", retryable=False)
    if runtime is not None:
        runtime.pending_course_title = title
    changed = previous != title
    if changed:
        builder.bump_revision()
    return ToolResult(output={
        "status": "metadata_staged" if changed else "metadata_unchanged",
        "course_title": title,
        "previous_title": previous,
        "changed": changed,
        "affected_json_paths": ["$.course_info.course_title"] if changed else [],
        "persistence": "staged",
    })


def _register_metadata_tools() -> None:
    register_tool(Tool(
        "vb_update_course_title",
        "暂存课程级名称修改，只允许修改 course_info.course_title，不得修改逐字稿正文或章节",
        UpdateCourseTitleInput,
        _vb_update_course_title,
        idempotent=True,
    ))
