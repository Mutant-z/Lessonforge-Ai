from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


TaskType = Literal["lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim"]


class AgentProfileSummary(BaseModel):
    mission: str
    audience: str
    task_goals: list[str]
    knowledge_focus: list[str]
    style_guidelines: list[str]
    hard_constraints: list[str]
    quality_focus: list[str]


class AgentProfileBase(BaseModel):
    task_type: TaskType
    mission: str
    responsibility_boundary: str
    project_background: str
    learner_profile: list[str]
    prior_knowledge: list[str]
    teaching_scenario: str
    task_goals: list[str]
    knowledge_focus: list[str]
    likely_misconceptions: list[str]
    pedagogy_guidelines: list[str]
    style_guidelines: list[str]
    content_scope: list[str]
    hard_constraints: list[str]
    required_source_refs: list[str] = Field(default_factory=list)
    project_requirement_summary: list[str] = Field(default_factory=list)
    material_summaries: list[str] = Field(default_factory=list)
    output_focus: list[str]
    quality_checklist: list[str]
    upstream_usage: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_specialized_content(self):
        required_lists = (
            self.learner_profile, self.task_goals, self.knowledge_focus,
            self.hard_constraints, self.output_focus, self.quality_checklist,
        )
        if not all(required_lists):
            raise ValueError(f"{self.task_type} 的专属配置缺少必要内容")
        return self

    def summary(self, audience: str) -> AgentProfileSummary:
        return AgentProfileSummary(
            mission=self.mission,
            audience=audience,
            task_goals=self.task_goals,
            knowledge_focus=self.knowledge_focus,
            style_guidelines=self.style_guidelines,
            hard_constraints=self.hard_constraints,
            quality_focus=self.quality_checklist,
        )


class LessonPlanProfile(AgentProfileBase):
    task_type: Literal["lesson_plan"]
    alignment_requirements: list[str]
    timeline_requirements: list[str]
    board_and_homework_requirements: list[str]


class PPTProfile(AgentProfileBase):
    task_type: Literal["ppt"]
    narrative_requirements: list[str]
    visual_hierarchy_requirements: list[str]
    information_density_requirements: list[str]
    animation_and_diagram_requirements: list[str]
    layout_requirements: list[str]
    typography_requirements: list[str]
    visual_suggestion_requirements: list[str]


class TaskSheetProfile(AgentProfileBase):
    task_type: Literal["task_sheet"]
    learner_action_requirements: list[str]
    deliverable_requirements: list[str]
    scaffolding_requirements: list[str]
    objective_evidence_alignment_requirements: list[str]
    lesson_plan_reference_requirements: list[str]
    recording_space_requirements: list[str]
    student_language_requirements: list[str]
    exercise_boundary_requirements: list[str]


class ExerciseProfile(AgentProfileBase):
    task_type: Literal["exercise"]
    objective_coverage_requirements: list[str]
    question_mix_requirements: list[str]
    difficulty_requirements: list[str]
    explanation_requirements: list[str]
    objective_evidence_alignment_requirements: list[str]
    lesson_plan_reference_requirements: list[str]
    task_sheet_non_reuse_requirements: list[str]
    section_and_scoring_requirements: list[str]
    printable_answer_space_requirements: list[str]
    visual_stimulus_requirements: list[str]
    review_and_repair_requirements: list[str]


class VideoScriptProfile(AgentProfileBase):
    task_type: Literal["video_script"]
    objective_alignment_requirements: list[str]
    narrative_arc_requirements: list[str]
    segmentation_requirements: list[str]
    continuity_requirements: list[str]
    visual_prompt_requirements: list[str]
    native_audio_requirements: list[str]
    fact_qa_requirements: list[str]
    negative_constraint_requirements: list[str]
    timing_and_pacing_requirements: list[str]
    cost_control_requirements: list[str]
    verbatim_handoff_requirements: list[str]
    review_and_repair_requirements: list[str]


class VerbatimProfile(AgentProfileBase):
    task_type: Literal["verbatim"]
    speaking_style_requirements: list[str]
    interaction_requirements: list[str]
    required_optional_requirements: list[str]
    timing_requirements: list[str]


SpecializedAgentProfile = Annotated[
    LessonPlanProfile | PPTProfile | TaskSheetProfile | ExerciseProfile | VideoScriptProfile | VerbatimProfile,
    Field(discriminator="task_type"),
]
class AgentInitializationBundle(BaseModel):
    profiles: list[SpecializedAgentProfile]

    @model_validator(mode="after")
    def exactly_six_profiles(self):
        expected = {"lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim"}
        actual = [profile.task_type for profile in self.profiles]
        if len(actual) != 6 or set(actual) != expected:
            raise ValueError("Agent 初始化配置必须恰好包含六种任务类型")
        for profile in self.profiles:
            for field_name, value in profile.model_dump().items():
                if field_name.endswith("_requirements") and isinstance(value, list) and not value:
                    raise ValueError(f"{profile.task_type}.{field_name} 不能为空")
        return self
