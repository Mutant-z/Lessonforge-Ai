from typing import Literal

from pydantic import BaseModel, Field


class LessonStage(BaseModel):
    id: str
    title: str
    duration_minutes: float
    teacher_activity: str
    learner_activity: str
    design_intent: str
    assessment: str


class LessonPlanContent(BaseModel):
    content_analysis: str
    learner_analysis: str
    objectives: list[str]
    key_points: list[str]
    difficulty_points: list[str]
    methods: list[str]
    resources: list[str]
    stages: list[LessonStage]
    board_design: str
    homework: str
    reflection_placeholder: str = "课后由教师填写教学反思。"


class Slide(BaseModel):
    id: str
    page_type: Literal["cover", "objectives", "scenario", "concept", "process", "comparison", "case", "question", "exercise", "summary", "homework"]
    title: str
    purpose: str
    body: list[str]
    layout: str
    visual_suggestion: str
    speaker_notes: str
    duration_seconds: int
    script_segment_ids: list[str] = []


class PPTContent(BaseModel):
    theme: str = "lessonforge_swiss_blue"
    slides: list[Slide]


class LearningTask(BaseModel):
    id: str
    action: str
    object: str
    output: str
    completion_criterion: str


class TaskSheetContent(BaseModel):
    learning_objectives: list[str]
    preparation: list[str]
    tasks: list[LearningTask]
    observation_prompts: list[str]
    learning_questions: list[str]
    self_assessment: list[str]
    extension: list[str]


class ExerciseItem(BaseModel):
    id: str
    question_type: Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "case_analysis", "practice"]
    stem: str
    options: list[str] = []
    correct_answers: list[str]
    explanation: str
    difficulty: Literal["basic", "intermediate", "advanced"]
    objective_ids: list[str]
    knowledge_point_ids: list[str]
    estimated_minutes: float
    source_refs: list[str] = []


class ExerciseContent(BaseModel):
    items: list[ExerciseItem]


class ScriptSegment(BaseModel):
    id: str
    time_range: str
    stage: str
    slide_ids: list[str]
    visual: str
    narration: str
    action: str
    on_screen_text: str
    pause: str
    production_notes: str


class VideoScriptContent(BaseModel):
    segments: list[ScriptSegment]


class VerbatimSection(BaseModel):
    id: str
    slide_ids: list[str]
    time_range: str
    required_text: str
    optional_text: str
    interaction: str


class VerbatimContent(BaseModel):
    speaking_rate: str = "standard"
    sections: list[VerbatimSection]


class ArtifactUpdate(BaseModel):
    content_json: dict
    content_markdown: str
    change_summary: str = "教师编辑"


class RegenerateRequest(BaseModel):
    path: str = ""
    instruction: str = Field(min_length=1)
    preserve_locked_content: bool = True


class AgentChatModelUpdate(BaseModel):
    model_config_id: str


class AgentArtifactRevision(BaseModel):
    content_json: dict
    content_markdown: str = Field(min_length=1)
    assistant_reply: str = Field(min_length=1, max_length=1000)


class QualityReportContent(BaseModel):
    score: int = Field(ge=0, le=100)
    summary: str
    issues: list[dict]


class CitationReportContent(BaseModel):
    source_refs: list[str]


class LockRequest(BaseModel):
    json_path: str
