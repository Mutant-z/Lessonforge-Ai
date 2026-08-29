"""学习任务单工具集：编辑类工具（方案 §2.3）。

只修改内存中的 TaskSheetBuilder 候选稿，绝不直接写正式 Artifact。
所有编辑工具检查：目标 ID/知识点 ID/环节 ID/稳定任务 ID 存在、锁定路径
（含祖先/后代）、修改范围属于本轮意图；高风险操作（删除/目标解绑）要求
有效人工确认令牌。违规返回可修复的 ToolResult(ok=False) 让 Agent 调整方案，
不得静默覆盖。

每个修改工具返回：实际修改路径（affected_json_paths）、修改前后摘要与可重试错误。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agent.agents.task_sheet.tools._common import (
    _builder,
    _lock_guard,
    _require_confirmation,
    _scope_guard,
)
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool

TASK_EDITABLE_FIELDS = {
    "title", "action", "object", "steps", "student_output", "completion_criterion",
    "estimated_minutes", "collaboration_mode", "objective_ids", "knowledge_point_ids",
    "stage_id", "scaffolds", "record_table",
}

# 普通内容编辑不应改变任务与学习目标的既有映射。模型在返回完整任务
# 对象时可能遗漏 objective_ids，遗漏不能被解释为“解绑目标”；真正的
# 映射调整必须明确走 ALIGNMENT_REPAIR 意图。
CONTENT_EDIT_INTENTS = {
    "GENERATE", "TASK_EDIT", "STRUCTURE_EDIT", "TIMING_ADJUST", "SCAFFOLD_EDIT",
    "RECORDING_EDIT", "SYNC_CONTEXT",
}


def _ok(output: dict[str, Any]) -> ToolResult:
    return ToolResult(output={"ok": True, **output})


def _fail(error: str, code: str = "task_sheet_edit_failed") -> ToolResult:
    return ToolResult(ok=False, error=error, error_code=code, retryable=True)


def _valid_ids(tc: ToolContext) -> tuple[set[str], set[str], set[str]]:
    """返回 (目标 ID 允许集, 知识点 ID 集合, 环节 ID 集合) 供引用校验。

    目标允许集 = 蓝图目标 ∪ 候选稿目录目标：学习目标目录允许新增/拆分蓝图外
    目标（教师细化指令），因此任务/评价/问题可引用目录中的新增目标；知识点与
    教学环节仍以蓝图为唯一权威。
    """
    bp = tc.ctx.blueprint if tc.ctx is not None else None
    bp_data = bp.model_dump() if hasattr(bp, "model_dump") else (bp or {})
    objectives = {item.get("id") for item in bp_data.get("objectives", [])}
    knowledge = {item.get("id") for item in bp_data.get("knowledge_points", [])}
    stages = {item.get("segment_id") for item in bp_data.get("timeline", [])}
    try:
        catalog = _builder(tc).objective_catalog
    except Exception:  # noqa: BLE001  builder 未初始化时仅蓝图目标合法
        catalog = []
    objectives |= {item.get("id") for item in catalog}
    return objectives, knowledge, stages


def _check_refs(tc: ToolContext, *, objective_ids: list[str] | None = None,
                knowledge_point_ids: list[str] | None = None, stage_id: str | None = None) -> str | None:
    """引用合法性检查：返回错误信息或 None。"""
    objectives, knowledge, stages = _valid_ids(tc)
    if objective_ids:
        invalid = [ref for ref in objective_ids if ref not in objectives]
        if invalid:
            return f"引用了蓝图中不存在的目标 ID：{invalid}"
    if knowledge_point_ids:
        invalid = [ref for ref in knowledge_point_ids if ref not in knowledge]
        if invalid:
            return f"引用了蓝图中不存在的知识点 ID：{invalid}"
    if stage_id and stage_id not in stages:
        return f"引用了蓝图中不存在的教学环节 ID：{stage_id}"
    return None


def _block_path(builder, section_id: str, block_id: str) -> str:
    """构造 Block 的 JSON 路径。"""
    section = builder.find_section(section_id) if section_id else None
    if section is None:
        return "$.sections[*].blocks[*]"
    index = next(
        (i for i, b in enumerate(section.get("blocks", [])) if b.get("id") == block_id),
        0,
    )
    return f"$.sections[{section_id}].blocks[{index}]"


def _first_block(builder, kind: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """返回 (block, section) 首个指定 kind 的 Block。"""
    for section in builder.sections:
        for block in section.get("blocks", []):
            if block.get("kind") == kind:
                return block, section
    return None, None


# ---------------------------------------------------------------------------
# 初始化 / 升级
# ---------------------------------------------------------------------------


class InitializeTaskSheetDraftInput(BaseModel):
    pass


async def _task_sheet_initialize_draft(tc: ToolContext, _: InitializeTaskSheetDraftInput) -> ToolResult:
    """首次生成或 V1 升级时创建 V3 候选稿基线（蓝图驱动确定性生成）。"""
    _lock_guard(tc, ["$"])
    builder = _builder(tc)
    if builder.count_sections() == 0:
        blueprint = tc.ctx.blueprint if tc.ctx is not None else None
        if blueprint is None:
            return _fail("上下文缺少课程蓝图", "blueprint_missing")
        bp_data = blueprint.model_dump() if hasattr(blueprint, "model_dump") else blueprint
        lesson_plan_raw = (tc.ctx.upstream or {}).get("lesson_plan") if tc.ctx is not None else None
        from app.agent.agents.task_sheet.builder import build_initial_builder

        fresh = build_initial_builder(bp_data, lesson_plan_raw)
        tc.extra["builder"] = fresh
        return _ok({
            "summary": "已初始化 V3 任务单草稿",
            "revision": fresh.revision,
            "affected_json_paths": ["$"],
            "section_count": fresh.count_sections(),
        })
    return _ok({"summary": "草稿已存在，跳过初始化", "revision": builder.revision, "affected_json_paths": []})


# ---------------------------------------------------------------------------
# 学习任务编辑
# ---------------------------------------------------------------------------


class AddTaskSheetTaskInput(BaseModel):
    task: dict[str, Any] = Field(description="learning_task Block（含 id/title/action/object/steps/student_output/completion_criterion/estimated_minutes/objective_ids）")
    section_id: str = Field(default="", description="目标章节 ID；为空自动追加到任务所在章节")
    position: int | None = None
    confirmation_token: str | None = None


async def _task_sheet_add_task(tc: ToolContext, inp: AddTaskSheetTaskInput) -> ToolResult:
    task = dict(inp.task)
    if task.get("kind") and task["kind"] != "learning_task":
        return _fail("新增任务的 kind 必须是 learning_task", "invalid_task_kind")
    task["kind"] = "learning_task"
    task_id = str(task.get("id") or "")
    if not task_id:
        return _fail("任务缺少稳定 id", "task_id_required")
    for field in ("title", "action", "object", "student_output", "completion_criterion"):
        if not task.get(field):
            return _fail(f"任务缺少必填字段 {field}", "task_field_missing")
    if not task.get("steps"):
        return _fail("任务缺少操作步骤 steps", "task_field_missing")
    if not task.get("estimated_minutes"):
        return _fail("任务缺少预计用时 estimated_minutes", "task_field_missing")
    ref_error = _check_refs(
        tc,
        objective_ids=list(task.get("objective_ids") or []),
        knowledge_point_ids=list(task.get("knowledge_point_ids") or []),
        stage_id=task.get("stage_id"),
    )
    if ref_error:
        return _fail(ref_error, "invalid_reference")
    # 新增任务不做 task_id 作用域检查（ID 由模型生成），只受环节作用域约束。
    _scope_guard(tc, phases=[task.get("stage_id")] if task.get("stage_id") else None)
    builder = _builder(tc)
    section = builder.find_section(inp.section_id) if inp.section_id else None
    if section is None:
        section = builder.find_section("SEC-TASKS") or next(
            (s for s in builder.sections if any(b.get("kind") == "learning_task" for b in s.get("blocks", []))),
            None,
        )
        if section is None:
            return _fail("候选稿缺少任务章节，请先初始化草稿", "section_missing")
    section_id = section.get("id", "")
    _lock_guard(tc, [f"$.sections[{section_id}].blocks[{task_id}]"])
    if builder.find_task(task_id)[0] is not None:
        return _fail(f"任务 ID 已存在：{task_id}", "task_id_exists")
    blocks = section.setdefault("blocks", [])
    position = len(blocks) if inp.position is None else min(max(0, inp.position), len(blocks))
    blocks.insert(position, dict(task))
    revision = builder.bump_revision()
    return _ok({
        "summary": f"新增任务 {task_id}",
        "affected_json_paths": [f"$.sections[{section_id}].blocks[{task_id}]"],
        "revision": revision,
        "task": dict(task),
    })


class UpdateTaskSheetTaskInput(BaseModel):
    task_id: str
    patch: dict[str, Any] = Field(description="learning_task 字段补丁")
    confirmation_token: str | None = None


async def _task_sheet_update_task(tc: ToolContext, inp: UpdateTaskSheetTaskInput) -> ToolResult:
    builder = _builder(tc)
    block, section = builder.find_task(inp.task_id)
    if block is None or section is None:
        return _fail(f"任务不存在：{inp.task_id}", "task_not_found")
    section_id = section.get("id", "")
    _lock_guard(tc, [builder.task_json_path(inp.task_id)])
    _scope_guard(tc, task_ids=[inp.task_id])
    patch = dict(inp.patch)
    unknown = set(patch) - TASK_EDITABLE_FIELDS
    if unknown:
        return _fail(f"不支持修改字段：{sorted(unknown)}", "invalid_field")
    if "id" in patch and patch["id"] != inp.task_id:
        return _fail("不允许修改任务 ID", "immutable_id")
    # 先校验引用合法性（新 ID 非法时直接拒绝，不进入解绑确认）
    ref_error = _check_refs(
        tc,
        objective_ids=list(patch.get("objective_ids") or block.get("objective_ids") or []),
        knowledge_point_ids=list(patch.get("knowledge_point_ids") or block.get("knowledge_point_ids") or []),
        stage_id=patch.get("stage_id", block.get("stage_id")),
    )
    if ref_error:
        return _fail(ref_error, "invalid_reference")
    preserved_alignment = False
    runtime = getattr(tc, "runtime", None)
    active_intent = str(getattr(runtime, "active_intent", "") or "")
    if (
        "objective_ids" in patch
        and active_intent in CONTENT_EDIT_INTENTS
        and list(patch.get("objective_ids") or []) != list(block.get("objective_ids") or [])
    ):
        # 只保留已有映射；新增/删除映射都属于对齐修复，避免普通润色
        # 因模型输出不完整而意外解绑目标。
        patch["objective_ids"] = list(block.get("objective_ids") or [])
        preserved_alignment = True
    if "objective_ids" in patch:
        removed = set(block.get("objective_ids") or []) - set(patch["objective_ids"])
        if removed:
            # 目标解绑 → 高风险，需确认
            _require_confirmation(tc, inp.confirmation_token, operation="目标解绑")
    before = dict(block)
    changed_keys = [key for key, value in patch.items() if key != "id" and before.get(key) != value]
    if not changed_keys:
        return _ok({
            "summary": f"任务 {inp.task_id} 内容未变化，已保留目标映射",
            "affected_json_paths": [],
            "revision": builder.revision,
            "preserved_fields": ["objective_ids"] if preserved_alignment else [],
        })
    for key, value in patch.items():
        if key == "id":
            continue
        block[key] = value
    revision = builder.bump_revision()
    return _ok({
        "summary": f"更新任务 {inp.task_id}：{', '.join(sorted(changed_keys))}",
        "affected_json_paths": [builder.task_json_path(inp.task_id)],
        "revision": revision,
        "preserved_fields": ["objective_ids"] if preserved_alignment else [],
        "before": summarize_diff(before, dict(block)),
    })


class MoveTaskSheetTaskInput(BaseModel):
    task_id: str
    target_section_id: str = ""
    position: int | None = None
    confirmation_token: str | None = None


async def _task_sheet_move_task(tc: ToolContext, inp: MoveTaskSheetTaskInput) -> ToolResult:
    builder = _builder(tc)
    block, section = builder.find_task(inp.task_id)
    if block is None or section is None:
        return _fail(f"任务不存在：{inp.task_id}", "task_not_found")
    target = builder.find_section(inp.target_section_id) if inp.target_section_id else section
    if target is None:
        return _fail(f"目标章节不存在：{inp.target_section_id}", "section_not_found")
    src_section_id = section.get("id", "")
    dst_section_id = target.get("id", "")
    _lock_guard(tc, [builder.task_json_path(inp.task_id)])
    _scope_guard(tc, task_ids=[inp.task_id])
    moved = builder.move_block(src_section_id, inp.task_id, dst_section_id, index=inp.position)
    revision = builder.bump_revision()
    return _ok({
        "summary": f"移动任务 {inp.task_id} 到章节 {dst_section_id}",
        "affected_json_paths": [f"$.sections[{src_section_id}].blocks[{inp.task_id}]",
                                f"$.sections[{dst_section_id}].blocks[{inp.task_id}]"],
        "revision": revision,
        "task": dict(moved),
    })


class DeleteTaskSheetTaskInput(BaseModel):
    task_id: str
    reason: str = Field(min_length=1, description="删除原因")
    confirmation_token: str | None = None


async def _task_sheet_delete_task(tc: ToolContext, inp: DeleteTaskSheetTaskInput) -> ToolResult:
    builder = _builder(tc)
    block, section = builder.find_task(inp.task_id)
    if block is None or section is None:
        return _fail(f"任务不存在：{inp.task_id}", "task_not_found")
    _require_confirmation(tc, inp.confirmation_token, operation=f"删除任务 {inp.task_id}")
    section_id = section.get("id", "")
    _lock_guard(tc, [builder.task_json_path(inp.task_id)])
    deleted = builder.delete_block(section_id, inp.task_id)
    revision = builder.bump_revision()
    return _ok({
        "summary": f"删除任务 {inp.task_id}（原因：{inp.reason[:60]}）",
        "affected_json_paths": [f"$.sections[{section_id}].blocks[{inp.task_id}]"],
        "revision": revision,
        "deleted_task": dict(deleted),
    })


# ---------------------------------------------------------------------------
# 目标目录 / 记录表 / 问题 / 自评 / 课前准备与课后拓展
# ---------------------------------------------------------------------------


class UpdateTaskSheetObjectivesInput(BaseModel):
    objective_catalog: list[dict[str, Any]] = Field(
        description="完整目标目录（必须包含全部目标条目，每条含 id/statement/success_criterion；"
        "可拆分/新增蓝图外目标，但蓝图目标必须保留）",
    )
    confirmation_token: str | None = None


async def _task_sheet_update_objectives(tc: ToolContext, inp: UpdateTaskSheetObjectivesInput) -> ToolResult:
    builder = _builder(tc)
    if inp.objective_catalog is None:
        return _fail("缺少 objective_catalog", "missing_input")
    catalog_ids = [str(item.get("id")) for item in inp.objective_catalog]
    if len(catalog_ids) != len(set(catalog_ids)):
        return _fail("目标目录包含重复 ID", "duplicate_objective_id")
    # 目标目录允许新增/拆分蓝图外目标（教师细化指令，非破坏性，免确认）；
    # 明确对齐修复中的移除仍属目标解绑，要求人工确认令牌。
    _lock_guard(tc, ["$.objective_catalog"])
    existing_ids = {item.get("id") for item in builder.objective_catalog}
    removed = existing_ids - set(catalog_ids)
    preserved_catalog = False
    active_intent = str(getattr(getattr(tc, "runtime", None), "active_intent", "") or "")
    catalog_items = [dict(item) for item in inp.objective_catalog]
    if removed:
        if active_intent in CONTENT_EDIT_INTENTS:
            # 普通内容润色传回不完整目录时，保留原目录条目；目标目录的
            # 增删/解绑必须由明确的 ALIGNMENT_REPAIR 意图承担。
            incoming_by_id = {str(item.get("id")): item for item in catalog_items}
            merged_catalog: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for item in builder.objective_catalog:
                item_id = str(item.get("id"))
                merged_catalog.append(dict(incoming_by_id.get(item_id) or item))
                seen_ids.add(item_id)
            merged_catalog.extend(
                item for item in catalog_items if str(item.get("id")) not in seen_ids
            )
            catalog_items = merged_catalog
            preserved_catalog = True
        else:
            _require_confirmation(tc, inp.confirmation_token, operation="目标解绑（移除目标目录条目）")
    builder._content["objective_catalog"] = catalog_items
    # 同步所有 objective_list Block：把目录中新增的 ID 追加到每个展示区域的末尾。
    # 目录是权威来源；渲染时前端从 objective_list Block 的 objective_ids 读取，
    # 不自动同步会导致用户看到的目标数与目录不符（显示 N-1 条而非 N 条）。
    new_catalog_ids: list[str] = [str(item.get("id") or "") for item in catalog_items]
    synced_block_paths: list[str] = []
    for section in builder.sections:
        for block in section.get("blocks", []):
            if block.get("kind") != "objective_list":
                continue
            existing: list[str] = list(block.get("objective_ids") or [])
            existing_set = set(existing)
            added = [oid for oid in new_catalog_ids if oid and oid not in existing_set]
            if added:
                block["objective_ids"] = existing + added
                synced_block_paths.append(
                    f"$.sections[{section.get('id', '')}].blocks[{block.get('id', '')}].objective_ids"
                )
    revision = builder.bump_revision()
    return _ok({
        "summary": f"更新目标目录（{len(catalog_items)} 条）" + (
            f"；已同步更新 {len(synced_block_paths)} 个目标展示区域" if synced_block_paths else ""
        ),
        "affected_json_paths": ["$.objective_catalog", *synced_block_paths],
        "revision": revision,
        "preserved_fields": ["objective_catalog"] if preserved_catalog else [],
    })


class UpdateTaskSheetRecordTableInput(BaseModel):
    task_id: str = ""
    record_table: dict[str, Any]
    confirmation_token: str | None = None


async def _task_sheet_update_record_table(tc: ToolContext, inp: UpdateTaskSheetRecordTableInput) -> ToolResult:
    """更新任务内嵌记录表；task_id 为空时更新章节级 record_table Block。"""
    builder = _builder(tc)
    table = dict(inp.record_table)
    if len(table.get("columns") or []) < 2:
        return _fail("记录表至少需要两列 columns", "invalid_record_table")
    if inp.task_id:
        block, section = builder.find_task(inp.task_id)
        if block is None or section is None:
            return _fail(f"任务不存在：{inp.task_id}", "task_not_found")
        _lock_guard(tc, [f"{builder.task_json_path(inp.task_id)}.record_table"])
        block["record_table"] = table
        path = f"{builder.task_json_path(inp.task_id)}.record_table"
    else:
        target, section = _first_block(builder, "record_table")
        if target is None or section is None:
            return _fail("候选稿缺少章节级记录表，请指定任务或先初始化草稿", "record_table_missing")
        _lock_guard(tc, [_block_path(builder, section.get("id", ""), target.get("id", ""))])
        for key, value in table.items():
            if key == "id":
                if value != target.get("id"):
                    return _fail("不允许修改记录表 ID", "immutable_id")
                continue
            if key not in {"title", "instructions", "columns", "blank_rows"}:
                return _fail(f"不支持字段：{key}", "invalid_field")
            target[key] = value
        path = _block_path(builder, section.get("id", ""), target.get("id", ""))
    revision = builder.bump_revision()
    return _ok({"summary": "更新学习记录表", "affected_json_paths": [path], "revision": revision})


class UpdateTaskSheetQuestionsInput(BaseModel):
    questions: list[dict[str, Any]]
    confirmation_token: str | None = None


async def _task_sheet_update_questions(tc: ToolContext, inp: UpdateTaskSheetQuestionsInput) -> ToolResult:
    builder = _builder(tc)
    objectives, _, stages = _valid_ids(tc)
    for question in inp.questions:
        invalid = [ref for ref in question.get("objective_ids") or [] if ref not in objectives]
        if invalid:
            return _fail(f"问题引用了蓝图中不存在的目标：{invalid}", "invalid_reference")
        if question.get("stage_id") and question.get("stage_id") not in stages:
            return _fail(f"问题引用了蓝图中不存在的环节：{question.get('stage_id')}", "invalid_reference")
    target, section = _first_block(builder, "question_set")
    if target is None or section is None:
        return _fail("候选稿缺少问题集 Block", "question_set_missing")
    _lock_guard(tc, [_block_path(builder, section.get("id", ""), target.get("id", ""))])
    target["questions"] = [dict(item) for item in inp.questions]
    revision = builder.bump_revision()
    return _ok({
        "summary": f"更新课堂问题（{len(inp.questions)} 条）",
        "affected_json_paths": [_block_path(builder, section.get("id", ""), target.get("id", ""))],
        "revision": revision,
    })


class UpdateTaskSheetSelfAssessmentInput(BaseModel):
    items: list[dict[str, Any]] | None = Field(
        default=None,
        description="完整自评条目列表（每条含 id/statement/objective_ids；建议与目标目录一一对应）",
    )
    scale: list[str] | None = None
    confirmation_token: str | None = None

    @model_validator(mode="after")
    def _require_content(self) -> "UpdateTaskSheetSelfAssessmentInput":
        if self.items is None and self.scale is None:
            raise ValueError("items 与 scale 至少提供一个")
        return self


async def _task_sheet_update_self_assessment(tc: ToolContext, inp: UpdateTaskSheetSelfAssessmentInput) -> ToolResult:
    builder = _builder(tc)
    target, section = _first_block(builder, "assessment")
    if target is None or section is None:
        return _fail("候选稿缺少自评 Block", "assessment_missing")
    _lock_guard(tc, [_block_path(builder, section.get("id", ""), target.get("id", ""))])
    if inp.items is None and inp.scale is None:
        # schema 已要求 items/scale 至少一个；此处防御直接调用（避免空操作伪造成功）。
        return _fail("未提供任何修改内容（items 或 scale）", "missing_input")
    if inp.scale is not None:
        if len(inp.scale) < 2:
            return _fail("自评量表至少需要两个档位", "invalid_scale")
        target["scale"] = list(inp.scale)
    if inp.items is not None:
        objectives, _, _ = _valid_ids(tc)
        invalid = [ref for item in inp.items for ref in item.get("objective_ids") or [] if ref not in objectives]
        if invalid:
            return _fail(f"自评条目引用了蓝图中不存在的目标：{invalid}", "invalid_reference")
        target["items"] = [dict(item) for item in inp.items]
    revision = builder.bump_revision()
    return _ok({
        "summary": "更新学习成效自我评价",
        "affected_json_paths": [_block_path(builder, section.get("id", ""), target.get("id", ""))],
        "revision": revision,
    })


class UpdateTaskSheetPreparationExtensionInput(BaseModel):
    preparation: list[str] | None = None
    extension: list[str] | None = None
    confirmation_token: str | None = None

    @model_validator(mode="after")
    def _require_content(self) -> "UpdateTaskSheetPreparationExtensionInput":
        if self.preparation is None and self.extension is None:
            raise ValueError("preparation 与 extension 至少提供一个")
        return self


async def _task_sheet_update_preparation_extension(tc: ToolContext, inp: UpdateTaskSheetPreparationExtensionInput) -> ToolResult:
    """更新课前准备清单与课后拓展任务（checklist Block 载荷）。"""
    builder = _builder(tc)
    changed_paths: list[str] = []
    if inp.preparation is not None:
        items = _checklist_items(inp.preparation)
        if items is None:
            return _fail("课前准备至少需要一项非空内容", "checklist_empty")
        _lock_guard(tc, ["$.sections[SEC-PREPARATION]"])
        target, section = _ensure_checklist(builder, "preparation")
        _lock_guard(tc, [_block_path(builder, section.get("id", ""), target.get("id", ""))])
        target["items"] = items
        changed_paths.append(_block_path(builder, section.get("id", ""), target.get("id", "")))
    if inp.extension is not None:
        items = _checklist_items(inp.extension)
        if items is None:
            return _fail("课后拓展至少需要一项非空内容", "checklist_empty")
        _lock_guard(tc, ["$.sections[SEC-EXTENSION]"])
        target, section = _ensure_checklist(builder, "extension")
        _lock_guard(tc, [_block_path(builder, section.get("id", ""), target.get("id", ""))])
        target["items"] = items
        changed_paths.append(_block_path(builder, section.get("id", ""), target.get("id", "")))
    if not changed_paths:
        return _fail("未提供任何修改内容", "missing_input")
    revision = builder.bump_revision()
    return _ok({
        "summary": "更新课前准备与课后拓展",
        "affected_json_paths": changed_paths,
        "revision": revision,
    })


def _find_checklist(builder, kind: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """按 checklist 标题内容定位课前准备 / 课后拓展清单。"""
    markers = {"preparation": ("准备", "preparation"), "extension": ("拓展", "extension")}
    titles = markers[kind]
    for section in builder.sections:
        for block in section.get("blocks", []):
            if block.get("kind") == "checklist":
                title = str(block.get("title", ""))
                if any(marker in title for marker in titles):
                    return block, section
    return None, None


def _checklist_items(values: list[str]) -> list[dict[str, str]] | None:
    """把工具输入规范化为 V3 checklist items；空内容不能生成非法候选稿。"""
    normalized = [str(value).strip() for value in values]
    if not normalized or any(not value for value in normalized):
        return None
    return [{"text": value} for value in normalized]


def _ensure_checklist(builder, kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """缺少可选清单时补建对应章节和 Block，再返回可编辑目标。"""
    target, section = _find_checklist(builder, kind)
    if target is not None and section is not None:
        return target, section

    specs = {
        "preparation": ("SEC-PREPARATION", "课前准备", "课前需要完成的准备工作。", "B-PREPARATION", "课前准备清单"),
        "extension": ("SEC-EXTENSION", "课后拓展", "把本课方法迁移到生活或专业场景。", "B-EXTENSION", "拓展任务"),
    }
    section_id, title, purpose, block_id, block_title = specs[kind]
    section = builder.find_section(section_id)
    if section is None:
        top_level = builder.top_level_sections()
        if kind == "preparation":
            index = next(
                (int(item.get("order", 0)) for item in top_level if item.get("id") == "SEC-TASKS"),
                len(top_level),
            )
        else:
            index = len(top_level)
        builder.add_section(section_id, title, index=index)
        section = builder.find_section(section_id)
    if section is None:  # defensive guard for unusual builder implementations
        raise ValueError(f"无法创建清单章节：{section_id}")
    if block_id in builder.all_block_ids():
        suffix = 2
        candidate = f"{block_id}-{suffix}"
        while candidate in builder.all_block_ids():
            suffix += 1
            candidate = f"{block_id}-{suffix}"
        block_id = candidate
    builder.add_block(section_id, {
        "kind": "checklist", "id": block_id, "title": block_title, "items": [],
    })
    target, section = _find_checklist(builder, kind)
    if target is None or section is None:
        raise ValueError(f"无法创建清单 Block：{block_id}")
    return target, section


# ---------------------------------------------------------------------------
# 章节级结构工具（task_architect 角色：新增/重命名/删除章节、阶段划分）
# ---------------------------------------------------------------------------


class AddTaskSheetSectionInput(BaseModel):
    section_id: str = Field(min_length=1, pattern=r"^SEC-[A-Z0-9-]+$")
    title: str = Field(min_length=1)
    parent_id: str = ""
    order: int | None = None
    purpose: str = ""
    confirmation_token: str | None = None


async def _task_sheet_add_section(tc: ToolContext, inp: AddTaskSheetSectionInput) -> ToolResult:
    """新增目录章节（结构调整）。"""
    _require_confirmation(tc, inp.confirmation_token, operation="新增/调整章节结构")
    builder = _builder(tc)
    _lock_guard(tc, [f"$.sections[{inp.section_id}]"])
    if builder.find_section(inp.section_id) is not None:
        return _fail(f"章节已存在：{inp.section_id}", "section_exists")
    try:
        node = builder.add_section(
            inp.section_id, inp.title, parent_id=inp.parent_id, index=inp.order,
        )
        if inp.purpose:
            builder.update_section_metadata(inp.section_id, purpose=inp.purpose)
    except ValueError as exc:
        return _fail(str(exc), "section_op_failed")
    revision = builder.bump_revision()
    return _ok({
        "summary": f"新增章节 {inp.section_id}",
        "affected_json_paths": [f"$.sections[{inp.section_id}]"],
        "revision": revision, "section": dict(node),
    })


class UpdateTaskSheetSectionInput(BaseModel):
    section_id: str
    title: str | None = None
    purpose: str | None = None
    objective_ids: list[str] | None = None
    confirmation_token: str | None = None

    @model_validator(mode="after")
    def _require_change(self) -> "UpdateTaskSheetSectionInput":
        if self.title is None and self.purpose is None and self.objective_ids is None:
            raise ValueError("title / purpose / objective_ids 至少提供一个")
        return self


async def _task_sheet_update_section(tc: ToolContext, inp: UpdateTaskSheetSectionInput) -> ToolResult:
    """重命名章节 / 更新目的 / 绑定目标（结构调整）。"""
    builder = _builder(tc)
    node = builder.find_section(inp.section_id)
    if node is None:
        return _fail(f"章节不存在：{inp.section_id}", "section_not_found")
    _lock_guard(tc, [f"$.sections[{inp.section_id}]"])
    if inp.objective_ids is not None:
        objectives, _, _ = _valid_ids(tc)
        invalid = [ref for ref in inp.objective_ids if ref not in objectives]
        if invalid:
            return _fail(f"章节绑定了蓝图中不存在的目标：{invalid}", "invalid_reference")
    changed: list[str] = []
    if inp.title is not None:
        builder.rename_section(inp.section_id, inp.title)
        changed.append("title")
    if inp.purpose is not None or inp.objective_ids is not None:
        builder.update_section_metadata(
            inp.section_id, purpose=inp.purpose, objective_ids=inp.objective_ids,
        )
        changed.extend(["purpose"] if inp.purpose is not None else [])
        changed.extend(["objective_ids"] if inp.objective_ids is not None else [])
    revision = builder.bump_revision()
    return _ok({
        "summary": f"更新章节 {inp.section_id}：{', '.join(changed)}",
        "affected_json_paths": [f"$.sections[{inp.section_id}]"],
        "revision": revision,
    })


class DeleteTaskSheetSectionInput(BaseModel):
    section_id: str
    reason: str = Field(min_length=1, description="删除原因")
    move_blocks_to: str = ""
    confirmation_token: str | None = None


async def _task_sheet_delete_section(tc: ToolContext, inp: DeleteTaskSheetSectionInput) -> ToolResult:
    """删除目录章节（高风险，需确认令牌；block 可迁移到 move_blocks_to 章节）。"""
    _require_confirmation(tc, inp.confirmation_token, operation=f"删除章节 {inp.section_id}")
    builder = _builder(tc)
    node = builder.find_section(inp.section_id)
    if node is None:
        return _fail(f"章节不存在：{inp.section_id}", "section_not_found")
    _lock_guard(tc, [f"$.sections[{inp.section_id}]"])
    if inp.move_blocks_to:
        target = builder.find_section(inp.move_blocks_to)
        if target is None:
            return _fail(f"迁移目标章节不存在：{inp.move_blocks_to}", "section_not_found")
    deleted = builder.delete_section(inp.section_id)
    if inp.move_blocks_to and inp.move_blocks_to != inp.section_id:
        for block in deleted.get("blocks", []):
            builder.move_block(inp.section_id, block.get("id"), inp.move_blocks_to)
    revision = builder.bump_revision()
    return _ok({
        "summary": f"删除章节 {inp.section_id}（原因：{inp.reason[:60]}）",
        "affected_json_paths": [f"$.sections[{inp.section_id}]"],
        "revision": revision,
        "deleted_section": dict(deleted),
    })


def summarize_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """修改前后摘要：返回变更字段（用于方案 §2.3「修改前后摘要」）。"""
    changed = {}
    all_keys = set(before) | set(after)
    for key in all_keys:
        if before.get(key) != after.get(key):
            changed[key] = {"from": before.get(key), "to": after.get(key)}
    return changed


def _register_edit_tools() -> None:
    _register_structure_tools()
    register_tool(Tool("task_sheet_initialize_draft", "首次生成或 V1 升级时创建 V3 候选稿基线",
                       InitializeTaskSheetDraftInput, _task_sheet_initialize_draft))
    register_tool(Tool("task_sheet_add_task", "新增学习任务（learning_task Block）",
                       AddTaskSheetTaskInput, _task_sheet_add_task))
    register_tool(Tool("task_sheet_update_task", "更新学习任务字段（步骤/完成标准/产出/支架等）",
                       UpdateTaskSheetTaskInput, _task_sheet_update_task))
    register_tool(Tool("task_sheet_move_task", "移动学习任务到其他章节或位置",
                       MoveTaskSheetTaskInput, _task_sheet_move_task))
    register_tool(Tool("task_sheet_delete_task", "删除学习任务（高风险，需人工确认令牌）",
                       DeleteTaskSheetTaskInput, _task_sheet_delete_task))
    register_tool(Tool("task_sheet_update_objectives", "更新目标目录（目标解绑需人工确认令牌）",
                       UpdateTaskSheetObjectivesInput, _task_sheet_update_objectives))
    register_tool(Tool("task_sheet_update_record_table", "更新学习观察记录表（任务内嵌或章节级）",
                       UpdateTaskSheetRecordTableInput, _task_sheet_update_record_table))
    register_tool(Tool("task_sheet_update_questions", "更新课堂问题集",
                       UpdateTaskSheetQuestionsInput, _task_sheet_update_questions))
    register_tool(Tool("task_sheet_update_self_assessment", "更新学习成效自我评价（条目与量表）",
                       UpdateTaskSheetSelfAssessmentInput, _task_sheet_update_self_assessment))
    register_tool(Tool("task_sheet_update_preparation_extension", "更新课前准备清单与课后拓展任务",
                       UpdateTaskSheetPreparationExtensionInput, _task_sheet_update_preparation_extension))


def _register_structure_tools() -> None:
    register_tool(Tool("task_sheet_add_section", "新增目录章节（结构调整，需确认令牌）",
                       AddTaskSheetSectionInput, _task_sheet_add_section))
    register_tool(Tool("task_sheet_update_section", "重命名章节/更新目的/绑定目标",
                       UpdateTaskSheetSectionInput, _task_sheet_update_section))
    register_tool(Tool("task_sheet_delete_section", "删除目录章节（高风险，需确认令牌）",
                       DeleteTaskSheetSectionInput, _task_sheet_delete_section))
