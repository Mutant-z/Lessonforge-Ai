from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


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


class PPTLead(BaseModel):
    """开篇结论/引导块：大字 + 可选副行。"""
    kind: Literal["lead"] = "lead"
    text: str
    sub: str = ""


class PPTBulletItem(BaseModel):
    text: str
    emphasize: bool = False


class PPTBulletsBlock(BaseModel):
    """要点列表：圆点或编号；emphasize 项渲染为主色高亮。"""
    kind: Literal["bullets"] = "bullets"
    items: list[PPTBulletItem]
    numbered: bool = False


class PPTStep(BaseModel):
    title: str
    detail: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_text_detail(cls, value):
        """Normalize the field name older/model-authored patches used.

        ``detail`` remains the canonical wire/storage field.  Accepting
        ``text`` here prevents otherwise valid step copy from being silently
        discarded by Pydantic's default extra-field handling.
        """
        if isinstance(value, dict) and "detail" not in value and "text" in value:
            value = {**value, "detail": value.get("text")}
        return value


class PPTStepsBlock(BaseModel):
    """递进步骤卡片：编号 + 标题 + 细节。"""
    kind: Literal["steps"] = "steps"
    steps: list[PPTStep]


class PPTCompareColumn(BaseModel):
    heading: str = ""
    items: list[str]


class PPTCompareBlock(BaseModel):
    """左右对比分栏：两栏各含标题与要点。"""
    kind: Literal["compare"] = "compare"
    left: PPTCompareColumn
    right: PPTCompareColumn


class PPTQuoteBlock(BaseModel):
    """重点引用/待判断句：大字 + 出处。"""
    kind: Literal["quote"] = "quote"
    text: str
    citation: str = ""


class PPTVisualBlock(BaseModel):
    """视觉元素占位：图示类型或图片引用，渲染为图示区。"""
    kind: Literal["visual"] = "visual"
    diagram: Literal["flow", "comparison", "causality", "hierarchy", "data_change"] | None = None
    image_id: str | None = None
    caption: str = ""
    alt_text: str = ""


class PPTNoteBlock(BaseModel):
    """小字注释/提示。"""
    kind: Literal["note"] = "note"
    text: str


PPTBlock = Annotated[
    PPTLead | PPTBulletsBlock | PPTStepsBlock | PPTCompareBlock | PPTQuoteBlock | PPTVisualBlock | PPTNoteBlock,
    Field(discriminator="kind"),
]


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
    blocks: list[PPTBlock] = []
    render_mode: Literal["semantic", "hybrid", "absolute"] | None = None
    # Persist agentic geometry so later local revisions start from the actual
    # edited page instead of losing the LLM-designed layout.
    elements: list[dict[str, Any]] = []


class PPTContent(BaseModel):
    theme: str = "lessonforge_deck_academic"
    slides: list[Slide]



class TaskSheetCourseInfo(BaseModel):
    course_title: str = Field(min_length=1)
    subject: str = ""
    grade_level: str = ""
    audience: str = ""
    duration_minutes: float = Field(gt=0)


class TaskSheetObjective(BaseModel):
    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    success_criterion: str = Field(min_length=1)


class TaskRecordTable(BaseModel):
    title: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    columns: list[str] = Field(min_length=2)
    blank_rows: int = Field(default=3, ge=1, le=12)


class LearningTask(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    phase: Literal["pre_class", "in_class", "after_class"]
    stage_id: str | None = None
    objective_ids: list[str] = Field(min_length=1)
    knowledge_point_ids: list[str] = Field(min_length=1)
    action: str = Field(min_length=1)
    object: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    student_output: str = Field(min_length=1)
    completion_criterion: str = Field(min_length=1)
    estimated_minutes: float = Field(gt=0)
    collaboration_mode: Literal["individual", "pair", "group", "whole_class"] = "individual"
    scaffolds: list[str] = Field(default_factory=list)
    record_table: TaskRecordTable | None = None

    @model_validator(mode="after")
    def require_in_class_stage(self):
        if self.phase == "in_class" and not self.stage_id:
            raise ValueError("课中任务必须映射到蓝图教学环节")
        return self


class TaskSheetQuestion(BaseModel):
    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    objective_ids: list[str] = Field(min_length=1)
    stage_id: str = Field(min_length=1)


class TaskSheetSelfAssessment(BaseModel):
    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    objective_ids: list[str] = Field(min_length=1)


class TaskSheetContent(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    course_info: TaskSheetCourseInfo
    learning_objectives: list[TaskSheetObjective] = Field(min_length=1)
    preparation: list[str]
    tasks: list[LearningTask] = Field(min_length=1)
    record_table: TaskRecordTable | None = None
    learning_questions: list[TaskSheetQuestion]
    self_assessment_scale: list[str] = Field(
        default_factory=lambda: ["尚未做到", "基本做到", "能够做到"],
        min_length=2,
    )
    self_assessment: list[TaskSheetSelfAssessment] = Field(min_length=1)
    extension: list[str]


class LegacyExerciseItem(BaseModel):
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


class LegacyExerciseContent(BaseModel):
    items: list[LegacyExerciseItem]


class ExerciseCourseInfo(BaseModel):
    course_title: str = Field(min_length=1)
    subject: str = ""
    grade_level: str = ""
    audience: str = ""
    duration_minutes: float = Field(gt=0)


class ExercisePaperSettings(BaseModel):
    title: str = Field(min_length=1)
    student_instructions: list[str] = Field(min_length=1)
    total_score: int = Field(default=100, ge=1, le=1000)
    estimated_minutes: float = Field(gt=0)
    answer_requirements: str = Field(min_length=1)


class ExerciseOption(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ExerciseAnswerKey(BaseModel):
    correct_option_ids: list[str] = Field(default_factory=list)
    accepted_answers: list[str] = Field(default_factory=list)
    reference_answer: str = ""


class ExerciseScoringPoint(BaseModel):
    id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    points: int = Field(gt=0)
    acceptable_evidence: str = Field(min_length=1)


class ExerciseAnswerSpace(BaseModel):
    mode: Literal["none", "lines", "grid", "table"] = "lines"
    lines: int = Field(default=2, ge=0, le=30)
    columns: list[str] = Field(default_factory=list)
    blank_rows: int = Field(default=0, ge=0, le=20)


class ExerciseVisual(BaseModel):
    visual_id: str = Field(min_length=1)
    mode: Literal["generated_image", "deterministic_diagram"]
    purpose: str = Field(min_length=1)
    alt_text: str = Field(min_length=1)
    caption: str = ""
    fallback_stimulus: str = Field(min_length=1)
    generation_prompt: str = ""
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1536x1024"
    diagram_type: Literal["coordinate", "force", "geometry", "flow"] | None = None
    diagram_spec: dict = Field(default_factory=dict)
    asset_id: str | None = None
    status: Literal["requested", "generating", "reviewing", "approved", "degraded"] = "requested"
    provider: str = ""
    model_name: str = ""
    review_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_visual_mode(self):
        if self.mode == "generated_image" and not self.generation_prompt:
            raise ValueError("生成式图片必须提供 generation_prompt")
        if self.mode == "deterministic_diagram" and not self.diagram_type:
            raise ValueError("确定性图示必须提供 diagram_type")
        return self


class ExerciseStimulus(BaseModel):
    id: str = Field(min_length=1)
    kind: Literal["text", "table", "visual"]
    title: str = ""
    text: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    visual: ExerciseVisual | None = None

    @model_validator(mode="after")
    def validate_stimulus(self):
        if self.kind == "text" and not self.text:
            raise ValueError("文本材料不能为空")
        if self.kind == "table" and (not self.columns or not self.rows):
            raise ValueError("表格材料必须包含列名和数据行")
        if self.kind == "table" and any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("表格材料每行列数必须一致")
        if self.kind == "visual" and not self.visual:
            raise ValueError("视觉材料必须提供 visual")
        return self


OBJECTIVE_QUESTION_TYPES = {"single_choice", "multiple_choice", "true_false", "fill_blank"}
SUBJECTIVE_QUESTION_TYPES = {"short_answer", "calculation", "case_analysis", "practical_task"}


class ExerciseQuestion(BaseModel):
    kind: Literal["question"] = "question"
    id: str = Field(min_length=1)
    question_type: Literal[
        "single_choice", "multiple_choice", "true_false", "fill_blank",
        "short_answer", "calculation", "case_analysis", "practical_task",
    ]
    stem: str = Field(min_length=1)
    options: list[ExerciseOption] = Field(default_factory=list)
    score: int = Field(gt=0)
    estimated_minutes: float = Field(gt=0)
    objective_ids: list[str] = Field(min_length=1)
    knowledge_point_ids: list[str] = Field(min_length=1)
    source_refs: list[str] = Field(default_factory=list)
    difficulty: Literal["basic", "intermediate", "advanced"]
    cognitive_level: Literal["remember", "understand", "apply", "analyze", "transfer", "evaluate", "create"]
    answer_key: ExerciseAnswerKey
    analysis: str = Field(min_length=1)
    scoring_points: list[ExerciseScoringPoint] = Field(default_factory=list)
    answer_space: ExerciseAnswerSpace = Field(default_factory=ExerciseAnswerSpace)
    common_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_question_contract(self):
        option_ids = [item.id for item in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("选项 ID 不能重复")
        if self.question_type in {"single_choice", "multiple_choice"} and len(self.options) < 2:
            raise ValueError("选择题至少需要两个选项")
        if self.question_type == "single_choice" and len(self.answer_key.correct_option_ids) != 1:
            raise ValueError("单选题必须且只能有一个正确选项")
        if self.question_type == "multiple_choice" and len(self.answer_key.correct_option_ids) < 2:
            raise ValueError("多选题至少需要两个正确选项")
        if any(item not in option_ids for item in self.answer_key.correct_option_ids):
            raise ValueError("答案引用了不存在的选项")
        if self.question_type in SUBJECTIVE_QUESTION_TYPES:
            if not self.answer_key.reference_answer:
                raise ValueError("主观题必须提供参考答案")
            if not self.scoring_points:
                raise ValueError("主观题必须提供分步评分点")
            if sum(item.points for item in self.scoring_points) != self.score:
                raise ValueError("主观题评分点分值之和必须等于题目分值")
        if self.question_type == "fill_blank" and not (
            self.answer_key.accepted_answers or self.answer_key.reference_answer
        ):
            raise ValueError("填空题必须提供可接受答案")
        return self


class ExerciseQuestionGroup(BaseModel):
    kind: Literal["question_group"] = "question_group"
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    instructions: str = ""
    stimuli: list[ExerciseStimulus] = Field(min_length=1)
    sub_questions: list[ExerciseQuestion] = Field(min_length=1)


ExerciseBlock = Annotated[ExerciseQuestion | ExerciseQuestionGroup, Field(discriminator="kind")]


class ExerciseSection(BaseModel):
    id: Literal["basic_consolidation", "understanding_application", "transfer_challenge"]
    title: str = Field(min_length=1)
    score: int = Field(gt=0)
    blocks: list[ExerciseBlock] = Field(min_length=1)


class ExerciseReviewSummary(BaseModel):
    rules_status: Literal["pending", "passed", "needs_attention"] = "pending"
    text_review_status: Literal["pending", "passed", "needs_attention"] = "pending"
    visual_review_status: Literal["not_required", "pending", "passed", "degraded", "needs_attention"] = "not_required"
    needs_teacher_attention: bool = False
    notes: list[str] = Field(default_factory=list)


class ExerciseContent(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    course_info: ExerciseCourseInfo
    paper_settings: ExercisePaperSettings
    sections: list[ExerciseSection] = Field(min_length=3, max_length=3)
    review_summary: ExerciseReviewSummary = Field(default_factory=ExerciseReviewSummary)

    @model_validator(mode="after")
    def validate_paper_totals(self):
        expected = ["basic_consolidation", "understanding_application", "transfer_challenge"]
        if [section.id for section in self.sections] != expected:
            raise ValueError("练习分区必须按基础巩固、理解应用、迁移挑战排序")
        if sum(section.score for section in self.sections) != self.paper_settings.total_score:
            raise ValueError("分区分值之和必须等于试卷总分")
        for section in self.sections:
            questions = []
            for block in section.blocks:
                questions.extend(block.sub_questions if isinstance(block, ExerciseQuestionGroup) else [block])
            if sum(question.score for question in questions) != section.score:
                raise ValueError(f"{section.id} 的题目分值之和必须等于分区分值")
        return self


class ScriptSegment(BaseModel):
    """Legacy V1 video-script segment kept for historical artifact reads."""

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


class LegacyVideoScriptContent(BaseModel):
    segments: list[ScriptSegment]


class VideoScriptCourseInfo(BaseModel):
    course_title: str = Field(min_length=1)
    subject: str = ""
    grade_level: str = ""
    audience: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)


class VideoProductionSettings(BaseModel):
    mode: Literal["ppt_screen_recording"] = "ppt_screen_recording"
    aspect_ratio: Literal["16:9"] = "16:9"
    target_duration_seconds: int = Field(gt=0)
    narration_chars_per_minute: int = Field(default=220, ge=120, le=360)
    subtitle_max_chars_per_line: int = Field(default=18, ge=8, le=30)
    subtitle_max_lines: int = Field(default=2, ge=1, le=3)


class AnimationCue(BaseModel):
    offset_seconds: float = Field(ge=0)
    target: str = Field(min_length=1)
    action: Literal["显示", "高亮", "缩放", "平移", "标注", "转场"]
    instruction: str = Field(min_length=1)


class PauseCue(BaseModel):
    offset_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0, le=30)
    purpose: str = Field(min_length=1)


class SoundCue(BaseModel):
    offset_seconds: float = Field(ge=0)
    description: str = Field(min_length=1)


class SubtitleChunk(BaseModel):
    start_offset_seconds: float = Field(ge=0)
    end_offset_seconds: float = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_offset_seconds <= self.start_offset_seconds:
            raise ValueError("字幕结束时间必须晚于开始时间")
        return self


class VideoVisualTrack(BaseModel):
    composition: str = Field(min_length=1)
    animation_cues: list[AnimationCue] = Field(default_factory=list)


PedagogicalActionType = Literal[
    "hook",
    "objective_guide",
    "scenario_connect",
    "metaphor_explain",
    "misconception_alert",
    "step_demonstration",
    "check_in",
    "summary_recap",
]


class VideoAudioTrack(BaseModel):
    narration_text: str = Field(min_length=1)
    pedagogical_action: PedagogicalActionType | None = None
    delivery_tone: str = Field(min_length=1)
    speaking_rate_cps: float = Field(default=4.0, gt=0)
    emphasis_terms: list[str] = Field(default_factory=list)
    pause_cues: list[PauseCue] = Field(default_factory=list)
    sound_cues: list[SoundCue] = Field(default_factory=list)


class VideoTextTrack(BaseModel):
    on_screen_text: list[str] = Field(default_factory=list)
    subtitle_chunks: list[SubtitleChunk] = Field(min_length=1)


class VideoInteraction(BaseModel):
    prompt: str = Field(min_length=1)
    wait_seconds: float = Field(gt=0, le=30)
    expected_response: str = Field(min_length=1)
    feedback_transition: str = Field(min_length=1)


class VideoScene(BaseModel):
    id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    title: str = Field(min_length=1)
    pedagogical_role: Literal["导入", "目标", "情境", "概念讲解", "示范", "练习", "检查点", "总结", "过渡"]
    lesson_stage_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    objective_ids: list[str] = Field(min_length=1)
    knowledge_point_ids: list[str] = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    learning_purpose: str = Field(min_length=1)
    visual_track: VideoVisualTrack
    audio_track: VideoAudioTrack
    text_track: VideoTextTrack
    interaction: VideoInteraction | None = None
    production_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scene_timing(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("分镜结束时间必须晚于开始时间")
        duration = self.end_seconds - self.start_seconds
        for cue in self.visual_track.animation_cues:
            if cue.offset_seconds > duration:
                raise ValueError("动效提示超出分镜时长")
        for cue in self.audio_track.pause_cues:
            if cue.offset_seconds + cue.duration_seconds > duration + 0.01:
                raise ValueError("停顿提示超出分镜时长")
        for cue in self.audio_track.sound_cues:
            if cue.offset_seconds > duration:
                raise ValueError("音效提示超出分镜时长")
        previous_end = 0.0
        for cue in self.text_track.subtitle_chunks:
            if cue.start_offset_seconds < previous_end - 0.01:
                raise ValueError("字幕时间不得重叠或倒序")
            if cue.end_offset_seconds > duration + 0.01:
                raise ValueError("字幕提示超出分镜时长")
            previous_end = cue.end_offset_seconds
        if self.interaction and self.interaction.wait_seconds > duration:
            raise ValueError("互动等待时间不得超过分镜时长")
        return self


class VideoScriptContent(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    course_info: VideoScriptCourseInfo
    production_settings: VideoProductionSettings
    scenes: list[VideoScene] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timeline(self):
        if self.production_settings.target_duration_seconds != self.course_info.duration_seconds:
            raise ValueError("制作目标时长必须与课程时长一致")
        ids = [scene.id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("分镜 ID 不能重复")
        if [scene.sequence for scene in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("分镜顺序号必须从 1 连续递增")
        if abs(self.scenes[0].start_seconds) > 1:
            raise ValueError("视频时间轴必须从 0 秒开始")
        previous_end = self.scenes[0].start_seconds
        for scene in self.scenes:
            if scene.start_seconds < previous_end - 0.01:
                raise ValueError("分镜时间不得重叠或倒序")
            if scene.start_seconds - previous_end > 1:
                raise ValueError("分镜之间不得出现超过 1 秒的空档")
            previous_end = scene.end_seconds
        if abs(previous_end - self.production_settings.target_duration_seconds) > 1:
            raise ValueError("分镜总时长必须与制作目标时长一致")
        return self


class VerbatimSection(BaseModel):
    id: str
    scene_id: str | None = None
    slide_ids: list[str]
    time_range: str
    pedagogical_action: PedagogicalActionType | None = None
    required_text: str
    optional_text: str
    key_emphasis: list[str] = Field(default_factory=list)
    word_count: int | None = None
    estimated_duration_seconds: float | None = None
    interaction: str


class VerbatimContent(BaseModel):
    speaking_rate: str = "standard"
    sections: list[VerbatimSection]


class ArtifactUpdate(BaseModel):
    content_json: dict
    content_markdown: str
    change_summary: str = "教师编辑"


class PPTTemplateApplyRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


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


class AgentArtifactRevisionPayload(BaseModel):
    """Compact model response; Markdown is rendered after content validation."""

    content_json: dict
    assistant_reply: str = Field(min_length=1, max_length=1000)


class QualityReportContent(BaseModel):
    score: int = Field(ge=0, le=100)
    summary: str
    issues: list[dict]


class CitationReportContent(BaseModel):
    source_refs: list[str]


class LockRequest(BaseModel):
    json_path: str
