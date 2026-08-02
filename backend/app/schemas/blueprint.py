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


class BlueprintUpdate(BaseModel):
    content: CourseBlueprintSchema
    change_summary: str = "教师编辑"

