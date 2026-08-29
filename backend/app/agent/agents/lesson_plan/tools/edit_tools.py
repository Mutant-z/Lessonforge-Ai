"""教学设计工具集：编辑类工具。

只修改内存中的 LessonPlanBuilder 候选稿，绝不直接写正式 Artifact。
所有编辑工具检查：目标章节存在、锁定路径、作用域、细粒度修改权限、蓝图引用；违规返回
可修复的 ToolResult(ok=False) 让 Agent 调整方案，不得静默覆盖。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.agents.lesson_plan.tools._common import (
    ToolGuardError,
    atomic_edit,
    normalize_blocks,
    normalize_outline_sections,
    patch_paths,
)
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool


def _error(exc: Exception, fallback_code: str, prefix: str) -> ToolResult:
    code = exc.code if isinstance(exc, ToolGuardError) else fallback_code
    out: dict[str, Any] = {"ok": False, "error_code": code}
    if isinstance(exc, ToolGuardError):
        if exc.requested_target is not None:
            out["requested_target"] = exc.requested_target
        if exc.allowed_scope is not None:
            out["allowed_scope"] = exc.allowed_scope
        if exc.suggestion:
            out["suggestion"] = exc.suggestion
    # 契约/守卫类错误属于模型不可修复的越权或语义错误：重试只会空转，
    # 必须立即终止当前修改链（core/loop 按 fatal_tool_error_codes 判定）。
    retryable = code not in _FATAL_GUARD_ERROR_CODES
    return ToolResult(
        ok=False,
        error=f"{prefix}：{str(exc)[:300]}",
        error_code=code,
        retryable=retryable,
        output=out,
    )


def _receipt(tc: ToolContext) -> dict[str, Any] | None:
    """返回最近一次写操作的 MutationReceipt（供工具输出携带）。"""
    receipt = (tc.extra or {}).get("last_mutation_receipt")
    if receipt is None:
        return None
    data = receipt.__dict__
    return {key: list(value) if isinstance(value, (set, tuple)) else value for key, value in data.items()}


#: 不可重试的契约/守卫错误码。与 runtime.fatal_tool_error_codes 保持一致；
#: 这类错误不依赖模型行为变化，重试无意义，直接终止当前 Agent。
_FATAL_GUARD_ERROR_CODES = frozenset({
    "invalid_section_id",
    "section_scope_violation",
    "structure_modification_forbidden",
    "core_field_unauthorized",
    "mutation_contract_error",
    "outline_replace_forbidden",
    "artifact_locked",
    "locked_path_conflict",
    "section_not_found",
    "section_already_exists",
    "tool_not_allowed",
})


class LessonCreateOutlineInput(BaseModel):
    sections: list[dict[str, Any]] = Field(min_length=1, description="完整目录树（章节含 id/title/children）")


async def _lesson_create_outline(tc: ToolContext, inp: LessonCreateOutlineInput) -> ToolResult:
    try:
        if tc.extra["builder"].outline:
            raise ToolGuardError(
                "outline_replace_forbidden",
                "已有目录不得整体替换，请使用新增、移动、重命名、合并或删除章节工具",
            )
        atomic_edit(
            tc,
            lambda builder: builder.set_outline(normalize_outline_sections(inp.sections)),
            change_paths=["$.outline"],
            global_change=True,
            is_add_section=True,
        )
        builder = tc.extra["builder"]
        return ToolResult(output={"ok": True, "section_count": builder.count_sections(), "section_ids": builder.all_section_ids(), "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "outline_invalid", "目录结构不合法")


class LessonAddSectionInput(BaseModel):
    section_id: str = Field(min_length=1, pattern=r"^SEC-[A-Z0-9-]+$")
    title: str = Field(min_length=1)
    parent_id: str = ""
    index: int | None = None
    summary: str = ""
    coverage_refs: list[str] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)


async def _lesson_add_section(tc: ToolContext, inp: LessonAddSectionInput) -> ToolResult:
    try:
        def mutate(builder):
            node = builder.add_section(inp.section_id, inp.title, parent_id=inp.parent_id, index=inp.index)
            if inp.summary or inp.blocks or inp.coverage_refs:
                node = builder.write_section(
                    inp.section_id,
                    summary=inp.summary or None,
                    blocks=inp.blocks or None,
                    coverage_refs=inp.coverage_refs or None,
                )
            return node

        node = atomic_edit(
            tc,
            mutate,
            change_paths=[f"$.outline.sections[{inp.section_id}]"],
            section_ids=[inp.section_id],
            global_change=False,
            is_add_section=True,
        )
        builder = tc.extra["builder"]
        return ToolResult(output={"ok": True, "section": node, "section_count": builder.count_sections(), "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "section_add_failed", "添加章节失败")


class LessonSplitSectionInput(BaseModel):
    source_section_id: str = Field(min_length=1, description="待拆分的源章节 ID")
    new_section_id: str = Field(min_length=1, pattern=r"^SEC-[A-Z0-9-]+$", description="新建的目标章节 ID")
    new_section_title: str = Field(min_length=1, description="新建章节标题")
    source_section_new_title: str | None = Field(default=None, description="源章节更新后的标题（可选）")
    moved_blocks: list[dict[str, Any]] = Field(default_factory=list, description="迁移到新建章节的 blocks")
    remaining_blocks: list[dict[str, Any]] | None = Field(default=None, description="留在源章节的 blocks（若不提供则保留原内容减去迁移部分）")
    new_section_coverage_refs: list[str] = Field(default_factory=list, description="新建章节的事实覆盖键")
    source_section_coverage_refs: list[str] | None = Field(default=None, description="源章节更新后保留的事实覆盖键")
    insert_after: bool = True


async def _lesson_split_section(tc: ToolContext, inp: LessonSplitSectionInput) -> ToolResult:
    """确定性拆分章节工具：将已有章节拆分为两个独立章节，保留其余内容。"""
    try:
        def mutate(builder):
            src = builder.find_section(inp.source_section_id)
            if src is None:
                raise ToolGuardError("section_not_found", f"待拆分章节不存在：{inp.source_section_id}")
            if builder.find_section(inp.new_section_id) is not None:
                raise ToolGuardError("section_already_exists", f"目标章节 ID 已存在：{inp.new_section_id}")

            # 找到源章节在父节点中的位置
            sections = builder.outline
            src_index = next((i for i, s in enumerate(sections) if str(s.get("id")) == inp.source_section_id), None)
            target_index = (src_index + 1) if (src_index is not None and inp.insert_after) else None

            # 创建新建章节
            builder.add_section(
                inp.new_section_id,
                inp.new_section_title,
                parent_id="",
                index=target_index,
            )
            builder.write_section(
                inp.new_section_id,
                blocks=inp.moved_blocks or None,
                coverage_refs=inp.new_section_coverage_refs or None,
            )

            # 更新源章节
            builder.write_section(
                inp.source_section_id,
                title=inp.source_section_new_title or None,
                blocks=inp.remaining_blocks if inp.remaining_blocks is not None else None,
                coverage_refs=inp.source_section_coverage_refs if inp.source_section_coverage_refs is not None else None,
            )
            return {
                "source_section": builder.find_section(inp.source_section_id),
                "new_section": builder.find_section(inp.new_section_id),
            }

        result = atomic_edit(
            tc,
            mutate,
            change_paths=[
                f"$.outline.sections[{inp.source_section_id}]",
                f"$.outline.sections[{inp.new_section_id}]",
            ],
            section_ids=[inp.source_section_id, inp.new_section_id],
            global_change=False,
            is_split_section=True,
        )
        builder = tc.extra["builder"]
        return ToolResult(output={"ok": True, "split_result": result, "section_ids": builder.all_section_ids(), "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "section_split_failed", "拆分章节失败")


class LessonMoveSectionInput(BaseModel):
    section_id: str = Field(min_length=1)
    target_parent_id: str = ""
    index: int | None = None


async def _lesson_move_section(tc: ToolContext, inp: LessonMoveSectionInput) -> ToolResult:
    try:
        node = atomic_edit(
            tc,
            lambda builder: builder.move_section(inp.section_id, target_parent_id=inp.target_parent_id, index=inp.index),
            change_paths=[f"$.outline.sections[{inp.section_id}]"],
            section_ids=[inp.section_id, inp.target_parent_id],
        )
        builder = tc.extra["builder"]
        return ToolResult(output={"ok": True, "section": node, "section_ids": builder.all_section_ids(), "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "section_move_failed", "移动章节失败")


class LessonRenameSectionInput(BaseModel):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)


async def _lesson_rename_section(tc: ToolContext, inp: LessonRenameSectionInput) -> ToolResult:
    try:
        node = atomic_edit(
            tc,
            lambda builder: builder.rename_section(inp.section_id, inp.title),
            change_paths=[f"$.outline.sections[{inp.section_id}].title"],
            section_ids=[inp.section_id],
        )
        return ToolResult(output={"ok": True, "section": node, "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "section_rename_failed", "重命名章节失败")


class LessonMergeSectionsInput(BaseModel):
    section_ids: list[str] = Field(min_length=2)
    new_title: str = Field(min_length=1)


async def _lesson_merge_sections(tc: ToolContext, inp: LessonMergeSectionsInput) -> ToolResult:
    try:
        node = atomic_edit(
            tc,
            lambda builder: builder.merge_sections(inp.section_ids, inp.new_title),
            change_paths=[f"$.outline.sections[{section_id}]" for section_id in inp.section_ids],
            section_ids=inp.section_ids,
        )
        builder = tc.extra["builder"]
        return ToolResult(output={"ok": True, "section": node, "section_ids": builder.all_section_ids(), "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "section_merge_failed", "合并章节失败")


class LessonDeleteSectionInput(BaseModel):
    section_id: str = Field(min_length=1)


async def _lesson_delete_section(tc: ToolContext, inp: LessonDeleteSectionInput) -> ToolResult:
    try:
        node = atomic_edit(
            tc,
            lambda builder: builder.delete_section(inp.section_id),
            change_paths=[f"$.outline.sections[{inp.section_id}]"],
            section_ids=[inp.section_id],
        )
        builder = tc.extra["builder"]
        return ToolResult(output={"ok": True, "deleted": node, "section_ids": builder.all_section_ids(), "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "section_delete_failed", "删除章节失败")


class LessonWriteSectionInput(BaseModel):
    section_id: str = Field(min_length=1)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None
    coverage_refs: list[str] | None = None
    title: str | None = None


async def _lesson_write_section(tc: ToolContext, inp: LessonWriteSectionInput) -> ToolResult:
    try:
        node = atomic_edit(
            tc,
            lambda builder: builder.write_section(
                inp.section_id,
                blocks=normalize_blocks(inp.blocks) or None,
                summary=inp.summary,
                coverage_refs=inp.coverage_refs,
                title=inp.title,
            ),
            change_paths=[f"$.outline.sections[{inp.section_id}]"],
            section_ids=[inp.section_id],
        )
        return ToolResult(output={"ok": True, "section": node, "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "section_write_failed", "写入章节失败")


class LessonUpdateCoreInput(BaseModel):
    patch: dict[str, Any] = Field(min_length=1, description="稳定内核字段更新（整体替换指定键）")


async def _lesson_update_core(tc: ToolContext, inp: LessonUpdateCoreInput) -> ToolResult:
    try:
        core = atomic_edit(
            tc,
            lambda builder: builder.update_core(inp.patch),
            change_paths=[f"$.pedagogical_core.{key}" for key in inp.patch],
            global_change=False,
            core_keys=list(inp.patch.keys()),
        )
        return ToolResult(output={"ok": True, "core": core, "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "core_update_failed", "更新内核失败")


class LessonApplyPatchInput(BaseModel):
    patch: dict[str, Any] = Field(min_length=1, description="深层合并补丁（可同时改大纲与内核）")


def _normalize_patch_blocks(patch: dict[str, Any]) -> dict[str, Any]:
    """深层遍历补丁，把其中所有 blocks 列表归一化（lesson_apply_patch 用）。"""
    normalized = dict(patch)
    outline = normalized.get("outline")
    if isinstance(outline, dict) and isinstance(outline.get("sections"), list):
        normalized["outline"] = {
            **outline,
            "sections": normalize_outline_sections(outline.get("sections")),
        }
    for key, value in list(normalized.items()):
        if key == "outline":
            continue
        if isinstance(value, list) and key == "blocks":
            normalized[key] = normalize_blocks(value)
        elif isinstance(value, dict):
            normalized[key] = _normalize_patch_blocks(value)
    return normalized


async def _lesson_apply_patch(tc: ToolContext, inp: LessonApplyPatchInput) -> ToolResult:
    try:
        patch = _normalize_patch_blocks(inp.patch)
        core_keys = list((patch.get("pedagogical_core") or {}).keys()) if isinstance(patch.get("pedagogical_core"), dict) else None
        content = atomic_edit(
            tc,
            lambda builder: builder.apply_patch(patch),
            change_paths=patch_paths(patch),
            global_change=True,
            core_keys=core_keys,
        )
        return ToolResult(output={"ok": True, "content": content, "mutation_receipt": _receipt(tc)})
    except Exception as exc:  # noqa: BLE001
        return _error(exc, "patch_apply_failed", "应用补丁失败")


def _register_edit_tools() -> None:
    register_tool(Tool(
        "lesson_create_outline",
        "仅用于空白候选稿首次初始化目录；已有目录必须使用增量结构工具",
        LessonCreateOutlineInput,
        _lesson_create_outline,
    ))
    register_tool(Tool("lesson_add_section", "在指定位置新增章节", LessonAddSectionInput, _lesson_add_section))
    register_tool(Tool("lesson_split_section", "确定性拆分已有章节为两个独立章节", LessonSplitSectionInput, _lesson_split_section))
    register_tool(Tool("lesson_move_section", "移动章节到新父节点/新位置", LessonMoveSectionInput, _lesson_move_section))
    register_tool(Tool("lesson_rename_section", "重命名章节", LessonRenameSectionInput, _lesson_rename_section))
    register_tool(Tool("lesson_merge_sections", "合并多个同级章节为一个", LessonMergeSectionsInput, _lesson_merge_sections))
    register_tool(Tool("lesson_delete_section", "删除章节（含子孙）", LessonDeleteSectionInput, _lesson_delete_section))
    register_tool(Tool("lesson_write_section", "写入章节内容（blocks 支持 paragraph[text]/bullets[items]/"
                                      "steps[steps[{title,detail}]]/table[columns+rows[{cells}]]/"
                                      "process_table[steps]/note[text]/checklist[items]；"
                                      "其他字段名写法会被自动归一化）",
                       LessonWriteSectionInput, _lesson_write_section))
    register_tool(Tool("lesson_update_core", "更新稳定教学内核（目标/环节/评价等）", LessonUpdateCoreInput, _lesson_update_core))
    register_tool(Tool("lesson_apply_patch", "深层合并补丁，同时改大纲与内核", LessonApplyPatchInput, _lesson_apply_patch))
