"""教师逐字稿工具集：编辑类工具。

只修改内存中的 VerbatimBuilder 候选稿，绝不直接写正式 Artifact。
所有编辑工具检查：章节/场景 ID 存在、锁定路径（含祖先/后代）、修改范围属于本轮
意图；删除章节/解绑场景等高风险操作要求有效人工确认令牌。违规返回可修复的
ToolResult(ok=False) 让 Agent 调整方案，不得静默覆盖。

每个修改工具返回：实际修改路径（affected_json_paths）、修改前后摘要与可重试错误。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.agents.verbatim.tools._common import (
    _builder,
    _lock_guard,
    _require_confirmation,
    _scope_guard,
)
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool

EDITABLE_FIELDS = {"required_text", "optional_text", "delivery_tone", "key_emphasis", "interaction", "pause_seconds"}


def _ok(output: dict[str, Any]) -> ToolResult:
    return ToolResult(output={"ok": True, **output})


def _fail(error: str, code: str = "verbatim_edit_failed") -> ToolResult:
    return ToolResult(ok=False, error=error, error_code=code, retryable=True)


def _section_path(section_id: str) -> str:
    return f"$.sections[{section_id}]"


class InitializeVerbatimDraftInput(BaseModel):
    pass


async def _vb_initialize_draft(tc: ToolContext, _: InitializeVerbatimDraftInput) -> ToolResult:
    """首次生成或 V1 升级时创建 V2 候选稿基线（蓝图 + 视频脚本确定性生成）。"""
    _lock_guard(tc, ["$"])
    builder = _builder(tc)
    if builder.count_sections() == 0:
        bp_data = tc.ctx.blueprint.model_dump() if tc.ctx is not None and hasattr(tc.ctx.blueprint, "model_dump") else (tc.ctx.blueprint or {}) if tc.ctx is not None else {}
        from app.agent.agents.verbatim.builder import build_initial_builder

        video_script_raw = _video_script_raw(tc)
        fresh = build_initial_builder(bp_data, video_script_raw)
        tc.extra["builder"] = fresh
        return _ok({
            "summary": f"已初始化 V2 逐字稿草稿（{fresh.count_sections()} 段）",
            "revision": fresh.revision,
            "affected_json_paths": ["$"],
            "section_count": fresh.count_sections(),
        })
    return _ok({"summary": "草稿已存在，跳过初始化", "revision": builder.revision, "affected_json_paths": []})


class UpdateVerbatimSectionInput(BaseModel):
    section_id: str = Field(min_length=1)
    required_text: str | None = Field(default=None, description="必讲口播（改写时不得丢失源场景必需术语/数字/结论）")
    optional_text: str | None = None
    delivery_tone: str | None = None
    key_emphasis: list[str] | None = None
    interaction: str | None = None
    pause_seconds: float | None = None
    confirmation_token: str | None = None


async def _vb_update_section(tc: ToolContext, inp: UpdateVerbatimSectionInput) -> ToolResult:
    """修改指定章节的口播/补充/语气/重音/互动/停顿。"""
    builder = _builder(tc)
    section = builder.find_section(inp.section_id)
    if section is None:
        return _fail(f"章节不存在：{inp.section_id}", "section_not_found")
    _lock_guard(tc, [_section_path(inp.section_id)])
    try:
        _scope_guard(tc, [inp.section_id])
    except ValueError as exc:
        return _fail(str(exc), "section_scope_violation")
    changed: list[str] = []
    try:
        if inp.required_text is not None:
            builder.update_required_text(inp.section_id, inp.required_text)
            changed.append("required_text")
        if inp.optional_text is not None:
            builder.update_optional_text(inp.section_id, inp.optional_text)
            changed.append("optional_text")
        if inp.delivery_tone is not None:
            builder.update_tone(inp.section_id, inp.delivery_tone)
            changed.append("delivery_tone")
        if inp.key_emphasis is not None:
            builder.update_emphasis(inp.section_id, inp.key_emphasis)
            changed.append("key_emphasis")
        if inp.interaction is not None:
            builder.update_interaction(inp.section_id, inp.interaction)
            changed.append("interaction")
        if inp.pause_seconds is not None:
            builder.update_pause(inp.section_id, inp.pause_seconds)
            changed.append("pause_seconds")
    except ValueError as exc:
        return _fail(str(exc), "section_update_failed")
    if not changed:
        return _fail("未提供任何修改字段", "missing_input")
    revision = builder.bump_revision()
    return _ok({
        "summary": f"更新章节 {inp.section_id}：{', '.join(changed)}",
        "affected_json_paths": [_section_path(inp.section_id)],
        "revision": revision,
        "section": builder.find_section(inp.section_id),
    })


class BatchVerbatimStyleInput(BaseModel):
    tone: str | None = Field(default=None, description="统一到该语气")
    emphasis: list[str] | None = Field(default=None, description="追加这些重音词（不覆盖已有）")
    pause_seconds: float | None = Field(default=None, ge=0, le=30)


async def _vb_batch_style(tc: ToolContext, inp: BatchVerbatimStyleInput) -> ToolResult:
    """批量风格润色：对全部章节统一语气/重音/停顿（不改动必讲事实与数字）。"""
    builder = _builder(tc)
    _lock_guard(tc, ["$.sections"])
    if inp.tone is None and inp.emphasis is None and inp.pause_seconds is None:
        return _fail("未提供任何风格修改", "missing_input")
    changed = builder.batch_style(tone=inp.tone, emphasis=inp.emphasis, pause_seconds=inp.pause_seconds)
    revision = builder.bump_revision()
    return _ok({
        "summary": f"批量风格润色（{len(changed)} 段）",
        "affected_json_paths": ["$.sections"],
        "revision": revision,
        "changed_section_ids": changed,
    })


class RebalanceVerbatimTimingInput(BaseModel):
    speaking_rate_cps: float | None = Field(default=None, ge=1.0, le=12.0, description="新默认语速（字/秒）")


async def _vb_rebalance_timing(tc: ToolContext, inp: RebalanceVerbatimTimingInput) -> ToolResult:
    """按语速与场景时长重算停顿，使「口播 + 停顿」贴合每段时长。"""
    builder = _builder(tc)
    _lock_guard(tc, ["$.sections", "$.speaking_rate_cps"])
    try:
        result = builder.rebalance_timing(speaking_rate_cps=inp.speaking_rate_cps)
    except ValueError as exc:
        return _fail(str(exc), "timing_rebalance_failed")
    revision = builder.bump_revision()
    return _ok({
        "summary": "重算语速与停顿",
        "affected_json_paths": ["$.sections", "$.speaking_rate_cps"],
        "revision": revision,
        "changed_section_ids": result["changed_section_ids"],
        "speaking_rate_cps": result["speaking_rate_cps"],
    })


class AddVerbatimSectionInput(BaseModel):
    section_id: str = Field(min_length=1, pattern=r"^VB-[A-Z0-9-]+$")
    scene_id: str = Field(min_length=1, description="关联的视频脚本场景 ID（必须未被占用）")
    required_text: str = Field(min_length=1)
    delivery_tone: str = ""
    pedagogical_action: str = "scenario_connect"
    confirmation_token: str | None = None


async def _vb_add_section(tc: ToolContext, inp: AddVerbatimSectionInput) -> ToolResult:
    """新增一个逐字稿章节（scene_id 必须唯一）。"""
    builder = _builder(tc)
    _lock_guard(tc, [_section_path(inp.section_id)])
    try:
        node = builder.add_section(
            inp.section_id, inp.scene_id, inp.required_text,
            delivery_tone=inp.delivery_tone, pedagogical_action=inp.pedagogical_action,
        )
    except ValueError as exc:
        return _fail(str(exc), "section_add_failed")
    revision = builder.bump_revision()
    return _ok({
        "summary": f"新增章节 {inp.section_id}（场景 {inp.scene_id}）",
        "affected_json_paths": [_section_path(inp.section_id)],
        "revision": revision,
        "section": dict(node),
    })


class DeleteVerbatimSectionInput(BaseModel):
    section_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, description="删除原因")
    confirmation_token: str | None = None


async def _vb_delete_section(tc: ToolContext, inp: DeleteVerbatimSectionInput) -> ToolResult:
    """删除一个逐字稿章节（高风险，需确认令牌）。"""
    builder = _builder(tc)
    if builder.find_section(inp.section_id) is None:
        return _fail(f"章节不存在：{inp.section_id}", "section_not_found")
    _require_confirmation(tc, inp.confirmation_token, operation=f"删除章节 {inp.section_id}")
    _lock_guard(tc, [_section_path(inp.section_id)])
    deleted = builder.delete_section(inp.section_id)
    revision = builder.bump_revision()
    return _ok({
        "summary": f"删除章节 {inp.section_id}（原因：{inp.reason[:60]}）",
        "affected_json_paths": [_section_path(inp.section_id)],
        "revision": revision,
        "deleted_section": dict(deleted),
    })


class MoveVerbatimSectionInput(BaseModel):
    section_id: str = Field(min_length=1)
    target_scene_id: str = Field(min_length=1, description="目标场景 ID（与另一章节交换时间槽与场景归属）")
    confirmation_token: str | None = None


async def _vb_move_section(tc: ToolContext, inp: MoveVerbatimSectionInput) -> ToolResult:
    """把章节移到目标场景的时间槽（与另一章节交换 scene 归属与时间轴）。"""
    builder = _builder(tc)
    if builder.find_section(inp.section_id) is None:
        return _fail(f"章节不存在：{inp.section_id}", "section_not_found")
    _lock_guard(tc, [_section_path(inp.section_id)])
    try:
        moved = builder.move_section(inp.section_id, inp.target_scene_id)
    except ValueError as exc:
        return _fail(str(exc), "section_move_failed")
    revision = builder.bump_revision()
    return _ok({
        "summary": f"移动章节 {inp.section_id} 到场景 {inp.target_scene_id}",
        "affected_json_paths": ["$.sections"],
        "revision": revision,
        "section": dict(moved),
    })


def _register_edit_tools() -> None:
    register_tool(Tool("vb_initialize_draft", "首次生成或 V1 升级时创建 V2 逐字稿基线",
                       InitializeVerbatimDraftInput, _vb_initialize_draft))
    register_tool(Tool("vb_update_section", "修改章节口播/补充/语气/重音/互动/停顿",
                       UpdateVerbatimSectionInput, _vb_update_section))
    register_tool(Tool("vb_batch_style", "批量统一全部章节的语气/重音/停顿（不改事实）",
                       BatchVerbatimStyleInput, _vb_batch_style))
    register_tool(Tool("vb_rebalance_timing", "按语速与场景时长重算停顿（时间轴适配）",
                       RebalanceVerbatimTimingInput, _vb_rebalance_timing))
    register_tool(Tool("vb_add_section", "新增逐字稿章节（scene_id 必须唯一）",
                       AddVerbatimSectionInput, _vb_add_section))
    register_tool(Tool("vb_delete_section", "删除逐字稿章节（高风险，需人工确认令牌）",
                       DeleteVerbatimSectionInput, _vb_delete_section))
    register_tool(Tool("vb_move_section", "移动章节到目标场景的时间槽（交换场景归属）",
                       MoveVerbatimSectionInput, _vb_move_section))
