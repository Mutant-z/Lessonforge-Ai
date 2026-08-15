"""教学设计 V2 数据契约。

双层结构：``pedagogical_core`` 是下游 Agent / 规则引擎 / 质量门禁使用的稳定教学内核，
``outline`` 是由 AI 动态维护的展示章节树。同一稳定内核事实可以被合并到不同的展示章节，
因此章节标题、数量、顺序和组合不再固定。

兼容约定：
- ``lesson_plan_core()`` 是 V1/V2 的统一投影入口，下游代码一律走它，不直接判断旧字段。
- V1 历史版本保持原样；首次修改或同步时通过 ``upgrade_lesson_plan_v2()`` 生成 V2 候选，
  旧 Artifact 不改写。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.blueprint import CourseBlueprintSchema

MAX_OUTLINE_SECTIONS = 30
MAX_OUTLINE_DEPTH = 3
MAX_TOP_LEVEL_SECTIONS = 15


# ---------------------------------------------------------------------------
# 稳定教学内核
# ---------------------------------------------------------------------------


class LessonObjectiveV2(BaseModel):
    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    behavior: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    blueprint_objective_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class LessonKnowledgePointV2(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class LessonStageV2(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    duration_minutes: float = Field(gt=0)
    teacher_activity: str = Field(min_length=1)
    learner_activity: str = Field(min_length=1)
    design_intent: str = Field(min_length=1)
    assessment: str = Field(min_length=1)
    objective_ids: list[str] = Field(default_factory=list)
    knowledge_point_ids: list[str] = Field(default_factory=list)


class LessonAssessmentItemV2(BaseModel):
    objective_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    criterion: str = Field(min_length=1)


class LessonPedagogicalCore(BaseModel):
    objectives: list[LessonObjectiveV2] = Field(min_length=1)
    knowledge_points: list[LessonKnowledgePointV2] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    difficulty_points: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    stages: list[LessonStageV2] = Field(min_length=1)
    assessment_plan: list[LessonAssessmentItemV2] = Field(default_factory=list)
    homework: str = ""
    board_design: str = ""
    reflection: str = "课后由教师填写教学反思。"

    @model_validator(mode="after")
    def validate_core(self):
        objective_ids = [item.id for item in self.objectives]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("教学目标 ID 不能重复")
        stage_ids = [item.id for item in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("教学环节 ID 不能重复")
        knowledge_ids = [item.id for item in self.knowledge_points]
        if len(knowledge_ids) != len(set(knowledge_ids)):
            raise ValueError("知识点 ID 不能重复")
        return self


# ---------------------------------------------------------------------------
# 动态展示章节树
# ---------------------------------------------------------------------------


class LessonParagraphBlock(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1)


class LessonBulletsBlock(BaseModel):
    kind: Literal["bullets"] = "bullets"
    items: list[str] = Field(min_length=1)
    numbered: bool = False


class LessonStepItem(BaseModel):
    title: str = Field(min_length=1)
    detail: str = ""


class LessonStepsBlock(BaseModel):
    kind: Literal["steps"] = "steps"
    steps: list[LessonStepItem] = Field(min_length=1)


class LessonTableRow(BaseModel):
    cells: list[str] = Field(min_length=1)


class LessonTableBlock(BaseModel):
    kind: Literal["table"] = "table"
    title: str = ""
    columns: list[str] = Field(min_length=1)
    rows: list[LessonTableRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rows(self):
        for row in self.rows:
            if len(row.cells) != len(self.columns):
                raise ValueError("表格每行列数必须与表头一致")
        return self


class LessonProcessStep(BaseModel):
    stage_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    duration_minutes: float = Field(gt=0)
    teacher_activity: str = ""
    learner_activity: str = ""
    design_intent: str = ""
    assessment: str = ""


class LessonProcessTableBlock(BaseModel):
    """教学过程表：从稳定内核的教学环节渲染，或由 AI 按大纲语境重组。"""
    kind: Literal["process_table"] = "process_table"
    title: str = "教学过程"
    steps: list[LessonProcessStep] = Field(min_length=1)


class LessonNoteBlock(BaseModel):
    kind: Literal["note"] = "note"
    text: str = Field(min_length=1)


class LessonChecklistItem(BaseModel):
    text: str = Field(min_length=1)
    checked: bool = False


class LessonChecklistBlock(BaseModel):
    kind: Literal["checklist"] = "checklist"
    title: str = ""
    items: list[LessonChecklistItem] = Field(min_length=1)


LessonBlock = (
    LessonParagraphBlock
    | LessonBulletsBlock
    | LessonStepsBlock
    | LessonTableBlock
    | LessonProcessTableBlock
    | LessonNoteBlock
    | LessonChecklistBlock
)


class LessonOutlineSection(BaseModel):
    id: str = Field(min_length=1, pattern=r"^SEC-[A-Z0-9-]+$")
    title: str = Field(min_length=1)
    summary: str = ""
    coverage_refs: list[str] = Field(default_factory=list)
    blocks: list[LessonBlock] = Field(default_factory=list)
    children: list["LessonOutlineSection"] = Field(default_factory=list)


class LessonOutline(BaseModel):
    sections: list[LessonOutlineSection] = Field(min_length=2, max_length=MAX_TOP_LEVEL_SECTIONS)

    @model_validator(mode="after")
    def validate_outline(self):
        ids: set[str] = set()
        total = 0

        def visit(section: LessonOutlineSection, depth: int) -> None:
            nonlocal total
            if depth > MAX_OUTLINE_DEPTH:
                raise ValueError(f"大纲目录深度不能超过 {MAX_OUTLINE_DEPTH} 级")
            if section.id in ids:
                raise ValueError(f"大纲章节 ID 重复：{section.id}")
            ids.add(section.id)
            total += 1
            if total > MAX_OUTLINE_SECTIONS:
                raise ValueError(f"大纲总章节数不能超过 {MAX_OUTLINE_SECTIONS}")
            for child in section.children:
                visit(child, depth + 1)

        for section in self.sections:
            visit(section, 1)
        return self


class LessonCourseInfoV2(BaseModel):
    title: str = Field(min_length=1)
    subject: str = ""
    grade_level: str = ""
    audience: str = ""
    duration_minutes: float = Field(gt=0)
    scenario: str = ""
    language: str = "中文"


class LessonPlanContentV2(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    course_info: LessonCourseInfoV2
    pedagogical_core: LessonPedagogicalCore
    outline: LessonOutline

    @model_validator(mode="after")
    def validate_timing_and_coverage(self):
        total = sum(item.duration_minutes for item in self.pedagogical_core.stages)
        if abs(total - self.course_info.duration_minutes) > 0.5:
            raise ValueError(
                f"教学环节时长合计 {total} 分钟，与课程时长 {self.course_info.duration_minutes} 分钟不一致（±0.5）"
            )
        stage_ids = {item.id for item in self.pedagogical_core.stages}
        objective_ids = {item.id for item in self.pedagogical_core.objectives}
        covered_stages: set[str] = set()
        covered_objectives: set[str] = set()
        for stage in self.pedagogical_core.stages:
            covered_stages.add(stage.id)
            covered_objectives.update(stage.objective_ids)
        for stage in self.pedagogical_core.stages:
            for ref in stage.objective_ids:
                if ref not in objective_ids:
                    raise ValueError(f"教学环节 {stage.id} 引用了不存在的目标 {ref}")
            for ref in stage.knowledge_point_ids:
                if ref not in {item.id for item in self.pedagogical_core.knowledge_points}:
                    raise ValueError(f"教学环节 {stage.id} 引用了不存在的知识点 {ref}")
        for item in self.pedagogical_core.assessment_plan:
            if item.objective_id not in objective_ids:
                raise ValueError(f"评价计划引用了不存在的目标 {item.objective_id}")
        if len(covered_stages) != len(self.pedagogical_core.stages):
            raise ValueError("存在未参与教学过程的环节")
        return self


# ---------------------------------------------------------------------------
# 统一投影：下游只读取稳定内核
# ---------------------------------------------------------------------------


def lesson_plan_core(content: dict[str, Any]) -> dict[str, Any]:
    """把 V1/V2 教学设计统一投影为稳定教学内核，供下游（任务单、练习、视频脚本、
    知识上下文、质量校验）读取。不判断旧字段，不要求新版本。
    """
    if not content:
        return {}
    if content.get("schema_version") == "2.0":
        core = content.get("pedagogical_core") or {}
        return {
            "objectives": [
                {"id": item.get("id"), "statement": item.get("statement"), "evidence": item.get("evidence")}
                for item in core.get("objectives", [])
            ],
            "key_points": core.get("key_points", []),
            "difficulty_points": core.get("difficulty_points", []),
            "methods": core.get("methods", []),
            "resources": core.get("resources", []),
            "stages": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "duration_minutes": item.get("duration_minutes"),
                    "teacher_activity": item.get("teacher_activity"),
                    "learner_activity": item.get("learner_activity"),
                    "design_intent": item.get("design_intent"),
                    "assessment": item.get("assessment"),
                    "objective_ids": item.get("objective_ids", []),
                    "knowledge_point_ids": item.get("knowledge_point_ids", []),
                }
                for item in core.get("stages", [])
            ],
            "homework": core.get("homework", ""),
            "board_design": core.get("board_design", ""),
        }
    # V1 兼容投影：旧字段形状保持不变（objectives 是字符串列表、stages 是 LessonStage）。
    return {
        "objectives": content.get("objectives", []),
        "key_points": content.get("key_points", []),
        "difficulty_points": content.get("difficulty_points", []),
        "methods": content.get("methods", []),
        "resources": content.get("resources", []),
        "stages": content.get("stages", []),
        "homework": content.get("homework", ""),
        "board_design": content.get("board_design", ""),
    }


def lesson_plan_outline_sections(content: dict[str, Any]) -> list[dict[str, Any]]:
    """返回展示章节树（V2）或基于稳定内核的默认目录（V1）。前端大纲树与导出共用。"""
    if content.get("schema_version") == "2.0":
        return content.get("outline", {}).get("sections", [])
    core = lesson_plan_core(content)
    stages = core.get("stages") or []

    def paragraph(text: str) -> dict[str, Any]:
        return {"kind": "paragraph", "text": text or "（待补充）"}

    default_sections = [
        {"id": "SEC-CONTENT", "title": "内容分析", "summary": "", "coverage_refs": ["content_analysis"], "blocks": [
            paragraph(content.get("content_analysis", "")),
        ], "children": []},
        {"id": "SEC-LEARNER", "title": "学情分析", "summary": "", "coverage_refs": ["learner_analysis"], "blocks": [
            paragraph(content.get("learner_analysis", "")),
        ], "children": []},
        {"id": "SEC-OBJECTIVES", "title": "教学目标", "summary": "", "coverage_refs": ["objectives"], "blocks": [
            {"kind": "bullets", "items": [str(item) for item in core.get("objectives", [])], "numbered": True},
        ], "children": []},
        {"id": "SEC-PROCESS", "title": "教学过程", "summary": "", "coverage_refs": ["stages"], "blocks": [
            {"kind": "process_table", "steps": [
                {"stage_id": item.get("id"), "title": item.get("title"),
                 "duration_minutes": item.get("duration_minutes"),
                 "teacher_activity": item.get("teacher_activity", ""),
                 "learner_activity": item.get("learner_activity", ""),
                 "design_intent": item.get("design_intent", ""),
                 "assessment": item.get("assessment", "")}
                for item in stages
            ]},
        ], "children": []},
        {"id": "SEC-BOARD", "title": "板书设计", "summary": "", "coverage_refs": ["board_design"], "blocks": [
            paragraph(content.get("board_design", "")),
        ], "children": []},
        {"id": "SEC-HOMEWORK", "title": "作业布置", "summary": "", "coverage_refs": ["homework"], "blocks": [
            paragraph(core.get("homework", "")),
        ], "children": []},
        {"id": "SEC-REFLECTION", "title": "教学反思", "summary": "", "coverage_refs": ["reflection"], "blocks": [
            paragraph(content.get("reflection_placeholder", "课后由教师填写教学反思。")),
        ], "children": []},
    ]
    return default_sections


# ---------------------------------------------------------------------------
# V1 → V2 确定性适配器
# ---------------------------------------------------------------------------


def upgrade_lesson_plan_v2(
    content: dict[str, Any],
    bp: CourseBlueprintSchema | None = None,
) -> LessonPlanContentV2:
    """把 V1 教学设计升级为 V2 候选（确定性、幂等），不改写旧 Artifact。

    映射策略：
    - V1 的 objectives（字符串列表）按蓝图目标解析为结构化目标，无法解析时按顺序生成；
    - V1 的 stages（LessonStage）平移进稳定内核；
    - 展示目录按 V1 固定字段生成默认章节树（经由 lesson_plan_outline_sections）。
    """
    if content.get("schema_version") == "2.0":
        return LessonPlanContentV2.model_validate(content)
    bp_objectives = bp.objectives if bp else []
    objectives: list[dict[str, Any]] = []
    for index, raw in enumerate(content.get("objectives", []) or []):
        raw = str(raw)
        match_id = None
        for item in bp_objectives:
            if item.id in raw:
                match_id = item.id
                break
        if match_id is None and index < len(bp_objectives):
            match_id = bp_objectives[index].id
        objectives.append({
            "id": match_id or f"OBJ-{index + 1:02d}",
            "statement": raw,
            "behavior": "理解",
            "criterion": raw,
            "blueprint_objective_id": match_id or f"OBJ-{index + 1:02d}",
            "evidence": "完成对应学习活动并说明依据",
        })
    stages = []
    for item in content.get("stages", []) or []:
        stages.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "duration_minutes": item.get("duration_minutes"),
            "teacher_activity": item.get("teacher_activity", ""),
            "learner_activity": item.get("learner_activity", ""),
            "design_intent": item.get("design_intent", ""),
            "assessment": item.get("assessment", ""),
            "objective_ids": [],
            "knowledge_point_ids": [],
        })
    course_info = {
        "title": content.get("course_info", {}).get("title") or "",
        "subject": content.get("course_info", {}).get("subject") or "",
        "grade_level": content.get("course_info", {}).get("grade_level") or "",
        "audience": content.get("course_info", {}).get("audience") or "",
        "duration_minutes": content.get("course_info", {}).get("duration_minutes") or 0,
        "scenario": content.get("course_info", {}).get("scenario") or "",
        "language": content.get("course_info", {}).get("language") or "中文",
    }
    if not course_info["title"]:
        # V1 没有 course_info：从蓝图或默认值补齐。
        course_info["title"] = bp.course_identity.title if bp else "未命名课程"
        course_info["duration_minutes"] = (
            bp.course_identity.duration_minutes if bp else sum(
                item.get("duration_minutes", 0) for item in stages
            )
        )
    knowledge_points = [
        {"id": f"KP-{index + 1:02d}", "name": str(item)}
        for index, item in enumerate(content.get("key_points", []) or [])
    ]
    # 时长守恒确定性收敛：V1 手工编辑可能破坏守恒，此处修正末环节时长补足差额，
    # 保证候选稿通过 schema 校验；语义层面是否合理交由 QA 门禁判断。
    total = sum(item["duration_minutes"] for item in stages)
    drift = total - course_info["duration_minutes"]
    if stages and abs(drift) > 0.5:
        stages[-1]["duration_minutes"] = max(0.1, round(stages[-1]["duration_minutes"] - drift, 2))
    core = {
        "objectives": objectives,
        "knowledge_points": knowledge_points,
        "key_points": content.get("key_points", []),
        "difficulty_points": content.get("difficulty_points", []),
        "methods": content.get("methods", []),
        "resources": content.get("resources", []),
        "stages": stages,
        "assessment_plan": [],
        "homework": content.get("homework", ""),
        "board_design": content.get("board_design", ""),
        "reflection": content.get("reflection_placeholder", "课后由教师填写教学反思。"),
    }
    outline = {
        "sections": lesson_plan_outline_sections({
            "content_analysis": content.get("content_analysis", ""),
            "learner_analysis": content.get("learner_analysis", ""),
            "objectives": [item["statement"] for item in objectives],
            "stages": stages,
            "board_design": core["board_design"],
            "homework": core["homework"],
            "reflection_placeholder": core["reflection"],
        }),
    }
    return LessonPlanContentV2.model_validate({
        "schema_version": "2.0",
        "course_info": course_info,
        "pedagogical_core": core,
        "outline": outline,
    })


def make_lesson_plan_v2(bp: CourseBlueprintSchema) -> LessonPlanContentV2:
    """基于已批准蓝图的确定性教学示例（Mock / 兜底路径）。"""
    objectives = [
        {
            "id": item.id,
            "statement": f"{item.condition}，{item.behavior}——{item.criterion}",
            "behavior": item.behavior,
            "criterion": item.criterion,
            "blueprint_objective_id": item.id,
            "evidence": "完成对应学习活动并给出可判定依据",
        }
        for item in bp.objectives
    ]
    stage_objective_ids = {
        item.segment_id: [objective.id for objective in bp.objectives if item.segment_id in objective.activity_ids]
        for item in bp.timeline
    }
    stage_knowledge_point_ids = {
        item.segment_id: sorted({
            kp_id
            for objective in bp.objectives
            if objective.id in stage_objective_ids[item.segment_id]
            for kp_id in objective.knowledge_point_ids
        })
        for item in bp.timeline
    }
    stages = [
        {
            "id": item.segment_id,
            "title": item.name,
            "duration_minutes": item.end_minute - item.start_minute,
            "teacher_activity": item.teacher_action,
            "learner_activity": item.learner_action,
            "design_intent": item.purpose,
            "assessment": item.evidence_of_learning,
            "objective_ids": stage_objective_ids[item.segment_id],
            "knowledge_point_ids": stage_knowledge_point_ids[item.segment_id],
        }
        for item in bp.timeline
    ]
    knowledge_points = [
        {"id": item.id, "name": item.name}
        for item in bp.knowledge_points
    ]
    course_info = {
        "title": bp.course_identity.title,
        "subject": bp.course_identity.subject,
        "grade_level": bp.course_identity.grade_level,
        "audience": bp.course_identity.audience,
        "duration_minutes": bp.course_identity.duration_minutes,
        "scenario": bp.course_identity.scenario,
        "language": bp.course_identity.language,
    }
    core = {
        "objectives": objectives,
        "knowledge_points": knowledge_points,
        "key_points": bp.key_points,
        "difficulty_points": bp.difficulty_points,
        "methods": bp.teaching_strategy,
        "resources": ["课程 PPT", "学习任务单", "课后练习"],
        "stages": stages,
        "assessment_plan": [
            {
                "objective_id": item.objective_id,
                "method": item.method,
                "evidence": item.evidence,
                "criterion": item.criterion,
            }
            for item in bp.assessment_plan
        ],
        "homework": "完成配套练习，并用一句话说明最关键的判断依据。",
        "board_design": f"{bp.course_identity.title}\n1. 核心概念\n2. 应用步骤\n3. 检查与总结",
        "reflection": "课后由教师填写教学反思。",
    }
    outline = {
        "sections": [
            {
                "id": "SEC-CONTENT", "title": "内容分析", "summary": "本课内容组织与核心关系。",
                "coverage_refs": ["content_analysis"], "blocks": [
                    {"kind": "paragraph", "text": f"本课围绕“{bp.course_identity.title}”组织内容，由概念理解推进到情境应用。"},
                ], "children": [],
            },
            {
                "id": "SEC-OBJECTIVES", "title": "教学目标", "summary": "本课需要达成的学习目标。",
                "coverage_refs": ["objectives"], "blocks": [
                    {"kind": "bullets", "items": [item["statement"] for item in objectives], "numbered": True},
                ], "children": [],
            },
            {
                "id": "SEC-PROCESS", "title": "教学过程", "summary": "按环节组织的教与学活动。",
                "coverage_refs": ["stages"], "blocks": [
                    {"kind": "process_table", "steps": [
                        {"stage_id": item["id"], "title": item["title"],
                         "duration_minutes": item["duration_minutes"],
                         "teacher_activity": item["teacher_activity"],
                         "learner_activity": item["learner_activity"],
                         "design_intent": item["design_intent"],
                         "assessment": item["assessment"]}
                        for item in stages
                    ]},
                ], "children": [],
            },
            {
                "id": "SEC-BOARD", "title": "板书设计", "summary": "课堂板书要点。",
                "coverage_refs": ["board_design"], "blocks": [
                    {"kind": "paragraph", "text": core["board_design"]},
                ], "children": [],
            },
            {
                "id": "SEC-HOMEWORK", "title": "作业布置", "summary": "巩固与迁移作业。",
                "coverage_refs": ["homework"], "blocks": [
                    {"kind": "paragraph", "text": core["homework"]},
                ], "children": [],
            },
            {
                "id": "SEC-REFLECTION", "title": "教学反思", "summary": "课后填写。",
                "coverage_refs": ["reflection"], "blocks": [
                    {"kind": "paragraph", "text": core["reflection"]},
                ], "children": [],
            },
        ],
    }
    return LessonPlanContentV2.model_validate({
        "schema_version": "2.0",
        "course_info": course_info,
        "pedagogical_core": core,
        "outline": outline,
    })


_CN_DIGITS = "零一二三四五六七八九"


def _chinese_number(value: int) -> str:
    """把正整数转为中文序号（1→一，12→十二，21→二十一）。"""
    if value <= 0:
        return str(value)
    if value < 10:
        return _CN_DIGITS[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        text = "" if tens == 1 else _CN_DIGITS[tens]
        text += "十"
        return text + (_CN_DIGITS[ones] if ones else "")
    return str(value)


def _section_heading_prefix(depth: int, index: int) -> str:
    """按章节树层级生成显示编号：一级一、二、三…；二级（一）（二）…；三级 1. 2. 3.…"""
    if depth <= 1:
        return f"{_chinese_number(index)}、"
    if depth == 2:
        return f"（{_chinese_number(index)}）"
    return f"{index}. "


def lesson_plan_to_markdown_v2(content: LessonPlanContentV2 | dict[str, Any]) -> str:
    """从 V2 章节树生成 Markdown（前端预览与导出共用）。

    章节显示编号由渲染器按章节树层级统一生成（一级一、二、三…；二级（一）（二）…；
    三级 1. 2. 3.…），正文只保存语义标题；重复渲染幂等。
    """
    if isinstance(content, LessonPlanContentV2):
        content = content.model_dump()
    lines: list[str] = [f"# 教学设计 V{content.get('schema_version', '2.0')}", ""]
    info = content.get("course_info") or {}
    lines.append(
        f"**课程：** {info.get('title')} · **学科/年级：** {info.get('subject')} / "
        f"{info.get('grade_level') or info.get('audience')} · **时长：** {info.get('duration_minutes')} 分钟"
    )
    lines.append("")

    def render_block(block: dict[str, Any]) -> None:
        kind = block.get("kind")
        if kind == "paragraph":
            lines.append(str(block.get("text", "")))
            lines.append("")
        elif kind == "bullets":
            items = block.get("items", [])
            for index, item in enumerate(items, 1):
                lines.append(f"{index}. {item}" if block.get("numbered") else f"- {item}")
            lines.append("")
        elif kind == "steps":
            for index, step in enumerate(block.get("steps", []), 1):
                lines.append(f"**{index}. {step.get('title')}**")
                if step.get("detail"):
                    lines.append(str(step["detail"]))
            lines.append("")
        elif kind == "table":
            columns = block.get("columns", [])
            lines.append(f"### {block.get('title')}" if block.get("title") else "### 表格")
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in block.get("rows", []):
                lines.append("| " + " | ".join(str(cell) for cell in row.get("cells", [])) + " |")
            lines.append("")
        elif kind == "process_table":
            lines.append(f"### {block.get('title') or '教学过程'}")
            lines.append("| 环节 | 教师活动 | 学生活动 | 设计意图 | 学习评价 | 用时 |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for step in block.get("steps", []):
                lines.append(
                    f"| {step.get('title', step.get('stage_id'))} | {step.get('teacher_activity', '')} | "
                    f"{step.get('learner_activity', '')} | {step.get('design_intent', '')} | "
                    f"{step.get('assessment', '')} | {step.get('duration_minutes', 0)} 分钟 |"
                )
            lines.append("")
        elif kind == "note":
            lines.append(f"> {block.get('text', '')}")
            lines.append("")
        elif kind == "checklist":
            lines.append(f"### {block.get('title')}" if block.get("title") else "### 检查表")
            for item in block.get("items", []):
                mark = "☑" if item.get("checked") else "□"
                lines.append(f"- {mark} {item.get('text', '')}")
            lines.append("")

    def visit(section: dict[str, Any], depth: int, index: int) -> None:
        heading = "#" * min(depth + 1, 4)
        prefix = _section_heading_prefix(depth, index)
        lines.append(f"{heading} {prefix}{section.get('title')}")
        if section.get("summary"):
            lines.append(f"> {section.get('summary')}")
            lines.append("")
        for block in section.get("blocks", []):
            render_block(block)
        for child_index, child in enumerate(section.get("children", []), 1):
            visit(child, depth + 1, child_index)

    for index, section in enumerate(content.get("outline", {}).get("sections", []), 1):
        visit(section, 1, index)
    return "\n".join(lines).strip() + "\n"


def lesson_plan_v1_from_any(raw: dict[str, Any] | None) -> Any:
    """把 V1/V2 教学设计统一投影为 V1 LessonPlanContent（legacy 生成器/校验消费）。

    教学设计 V2 上线后 lesson_plan Artifact 可能是 schema_version 2.0；旧版
    LessonPlanContent.model_validate 无法直接接受 V2 结构。该投影把 V2
    pedagogical_core 平移为 V1 stages / objectives 形状，保证下游（legacy
    视频脚本生成、质量校验、Builder 初始化）无感知继续工作。
    """
    from app.schemas.artifact import LessonPlanContent, LessonStage

    if not raw:
        return None
    if raw.get("schema_version") != "2.0":
        return LessonPlanContent.model_validate(raw)
    v2 = LessonPlanContentV2.model_validate(raw)
    core = v2.pedagogical_core
    return LessonPlanContent(
        content_analysis="",
        learner_analysis="",
        objectives=[f"{item.id}：{item.behavior}——{item.criterion}" for item in core.objectives],
        key_points=core.key_points,
        difficulty_points=core.difficulty_points,
        methods=core.methods,
        resources=core.resources,
        stages=[
            LessonStage(
                id=stage.id, title=stage.title, duration_minutes=stage.duration_minutes,
                teacher_activity=stage.teacher_activity, learner_activity=stage.learner_activity,
                design_intent=stage.design_intent, assessment=stage.assessment,
            )
            for stage in core.stages
        ],
        board_design=core.board_design,
        homework=core.homework,
        reflection_placeholder=core.reflection,
    )
