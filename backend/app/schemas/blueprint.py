from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CourseIdentity(BaseModel):
    title: str
    subject: str
    grade_level: str
    audience: str
    duration_minutes: int = Field(gt=0)
    scenario: str
    language: str = "中文"


class LearningAnalysis(BaseModel):
    prior_knowledge: list[str]
    learner_characteristics: list[str]
    likely_misconceptions: list[str]


class LearningObjective(BaseModel):
    id: str
    domain: Literal["knowledge", "skill", "competency", "value"]
    behavior: str
    condition: str
    criterion: str
    knowledge_point_ids: list[str]
    activity_ids: list[str]
    exercise_ids: list[str]


class KnowledgePoint(BaseModel):
    id: str
    name: str
    level: str = "core"
    prerequisite_ids: list[str] = []
    source_refs: list[str] = []


class TimelineSegment(BaseModel):
    segment_id: str
    name: str
    start_minute: float = Field(ge=0)
    end_minute: float = Field(gt=0)
    purpose: str
    teacher_action: str
    learner_action: str
    evidence_of_learning: str

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_minute <= self.start_minute:
            raise ValueError("环节结束时间必须晚于开始时间")
        return self


class AssessmentItem(BaseModel):
    objective_id: str
    method: str
    evidence: str
    criterion: str


class CourseBlueprintSchema(BaseModel):
    course_identity: CourseIdentity
    learning_analysis: LearningAnalysis
    objectives: list[LearningObjective]
    knowledge_points: list[KnowledgePoint]
    key_points: list[str]
    difficulty_points: list[str]
    teaching_strategy: list[str]
    timeline: list[TimelineSegment]
    assessment_plan: list[AssessmentItem]
    terminology: dict[str, str]
    source_refs: list[str] = []
    resource_constraints: list[str] = []


def normalize_blueprint_references(bp: CourseBlueprintSchema) -> CourseBlueprintSchema:
    """Repair cross-references that are structurally valid but unusable downstream.

    LLMs occasionally return an otherwise valid blueprint with an empty timeline,
    duplicate IDs, or objective/activity references from a previous draft.  Those
    values pass Pydantic but make every initial artifact fail its semantic gate.
    Keep the teacher's wording and repair only the identity graph and timing so
    every generated artifact has a stable, internally consistent source of truth.
    """
    identity = bp.course_identity
    duration = float(identity.duration_minutes)

    timeline = list(bp.timeline)
    if not timeline:
        third = duration / 3
        timeline = [
            TimelineSegment(
                segment_id=f"ACT-{index:02d}",
                name=name,
                start_minute=start,
                end_minute=end,
                purpose=purpose,
                teacher_action=teacher_action,
                learner_action=learner_action,
                evidence_of_learning=evidence,
            )
            for index, (name, start, end, purpose, teacher_action, learner_action, evidence) in enumerate([
                ("情境导入", 0, third, "激活已有经验并明确任务", "提出真实情境问题", "观察、预测并表达已有认识", "给出初步判断"),
                ("核心建构", third, third * 2, "建立核心概念与方法", "示范关键推理过程", "记录关键关系并回答检查问题", "解释关键关系"),
                ("应用总结", third * 2, duration, "迁移应用并形成总结", "提供练习、反馈并总结", "独立完成任务并自评", "完成练习并说明依据"),
            ], start=1)
        ]

    # Re-index duplicate/missing segment IDs and normalize their durations to
    # the approved course length.  This also removes gaps/overlaps from model
    # generated timelines without changing their order or descriptions.
    lengths = [max(0.01, item.end_minute - item.start_minute) for item in timeline]
    length_total = sum(lengths)
    cursor = 0.0
    normalized_timeline: list[TimelineSegment] = []
    seen_segment_ids: set[str] = set()
    for index, (item, length) in enumerate(zip(timeline, lengths), start=1):
        segment_id = item.segment_id.strip() or f"ACT-{index:02d}"
        if segment_id in seen_segment_ids:
            segment_id = f"ACT-{index:02d}"
            while segment_id in seen_segment_ids:
                segment_id = f"ACT-{index:02d}-{len(seen_segment_ids) + 1}"
        seen_segment_ids.add(segment_id)
        start = cursor
        end = duration if index == len(timeline) else cursor + duration * length / length_total
        normalized_timeline.append(item.model_copy(update={
            "segment_id": segment_id,
            "start_minute": start,
            "end_minute": end,
        }))
        cursor = end

    knowledge_points = list(bp.knowledge_points)
    if not knowledge_points:
        knowledge_points = [KnowledgePoint(id="KP-01", name=f"{identity.title}核心概念")]
    normalized_knowledge_points: list[KnowledgePoint] = []
    seen_knowledge_ids: set[str] = set()
    for index, item in enumerate(knowledge_points, start=1):
        knowledge_id = item.id.strip() or f"KP-{index:02d}"
        if knowledge_id in seen_knowledge_ids:
            knowledge_id = f"KP-{index:02d}"
        seen_knowledge_ids.add(knowledge_id)
        normalized_knowledge_points.append(item.model_copy(update={"id": knowledge_id}))
    knowledge_ids = [item.id for item in normalized_knowledge_points]
    segment_ids = [item.segment_id for item in normalized_timeline]

    objectives = list(bp.objectives)
    if not objectives:
        objectives = [LearningObjective(
            id="OBJ-01", domain="knowledge", behavior="解释", condition="给出典型情境时",
            criterion=f"能准确说明{identity.title}的核心概念及适用条件",
            knowledge_point_ids=[knowledge_ids[0]], activity_ids=[segment_ids[0]], exercise_ids=["Q-01"],
        )]
    normalized_objectives: list[LearningObjective] = []
    seen_objective_ids: set[str] = set()
    for index, item in enumerate(objectives, start=1):
        objective_id = item.id.strip() or f"OBJ-{index:02d}"
        if objective_id in seen_objective_ids:
            objective_id = f"OBJ-{index:02d}"
        seen_objective_ids.add(objective_id)
        valid_knowledge = [ref for ref in item.knowledge_point_ids if ref in knowledge_ids]
        if not valid_knowledge:
            valid_knowledge = [knowledge_ids[(index - 1) % len(knowledge_ids)]]
        valid_activities = [ref for ref in item.activity_ids if ref in segment_ids]
        if not valid_activities:
            valid_activities = [segment_ids[(index - 1) % len(segment_ids)]]
        normalized_objectives.append(item.model_copy(update={
            "id": objective_id,
            "knowledge_point_ids": list(dict.fromkeys(valid_knowledge)),
            "activity_ids": list(dict.fromkeys(valid_activities)),
        }))

    objective_ids = [item.id for item in normalized_objectives]
    assessments = [item for item in bp.assessment_plan if item.objective_id in objective_ids]
    assessed = {item.objective_id for item in assessments}
    assessments.extend(
        AssessmentItem(
            objective_id=item.id,
            method="课堂检查",
            evidence="完成对应学习活动并给出可判定依据",
            criterion=item.criterion,
        )
        for item in normalized_objectives
        if item.id not in assessed
    )

    return bp.model_copy(update={
        "objectives": normalized_objectives,
        "knowledge_points": normalized_knowledge_points,
        "timeline": normalized_timeline,
        "assessment_plan": assessments,
        "key_points": bp.key_points or [f"{identity.title}核心概念与关键关系"],
        "difficulty_points": bp.difficulty_points or [f"在新情境中应用{identity.title}的方法"],
        "teaching_strategy": bp.teaching_strategy or ["情境驱动", "讲练结合"],
        "terminology": bp.terminology or {identity.title: f"本课核心主题：{identity.title}"},
    })


class BlueprintUpdate(BaseModel):
    content: CourseBlueprintSchema
    change_summary: str = "教师编辑"
