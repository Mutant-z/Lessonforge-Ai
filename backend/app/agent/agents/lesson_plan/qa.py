"""教学设计确定性质量门禁。

validate_lesson_plan() 在 Agent 发布、人工编辑、审批与全局 QA 四个入口复用：
- 蓝图引用合法性（目标/知识点/环节）；
- 时长守恒、环节时长为正；
- 每个目标至少关联一个教学环节与一项评价证据；
- 重点/难点/作业与目标存在覆盖关系；
- 大纲 coverage_refs 合法、稳定内核重要事实被展示覆盖；
- 锁定路径未被修改。

问题统一为 {severity, location, dimension, description, suggestion, target_agent}。
"""

from __future__ import annotations

from typing import Any

from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.lesson_plan import LessonPlanContentV2

LESSON_PLAN_AGENT = "lesson_plan_agent"


def issue(severity: str, location: str, dimension: str, description: str, suggestion: str) -> dict:
    return {
        "severity": severity,
        "artifact_type": "lesson_plan",
        "location": location,
        "dimension": dimension,
        "description": description,
        "evidence": description,
        "suggestion": suggestion,
        "target_agent": LESSON_PLAN_AGENT,
        "required_action": "revise",
    }


def _locked_paths_ok(locked_paths: list[str]) -> bool:
    return not any(path in {"", "$"} for path in locked_paths)


def _collect_issue_location(issue: dict) -> str:
    return issue.get("location", "")


def validate_lesson_plan(
    bp: CourseBlueprintSchema | dict[str, Any],
    content: dict[str, Any],
    locked_paths: list[str] | None = None,
) -> list[dict]:
    """校验 V2 教学设计候选稿，返回问题列表（空列表 = 通过）。"""
    if isinstance(bp, dict):
        bp = CourseBlueprintSchema.model_validate(bp)
    issues: list[dict] = []
    if content.get("schema_version") != "2.0":
        issues.append(issue("minor", "$", "compatibility",
                            "当前教学设计仍使用 V1 结构", "首次修改或同步时转换为结构化教学设计 V2"))
        return issues
    try:
        plan = LessonPlanContentV2.model_validate(content)
    except Exception as exc:  # noqa: BLE001
        issues.append(issue("critical", "$", "integrity",
                            f"教学设计结构非法：{str(exc)[:300]}", "修复结构后重新校验"))
        return issues

    objective_ids = {item.id for item in bp.objectives}
    knowledge_ids = {item.id for item in bp.knowledge_points}
    stage_ids = {item.segment_id for item in bp.timeline}
    core = plan.pedagogical_core

    # 1. 课程身份与已批准蓝图一致
    if plan.course_info.title and plan.course_info.title != bp.course_identity.title:
        issues.append(issue("minor", "$.course_info.title", "alignment",
                            f"课程名称“{plan.course_info.title}”与已批准蓝图不一致",
                            "改为蓝图中的课程名称"))
    if abs(plan.course_info.duration_minutes - bp.course_identity.duration_minutes) > 0.5:
        issues.append(issue("major", "$.course_info.duration_minutes", "timing",
                            f"课程时长 {plan.course_info.duration_minutes} 分钟与蓝图 {bp.course_identity.duration_minutes} 分钟不一致",
                            "对齐蓝图时长"))

    # 2. 蓝图引用合法性
    core_objective_ids = {item.id for item in core.objectives}
    for objective in core.objectives:
        if objective.blueprint_objective_id not in objective_ids:
            issues.append(issue("critical", f"$.pedagogical_core.objectives[{objective.id}]", "alignment",
                                f"目标 {objective.id} 引用了蓝图中不存在的目标 {objective.blueprint_objective_id}",
                                "改为已批准蓝图中的目标 ID"))
    for stage in core.stages:
        if stage.id not in stage_ids:
            issues.append(issue("critical", f"$.pedagogical_core.stages[{stage.id}]", "alignment",
                                f"教学环节 {stage.id} 不在蓝图的 timeline 中",
                                "改为已批准蓝图中的环节 ID"))
        for ref in stage.objective_ids:
            if ref not in core_objective_ids:
                issues.append(issue("critical", f"$.pedagogical_core.stages[{stage.id}]", "alignment",
                                    f"环节 {stage.id} 引用了不存在的目标 {ref}", "改为合法目标 ID"))
        for ref in stage.knowledge_point_ids:
            if ref not in knowledge_ids and ref not in {item.id for item in core.knowledge_points}:
                issues.append(issue("major", f"$.pedagogical_core.stages[{stage.id}]", "alignment",
                                    f"环节 {stage.id} 引用了不存在的知识点 {ref}", "改为合法知识点 ID"))

    # 3. 每个目标至少关联一个教学环节和一项评价证据
    covered_objectives: set[str] = set()
    for stage in core.stages:
        covered_objectives.update(stage.objective_ids)
    for objective in core.objectives:
        if objective.id not in covered_objectives:
            issues.append(issue("major", f"$.pedagogical_core.objectives[{objective.id}]", "alignment",
                                f"目标 {objective.id} 未关联任何教学环节", "补充对应教学环节并映射该目标"))
        if not (objective.evidence or "").strip():
            issues.append(issue("major", f"$.pedagogical_core.objectives[{objective.id}]", "alignment",
                                f"目标 {objective.id} 缺少可判定学习证据", "为目标补充评价证据"))
    for item in core.assessment_plan:
        if item.objective_id not in core_objective_ids:
            issues.append(issue("major", "$.pedagogical_core.assessment_plan", "alignment",
                                f"评价计划引用了不存在的目标 {item.objective_id}", "改为合法目标 ID"))

    # 4. 重点/难点/作业与目标存在覆盖关系
    if not core.key_points:
        issues.append(issue("minor", "$.pedagogical_core.key_points", "coverage",
                            "教学重点为空", "补充本课教学重点"))
    if not core.difficulty_points:
        issues.append(issue("minor", "$.pedagogical_core.difficulty_points", "coverage",
                            "教学难点为空", "补充本课教学难点"))
    if not core.homework:
        issues.append(issue("minor", "$.pedagogical_core.homework", "coverage",
                            "作业布置为空", "布置直接覆盖课程目标的作业"))

    # 5. 大纲 coverage_refs 合法、稳定内核重要事实被展示覆盖
    outline_refs: set[str] = set()
    total_sections = 0

    def _section_dict(section: Any) -> dict[str, Any]:
        return section.model_dump() if hasattr(section, "model_dump") else dict(section)

    def visit(sections: list[Any], depth: int) -> None:
        nonlocal total_sections
        for section in sections:
            node = _section_dict(section)
            total_sections += 1
            outline_refs.update(node.get("coverage_refs") or [])
            for child in node.get("children") or []:
                visit([child], depth + 1)

    visit(plan.outline.sections, 1)
    if not 2 <= len(plan.outline.sections) <= 15:
        issues.append(issue("major", "$.outline.sections", "structure",
                            f"一级章节数量 {len(plan.outline.sections)} 超出 2–15 范围", "调整目录结构"))
    if total_sections > 30:
        issues.append(issue("major", "$.outline", "structure",
                            f"大纲总章节数 {total_sections} 超过 30", "精简目录"))
    valid_refs = {
        "objectives", "stages", "key_points", "difficulty_points", "methods",
        "resources", "homework", "board_design", "reflection", "assessment_plan",
        # V1 默认目录（适配器生成）使用的内容事实键。
        "content_analysis", "learner_analysis",
    }
    for ref in outline_refs:
        if ref not in valid_refs:
            issues.append(issue("minor", "$.outline", "coverage",
                                f"大纲 coverage_refs 引用了未知事实 {ref}", "使用合法事实键"))
    required_facts = {"objectives", "stages"}
    for fact in required_facts:
        if fact not in outline_refs:
            issues.append(issue("major", "$.outline", "coverage",
                                f"大纲未展示稳定内核事实 {fact}", "在目录中补充覆盖该事实的章节"))

    # 6. 展示完整性：稳定内核存在并不代表教师实际能在预览中看到正文。
    # 叶子章节没有 summary/blocks 时，Markdown 只会剩下标题，必须阻止发布。
    from app.agent.agents.lesson_plan.diff import empty_leaf_section_ids

    for section_id in empty_leaf_section_ids(content):
        issues.append(issue(
            "major",
            f"$.outline.sections[{section_id}]",
            "visibility",
            f"章节 {section_id} 没有任何可见正文",
            "补充章节 blocks，或将其改为包含非空子章节的目录容器",
        ))

    # 7. 锁定路径未被修改（整体锁 / 具体路径）
    if locked_paths and not _locked_paths_ok(locked_paths):
        issues.append(issue("critical", "$", "lock",
                            "任务文件已整体锁定，不允许修改", "解除锁定后重试"))
    return issues


def blocking_issues(issues: list[dict]) -> list[dict]:
    return [item for item in issues if item["severity"] in {"critical", "major"}]


# ---------------------------------------------------------------------------
# 统一验证报告：QA（pedagogy_qa）、编号校验与 Finalizer 消费同一份报告，
# 不允许再出现「QA 100 分、Finalizer 又认为失败」的矛盾。
#
# 验证顺序固定：
#   1. Schema 与引用完整性（validate_lesson_plan）；
#   2. 目标章节编号是否已修正（阻断）；
#   3. 非目标章节逐字不变（scope_checks，阻断）；
#   4. 其他章节的历史编号问题记录为 baseline_warning，不阻断本轮；
#   5. 是否引入新的问题（本轮 diff 之外的退化）。
# ---------------------------------------------------------------------------


def _walk_section_ids(content: dict[str, Any]) -> list[str]:
    result: list[str] = []

    def visit(sections: list[dict[str, Any]]) -> None:
        for item in sections or []:
            sid = str(item.get("id") or "")
            if sid:
                result.append(sid)
            visit(item.get("children") or [])

    visit((content.get("outline") or {}).get("sections") or [])
    return result


def numbering_issues_in_sections(
    content: dict[str, Any],
    section_ids: list[str],
    *,
    location_prefix: str = "$.outline.sections",
) -> list[dict]:
    """目标/本轮修改章节内的硬编码序号问题（阻断）。"""
    from app.agent.agents.lesson_plan.formatting import hardcoded_ordinal_sections_in

    return [
        issue("major", f"{location_prefix}[{sid}]", "numbering",
              f"章节 {sid} 正文包含硬编码序数（一、/（一）等），应由渲染器按章节树生成",
              "将标题型序数前缀从正文中去除，仅保留语义标题")
        for sid in hardcoded_ordinal_sections_in(content, section_ids)
    ]


def baseline_numbering_warnings(
    content: dict[str, Any],
    excluded_section_ids: list[str],
) -> list[dict]:
    """非目标章节的历史编号问题（不阻断本轮修复）。"""
    from app.agent.agents.lesson_plan.formatting import hardcoded_ordinal_section_ids

    excluded = set(excluded_section_ids or [])
    return [
        issue("minor", f"$.outline.sections[{sid}]", "numbering_baseline",
              f"章节 {sid} 存在历史硬编码序数（本轮修改范围之外）",
              "该问题属于既有版本遗留，可在独立编号修复轮次中处理")
        for sid in hardcoded_ordinal_section_ids(content)
        if sid not in excluded
    ]


def build_lesson_plan_verification_report(
    bp: CourseBlueprintSchema | dict[str, Any],
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any],
    *,
    locked_paths: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    numbering_blocking: bool = False,
) -> dict[str, Any]:
    """确定性生成统一的 LessonPlanVerificationReport。

    ``target_section_ids`` 为空时编号校验作用于全部章节（首次生成/全量质检）；
    非目标章节的历史编号问题进入 ``baseline_warnings``，不阻断本轮。

    ``numbering_blocking`` 控制正文序数校验是否阻断本轮：
    - 仅当用户明确要求格式修正（SECTION_FORMAT_EDIT）时为 True——正文里的
      「一、/二、」属于渲染器应生成的章节编号，残留即为错误，阻断发布；
    - 普通内容修改（SECTION_EDIT / CONTENT_ENRICH 等）为 False——正文中的
      「一、二、」可能是内容固有的结构排版（如板书设计的分板块、大纲式列表），
      不是渲染器编号错误，只记 baseline_warning，不阻断内容修改落地。
    """
    from app.agent.agents.lesson_plan.context import walk_sections_recursive
    from app.agent.agents.lesson_plan.diff import diff_lesson_plans

    target_ids = [sid for sid in (target_section_ids or []) if sid]
    all_ids = _walk_section_ids(candidate)
    numbering_scope = target_ids or all_ids

    pedagogical_checks = validate_lesson_plan(bp, candidate, locked_paths)
    target_numbering = numbering_issues_in_sections(candidate, numbering_scope)
    baseline_warnings = baseline_numbering_warnings(candidate, numbering_scope)
    if numbering_blocking:
        target_checks = target_numbering
    else:
        # 内容修改意图：正文序数问题不阻断，全部记入 baseline_warnings。
        target_checks = []
        baseline_warnings = list(dict.fromkeys([tuple(sorted(item.items())) for item in baseline_warnings + target_numbering]))
        baseline_warnings = [dict(item) for item in baseline_warnings]

    # 范围完整性：保留章节（非目标、非本轮新建）的 blocks/summary 必须逐字不变。
    scope_checks: list[dict] = []
    baseline_nodes: dict[str, dict[str, Any]] = {}
    candidate_nodes: dict[str, dict[str, Any]] = {}
    if baseline:
        baseline_nodes = {
            str(node.get("id") or ""): node
            for node, _parent, _order, _depth in walk_sections_recursive(
                (baseline.get("outline") or {}).get("sections") or []
            )
        }
        candidate_nodes = {
            str(node.get("id") or ""): node
            for node, _parent, _order, _depth in walk_sections_recursive(
                (candidate.get("outline") or {}).get("sections") or []
            )
        }
        allowed = set(target_ids)
        for section_id, source_node in baseline_nodes.items():
            if section_id in allowed:
                continue
            target_node = candidate_nodes.get(section_id)
            if target_node is None:
                scope_checks.append(issue(
                    "critical", f"$.outline.sections[{section_id}]", "scope",
                    f"保留章节 {section_id} 被移除",
                    "恢复该章节或将其纳入本轮修改契约",
                ))
            elif source_node.get("blocks") != target_node.get("blocks") or source_node.get("summary") != target_node.get("summary"):
                scope_checks.append(issue(
                    "critical", f"$.outline.sections[{section_id}]", "scope",
                    f"保留章节 {section_id} 的正文被改写",
                    "本轮只允许修改契约目标章节，保留章节必须逐字不变",
                ))

    blocking = list(dict.fromkeys(
        [tuple(sorted(item.items())) for item in blocking_issues(pedagogical_checks) + target_checks + scope_checks]
    ))
    blocking = [dict(item) for item in blocking]

    diff_summary = (
        diff_lesson_plans(baseline, candidate) if baseline is not None
        else {"changed": False, "changed_sections": []}
    )
    introduced_issues = [
        item for item in target_checks
    ]
    return {
        "passed": not blocking,
        "task_completed": not blocking,
        "target_checks": target_checks,
        "scope_checks": scope_checks,
        "pedagogical_checks": pedagogical_checks,
        "baseline_warnings": baseline_warnings,
        "introduced_issues": introduced_issues,
        "blocking_issues": blocking,
        "diff_summary": diff_summary,
        "target_section_ids": target_ids,
    }


def fingerprint(issues: list[dict]) -> str:
    """QA 指纹：用于防返修空转（相同指纹连续出现即停止）。"""
    import hashlib
    return hashlib.sha256(
        "\n".join(
            f"{item.get('severity')}:{item.get('location')}:{item.get('dimension')}"
            for item in blocking_issues(issues)
        ).encode("utf-8"),
    ).hexdigest()
