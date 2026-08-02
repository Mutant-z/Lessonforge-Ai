from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CourseStatus = Literal["draft", "requirement_review", "planning", "blueprint_generating", "blueprint_review", "resource_generating", "quality_checking", "teacher_review", "needs_attention", "completed", "failed", "archived"]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: str | None = None
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    email: str | None
    role: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=120)
    grade_level: str = Field(min_length=1, max_length=120)
    audience: str = Field(min_length=1)
    duration_minutes: int = Field(ge=1, le=300)
    scenario: str = Field(min_length=1, max_length=80)
    language: str = "中文"
    course_task: str = ""
    teaching_objectives: str = ""
    key_points: str = ""
    difficulty_points: str = ""
    teaching_method: str = ""
    style_requirements: str = ""
    raw_prompt: str = ""
    model_config_id: str | None = None


class CourseUpdate(BaseModel):
    title: str | None = None
    subject: str | None = None
    grade_level: str | None = None
    audience: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=300)
    scenario: str | None = None
    language: str | None = None
    status: CourseStatus | None = None
    settings_json: dict | None = None


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    subject: str
    grade_level: str
    audience: str
    duration_minutes: int
    scenario: str
    language: str
    status: str
    current_blueprint_version: int
    settings_json: dict
    model_config_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CourseList(BaseModel):
    items: list[CourseRead]
    total: int
