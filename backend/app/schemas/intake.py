from typing import Any, Literal

from pydantic import BaseModel, Field


REQUIRED_INTAKE_FIELDS = (
    "title",
    "subject",
    "grade_level",
    "audience",
    "duration_minutes",
    "scenario",
    "course_task",
)


class IntakeCreate(BaseModel):
    model_config_id: str | None = None


class IntakeModelUpdate(BaseModel):
    model_config_id: str


class IntakeDraft(BaseModel):
    title: str | None = None
    subject: str | None = None
    grade_level: str | None = None
    audience: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=300)
    scenario: str | None = None
    language: str | None = None
    course_task: str | None = None
    teaching_objectives: str | None = None
    key_points: str | None = None
    difficulty_points: str | None = None
    teaching_method: str | None = None
    style_requirements: str | None = None


class RequirementAssumption(BaseModel):
    field: str
    value: Any
    reason: str


class RequirementConflict(BaseModel):
    field: str
    severity: Literal["warning", "blocking"] = "warning"
    description: str
    suggestion: str = ""


class RequirementAnalysisResult(BaseModel):
    draft: IntakeDraft
    field_sources: dict[str, Literal["user", "material", "manual", "assumption"]] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    assumptions: list[RequirementAssumption] = Field(default_factory=list)
    conflicts: list[RequirementConflict] = Field(default_factory=list)
    next_question: str = ""
    ready_to_confirm: bool = False


class IntakeMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    expected_revision: int = Field(ge=0)


class IntakeDraftPatch(BaseModel):
    field: str
    value: Any
    expected_revision: int = Field(ge=0)


class IntakeConfirm(BaseModel):
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class IntakeRead(BaseModel):
    id: str
    status: str
    current_revision: int
    draft: dict[str, Any]
    field_sources: dict[str, Any]
    missing_fields: list[str]
    assumptions: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    course_id: str | None
    active_turn_id: str | None = None
    model_config_id: str | None = None
    last_failure: dict[str, Any] | None = None
