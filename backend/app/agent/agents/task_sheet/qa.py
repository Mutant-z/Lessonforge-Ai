"""学习任务单确定性质量门禁（方案 §2.3 QA 与返修）。

validate_task_sheet_v3() 在 Agent 发布、人工编辑与全局 QA 入口复用；
check_tools 的分维度工具复用同一组维度函数：
- Schema 与唯一 ID（深度、循环、order 冲突、Block ID）；
- 蓝图与教学设计引用合法性（目标 / 知识点 / 环节）；
- 目标覆盖与学习证据（每个蓝图目标被任务覆盖、至少一个可填记录表、至少一个评价）；
- 任务可执行性（动作/对象/步骤/产出/标准齐全）；
- 时间一致性（课中任务用时 ≤ 课程与对应环节时长）；
- 学生版职责边界（不出现参考答案、教师提示、教师版解析）；
- 学生语言适切性（年级适切、无答案泄漏、完成标准可判断）；
- 锁定路径未被修改。

统一问题结构（方案 §2.3）：id/severity/dimension/path/description/suggestion/target_role。
为兼容旧调用方与 quality_service 形状，同时保留 location/evidence/target_agent 字段。
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.task_sheet import TaskSheetContentV3

TASK_SHEET_AGENT = "task_sheet_agent"

# 学生版职责边界：不得出现的教师侧内容标记
FORBIDDEN_TEACHER_MARKERS = [
    "参考答案", "教师提示", "教师讲解", "教学提示", "教师版",
    "参考答案：", "解析：", "答案：", "要点提示",
]
# 需要完整字段的学习任务
TASK_REQUIRED_FIELDS = (
    "action", "object", "steps", "student_output", "completion_criterion",
)


def issue(
    severity: str,
    path: str,
    dimension: str,
    description: str,
    suggestion: str,
    target_role: str = "task_designer",
) -> dict:
    """统一问题结构：id/severity/dimension/path/description/suggestion/target_role。

    同时输出 location/evidence/target_agent 兼容字段（旧测试与 quality_service）。
    """
    raw = "".join(
        char for char in f"{severity}:{path}:{dimension}:{description}".lower() if char.isalnum()
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"TS-{digest}",
        "severity": severity,
        "artifact_type": "task_sheet",
        "path": path,
        "location": path,
        "dimension": dimension,
        "description": description,
        "evidence": description,
        "suggestion": suggestion,
        "target_role": target_role,
        "target_agent": TASK_SHEET_AGENT,
        "required_action": "revise",
    }


def blocking_issues(issues: list[dict]) -> list[dict]:
    return [item for item in issues if item["severity"] in {"critical", "major"}]


def fingerprint(issues: list[dict]) -> str:
    """QA 指纹：用于防返修空转（相同指纹连续出现即停止）。"""
    return hashlib.sha256(
        "\n".join(
            f"{item.get('severity')}:{item.get('location') or item.get('path')}:{item.get('dimension')}"
            for item in blocking_issues(issues)
        ).encode("utf-8"),
    ).hexdigest()


def _collect_all_blocks(content: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """返回 [(section_id, block_id, block)] 扁平列表。"""
    result: list[tuple[str, str, dict[str, Any]]] = []
    for section in content.get("sections", []):
        for block in section.get("blocks", []):
            result.append((section.get("id", ""), block.get("id", ""), block))
    return result


def _looks_like_teacher_content(text: str) -> bool:
    return any(marker in text for marker in FORBIDDEN_TEACHER_MARKERS)


def _stage_durations(
    bp: CourseBlueprintSchema,
    lesson_plan_raw: dict[str, Any] | None,
) -> tuple[dict[str, float], set[str] | None]:
    """返回 (环节时长表, 教学设计环节集合)；教学设计非 V2 时不参与时长检查。"""
    durations = {item.segment_id: item.end_minute - item.start_minute for item in bp.timeline}
    lesson_stage_ids: set[str] | None = None
    if lesson_plan_raw:
        try:
            from app.schemas.lesson_plan import LessonPlanContentV2

            plan = LessonPlanContentV2.model_validate(lesson_plan_raw)
            durations = {item.id: item.duration_minutes for item in plan.pedagogical_core.stages}
            lesson_stage_ids = set(durations)
        except Exception:  # noqa: BLE001  V1 或结构非法的教学设计不参与时长检查
            pass
    return durations, lesson_stage_ids


# ---------------------------------------------------------------------------
# 分维度校验（check_tools 复用）
# ---------------------------------------------------------------------------


def _reference_issues_v3(bp: CourseBlueprintSchema, content: dict[str, Any]) -> list[dict]:
    """引用合法性：目录目标、任务/问题/评价/目标列表引用。

    学习目标目录允许新增/拆分蓝图外目标（教师细化指令），因此 catalog 本身
    不再要求全部来自蓝图；但所有 Block 的目标引用必须落在目录内（目录是任务单
    自己的权威目标集合）。知识点与教学环节仍以蓝图为唯一权威。
    """
    issues: list[dict] = []
    knowledge_ids = {item.id for item in bp.knowledge_points}
    stage_ids = {item.segment_id for item in bp.timeline}
    catalog_ids = {item.get("id") for item in content.get("objective_catalog", [])}
    for section in content.get("sections", []):
        for block_index, block in enumerate(section.get("blocks", [])):
            block_loc = f"$.sections[{section.get('id', '')}].blocks[{block_index}]"
            if block.get("kind") == "learning_task":
                for ref in block.get("objective_ids", []):
                    if ref not in catalog_ids:
                        issues.append(issue("critical", f"{block_loc}.objective_ids", "alignment",
                                            f"学习任务引用了目标目录外的目标 {ref}", "改为目标目录中的目标 ID"))
                for ref in block.get("knowledge_point_ids", []):
                    if ref not in knowledge_ids:
                        issues.append(issue("critical", f"{block_loc}.knowledge_point_ids", "alignment",
                                            f"学习任务引用了不存在的知识点 {ref}", "改为蓝图中的知识点 ID"))
                stage_id = block.get("stage_id")
                if stage_id and stage_id not in stage_ids:
                    issues.append(issue("major", f"{block_loc}.stage_id", "alignment",
                                        f"引用了蓝图中不存在的教学环节 {stage_id}", "改为已批准蓝图中的环节 ID"))
            elif block.get("kind") == "objective_list":
                for ref in block.get("objective_ids", []):
                    if ref not in catalog_ids:
                        issues.append(issue("major", f"{block_loc}.objective_ids", "alignment",
                                            f"目标列表引用了目录外目标 {ref}", "改为目标目录中的目标 ID"))
            elif block.get("kind") == "assessment":
                for item in block.get("items", []):
                    for ref in item.get("objective_ids", []):
                        if ref not in catalog_ids:
                            issues.append(issue("major", f"{block_loc}.items", "alignment",
                                                f"评价条目引用了目录外目标 {ref}", "改为目标目录中的目标 ID"))
            elif block.get("kind") == "question_set":
                for question in block.get("questions", []):
                    for ref in question.get("objective_ids", []):
                        if ref not in catalog_ids:
                            issues.append(issue("major", f"{block_loc}.questions", "alignment",
                                                f"问题引用了目录外目标 {ref}", "改为目标目录中的目标 ID"))
                    if question.get("stage_id") and question.get("stage_id") not in stage_ids:
                        issues.append(issue("major", f"{block_loc}.questions", "alignment",
                                            f"问题引用了蓝图中不存在的环节 {question.get('stage_id')}",
                                            "改为已批准蓝图中的环节 ID"))
    return issues


def _alignment_issues_v3(bp: CourseBlueprintSchema, content: dict[str, Any]) -> list[dict]:
    """目标覆盖与环节映射一致性。

    蓝图目标必须全部被学习任务覆盖；目录中新增的蓝图外目标同样必须被某个学习
    任务覆盖（防孤儿目标），否则报 coverage 问题。
    """
    issues: list[dict] = []
    stage_durations = {item.segment_id: item.end_minute - item.start_minute for item in bp.timeline}
    covered: set[str] = set()
    for section in content.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("kind") == "learning_task":
                covered.update(block.get("objective_ids") or [])
                stage_id = block.get("stage_id")
                if stage_id and stage_id not in stage_durations:
                    issues.append(issue("major", f"$.sections[{section.get('id', '')}]", "alignment",
                                        f"引用了蓝图中不存在的教学环节 {stage_id}", "改为已批准蓝图中的环节 ID"))
    for objective in bp.objectives:
        if objective.id not in covered:
            issues.append(issue("major", "$.sections", "alignment",
                                f"目标 {objective.id} 未被任何学习任务覆盖", "补充对应的学习任务和学习证据"))
    catalog_ids = {item.get("id") for item in content.get("objective_catalog", [])}
    blueprint_ids = {item.id for item in bp.objectives}
    for catalog_id in catalog_ids - blueprint_ids - covered:
        issues.append(issue("major", "$.objective_catalog", "coverage",
                            f"目录目标 {catalog_id} 未被任何学习任务覆盖", "在某个学习任务中引用该目标"))
    return issues


def _timing_issues_v3(
    bp: CourseBlueprintSchema,
    content: dict[str, Any],
    lesson_plan_raw: dict[str, Any] | None = None,
) -> list[dict]:
    """时间一致性：课中任务合计与课程/环节时长。"""
    issues: list[dict] = []
    stage_durations, _ = _stage_durations(bp, lesson_plan_raw)
    in_class_minutes = 0.0
    stage_minutes: dict[str, float] = {}
    for section in content.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("kind") == "learning_task" and block.get("stage_id"):
                in_class_minutes += float(block.get("estimated_minutes", 0))
                stage_id = block.get("stage_id")
                stage_minutes[stage_id] = stage_minutes.get(stage_id, 0.0) + float(block.get("estimated_minutes", 0))
    if in_class_minutes > bp.course_identity.duration_minutes + 0.5:
        issues.append(issue("major", "$.sections", "timing",
                            f"课中任务合计 {in_class_minutes:.1f} 分钟，超过课程时长 {bp.course_identity.duration_minutes} 分钟",
                            "压缩任务用时或移至课后"))
    for stage_id, minutes in stage_minutes.items():
        if stage_id in stage_durations and minutes > stage_durations[stage_id] + 0.5:
            issues.append(issue("major", "$.sections", "timing",
                                f"环节 {stage_id} 任务用时 {minutes:.1f} 分钟，超过教学设计分配 {stage_durations[stage_id]:.1f} 分钟",
                                "调整任务时长与教学环节一致"))
    return issues


def _usability_issues_v3(content: dict[str, Any]) -> list[dict]:
    """任务可执行性、记录空间、产出与完成标准一致性。"""
    issues: list[dict] = []
    has_record_table = False
    has_assessment = False
    has_learning_task = False
    for section in content.get("sections", []):
        for block_index, block in enumerate(section.get("blocks", [])):
            block_loc = f"$.sections[{section.get('id', '')}].blocks[{block_index}]"
            if block.get("kind") == "learning_task":
                has_learning_task = True
                for field in TASK_REQUIRED_FIELDS:
                    if not block.get(field):
                        issues.append(issue("critical", f"{block_loc}.{field}", "integrity",
                                            f"学习任务 {block.get('id')} 缺少 {field}", "补充该字段"))
                if not block.get("steps"):
                    issues.append(issue("major", f"{block_loc}.steps", "integrity",
                                        f"学习任务 {block.get('id')} 缺少操作步骤", "补充步骤列表"))
                if block.get("record_table"):
                    has_record_table = True
            elif block.get("kind") == "record_table":
                has_record_table = True
            elif block.get("kind") == "assessment":
                has_assessment = True
    if not has_learning_task:
        issues.append(issue("major", "$.sections", "coverage",
                            "任务单缺少可执行学习任务（learning_task）", "增加学习任务 Block"))
    if not has_record_table:
        issues.append(issue("major", "$.sections", "usability",
                            "任务单没有可填写的观察或记录表", "增加 record_table Block"))
    if not has_assessment:
        issues.append(issue("major", "$.sections", "usability",
                            "任务单缺少学生评价（assessment）", "增加自评或互评 Block"))
    return issues


def _student_language_issues_v3(content: dict[str, Any]) -> list[dict]:
    """学生版职责边界：不出现参考答案/教师提示；语言对学生可执行、可判断。"""
    issues: list[dict] = []
    for section in content.get("sections", []):
        for block_index, block in enumerate(section.get("blocks", [])):
            block_loc = f"$.sections[{section.get('id', '')}].blocks[{block_index}]"
            texts: list[str] = []
            if block.get("kind") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("kind") == "learning_task":
                texts.append(str(block.get("completion_criterion", "")))
                for scaffold in block.get("scaffolds", []):
                    texts.append(str(scaffold))
            elif block.get("kind") == "question_set":
                for question in block.get("questions", []):
                    texts.append(str(question.get("prompt", "")))
            elif block.get("kind") == "assessment":
                for item in block.get("items", []):
                    texts.append(str(item.get("statement", "")))
            elif block.get("kind") == "checklist":
                for item in block.get("items", []):
                    texts.append(str(item.get("text", "")))
            for text in texts:
                if _looks_like_teacher_content(text):
                    issues.append(issue("major", block_loc, "boundary",
                                        "任务单出现参考答案、教师提示或教师版解析", "移除教师侧内容，仅保留学生可执行内容"))
                    break
            if block.get("kind") == "learning_task":
                criterion = str(block.get("completion_criterion", ""))
                if len(criterion) < 4 or not any(m in criterion for m in ("是否", "完成", "正确", "清晰", "规范", "完整")):
                    issues.append(issue("minor", f"{block_loc}.completion_criterion", "usability",
                                        f"任务 {block.get('id')} 的完成标准不易判断", "补充可观察、可判断的完成标准"))
    return issues


# ---------------------------------------------------------------------------
# 完整门禁
# ---------------------------------------------------------------------------


def validate_task_sheet_v3(
    bp: CourseBlueprintSchema,
    content: dict[str, Any],
    lesson_plan_raw: dict[str, Any] | None = None,
    locked_paths: list[str] | None = None,
) -> list[dict]:
    """校验 V3 任务单候选稿，返回问题列表（空列表 = 通过）。

    组合全部维度函数 + 锁定路径检查；保持旧签名兼容。
    """
    issues: list[dict] = []
    if content.get("schema_version") != "3.0":
        issues.append(issue("minor", "$", "compatibility",
                            "当前任务单不是 V3 结构", "首次修改或同步时转换为 V3 结构化任务单"))
        return issues
    if locked_paths and any(path in {"", "$"} for path in locked_paths):
        issues.append(issue("critical", "$", "lock",
                            "任务文件已整体锁定，不允许修改", "解除锁定后重试"))
        return issues
    try:
        sheet = TaskSheetContentV3.model_validate(content)
    except Exception as exc:  # noqa: BLE001
        issues.append(issue("critical", "$", "integrity",
                            f"任务单结构非法：{str(exc)[:300]}", "修复结构后重新校验"))
        return issues
    content = sheet.model_dump()

    # 1. 蓝图引用合法性
    issues.extend(_reference_issues_v3(bp, content))
    # 2. 目标覆盖 + 环节映射
    issues.extend(_alignment_issues_v3(bp, content))
    # 3. 必备语义 + 任务可执行性
    issues.extend(_usability_issues_v3(content))
    # 4. 时间一致性
    issues.extend(_timing_issues_v3(bp, content, lesson_plan_raw))
    # 5. 学生版职责边界 + 学生语言
    issues.extend(_student_language_issues_v3(content))
    # 6. 目标目录完整性（蓝图目标必须全部进入目录）
    catalog_ids = {item.get("id") for item in content.get("objective_catalog", [])}
    for objective in bp.objectives:
        if objective.id not in catalog_ids:
            issues.append(issue("major", "$.objective_catalog", "alignment",
                                f"目标 {objective.id} 不在目标目录中", "将蓝图目标加入目标目录"))
    return issues


# 兼容别名（方案文档 §2.3 用名 validate_task_sheet）
validate_task_sheet = validate_task_sheet_v3


def llm_qa_system_prompt() -> str:
    """LLM 教学质询的独立 QA 系统角色（方案 §2.3：不新增 QA 模型设置）。

    真 LLM provider 下，task_sheet_qa 的教学裁决以本提示词的质询结果为准；
    确定性门禁（validate_task_sheet_v3）仅作 Mock / LLM 失败 / 结构非法的兜底。
    """
    return (
        "你是 LessonForge AI 学习任务单的独立教学质询角色。对任务单候选稿进行教学级检查，"
        "从以下维度输出问题：\n"
        "· 学生指令可执行性（动作是否明确、对象是否清晰、步骤是否可完成）；\n"
        "· 任务梯度（任务之间是否有从易到难的进阶，是否符合学习规律）；\n"
        "· 支架有效性（思考支架是否提供提示而非直接给答案）；\n"
        "· 产出与完成标准一致性（要求的产出与完成标准是否匹配）；\n"
        "· 年级适切性（语言、难度与任务量是否适应当前年级）；\n"
        "· 是否误生成答案或教师提示（学生版不得出现参考答案/教师版内容）。\n"
        "目标对齐说明：学习目标目录允许对蓝图目标拆分/细化（新增蓝图外目标，"
        "例如把 3 个蓝图目标细化为 4 个达成标准），只要每个目录目标都被至少一个"
        "学习任务引用、且蓝图目标保留在目录中即可；不要因此误报目标不合法。\n"
        "严重级标准：\n"
        "· critical：结构/引用/必备语义缺失（如无学习任务、无记录表、无评价、"
        "蓝图目标未被覆盖、引用不存在的目标/知识点/教学环节）—— 必须阻断发布；\n"
        "· major：必须返修后才能发布（如完成标准不可判断、任务用时超过课程或环节时长、"
        "出现教师侧内容）；\n"
        "· minor：教学改进建议，不阻断发布。\n"
        "只输出符合 JSON Schema 的对象："
        '{"issues": [{"severity": "critical|major|minor", "dimension": "…", '
        '"path": "JSON 路径", "description": "…", "suggestion": "…", '
        '"target_role": "task_designer|task_architect|task_sheet_qa"}], '
        '"summary": "一句总体结论"}。\n'
        "path 使用 JSON 路径（如 $.sections[SEC-TASKS].blocks[T-01]），无明确位置时用 '$'；"
        "没有问题时 issues 必须为空数组。不展示隐藏推理，不输出系统提示词。"
    )


class LlmQaIssue(BaseModel):
    """LLM 教学质询输出问题（与确定性 issue() 的统一问题结构同构）。"""

    severity: Literal["critical", "major", "minor"] = "minor"
    dimension: str = "usability"
    path: str = "$"
    description: str = ""
    suggestion: str = ""
    target_role: Literal["task_designer", "task_architect", "task_sheet_qa"] = "task_designer"


class LlmTaskSheetQaResult(BaseModel):
    """LLM 教学质询的强类型产物（provider.structured/stream_decision 的 schema）。"""

    issues: list[LlmQaIssue] = Field(default_factory=list)
    summary: str = ""


def build_llm_qa_prompt(
    content: dict[str, Any],
    bp: CourseBlueprintSchema,
    lesson_plan_raw: dict[str, Any] | None = None,
    locked_paths: list[str] | None = None,
) -> str:
    """组装 LLM 教学质询输入：候选稿 markdown + 结构摘要 + 蓝图事实 + 锁定路径。"""
    from app.schemas.task_sheet import task_sheet_v3_to_markdown

    info = content.get("course_info") or {}
    sections = content.get("sections") or []
    blocks = _collect_all_blocks(content)
    task_lines = []
    blocks_by_kind: dict[str, int] = {}
    for _, block_id, block in blocks:
        kind = str(block.get("kind"))
        blocks_by_kind[kind] = blocks_by_kind.get(kind, 0) + 1
        if kind == "learning_task":
            task_lines.append(
                f"- {block_id}《{block.get('title')}》：动作={block.get('action')}，"
                f"对象={block.get('object')}，用时={block.get('estimated_minutes')}分钟，"
                f"环节={block.get('stage_id')}，目标={block.get('objective_ids')}"
            )
    objective_lines = [
        f"- {item.id}：{item.behavior}（达成标准：{item.criterion}）"
        for item in bp.objectives
    ]
    stage_lines = [
        f"- {item.segment_id} {item.name}（{item.start_minute}-{item.end_minute}分钟）"
        for item in bp.timeline
    ]
    section_titles = [
        f"{section.get('order')}.{section.get('title')}({section.get('id')})"
        for section in sections
    ]
    markdown = task_sheet_v3_to_markdown(content)
    if len(markdown) > 16000:
        markdown = markdown[:16000] + "\n……（内容过长已截断）"
    lesson_plan_text = ""
    if lesson_plan_raw:
        try:
            from app.schemas.lesson_plan import LessonPlanContentV2

            plan = LessonPlanContentV2.model_validate(lesson_plan_raw)
            core = plan.pedagogical_core
            lesson_plan_text = (
                "教学设计核心：\n"
                f"- 目标：{'; '.join(core.objectives)}\n"
                f"- 环节：{'; '.join(f'{item.id} {item.title} {item.duration_minutes}分钟' for item in core.stages)}\n"
            )
        except Exception:  # noqa: BLE001  V1 或结构非法的教学设计不参与质询
            lesson_plan_text = ""
    return (
        "以下是待评审的学习任务单候选稿与课程事实，请按系统提示维度进行教学质询。\n\n"
        "## 课程信息\n"
        f"- 课程：{info.get('course_title')} · {info.get('subject')} / "
        f"{info.get('grade_level') or info.get('audience')} · {info.get('duration_minutes')}分钟\n\n"
        "## 蓝图目标\n" + ("\n".join(objective_lines) or "（无）") + "\n\n"
        "## 教学环节（蓝图）\n" + ("\n".join(stage_lines) or "（无）") + "\n\n"
        "## 任务单结构\n"
        f"- 章节数：{len(sections)}；章节：{'、'.join(section_titles) or '无'}\n"
        f"- Block 分布：{blocks_by_kind or '无'}\n"
        "- 学习任务清单：\n" + ("\n".join(task_lines) or "  （无）") + "\n\n"
        "## 锁定路径（禁止修改）\n" + ("；".join(locked_paths or []) or "无") + "\n\n"
        "## 候选稿全文（Markdown）\n" + markdown + "\n"
        + (("\n## " + lesson_plan_text) if lesson_plan_text else "")
    )


VALID_LLM_SEVERITIES = frozenset({"critical", "major", "minor"})
VALID_LLM_TARGET_ROLES = frozenset({"task_designer", "task_architect", "task_sheet_qa"})


def normalize_llm_issues(raw: Any) -> list[dict]:
    """归一化 LLM 质询输出：非法值回退默认、丢弃非 dict 项、去重，绝不因格式崩溃。

    输出与确定性 issue() 同构（id/severity/dimension/path/description/suggestion/
    target_role + location/evidence/target_agent 兼容字段），可直接进入统一门禁
    与返修路由（fingerprint 只依赖 severity/path/dimension，防空转保持稳定）。
    """
    if isinstance(raw, dict):
        raw = raw.get("issues")
    if not isinstance(raw, list):
        return []
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "minor")
        if severity not in VALID_LLM_SEVERITIES:
            severity = "minor"
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        path = str(item.get("path") or "$").strip() or "$"
        dimension = str(item.get("dimension") or "usability").strip() or "usability"
        target_role = str(item.get("target_role") or "task_designer")
        if target_role not in VALID_LLM_TARGET_ROLES:
            target_role = "task_designer"
        suggestion = str(item.get("suggestion") or "").strip()
        key = f"{severity}:{path}:{dimension}:{description}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "id": f"TS-LLM-{index:03d}",
            "severity": severity,
            "artifact_type": "task_sheet",
            "path": path,
            "location": path,
            "dimension": dimension,
            "description": description,
            "evidence": description,
            "suggestion": suggestion,
            "target_role": target_role,
            "target_agent": TASK_SHEET_AGENT,
            "required_action": "revise",
        })
    return normalized
