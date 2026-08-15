"""教学设计工具集：检查与输出类工具。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.agents.lesson_plan.tools._common import blueprint_schema, builder_for
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool


class LessonCalculateTimelineInput(BaseModel):
    pass


async def _lesson_calculate_timeline(tc: ToolContext, _: LessonCalculateTimelineInput) -> ToolResult:
    builder = builder_for(tc)
    core = builder.core
    stages = core.get("stages", [])
    total = sum(float(item.get("duration_minutes", 0)) for item in stages)
    target = float(builder.to_content().get("course_info", {}).get("duration_minutes", 0))
    drift = total - target
    return ToolResult(output={
        "total_minutes": round(total, 2),
        "target_minutes": target,
        "drift_minutes": round(drift, 2),
        "consistent": abs(drift) <= 0.5,
        "stages": [{"id": item.get("id"), "title": item.get("title"), "duration_minutes": item.get("duration_minutes")} for item in stages],
    })


class LessonValidateAlignmentInput(BaseModel):
    pass


async def _lesson_validate_alignment(tc: ToolContext, _: LessonValidateAlignmentInput) -> ToolResult:
    """运行完整确定性质量门禁，返回问题列表。"""
    from app.agent.agents.lesson_plan.qa import validate_lesson_plan

    builder = builder_for(tc)
    try:
        blueprint = blueprint_schema(tc)
    except LookupError:
        return ToolResult(ok=False, error="上下文缺少课程蓝图", error_code="blueprint_missing", retryable=False)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=f"课程蓝图结构非法：{str(exc)[:300]}",
            error_code="blueprint_invalid",
            retryable=False,
        )
    locks = getattr(tc.runtime, "locks", None) if tc.runtime else None
    locked_paths = [
        getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
        for lock in (locks or [])
    ]
    issues = validate_lesson_plan(blueprint, builder.to_content(), locked_paths)
    return ToolResult(output={
        "issues": issues,
        "blocking_count": len([item for item in issues if item["severity"] in {"critical", "major"}]),
        "passed": not any(item["severity"] in {"critical", "major"} for item in issues),
    })


class LessonValidateOutlineCoverageInput(BaseModel):
    pass


async def _lesson_validate_outline_coverage(tc: ToolContext, _: LessonValidateOutlineCoverageInput) -> ToolResult:
    builder = builder_for(tc)
    outline_refs: set[str] = set()
    total = 0

    def visit(sections: list[dict[str, Any]]) -> None:
        nonlocal total
        for section in sections:
            total += 1
            outline_refs.update(section.get("coverage_refs") or [])
            visit(section.get("children") or [])

    visit(builder.outline)
    core = builder.core
    covered = {
        "objectives": bool(core.get("objectives")),
        "stages": bool(core.get("stages")),
        "key_points": bool(core.get("key_points")),
        "homework": bool(core.get("homework")),
    }
    return ToolResult(output={
        "section_count": total,
        "top_level_count": len(builder.outline),
        "coverage_refs": sorted(outline_refs),
        "core_present": covered,
        "objectives_covered": "objectives" in outline_refs,
        "stages_covered": "stages" in outline_refs,
    })


class LessonValidateReferencesInput(BaseModel):
    pass


async def _lesson_validate_references(tc: ToolContext, _: LessonValidateReferencesInput) -> ToolResult:
    """蓝图引用合法性检查（目标/知识点/环节 ID）。"""
    builder = builder_for(tc)
    try:
        data = blueprint_schema(tc).model_dump()
    except LookupError:
        return ToolResult(ok=False, error="上下文缺少课程蓝图", error_code="blueprint_missing", retryable=False)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"课程蓝图结构非法：{str(exc)[:300]}", error_code="blueprint_invalid", retryable=False)
    objective_ids = {item.get("id") for item in data.get("objectives", [])}
    stage_ids = {item.get("segment_id") for item in data.get("timeline", [])}
    core = builder.core
    problems = []
    for objective in core.get("objectives", []):
        if objective.get("blueprint_objective_id") not in objective_ids:
            problems.append(f"目标 {objective.get('id')} 引用蓝图外目标 {objective.get('blueprint_objective_id')}")
    for stage in core.get("stages", []):
        if stage.get("id") not in stage_ids:
            problems.append(f"环节 {stage.get('id')} 不在蓝图 timeline")
    return ToolResult(output={"valid": not problems, "problems": problems[:20]})


class LessonRenderPreviewInput(BaseModel):
    format: str = "markdown"
    include_content: bool = False


async def _lesson_render_preview(tc: ToolContext, inp: LessonRenderPreviewInput) -> ToolResult:
    from app.agent.agents.lesson_plan.diff import visible_content_chars
    from app.schemas.lesson_plan import lesson_plan_to_markdown_v2

    builder = builder_for(tc)
    content = builder.to_content()
    if visible_content_chars(content) <= 0:
        return ToolResult(
            ok=False,
            error="候选稿只有章节标题，没有任何可见正文",
            error_code="rendered_content_missing",
            retryable=True,
        )
    markdown = lesson_plan_to_markdown_v2(content)
    output = {"format": inp.format, "markdown": markdown[:6000]}
    if inp.include_content and getattr(tc.runtime, "current_agent_key", "") == "finalizer":
        output["content"] = content
    return ToolResult(output=output)


class LessonDiffVersionsInput(BaseModel):
    pass


async def _lesson_diff_versions(tc: ToolContext, _: LessonDiffVersionsInput) -> ToolResult:
    """对比候选稿与正式源版本（完整 ID/路径感知 diff）。"""
    from app.agent.agents.lesson_plan.diff import diff_lesson_plans

    builder = builder_for(tc)
    source = getattr(tc.runtime, "source_artifact", None)
    source_content = getattr(source, "content_json", None) if source else None
    candidate = builder.to_content()
    if not source_content:
        return ToolResult(output={"is_new": True, "note": "首次生成，无源版本可对比"})
    return ToolResult(output=diff_lesson_plans(source_content, candidate))


class LessonValidateScopeInput(BaseModel):
    pass


async def _lesson_validate_scope(tc: ToolContext, _: LessonValidateScopeInput) -> ToolResult:
    """作用域完整性检查：契约目标/新建章节之外的保留章节正文必须逐字不变。"""
    builder = builder_for(tc)
    runtime = getattr(tc, "runtime", None)
    source = getattr(runtime, "source_artifact", None) if runtime else None
    decision = getattr(runtime, "resolved_intent", None) if runtime else None
    if source is None or decision is None:
        return ToolResult(output={"ok": True, "note": "无源版本或契约，跳过作用域检查"})
    source_content = getattr(source, "content_json", None) or {}
    candidate = builder.to_content()
    from app.agent.agents.lesson_plan.context import walk_sections_recursive

    baseline_nodes = {
        str(node.get("id") or ""): node
        for node, _parent, _order, _depth in walk_sections_recursive(
            (source_content.get("outline") or {}).get("sections") or []
        )
    }
    candidate_nodes = {
        str(node.get("id") or ""): node
        for node, _parent, _order, _depth in walk_sections_recursive(
            (candidate.get("outline") or {}).get("sections") or []
        )
    }
    allowed = set(decision.target_section_ids or []) | set(decision.resolved_scope or [])
    failures: list[str] = []
    for section_id, source_node in baseline_nodes.items():
        if section_id in allowed:
            continue
        target_node = candidate_nodes.get(section_id)
        if target_node is None:
            failures.append(f"preserved_section_removed:{section_id}")
            continue
        if source_node.get("blocks") != target_node.get("blocks") or source_node.get("summary") != target_node.get("summary"):
            failures.append(f"preserved_section_content_changed:{section_id}")
    return ToolResult(output={
        "ok": not failures,
        "failures": failures,
        "preserved_section_ids": sorted(set(baseline_nodes) - allowed),
    })


class LessonValidateNumberingInput(BaseModel):
    pass


async def _lesson_validate_numbering(tc: ToolContext, _: LessonValidateNumberingInput) -> ToolResult:
    """编号校验：只校验本轮契约目标章节 + 本轮 diff 变化的章节。

    其他章节已有的历史编号问题记录为 baseline_warnings（不阻断本轮），
    避免“格式修复后仍报旧文档其他章节的历史编号错误”。
    """
    from app.agent.agents.lesson_plan.diff import diff_lesson_plans
    from app.agent.agents.lesson_plan.qa import baseline_numbering_warnings, numbering_issues_in_sections

    builder = builder_for(tc)
    content = builder.to_content()
    runtime = getattr(tc, "runtime", None)
    decision = getattr(runtime, "resolved_intent", None) if runtime else None
    target_ids = list(getattr(decision, "target_section_ids", None) or [])
    if not target_ids:
        target_ids = list(getattr(runtime, "selected_section_ids", None) or [])
    changed_ids: list[str] = []
    source = getattr(runtime, "source_artifact", None) if runtime else None
    if source is not None:
        changed_ids = list((diff_lesson_plans(source.content_json or {}, content) or {}).get("changed_sections") or [])
    scope = sorted(set(target_ids) | set(changed_ids))
    if not scope:
        # 无目标、无变化的纯查询：扫描全部章节（不阻断，仅提示）。
        from app.agent.agents.lesson_plan.formatting import hardcoded_ordinal_section_ids

        problems = [
            f"章节 {sid} 正文包含硬编码序数（一、/（一）等），应由渲染器按章节树生成"
            for sid in hardcoded_ordinal_section_ids(content)
        ]
        return ToolResult(output={
            "ok": not problems,
            "problems": problems,
            "baseline_warnings": [],
            "note": "章节显示编号由渲染器按大纲层级统一生成，正文只保存语义标题。",
        })
    blocking = numbering_issues_in_sections(content, scope)
    warnings = baseline_numbering_warnings(content, scope)
    return ToolResult(output={
        "ok": not blocking,
        "problems": [item["description"] for item in blocking],
        "baseline_warnings": [item["description"] for item in warnings],
        "target_section_ids": scope,
        "note": "本轮只校验契约目标与发生变化的章节；其他章节历史编号问题记为 baseline_warning。",
    })


def _register_check_tools() -> None:
    register_tool(Tool("lesson_calculate_timeline", "计算教学环节总时长与课程时长是否守恒",
                       LessonCalculateTimelineInput, _lesson_calculate_timeline, idempotent=True))
    register_tool(Tool("lesson_validate_alignment", "运行教学设计完整质量门禁（结构/引用/覆盖/锁定）",
                       LessonValidateAlignmentInput, _lesson_validate_alignment, idempotent=True))
    register_tool(Tool("lesson_validate_outline_coverage", "检查大纲是否覆盖稳定内核重要事实",
                       LessonValidateOutlineCoverageInput, _lesson_validate_outline_coverage, idempotent=True))
    register_tool(Tool("lesson_validate_references", "检查蓝图引用合法性（目标/知识点/环节 ID）",
                       LessonValidateReferencesInput, _lesson_validate_references, idempotent=True))
    register_tool(Tool("lesson_validate_scope", "检查契约目标之外的保留章节正文是否逐字不变",
                       LessonValidateScopeInput, _lesson_validate_scope, idempotent=True))
    register_tool(Tool("lesson_validate_numbering", "检查章节正文是否包含硬编码序号（应由渲染器生成）",
                       LessonValidateNumberingInput, _lesson_validate_numbering, idempotent=True))
    register_tool(Tool("lesson_render_preview", "渲染候选稿 Markdown/内容预览", LessonRenderPreviewInput, _lesson_render_preview, idempotent=True))
    register_tool(Tool("lesson_diff_versions", "对比候选稿与正式源版本的章节差异", LessonDiffVersionsInput, _lesson_diff_versions, idempotent=True))
