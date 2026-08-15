"""学习任务单工具集：检查与交付类工具（方案 §2.3）。

- task_sheet_validate_schema：Schema 结构校验（TaskSheetContentV3）。
- task_sheet_validate_references：蓝图/教学设计引用合法性。
- task_sheet_validate_alignment：目标覆盖、环节映射一致性。
- task_sheet_validate_timing：任务用时与课程/环节时长守恒。
- task_sheet_validate_usability：记录空间、任务可执行性、学生版可用性。
- task_sheet_validate_student_language：年级适切与学生语言（误生成答案/教师提示检查）。
- task_sheet_diff_versions：候选稿与正式源版本差异。
- task_sheet_render_preview：渲染 Markdown / 结构化预览。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agent.agents.task_sheet.tools._common import _builder, _lock_paths
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool


def _blueprint(tc: ToolContext):
    from app.schemas.blueprint import CourseBlueprintSchema

    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    bp_data = blueprint.model_dump() if hasattr(blueprint, "model_dump") else (blueprint or {})
    return CourseBlueprintSchema.model_validate(bp_data)


def _lesson_plan_raw(tc: ToolContext) -> dict[str, Any] | None:
    knowledge = {}
    if tc.runtime is not None and getattr(tc.runtime, "knowledge_context", None):
        knowledge = dict(tc.runtime.knowledge_context)
    raw = (
        knowledge.get("hard_dependencies", {}).get("lesson_plan")
        or knowledge.get("sibling_artifacts", {}).get("lesson_plan")
    )
    if isinstance(raw, dict):
        raw = raw.get("content") or raw
    return raw if isinstance(raw, dict) else None


class ValidateTaskSheetSchemaInput(BaseModel):
    pass


async def _task_sheet_validate_schema(tc: ToolContext, _: ValidateTaskSheetSchemaInput) -> ToolResult:
    """校验候选稿是否符合 TaskSheetContentV3 Schema（含必备语义）。"""
    from app.schemas.task_sheet import TaskSheetContentV3

    builder = _builder(tc)
    try:
        TaskSheetContentV3.model_validate(builder.to_content())
        return ToolResult(output={"ok": True, "issues": [], "valid": True})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(output={
            "ok": False, "valid": False,
            "issues": [{
                "severity": "critical", "dimension": "integrity",
                "path": "$", "description": f"任务单结构非法：{str(exc)[:300]}",
                "suggestion": "修复结构后重新校验", "target_role": "task_designer",
            }],
        })


class ValidateTaskSheetReferencesInput(BaseModel):
    pass


async def _task_sheet_validate_references(tc: ToolContext, _: ValidateTaskSheetReferencesInput) -> ToolResult:
    """校验目标/知识点/环节引用合法性（蓝图权威）。"""
    from app.agent.agents.task_sheet.qa import _reference_issues_v3

    builder = _builder(tc)
    issues = _reference_issues_v3(_blueprint(tc), builder.to_content())
    return ToolResult(output={"ok": not issues, "issues": issues})


class ValidateTaskSheetAlignmentInput(BaseModel):
    pass


async def _task_sheet_validate_alignment(tc: ToolContext, _: ValidateTaskSheetAlignmentInput) -> ToolResult:
    """校验目标覆盖与环节映射一致性。"""
    from app.agent.agents.task_sheet.qa import _alignment_issues_v3

    builder = _builder(tc)
    issues = _alignment_issues_v3(_blueprint(tc), builder.to_content())
    return ToolResult(output={"ok": not issues, "issues": issues})


class ValidateTaskSheetTimingInput(BaseModel):
    pass


async def _task_sheet_validate_timing(tc: ToolContext, _: ValidateTaskSheetTimingInput) -> ToolResult:
    """校验任务用时与课程/环节时长守恒。"""
    from app.agent.agents.task_sheet.qa import _timing_issues_v3

    builder = _builder(tc)
    issues = _timing_issues_v3(_blueprint(tc), builder.to_content(), _lesson_plan_raw(tc))
    return ToolResult(output={"ok": not issues, "issues": issues})


class ValidateTaskSheetUsabilityInput(BaseModel):
    pass


async def _task_sheet_validate_usability(tc: ToolContext, _: ValidateTaskSheetUsabilityInput) -> ToolResult:
    """校验任务可执行性、记录空间与产出/完成标准一致性。"""
    from app.agent.agents.task_sheet.qa import _usability_issues_v3

    builder = _builder(tc)
    issues = _usability_issues_v3(builder.to_content())
    return ToolResult(output={"ok": not issues, "issues": issues})


class ValidateTaskSheetStudentLanguageInput(BaseModel):
    pass


async def _task_sheet_validate_student_language(tc: ToolContext, _: ValidateTaskSheetStudentLanguageInput) -> ToolResult:
    """校验学生指令可执行性、年级适切性与职责边界（不出现答案/教师提示）。"""
    from app.agent.agents.task_sheet.qa import _student_language_issues_v3

    builder = _builder(tc)
    issues = _student_language_issues_v3(builder.to_content())
    return ToolResult(output={"ok": not issues, "issues": issues})


class DiffTaskSheetVersionsInput(BaseModel):
    pass


async def _task_sheet_diff_versions(tc: ToolContext, _: DiffTaskSheetVersionsInput) -> ToolResult:
    """对比候选稿与正式源版本（ID 感知的目录与 Block 差异）。"""
    builder = _builder(tc)
    source = getattr(tc.runtime, "source_artifact", None)
    source_content = getattr(source, "content_json", None) if source else None
    candidate = builder.to_content()
    if not source_content:
        return ToolResult(output={"is_new": True, "note": "首次生成，无源版本可对比"})
    if source_content.get("schema_version") != candidate.get("schema_version"):
        return ToolResult(output={
            "is_new": True,
            "note": f"源版本为 {source_content.get('schema_version')}，本轮将生成 {candidate.get('schema_version')} 版本",
            "migration_required": True,
        })
    source_sections = {str(item.get("id")): item for item in source_content.get("sections", [])}
    candidate_sections = {str(item.get("id")): item for item in candidate.get("sections", [])}
    added = sorted(set(candidate_sections) - set(source_sections))
    removed = sorted(set(source_sections) - set(candidate_sections))
    changed = sorted(
        section_id for section_id in set(source_sections) & set(candidate_sections)
        if source_sections[section_id].get("title") != candidate_sections[section_id].get("title")
        or source_sections[section_id].get("blocks") != candidate_sections[section_id].get("blocks")
    )
    changed_blocks: list[str] = []
    for section_id in set(source_sections) & set(candidate_sections):
        src_blocks = {b.get("id"): b for b in source_sections[section_id].get("blocks", [])}
        cand_blocks = {b.get("id"): b for b in candidate_sections[section_id].get("blocks", [])}
        changed_blocks.extend(
            block_id for block_id in set(src_blocks) & set(cand_blocks)
            if src_blocks[block_id] != cand_blocks[block_id]
        )
    return ToolResult(output={
        "added_sections": added,
        "removed_sections": removed,
        "changed_sections": changed,
        "changed_blocks": sorted(set(changed_blocks)),
        "changed": bool(added or removed or changed or changed_blocks),
    })


class RenderTaskSheetPreviewInput(BaseModel):
    format: str = "markdown"


async def _task_sheet_render_preview(tc: ToolContext, inp: RenderTaskSheetPreviewInput) -> ToolResult:
    from app.schemas.task_sheet import task_sheet_v3_to_markdown

    builder = _builder(tc)
    content = builder.to_content()
    markdown = task_sheet_v3_to_markdown(content)
    return ToolResult(output={
        "format": inp.format, "markdown": markdown[:8000],
        "content": content, "schema_version": content.get("schema_version"),
    })


def _register_check_tools() -> None:
    # 只读/校验工具标记 idempotent：core/loop 对同一输入（含 builder 状态指纹）
    # 命中幂等缓存 → 不算新进展，配合 no-progress 检测防止 Agent 反复调只读工具空转。
    register_tool(Tool("task_sheet_validate_schema", "校验候选稿 Schema 结构（含必备语义）",
                       ValidateTaskSheetSchemaInput, _task_sheet_validate_schema, idempotent=True))
    register_tool(Tool("task_sheet_validate_references", "校验目标/知识点/环节引用合法性",
                       ValidateTaskSheetReferencesInput, _task_sheet_validate_references, idempotent=True))
    register_tool(Tool("task_sheet_validate_alignment", "校验目标覆盖与环节映射一致性",
                       ValidateTaskSheetAlignmentInput, _task_sheet_validate_alignment, idempotent=True))
    register_tool(Tool("task_sheet_validate_timing", "校验任务用时与课程/环节时长守恒",
                       ValidateTaskSheetTimingInput, _task_sheet_validate_timing, idempotent=True))
    register_tool(Tool("task_sheet_validate_usability", "校验任务可执行性/记录空间/产出与完成标准",
                       ValidateTaskSheetUsabilityInput, _task_sheet_validate_usability, idempotent=True))
    register_tool(Tool("task_sheet_validate_student_language", "校验学生指令可执行性/年级适切/职责边界",
                       ValidateTaskSheetStudentLanguageInput, _task_sheet_validate_student_language, idempotent=True))
    register_tool(Tool("task_sheet_diff_versions", "对比候选稿与正式源版本差异",
                       DiffTaskSheetVersionsInput, _task_sheet_diff_versions, idempotent=True))
    register_tool(Tool("task_sheet_render_preview", "渲染候选稿 Markdown / 结构化预览",
                       RenderTaskSheetPreviewInput, _task_sheet_render_preview, idempotent=True))
