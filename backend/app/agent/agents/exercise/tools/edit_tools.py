"""课后练习工具集：修改类工具。

所有修改作用于内存候选稿（ExerciseBuilder），绝不直接改写正式 Artifact。
修改工具必须通过锁定/作用域守卫；删除等高风险操作要求有效的人工确认令牌。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.agents.exercise.tools._common import (
    _builder, _lock_guard, _require_confirmation, _scope_guard,
)
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool, summarize
from app.schemas.artifact import ExerciseContent


class InitializeDraftInput(BaseModel):
    pass


async def _exercise_initialize_draft(tc: ToolContext, _: InitializeDraftInput) -> ToolResult:
    """初始化候选稿（无参）。首次生成时由 builder 以蓝图确定性示例为种子。

    修订场景中候选稿已由 runtime._prepare_builder 加载源文档，本工具为 no-op；
    关键作用是向 LLM 暴露现有题目 ID，使其生成新题目时避免 ID 冲突。
    """
    builder = _builder(tc)
    if len(builder.sections) == 0:
        from app.agent.agents.exercise.builder import build_initial_builder

        bp_data = tc.ctx.blueprint if tc.ctx is not None else None
        bp_content = bp_data.model_dump() if hasattr(bp_data, "model_dump") else (bp_data or {})
        task_sheet_raw = (tc.ctx.upstream or {}).get("task_sheet") if tc.ctx is not None else None
        tc.extra["builder"] = build_initial_builder(bp_content, task_sheet_raw)
        builder = tc.extra["builder"]
    existing_ids = builder.all_question_ids()
    return ToolResult(output={
        "ok": True,
        "schema_version": builder.to_content().get("schema_version"),
        "sections": [
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "score": s.get("score"),
                "existing_question_ids": [
                    b.get("id") for b in s.get("blocks", [])
                ],
            }
            for s in builder.sections
        ],
        "existing_question_ids": existing_ids,
        "note": (
            "候选稿已就绪，可通过 add/update 工具精修。"
            f"现有题目 ID（新增题目时必须使用不在此列表中的全新 ID）：{existing_ids}"
        ),
    })


class AddQuestionInput(BaseModel):
    section_id: str = Field(description="目标分区 ID：basic_consolidation / understanding_application / transfer_challenge")
    question: dict = Field(description="完整题目对象（kind=question，含 stem/score/objective_ids/answer_key 等）")


async def _exercise_add_question(tc: ToolContext, inp: AddQuestionInput) -> ToolResult:
    """向指定分区添加一道独立题目。"""
    builder = _builder(tc)
    _lock_guard(tc, [f"$.sections[{inp.section_id}].blocks"])
    _scope_guard(tc, section_ids=[inp.section_id])
    question = dict(inp.question)
    question["kind"] = "question"
    builder.add_block(inp.section_id, question)
    builder.bump_revision()
    return ToolResult(output={
        "ok": True,
        "question_id": question.get("id"),
        "path": builder.question_json_path(question["id"]),
        "section_scores": [{"id": s.get("id"), "score": s.get("score")} for s in builder.sections],
        "note": "题目已加入候选稿；需保证分区题目分值之和等于分区分值。",
    })


class BatchQuestionAddition(BaseModel):
    section_id: str
    question: dict


class BatchScoreUpdate(BaseModel):
    question_id: str
    score: int = Field(gt=0)
    scoring_points: list[dict] | None = None


class BatchQuestionUpdate(BaseModel):
    question_id: str
    patch: dict = Field(description="仅用于修复本轮新增题；kind/id/section 不可改")


class ApplyQuestionBatchInput(BaseModel):
    base_revision: int = Field(ge=0, description="读取候选稿时获得的 builder_revision")
    additions: list[BatchQuestionAddition] = Field(default_factory=list)
    removals: list[str] = Field(default_factory=list, description="精确缩减时原子删除的既有题目 ID")
    question_updates: list[BatchQuestionUpdate] = Field(default_factory=list)
    score_updates: list[BatchScoreUpdate] = Field(default_factory=list)
    expected_question_type: str | None = None
    expected_type_count: int | None = Field(default=None, ge=0)
    expected_total_delta: int | None = None
    allowed_section_ids: list[str] = Field(default_factory=list)


async def _exercise_apply_question_batch(tc: ToolContext, inp: ApplyQuestionBatchInput) -> ToolResult:
    """Atomically add complete questions and rebalance scores in affected sections."""
    from app.agent.agents.exercise.builder import ExerciseBuilder

    builder = _builder(tc)
    if inp.base_revision != builder.revision:
        return ToolResult(
            ok=False,
            error=f"候选稿版本冲突：期望 {inp.base_revision}，当前 {builder.revision}",
            error_code="builder_revision_conflict",
            retryable=True,
        )
    runtime = getattr(tc, "runtime", None)
    plan = getattr(runtime, "intent_plan", None) if runtime else None
    allowed_sections = set(inp.allowed_section_ids or getattr(plan, "allowed_section_ids", None) or [])
    before = builder.to_content()
    before_ids = set(builder.all_question_ids())
    before_counts = builder.question_type_counts()
    before_sections = {
        item.get("id"): (item.get("title"), item.get("score"))
        for item in before.get("sections", [])
    }
    candidate = ExerciseBuilder(before)
    baseline_content = getattr(runtime, "baseline_content", before) if runtime else before
    baseline_ids = set(ExerciseBuilder(baseline_content).all_question_ids())

    try:
        if inp.removals and getattr(plan, "mutation_mode", None) != "delete_excess":
            raise ValueError("只有已明确授权的精确缩减意图可以批量删除题目")
        planned_removals = set(getattr(plan, "delete_question_ids", None) or [])
        if planned_removals and set(inp.removals) != planned_removals:
            raise ValueError(
                f"批次删除目标与意图解析不一致：期望 {sorted(planned_removals)}，实际 {sorted(inp.removals)}"
            )
        expected_type = inp.expected_question_type or getattr(plan, "question_type", None)
        for question_id in inp.removals:
            existing, section, _ = candidate.find_question(question_id)
            if existing is None or section is None:
                raise ValueError(f"待删除题目不存在：{question_id}")
            section_id = str(section.get("id") or "")
            if allowed_sections and section_id not in allowed_sections:
                raise ValueError(f"题目 {question_id} 不在允许缩减的分区")
            if expected_type and existing.get("question_type") != expected_type:
                raise ValueError(f"精确缩减不得删除其他题型：{question_id}")
            _scope_guard(tc, question_ids=[question_id], section_ids=[section_id])
            _lock_guard(tc, [candidate.question_json_path(question_id)])
            candidate.delete_block(question_id)

        for addition in inp.additions:
            if allowed_sections and addition.section_id not in allowed_sections:
                raise ValueError(f"分区 {addition.section_id} 不属于本轮允许范围：{sorted(allowed_sections)}")
            _scope_guard(tc, section_ids=[addition.section_id])
            _lock_guard(tc, [f"$.sections[{addition.section_id}].blocks"])
            question = dict(addition.question)
            question["kind"] = "question"
            question_id = str(question.get("id") or "")
            if not question_id:
                raise ValueError("批量新增题目必须提供稳定 ID")
            if question_id in before_ids:
                raise ValueError(f"add_only 批次不得覆盖已有题目：{question_id}")
            candidate.add_block(addition.section_id, question)

        for update in inp.question_updates:
            if update.question_id in baseline_ids:
                raise ValueError(f"add_only 批次不得修改源卷既有题目内容：{update.question_id}")
            existing, section, _ = candidate.find_question(update.question_id)
            if existing is None or section is None:
                raise ValueError(f"本轮新增题目不存在：{update.question_id}")
            section_id = str(section.get("id") or "")
            if allowed_sections and section_id not in allowed_sections:
                raise ValueError(f"题目 {update.question_id} 不在允许修改的分区")
            forbidden = {"id", "kind", "question_type"} & set(update.patch)
            if forbidden:
                raise ValueError(f"修复补丁不得修改字段：{sorted(forbidden)}")
            _lock_guard(tc, [candidate.question_json_path(update.question_id)])
            candidate.update_block(update.question_id, dict(update.patch))

        for update in inp.score_updates:
            existing, section, _ = candidate.find_question(update.question_id)
            if existing is None or section is None:
                raise ValueError(f"题目不存在：{update.question_id}")
            section_id = str(section.get("id") or "")
            if allowed_sections and section_id not in allowed_sections:
                raise ValueError(f"题目 {update.question_id} 不在允许调整分值的分区")
            _scope_guard(tc, question_ids=[update.question_id], section_ids=[section_id])
            path = candidate.question_json_path(update.question_id)
            _lock_guard(tc, [path])
            patch: dict[str, Any] = {"score": update.score}
            if update.scoring_points is not None:
                patch["scoring_points"] = update.scoring_points
            candidate.update_block(update.question_id, patch)

        candidate_content = candidate.to_content()
        after_sections = {
            item.get("id"): (item.get("title"), item.get("score"))
            for item in candidate_content.get("sections", [])
        }
        if getattr(plan, "preserve_section_scores", False) and after_sections != before_sections:
            raise ValueError("本轮必须保留源卷分区标题与分值")
        validated = ExerciseContent.model_validate(candidate_content).model_dump()
        after_candidate = ExerciseBuilder(validated)
        after_counts = after_candidate.question_type_counts()
        actual_delta = len(after_candidate.all_question_ids()) - len(baseline_ids)
        expected_count = inp.expected_type_count
        if expected_count is None:
            expected_count = getattr(plan, "target_count", None)
        expected_delta = inp.expected_total_delta
        if expected_delta is None:
            expected_delta = getattr(plan, "requested_delta", None)
        if expected_type and expected_count is not None and after_counts.get(expected_type, 0) != expected_count:
            raise ValueError(
                f"批次后 {expected_type} 数量为 {after_counts.get(expected_type, 0)}，目标为 {expected_count}"
            )
        if expected_delta is not None and actual_delta != expected_delta:
            raise ValueError(f"批次题目总数变化 {actual_delta}，目标变化 {expected_delta}")
    except Exception as exc:  # candidate is isolated; live builder remains untouched
        return ToolResult(
            ok=False,
            error=f"批量修改未应用：{str(exc)[:500]}",
            error_code="question_batch_rejected",
            retryable=True,
            output={
                "rolled_back": True,
                "builder_revision": builder.revision,
                "question_type_counts": before_counts,
            },
        )

    builder.replace_content(validated, revision=builder.revision + 1)
    added_ids = [item for item in builder.all_question_ids() if item not in before_ids]
    removed_ids = [item for item in before_ids if item not in set(builder.all_question_ids())]
    if runtime is not None:
        affected = {item.section_id for item in inp.additions}
        for question_id in removed_ids:
            _, section, _ = ExerciseBuilder(before).find_question(question_id)
            if section is not None:
                affected.add(str(section.get("id") or ""))
        runtime.affected_section_ids = sorted(item for item in affected if item)
    return ToolResult(output={
        "ok": True,
        "builder_revision": builder.revision,
        "added_question_ids": added_ids,
        "removed_question_ids": removed_ids,
        "score_updated_question_ids": [item.question_id for item in inp.score_updates],
        "updated_new_question_ids": [item.question_id for item in inp.question_updates],
        "actual_delta": len(builder.all_question_ids()) - len(before_ids),
        "before_type_counts": before_counts,
        "after_type_counts": builder.question_type_counts(),
        "section_scores": [
            {"id": item.get("id"), "score": item.get("score")}
            for item in builder.sections
        ],
    })


class AddQuestionGroupInput(BaseModel):
    section_id: str = Field(description="目标分区 ID")
    group: dict = Field(description="完整题组对象（kind=question_group，含 title/stimuli/sub_questions）")


class MoveQuestionInput(BaseModel):
    question_id: str = Field(description="要移动的既有顶层题目 ID")
    destination_section_id: str = Field(description="目标分区 ID")


async def _exercise_move_question(tc: ToolContext, inp: MoveQuestionInput) -> ToolResult:
    """原子移动既有题目，不允许模型重写题目，并同步重算分区分值。"""
    from app.agent.agents.exercise.builder import ExerciseBuilder

    builder = _builder(tc)
    question, source, group = builder.find_question(inp.question_id)
    destination = builder.find_section(inp.destination_section_id)
    if question is None or source is None:
        return ToolResult(ok=False, error=f"题目不存在：{inp.question_id}", error_code="question_not_found")
    if group is not None:
        return ToolResult(ok=False, error="题组子题不能脱离共享材料单独移动", error_code="group_question_move_unsupported")
    if destination is None:
        return ToolResult(ok=False, error=f"分区不存在：{inp.destination_section_id}", error_code="section_not_found")
    source_path = builder.question_json_path(inp.question_id)
    destination_index = next(
        index for index, item in enumerate(builder.sections) if item.get("id") == inp.destination_section_id
    )
    _lock_guard(tc, [source_path, f"$.sections[{destination_index}].blocks"])
    _scope_guard(tc, question_ids=[inp.question_id])
    candidate = ExerciseBuilder(builder.to_content())
    try:
        result = candidate.move_question(inp.question_id, inp.destination_section_id)
        validated = ExerciseContent.model_validate(candidate.to_content()).model_dump()
    except Exception as exc:
        return ToolResult(
            ok=False,
            error=f"题目移动未应用：{str(exc)[:500]}",
            error_code="question_move_rejected",
            retryable=True,
            output={"rolled_back": True, "builder_revision": builder.revision},
        )
    if result["moved"]:
        builder.replace_content(validated, revision=builder.revision + 1)
    runtime = getattr(tc, "runtime", None)
    if runtime is not None:
        runtime.affected_section_ids = sorted({
            result["source_section_id"], result["destination_section_id"],
        })
    return ToolResult(output={
        "ok": True,
        **result,
        "path": builder.question_json_path(inp.question_id),
        "section_scores": [{"id": s.get("id"), "score": s.get("score")} for s in builder.sections],
        "note": "既有题目已原样移动；分区分值已按各区题目分值之和同步重算。",
    })


async def _exercise_add_question_group(tc: ToolContext, inp: AddQuestionGroupInput) -> ToolResult:
    """向指定分区添加一个共享材料题组。"""
    builder = _builder(tc)
    _lock_guard(tc, [f"$.sections[{inp.section_id}].blocks"])
    _scope_guard(tc, section_ids=[inp.section_id])
    group = dict(inp.group)
    group["kind"] = "question_group"
    builder.add_block(inp.section_id, group)
    builder.bump_revision()
    return ToolResult(output={
        "ok": True,
        "group_id": group.get("id"),
        "note": "题组已加入候选稿；子题分值之和会计入分区分值。",
    })


class UpdateQuestionInput(BaseModel):
    question_id: str = Field(description="题目 ID（顶层 question 或题组 sub_question）")
    patch: dict = Field(description="字段补丁：覆盖 stem/options/score/answer_key/scoring_points 等；kind/id 不可改")


async def _exercise_update_question(tc: ToolContext, inp: UpdateQuestionInput) -> ToolResult:
    """更新一道题目（题干/选项/答案/评分点/难度/用时等）。"""
    builder = _builder(tc)
    question, section, group = builder.find_question(inp.question_id)
    if question is None:
        return ToolResult(ok=False, error=f"题目不存在：{inp.question_id}", error_code="question_not_found", retryable=True)
    path = builder.question_json_path(inp.question_id)
    _lock_guard(tc, [path])
    _scope_guard(tc, question_ids=[inp.question_id], section_ids=[section.get("id")])
    builder.update_block(inp.question_id, dict(inp.patch))
    builder.bump_revision()
    return ToolResult(output={
        "ok": True,
        "question_id": inp.question_id,
        "path": path,
        "note": "题目已更新；若改了分值，需保证评分点之和等于题目分值。",
    })


class UpdateQuestionGroupInput(BaseModel):
    group_id: str = Field(description="题组 ID")
    patch: dict = Field(description="字段补丁：覆盖 title/instructions；kind/id 不可改")


async def _exercise_update_question_group(tc: ToolContext, inp: UpdateQuestionGroupInput) -> ToolResult:
    """更新题组元数据（标题/指令）。"""
    builder = _builder(tc)
    block, section = builder._block_owner(inp.group_id)
    if block is None or block.get("kind") != "question_group":
        return ToolResult(ok=False, error=f"题组不存在：{inp.group_id}", error_code="group_not_found", retryable=True)
    _lock_guard(tc, [f"$.sections[{section.get('id')}].blocks"])
    _scope_guard(tc, section_ids=[section.get("id")])
    builder.update_block(inp.group_id, dict(inp.patch))
    builder.bump_revision()
    return ToolResult(output={"ok": True, "group_id": inp.group_id})


class DeleteQuestionInput(BaseModel):
    question_id: str = Field(description="题目或题组 ID")
    confirmation_token: str | None = Field(default=None, description="高风险操作的人工确认令牌")


async def _exercise_delete_question(tc: ToolContext, inp: DeleteQuestionInput) -> ToolResult:
    """删除一道题目或题组（高风险操作，需要人工确认令牌）。"""
    builder = _builder(tc)
    question, section, group = builder.find_question(inp.question_id)
    if question is not None:
        path = builder.question_json_path(inp.question_id)
    else:
        block, section_owner = builder._block_owner(inp.question_id)
        if block is None:
            return ToolResult(ok=False, error=f"题目/题组不存在：{inp.question_id}", error_code="question_not_found", retryable=True)
        section = section_owner
        path = f"$.sections[{section.get('id')}].blocks"
    _lock_guard(tc, [path])
    _scope_guard(tc, question_ids=[inp.question_id], section_ids=[section.get("id")])
    _require_confirmation(tc, inp.confirmation_token, operation="删除题目/题组")
    builder.delete_block(inp.question_id)
    builder.bump_revision()
    return ToolResult(output={
        "ok": True,
        "deleted_id": inp.question_id,
        "section_scores": [{"id": s.get("id"), "score": s.get("score")} for s in builder.sections],
        "note": "已删除；需重新核算分区分值使总分保持 100。",
    })


class UpdateSectionInput(BaseModel):
    section_id: str = Field(description="目标分区 ID")
    title: str | None = None
    score: int | None = Field(default=None, description="新的分区分值（正整数）")


async def _exercise_update_section(tc: ToolContext, inp: UpdateSectionInput) -> ToolResult:
    """更新分区标题或分区分值。修改分值后需保证三分区之和仍为 100。"""
    builder = _builder(tc)
    _lock_guard(tc, [f"$.sections[{inp.section_id}]"])
    _scope_guard(tc, section_ids=[inp.section_id])
    section = builder.find_section(inp.section_id)
    if section is None:
        return ToolResult(ok=False, error=f"分区不存在：{inp.section_id}", error_code="section_not_found", retryable=True)
    if inp.title is not None:
        builder.update_section_title(inp.section_id, inp.title)
    if inp.score is not None:
        builder.update_section_score(inp.section_id, inp.score)
    builder.bump_revision()
    return ToolResult(output={
        "ok": True,
        "section": {"id": inp.section_id, "title": section.get("title"), "score": section.get("score")},
        "section_scores": [{"id": s.get("id"), "score": s.get("score")} for s in builder.sections],
        "note": "已更新分区；三分区之和必须等于 100。",
    })


class UpdatePaperSettingsInput(BaseModel):
    patch: dict = Field(description="试卷设置补丁：title/student_instructions/estimated_minutes/answer_requirements")


async def _exercise_update_paper_settings(tc: ToolContext, inp: UpdatePaperSettingsInput) -> ToolResult:
    """更新试卷设置（标题/学生指令/预计用时/作答要求）。"""
    builder = _builder(tc)
    _lock_guard(tc, ["$.paper_settings"])
    builder.update_paper_settings(dict(inp.patch))
    builder.bump_revision()
    return ToolResult(output={
        "ok": True,
        "paper_settings": builder.paper_settings,
        "note": "total_score 固定为 100，由各分区与题目分值决定，不可直接修改。",
    })


class UpdateStimulusInput(BaseModel):
    stimulus_id: str = Field(description="材料 ID（题组 stimuli 中）")
    patch: dict = Field(description="材料补丁：title/text/columns/rows/visual 等；kind/id 不可改")


async def _exercise_update_stimulus(tc: ToolContext, inp: UpdateStimulusInput) -> ToolResult:
    """更新题组共享材料（文本/表格/视觉材料字段）。"""
    builder = _builder(tc)
    builder.update_stimulus(inp.stimulus_id, dict(inp.patch))
    builder.bump_revision()
    return ToolResult(output={"ok": True, "stimulus_id": inp.stimulus_id})


def _register_edit_tools() -> None:
    register_tool(Tool(
        "exercise_initialize_draft", "初始化候选稿（首次生成或候选稿为空时调用）",
        InitializeDraftInput, _exercise_initialize_draft,
    ))
    register_tool(Tool(
        "exercise_add_question", "向指定分区添加一道独立题目",
        AddQuestionInput, _exercise_add_question,
    ))
    register_tool(Tool(
        "exercise_move_question", "原子移动一道既有顶层题目到目标分区，并保持题目内容不变",
        MoveQuestionInput, _exercise_move_question,
    ))
    register_tool(Tool(
        "exercise_apply_question_batch",
        "原子批量新增完整题目并在受影响分区内重平衡分值；失败时完整回滚",
        ApplyQuestionBatchInput, _exercise_apply_question_batch,
    ))
    register_tool(Tool(
        "exercise_add_question_group", "向指定分区添加一个共享材料题组",
        AddQuestionGroupInput, _exercise_add_question_group,
    ))
    register_tool(Tool(
        "exercise_update_question", "更新一道题目（题干/选项/答案/评分点/难度/用时等）",
        UpdateQuestionInput, _exercise_update_question,
    ))
    register_tool(Tool(
        "exercise_update_question_group", "更新题组元数据（标题/指令）",
        UpdateQuestionGroupInput, _exercise_update_question_group,
    ))
    register_tool(Tool(
        "exercise_delete_question", "删除一道题目或题组（高风险，需确认令牌）",
        DeleteQuestionInput, _exercise_delete_question,
    ))
    register_tool(Tool(
        "exercise_update_section", "更新分区标题或分区分值",
        UpdateSectionInput, _exercise_update_section,
    ))
    register_tool(Tool(
        "exercise_update_paper_settings", "更新试卷设置（标题/指令/用时/作答要求）",
        UpdatePaperSettingsInput, _exercise_update_paper_settings,
    ))
    register_tool(Tool(
        "exercise_update_stimulus", "更新题组共享材料（文本/表格/视觉字段）",
        UpdateStimulusInput, _exercise_update_stimulus,
    ))
