"""学习任务单 V3 数据契约：动态目录 + 强类型 Block。

与 V2 固定八段结构的差异：
- ``sections`` 使用稳定 ID + parent_id + 同级 order 表达动态目录树，AI 可增删、
  重命名、排序、嵌套章节（默认最大深度 3 层）。
- 章节内容由判别联合 Block 承载：text / objective_list / learning_task /
  record_table / question_set / assessment / checklist。
- 目录名称与位置不固定，但保存前必须满足「必备语义」（目标、任务、学习证据、
  评价），由 model_validator 强制，其余蓝图引用 / 时长 / 职责边界检查由
  ``app.agent.agents.task_sheet.qa`` 确定性门禁完成。

兼容约定：
- V2 历史版本保持原样，继续可预览与导出。
- 第一次 AI 修改 V2 时通过 ``task_sheet_to_v3()`` 在运行期生成 V3 候选，
  旧 Artifact 不改写。
- ``task_sheet_objectives()`` 是 V1/V2/V3 的统一目标投影入口。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.blueprint import CourseBlueprintSchema

MAX_TASK_SHEET_SECTIONS = 30
MAX_TASK_SHEET_DEPTH = 3
MAX_TOP_LEVEL_SECTIONS = 15

TASK_SHEET_V3 = "3.0"
TASK_SHEET_V2 = "2.0"


# ---------------------------------------------------------------------------
# 文档级事实
# ---------------------------------------------------------------------------


class TaskSheetCourseInfoV3(BaseModel):
    course_title: str = Field(min_length=1)
    subject: str = ""
    grade_level: str = ""
    audience: str = ""
    duration_minutes: float = Field(gt=0)


class TaskSheetObjectiveCatalog(BaseModel):
    """文档级目标目录：所有 Block 引用必须落在其中。"""

    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    success_criterion: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 强类型 Block（判别联合）
# ---------------------------------------------------------------------------


class TaskSheetTextBlock(BaseModel):
    kind: Literal["text"] = "text"
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class TaskSheetObjectiveListBlock(BaseModel):
    kind: Literal["objective_list"] = "objective_list"
    id: str = Field(min_length=1)
    title: str = "学习目标"
    objective_ids: list[str] = Field(min_length=1)


class TaskSheetTaskRecordTable(BaseModel):
    title: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    columns: list[str] = Field(min_length=2)
    blank_rows: int = Field(default=3, ge=1, le=12)


class TaskSheetLearningTaskBlock(BaseModel):
    kind: Literal["learning_task"] = "learning_task"
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    action: str = Field(min_length=1)
    object: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    student_output: str = Field(min_length=1)
    completion_criterion: str = Field(min_length=1)
    estimated_minutes: float = Field(gt=0)
    collaboration_mode: Literal["individual", "pair", "group", "whole_class"] = "individual"
    objective_ids: list[str] = Field(min_length=1)
    knowledge_point_ids: list[str] = Field(default_factory=list)
    stage_id: str | None = None
    scaffolds: list[str] = Field(default_factory=list)
    record_table: TaskSheetTaskRecordTable | None = None

    @model_validator(mode="after")
    def require_in_class_stage(self):
        # stage_id 与教学环节映射：V3 保留阶段枚举语义，任务是否属于课中由 stage_id 判定。
        # 阶段映射合法性（蓝图中是否存在该环节）由 QA 门禁检查，这里不做蓝图依赖。
        if self.stage_id and not self.stage_id.strip():
            raise ValueError("教学环节 ID 不能为空字符串")
        return self


class TaskSheetRecordTableBlock(BaseModel):
    kind: Literal["record_table"] = "record_table"
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    columns: list[str] = Field(min_length=2)
    blank_rows: int = Field(default=3, ge=1, le=12)


class TaskSheetQuestionItem(BaseModel):
    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    objective_ids: list[str] = Field(default_factory=list)
    stage_id: str | None = None


class TaskSheetQuestionSetBlock(BaseModel):
    kind: Literal["question_set"] = "question_set"
    id: str = Field(min_length=1)
    title: str = "课堂问题"
    questions: list[TaskSheetQuestionItem] = Field(min_length=1)


class TaskSheetAssessmentItem(BaseModel):
    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    objective_ids: list[str] = Field(default_factory=list)


class TaskSheetAssessmentBlock(BaseModel):
    kind: Literal["assessment"] = "assessment"
    id: str = Field(min_length=1)
    title: str = "学习成效自我评价"
    scale: list[str] = Field(
        default_factory=lambda: ["尚未做到", "基本做到", "能够做到"],
        min_length=2,
    )
    items: list[TaskSheetAssessmentItem] = Field(min_length=1)


class TaskSheetChecklistItem(BaseModel):
    text: str = Field(min_length=1)


class TaskSheetChecklistBlock(BaseModel):
    kind: Literal["checklist"] = "checklist"
    id: str = Field(min_length=1)
    title: str = "检查表"
    items: list[TaskSheetChecklistItem] = Field(min_length=1)


TaskSheetBlock = (
    TaskSheetTextBlock
    | TaskSheetObjectiveListBlock
    | TaskSheetLearningTaskBlock
    | TaskSheetRecordTableBlock
    | TaskSheetQuestionSetBlock
    | TaskSheetAssessmentBlock
    | TaskSheetChecklistBlock
)


# ---------------------------------------------------------------------------
# 动态目录章节
# ---------------------------------------------------------------------------


class TaskSheetSectionV3(BaseModel):
    id: str = Field(min_length=1, pattern=r"^SEC-[A-Z0-9-]+$")
    parent_id: str = Field(default="", description="空字符串表示顶级章节")
    order: int = Field(ge=0)
    title: str = Field(min_length=1)
    purpose: str = ""
    objective_ids: list[str] = Field(default_factory=list)
    blocks: list[TaskSheetBlock] = Field(default_factory=list)


def _flatten_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把扁平 sections（parent_id/order）展开为深度优先列表（树序遍历）。"""

    def visit(items: list[dict[str, Any]], depth: int, parent: str) -> list[dict[str, Any]]:
        if depth > MAX_TASK_SHEET_DEPTH:
            raise ValueError(f"任务单目录深度不能超过 {MAX_TASK_SHEET_DEPTH} 级")
        result: list[dict[str, Any]] = []
        for item in sorted(items, key=lambda x: int(x.get("order", 0))):
            if item.get("parent_id") != parent:
                continue
            result.append(item)
            children = [child for child in items if child.get("parent_id") == item.get("id")]
            result.extend(visit(children, depth + 1, item.get("id", "")))
        return result

    return visit(sections, 1, "")


def task_sheet_sections_depth(sections: list[dict[str, Any]]) -> int:
    """返回目录实际深度（顶级为 1）。"""
    max_depth = 0

    def walk(items: list[dict[str, Any]], depth: int) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        for item in items:
            children = [child for child in sections if child.get("parent_id") == item.get("id")]
            if children:
                walk(children, depth + 1)

    walk(sections, 1)
    return max_depth


def task_sheet_outline_sections(content: dict[str, Any]) -> list[dict[str, Any]]:
    """V2/V3 统一目录投影：V2 返回默认八段目录，V3 返回实际动态目录。

    前端目录树与导出共用；V2 的历史结构保持不变。
    """
    if content.get("schema_version") == TASK_SHEET_V3:
        return [dict(item) for item in content.get("sections", [])]
    return default_outline_sections(content)


def default_outline_sections(content: dict[str, Any]) -> list[dict[str, Any]]:
    """V2 → 默认目录投影（用于统一投影，不改写 V2 原文）。"""
    info = content.get("course_info") or {}
    return [
        {"id": "SEC-COURSE", "parent_id": "", "order": 0, "title": "课程信息", "purpose": "课程基本信息。", "objective_ids": [], "blocks": [
            {"kind": "text", "id": "B-COURSE-INFO", "text": f"{info.get('subject', '')} · {info.get('grade_level', '') or info.get('audience', '')} · 建议时长 {info.get('duration_minutes', 0)} 分钟"},
        ]},
        {"id": "SEC-OBJECTIVES", "parent_id": "", "order": 1, "title": "学习目标与达成标准", "purpose": "本课需要达成的学习目标。", "objective_ids": [item.get("id") for item in content.get("learning_objectives", [])], "blocks": [
            {"kind": "objective_list", "id": "B-OBJECTIVES", "title": "学习目标", "objective_ids": [item.get("id") for item in content.get("learning_objectives", [])]},
        ]},
        {"id": "SEC-PREPARATION", "parent_id": "", "order": 2, "title": "课前准备", "purpose": "课前需要完成的准备工作。", "objective_ids": [], "blocks": [
            {"kind": "checklist", "id": "B-PREPARATION", "title": "课前准备清单", "items": [{"text": item} for item in content.get("preparation", [])]},
        ]},
        {"id": "SEC-TASKS", "parent_id": "", "order": 3, "title": "学习任务", "purpose": "按阶段组织的可执行学习任务。", "objective_ids": [], "blocks": [
            {"kind": "learning_task", **task_block_payload(item)}
            for item in content.get("tasks", [])
        ]},
        {"id": "SEC-RECORD", "parent_id": "", "order": 4, "title": "学习观察记录", "purpose": "完成任务过程中可填写的学习证据表。", "objective_ids": [], "blocks": [
            {"kind": "record_table", "id": "B-RECORD", **(content.get("record_table") or {"title": "学习观察记录", "instructions": "记录关键信息与检查结果。", "columns": ["任务", "关键信息或现象", "我的解释", "检查结果"], "blank_rows": 3})},
        ]},
        {"id": "SEC-QUESTIONS", "parent_id": "", "order": 5, "title": "课堂问题", "purpose": "过程性学习问题，帮助学生深化理解。", "objective_ids": [], "blocks": [
            {"kind": "question_set", "id": "B-QUESTIONS", "title": "课堂问题", "questions": [
                {"id": item.get("id"), "prompt": item.get("prompt"), "objective_ids": item.get("objective_ids", []), "stage_id": item.get("stage_id")}
                for item in content.get("learning_questions", [])
            ]},
        ]},
        {"id": "SEC-ASSESSMENT", "parent_id": "", "order": 6, "title": "学习成效自我评价", "purpose": "学生自评与同伴互评。", "objective_ids": [item.get("id") for item in content.get("self_assessment", [])], "blocks": [
            {"kind": "assessment", "id": "B-ASSESSMENT", "title": "学习成效自我评价", "scale": content.get("self_assessment_scale", ["尚未做到", "基本做到", "能够做到"]), "items": [
                {"id": item.get("id"), "statement": item.get("statement"), "objective_ids": item.get("objective_ids", [])}
                for item in content.get("self_assessment", [])
            ]},
        ]},
        {"id": "SEC-EXTENSION", "parent_id": "", "order": 7, "title": "课后拓展", "purpose": "迁移与应用任务。", "objective_ids": [], "blocks": [
            {"kind": "checklist", "id": "B-EXTENSION", "title": "拓展任务", "items": [{"text": item} for item in content.get("extension", [])]},
        ]},
    ]


def task_block_payload(task: dict[str, Any]) -> dict[str, Any]:
    """V2 LearningTask → V3 learning_task Block 载荷（无损，保留全部字段）。"""
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "action": task.get("action"),
        "object": task.get("object"),
        "steps": task.get("steps", []),
        "student_output": task.get("student_output"),
        "completion_criterion": task.get("completion_criterion"),
        "estimated_minutes": task.get("estimated_minutes"),
        "collaboration_mode": task.get("collaboration_mode", "individual"),
        "objective_ids": task.get("objective_ids", []),
        "knowledge_point_ids": task.get("knowledge_point_ids", []),
        "stage_id": task.get("stage_id"),
        "scaffolds": task.get("scaffolds", []),
        "record_table": task.get("record_table"),
    }


# ---------------------------------------------------------------------------
# V3 顶层文档
# ---------------------------------------------------------------------------


class TaskSheetContentV3(BaseModel):
    schema_version: Literal["3.0"] = "3.0"
    course_info: TaskSheetCourseInfoV3
    objective_catalog: list[TaskSheetObjectiveCatalog] = Field(min_length=1)
    sections: list[TaskSheetSectionV3] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_v3(self):
        self._validate_tree()
        self._validate_semantics()
        return self

    def _validate_tree(self) -> None:
        if not self.sections:
            raise ValueError("任务单目录不能为空")
        if len([s for s in self.sections if not s.parent_id]) > MAX_TOP_LEVEL_SECTIONS:
            raise ValueError(f"顶级章节数量不能超过 {MAX_TOP_LEVEL_SECTIONS}")
        section_ids: set[str] = set()
        block_ids: set[str] = set()
        seen_orders: dict[str, set[int]] = {}
        for section in self.sections:
            if section.id in section_ids:
                raise ValueError(f"章节 ID 重复：{section.id}")
            section_ids.add(section.id)
            if section.parent_id and section.parent_id not in {item.id for item in self.sections}:
                raise ValueError(f"章节 {section.id} 引用了不存在的父章节 {section.parent_id}")
            if section.parent_id == section.id:
                raise ValueError(f"章节 {section.id} 不能作为自己的父章节")
            seen_orders.setdefault(section.parent_id, set())
            if section.order in seen_orders[section.parent_id]:
                raise ValueError(f"章节 {section.id} 与同级章节 order 冲突")
            seen_orders[section.parent_id].add(section.order)
            for block in section.blocks:
                if block.id in block_ids:
                    raise ValueError(f"Block ID 重复：{block.id}")
                block_ids.add(block.id)
        if len(section_ids) > MAX_TASK_SHEET_SECTIONS:
            raise ValueError(f"任务单总章节数不能超过 {MAX_TASK_SHEET_SECTIONS}")
        if task_sheet_sections_depth([s.model_dump() for s in self.sections]) > MAX_TASK_SHEET_DEPTH:
            raise ValueError(f"任务单目录深度不能超过 {MAX_TASK_SHEET_DEPTH} 级")

    def _validate_semantics(self) -> None:
        """必备语义：目录位置不固定，但目标/任务/学习证据/评价必须保留。"""
        catalog_ids = {item.id for item in self.objective_catalog}
        if len(catalog_ids) != len(self.objective_catalog):
            raise ValueError("目标目录包含重复 ID")
        has_objective_list = False
        has_learning_task = False
        has_record_table = False
        has_assessment = False
        covered: set[str] = set()
        for section in self.sections:
            for block in section.blocks:
                if block.kind == "objective_list":
                    has_objective_list = True
                    for ref in block.objective_ids:
                        if ref not in catalog_ids:
                            raise ValueError(f"objective_list {block.id} 引用了目录外目标 {ref}")
                elif block.kind == "learning_task":
                    has_learning_task = True
                    for ref in block.objective_ids:
                        if ref not in catalog_ids:
                            raise ValueError(f"学习任务 {block.id} 引用了目录外目标 {ref}")
                        covered.add(ref)
                    if block.record_table is not None:
                        has_record_table = True
                elif block.kind == "record_table":
                    has_record_table = True
                elif block.kind == "assessment":
                    has_assessment = True
                    for item in block.items:
                        for ref in item.objective_ids:
                            if ref not in catalog_ids:
                                raise ValueError(f"评价条目 {item.id} 引用了目录外目标 {ref}")
                elif block.kind == "question_set":
                    for question in block.questions:
                        for ref in question.objective_ids:
                            if ref not in catalog_ids:
                                raise ValueError(f"问题 {question.id} 引用了目录外目标 {ref}")
        if not has_objective_list:
            raise ValueError("任务单必须至少包含一个目标列表（objective_list）")
        if not has_learning_task:
            raise ValueError("任务单必须至少包含一个可执行学习任务（learning_task）")
        if not has_record_table:
            raise ValueError("任务单必须至少包含一个可填写记录表（record_table）")
        if not has_assessment:
            raise ValueError("任务单必须至少包含一个学生评价（assessment）")
        uncovered = catalog_ids - covered
        if uncovered:
            raise ValueError(f"以下目标未被任何学习任务覆盖：{sorted(uncovered)}")


# ---------------------------------------------------------------------------
# V2 → V3 确定性适配器
# ---------------------------------------------------------------------------


def task_sheet_to_v3(
    content: dict[str, Any],
    bp: CourseBlueprintSchema | None = None,
    lesson_plan_raw: dict[str, Any] | None = None,
) -> TaskSheetContentV3:
    """把 V1/V2 任务单升级为 V3 候选（确定性、幂等），不改写旧 Artifact。

    迁移阶段原样保留旧内容，不做润色；目录重组由后续编辑工具执行。
    """
    if content.get("schema_version") == TASK_SHEET_V3:
        return TaskSheetContentV3.model_validate(content)
    info = content.get("course_info") or {}
    course_info = TaskSheetCourseInfoV3(
        course_title=info.get("course_title") or (bp.course_identity.title if bp else "未命名课程"),
        subject=info.get("subject", ""),
        grade_level=info.get("grade_level", ""),
        audience=info.get("audience", ""),
        duration_minutes=float(info.get("duration_minutes") or (bp.course_identity.duration_minutes if bp else 0)),
    )
    objectives = content.get("learning_objectives", []) or []
    catalog = [
        TaskSheetObjectiveCatalog(
            id=item.get("id") or f"OBJ-{index + 1:02d}",
            statement=item.get("statement", ""),
            success_criterion=item.get("success_criterion", ""),
        )
        for index, item in enumerate(objectives)
    ]
    if not catalog and bp:
        catalog = [
            TaskSheetObjectiveCatalog(id=item.id, statement=item.behavior, success_criterion=item.criterion)
            for item in bp.objectives
        ]
    v2 = dict(content)
    v2.setdefault("preparation", [])
    v2.setdefault("record_table", None)
    v2.setdefault("learning_questions", [])
    v2.setdefault("self_assessment_scale", ["尚未做到", "基本做到", "能够做到"])
    v2.setdefault("self_assessment", [])
    v2.setdefault("extension", [])
    sections = default_outline_sections(v2)
    return TaskSheetContentV3.model_validate({
        "schema_version": TASK_SHEET_V3,
        "course_info": course_info.model_dump(),
        "objective_catalog": [item.model_dump() for item in catalog],
        "sections": sections,
    })


def make_task_sheet_v3(
    bp: CourseBlueprintSchema,
    lesson_plan_raw: dict[str, Any] | None = None,
) -> TaskSheetContentV3:
    """蓝图驱动首稿：确定性生成完整 V3 任务单（Mock / 兜底路径）。

    目录按「导入 → 目标 → 任务链 → 记录 → 评价 → 拓展」组织；任务是语义必备要素，
    标题与出现位置由后续 Agent 动态调整。
    """
    catalog = [
        TaskSheetObjectiveCatalog(
            id=item.id,
            statement=f"{item.condition}，{item.behavior}{bp.course_identity.title}相关任务",
            success_criterion=item.criterion,
        )
        for item in bp.objectives
    ]
    objective_ids = [item.id for item in bp.objectives]
    knowledge_ids = [point.id for point in bp.knowledge_points]
    stages = bp.timeline
    if not stages:
        raise ValueError("已批准蓝图缺少教学环节 timeline")

    def _stage_minutes(segment_id: str) -> float:
        item = next((s for s in stages if s.segment_id == segment_id), None)
        return max(1, round(item.end_minute - item.start_minute, 2)) if item else 1.0

    # 时长守恒：课中任务按环节预算切分，保证合计不超过课程时长（QA 门禁要求）。
    stage_budget: dict[str, float] = {item.segment_id: max(0.0, item.end_minute - item.start_minute) for item in stages}
    if len(stages) >= 2:
        t1_minutes = max(1.0, min(stage_budget.get(stages[0].segment_id, 0.0), _stage_minutes(stages[0].segment_id)))
        s2_budget = stage_budget.get(stages[-1].segment_id, 0.0)
        if s2_budget >= 2.0:
            t2_minutes = max(1.0, round(s2_budget * 0.5, 2))
            t3_minutes = max(1.0, round(s2_budget - t2_minutes, 2))
        else:
            t2_minutes = max(1.0, round(s2_budget, 2))
            t3_minutes = 1.0
    else:
        # 单环节：把环节预算三等分给三个任务，避免超出该环节时长。
        s1_budget = stage_budget.get(stages[0].segment_id, 0.0)
        t1_minutes = max(1.0, round(s1_budget * 0.3, 2))
        t2_minutes = max(1.0, round(s1_budget * 0.4, 2))
        t3_minutes = max(1.0, round(s1_budget - t1_minutes - t2_minutes, 2))

    tasks: list[dict[str, Any]] = [
        {
            "id": "T-01",
            "title": "观察情境并做出初步判断",
            "action": "观察、标记并判断",
            "object": "课程导入情境",
            "steps": ["圈出情境中的关键条件", "写下你的初步判断", "用一条信息说明判断依据"],
            "student_output": "一条初步判断和至少一条依据",
            "completion_criterion": "判断明确，依据来自情境中的真实信息",
            "estimated_minutes": t1_minutes,
            "collaboration_mode": "individual",
            "objective_ids": [objective_ids[0]],
            "knowledge_point_ids": [knowledge_ids[0]] if knowledge_ids else [],
            "stage_id": stages[0].segment_id,
            "scaffolds": ["我看到的关键信息是……", "我判断……，因为……"],
            "record_table": None,
        },
        {
            "id": "T-02",
            "title": "解释核心关系",
            "action": "整理并解释",
            "object": bp.key_points[0] if bp.key_points else "本课核心概念",
            "steps": ["写出核心概念", "标明概念成立的条件", "用自己的话解释关键关系"],
            "student_output": "一段包含概念、条件和关系的解释",
            "completion_criterion": bp.objectives[0].criterion,
            "estimated_minutes": t2_minutes,
            "collaboration_mode": "pair",
            "objective_ids": [objective_ids[0]],
            "knowledge_point_ids": [knowledge_ids[0]] if knowledge_ids else [],
            "stage_id": stages[1].segment_id if len(stages) > 1 else stages[0].segment_id,
            "scaffolds": ["这个概念适用于……", "关键关系可以用……表示"],
            "record_table": None,
        },
        {
            "id": "T-03",
            "title": "应用方法并检查结论",
            "action": "应用、记录并检查",
            "object": f"{bp.course_identity.title}的基础应用任务",
            "steps": ["识别任务中的条件", "选择对应概念或方法", "完成推理并对照条件检查结论"],
            "student_output": "完整的处理步骤、结论和检查说明",
            "completion_criterion": bp.objectives[-1].criterion,
            "estimated_minutes": t3_minutes,
            "collaboration_mode": "individual",
            "objective_ids": objective_ids,
            "knowledge_point_ids": knowledge_ids,
            "stage_id": stages[-1].segment_id,
            "scaffolds": ["已知条件是……", "我选择的方法是……", "我用……检查了结论"],
            "record_table": None,
        },
    ]
    record_table = {
        "title": "学习观察记录",
        "instructions": "在完成任务时记录关键信息、你的解释和检查结果。",
        "columns": ["任务", "关键信息或现象", "我的解释", "检查结果"],
        "blank_rows": 4,
    }
    questions = [
        {"id": "LQ-01", "prompt": "这个概念在什么条件下适用？", "objective_ids": [objective_ids[0]], "stage_id": stages[1].segment_id if len(stages) > 1 else stages[0].segment_id},
        {"id": "LQ-02", "prompt": "遇到新问题时，你如何选择第一步？", "objective_ids": [objective_ids[-1]], "stage_id": stages[-1].segment_id},
    ]
    assessment_items = [
        {"id": f"SA-{index:02d}", "statement": f"我已达成：{item.statement}", "objective_ids": [item.id]}
        for index, item in enumerate(catalog, 1)
    ]
    sections = [
        {
            "id": "SEC-HOOK", "parent_id": "", "order": 0,
            "title": "导入情境", "purpose": "用真实情境唤起学生已有经验，明确本课要解决的问题。",
            "objective_ids": [objective_ids[0]], "blocks": [
                {"kind": "text", "id": "B-HOOK", "text": f"请先观察与「{bp.course_identity.title}」相关的情境，记录你注意到的关键信息，并完成第一个判断任务。"},
            ],
        },
        {
            "id": "SEC-OBJECTIVES", "parent_id": "", "order": 1,
            "title": "学习目标", "purpose": "清晰说明本课要达成的目标与达成标准。",
            "objective_ids": objective_ids, "blocks": [
                {"kind": "objective_list", "id": "B-OBJECTIVES", "title": "学习目标", "objective_ids": objective_ids},
            ],
        },
        {
            "id": "SEC-PREPARATION", "parent_id": "", "order": 2,
            "title": "课前准备", "purpose": "进入任务前准备材料并明确观察重点。",
            "objective_ids": [], "blocks": [
                {"kind": "checklist", "id": "B-PREPARATION", "title": "课前准备清单",
                 "items": [{"text": "准备学习用品和记录纸，带着“我观察到什么、如何验证”的问题进入任务。"}]},
            ],
        },
        {
            "id": "SEC-TASKS", "parent_id": "", "order": 3,
            "title": "学习任务链", "purpose": "从观察判断推进到解释与应用的可执行任务。",
            "objective_ids": objective_ids, "blocks": [{"kind": "learning_task", **task} for task in tasks],
        },
        {
            "id": "SEC-RECORD", "parent_id": "", "order": 4,
            "title": "学习观察记录", "purpose": "任务过程中的学习证据记录表。",
            "objective_ids": objective_ids, "blocks": [
                {"kind": "record_table", "id": "B-RECORD", **record_table},
            ],
        },
        {
            "id": "SEC-QUESTIONS", "parent_id": "", "order": 5,
            "title": "深度思考与延伸反思", "purpose": "过程性问题，帮助学生迁移与反思。",
            "objective_ids": [objective_ids[-1]], "blocks": [
                {"kind": "question_set", "id": "B-QUESTIONS", "title": "课堂问题", "questions": questions},
            ],
        },
        {
            "id": "SEC-ASSESSMENT", "parent_id": "", "order": 6,
            "title": "学习成效自我评价", "purpose": "对照目标完成自评，明确自己的达成情况。",
            "objective_ids": objective_ids, "blocks": [
                {"kind": "assessment", "id": "B-ASSESSMENT", "title": "学习成效自我评价",
                 "scale": ["尚未做到", "基本做到", "能够做到"], "items": assessment_items},
            ],
        },
        {
            "id": "SEC-EXTENSION", "parent_id": "", "order": 7,
            "title": "课后拓展", "purpose": "把本课方法迁移到生活或专业场景。",
            "objective_ids": [objective_ids[-1]], "blocks": [
                {"kind": "checklist", "id": "B-EXTENSION", "title": "拓展任务",
                 "items": [{"text": "寻找一个生活或专业场景，说明本课方法如何应用。"}]},
            ],
        },
    ]
    return TaskSheetContentV3.model_validate({
        "schema_version": TASK_SHEET_V3,
        "course_info": {
            "course_title": bp.course_identity.title,
            "subject": bp.course_identity.subject,
            "grade_level": bp.course_identity.grade_level,
            "audience": bp.course_identity.audience,
            "duration_minutes": bp.course_identity.duration_minutes,
        },
        "objective_catalog": [item.model_dump() for item in catalog],
        "sections": sections,
    })


# ---------------------------------------------------------------------------
# 统一目标投影
# ---------------------------------------------------------------------------


def task_sheet_objectives(content: dict[str, Any] | None) -> list[dict[str, Any]]:
    """V1/V2/V3 任务单统一目标投影，供下游（练习、知识上下文、质量校验）读取。"""
    if not content:
        return []
    if content.get("schema_version") == TASK_SHEET_V3:
        return [
            {"id": item.get("id"), "statement": item.get("statement"), "success_criterion": item.get("success_criterion")}
            for item in content.get("objective_catalog", [])
        ]
    if content.get("schema_version") == TASK_SHEET_V2:
        return [
            {"id": item.get("id"), "statement": item.get("statement"), "success_criterion": item.get("success_criterion")}
            for item in content.get("learning_objectives", [])
        ]
    return [
        {"id": item.get("id"), "statement": item.get("statement"), "success_criterion": item.get("success_criterion")}
        for item in content.get("learning_objectives", [])
    ]


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def task_sheet_v3_to_markdown(content: TaskSheetContentV3 | dict[str, Any]) -> str:
    """从 V3 动态目录树生成 Markdown（前端预览与导出共用）。"""
    if isinstance(content, TaskSheetContentV3):
        content = content.model_dump()
    lines: list[str] = ["# 学习任务单 V3", ""]
    info = content.get("course_info") or {}
    lines.append(
        f"**课程：** {info.get('course_title')} · **学科/年级：** {info.get('subject')} / "
        f"{info.get('grade_level') or info.get('audience')} · **建议时长：** {info.get('duration_minutes')} 分钟"
    )
    lines.append("")

    def render_block(block: dict[str, Any]) -> None:
        kind = block.get("kind")
        if kind == "text":
            lines.append(str(block.get("text", "")))
            lines.append("")
        elif kind == "objective_list":
            lines.append(f"### {block.get('title') or '学习目标'}")
            for objective in content.get("objective_catalog", []):
                if objective.get("id") in (block.get("objective_ids") or []):
                    lines.append(f"- {objective.get('id')}：{objective.get('statement')}（达成标准：{objective.get('success_criterion')}）")
            lines.append("")
        elif kind == "learning_task":
            lines.append(f"### {block.get('id')} · {block.get('title')}")
            lines.append(f"- 对应目标：{'、'.join(block.get('objective_ids', []))}")
            lines.append(f"- 预计用时：{block.get('estimated_minutes')} 分钟")
            if block.get("stage_id"):
                lines.append(f"- 教学环节：{block.get('stage_id')}")
            lines.append(f"- 学习动作：{block.get('action')}")
            lines.append(f"- 操作对象：{block.get('object')}")
            lines.append("- 操作步骤：")
            for step in block.get("steps", []):
                lines.append(f"  - {step}")
            lines.append(f"- 成果要求：{block.get('student_output')}")
            lines.append(f"- 完成标准：{block.get('completion_criterion')}")
            for scaffold in block.get("scaffolds", []):
                lines.append(f"- 思考支架：{scaffold}")
            if block.get("record_table"):
                table = block["record_table"]
                lines.append(f"#### {table.get('title')}")
                lines.append(table.get("instructions", ""))
                columns = table.get("columns", [])
                lines.append("| " + " | ".join(columns) + " |")
                lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
                for _ in range(int(table.get("blank_rows", 3))):
                    lines.append("| " + " | ".join([" "] * len(columns)) + " |")
            lines.append("")
        elif kind == "record_table":
            lines.append(f"### {block.get('title')}")
            lines.append(block.get("instructions", ""))
            columns = block.get("columns", [])
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for _ in range(int(block.get("blank_rows", 3))):
                lines.append("| " + " | ".join([" "] * len(columns)) + " |")
            lines.append("")
        elif kind == "question_set":
            lines.append(f"### {block.get('title') or '课堂问题'}")
            for question in block.get("questions", []):
                lines.append(f"- {question.get('prompt')}")
            lines.append("")
        elif kind == "assessment":
            lines.append(f"### {block.get('title') or '学习成效自我评价'}（{' / '.join(block.get('scale', []))}）")
            for item in block.get("items", []):
                lines.append(f"- □ {item.get('statement')}")
            lines.append("")
        elif kind == "checklist":
            lines.append(f"### {block.get('title') or '检查表'}")
            for item in block.get("items", []):
                lines.append(f"- □ {item.get('text')}")
            lines.append("")

    sections = content.get("sections", [])
    ordered = _flatten_sections([dict(s) for s in sections])
    depth_map: dict[str, int] = {}
    for section in sections:
        depth_map[section.get("id")] = 1 if not section.get("parent_id") else depth_map.get(section.get("parent_id"), 1) + 1
    for section in ordered:
        heading = "#" * min(depth_map.get(section.get("id"), 1) + 1, 4)
        lines.append(f"{heading} {section.get('title')}")
        if section.get("purpose"):
            lines.append(f"> {section.get('purpose')}")
            lines.append("")
        for block in section.get("blocks", []):
            render_block(block)
    return "\n".join(lines).strip() + "\n"
