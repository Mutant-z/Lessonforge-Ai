export interface Artifact {
  id: string;
  course_id: string;
  artifact_type: string;
  version: number;
  blueprint_version: number;
  content_json: any;
  content_markdown: string;
  status: string;
  is_locked: boolean;
  change_summary?: string;
  source_versions_json?: Record<string, number>;
  agent_profile_id?: string | null;
  created_at: string;
}

export interface LessonPlanContent {
  course_title: string;
  grade_level: string;
  subject: string;
  duration_minutes: number;
  student_analysis: string;
  objectives: string[];
  key_points: string[];
  difficulty_points: string[];
  activities: Array<{
    stage: string;
    duration_minutes: number;
    teacher_activity: string;
    student_activity: string;
    design_intent: string;
    assessment: string;
  }>;
  assessment_plan: string;
  board_design: string;
  reflection_notes: string;
}

export interface PPTBulletItem {
  text: string;
  emphasize?: boolean;
}
export interface PPTLeadBlock {
  kind: 'lead';
  text: string;
  sub?: string;
}
export interface PPTBulletsBlock {
  kind: 'bullets';
  items: PPTBulletItem[];
  numbered?: boolean;
}
export interface PPTStep {
  title: string;
  detail?: string;
}
export interface PPTStepsBlock {
  kind: 'steps';
  steps: PPTStep[];
}
export interface PPTCompareColumn {
  heading?: string;
  items: string[];
}
export interface PPTCompareBlock {
  kind: 'compare';
  left: PPTCompareColumn;
  right: PPTCompareColumn;
}
export interface PPTQuoteBlock {
  kind: 'quote';
  text: string;
  citation?: string;
}
export interface PPTVisualBlock {
  kind: 'visual';
  diagram?: string;
  image_id?: string;
  caption?: string;
  alt_text?: string;
}
export interface PPTNoteBlock {
  kind: 'note';
  text: string;
}
export type PPTBlock =
  | PPTLeadBlock
  | PPTBulletsBlock
  | PPTStepsBlock
  | PPTCompareBlock
  | PPTQuoteBlock
  | PPTVisualBlock
  | PPTNoteBlock;

export interface PPTLayoutElement {
  id?: string;
  kind: 'textbox' | 'shape' | 'image' | 'chart';
  role?: string;
  text?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  z?: number;
  style?: Record<string, unknown>;
  shape_type?: string;
  fill?: string | null;
  line?: string | null;
  file_path?: string;
  asset_path?: string;
  asset_id?: string;
  provider?: string;
  degraded?: boolean;
  content_ref?: string;
  visual_slot?: string;
}

export interface PPTSlide {
  id?: string;
  slide_number?: number;
  page_type?: string;
  title: string;
  purpose?: string;
  layout_type?: string;
  layout?: string;
  bullet_points?: string[];
  body?: string[];
  visual_suggestion: string;
  speaker_notes: string;
  duration_seconds?: number;
  blocks?: PPTBlock[];
  elements?: PPTLayoutElement[];
  render_mode?: 'semantic' | 'hybrid' | 'absolute';
}

export interface PPTContent {
  theme: string;
  slides: PPTSlide[];
}

export interface PPTTemplatePalette {
  background: string;
  surface: string;
  primary: string;
  secondary: string;
  text: string;
  muted: string;
  on_primary: string;
}

export interface PPTTemplateTypography {
  heading: string;
  body: string;
  latin: string;
}

export interface PPTTemplate {
  id: string;
  name: string;
  short_name: string;
  description: string;
  recommended_for: string[];
  composition: 'swiss_rail' | 'nordic_field' | 'academic_offset' | 'editorial_margin' | 'science_signal' | 'primary_blocks' | 'deck';
  palette: PPTTemplatePalette;
  typography: PPTTemplateTypography;
}

export interface PPTTemplateCatalog {
  version: string;
  templates: PPTTemplate[];
}

export type TaskSheetPhase = 'pre_class' | 'in_class' | 'after_class';
export type TaskSheetCollaboration = 'individual' | 'pair' | 'group' | 'whole_class';

export interface TaskSheetCourseInfo {
  course_title: string;
  subject: string;
  grade_level: string;
  audience: string;
  duration_minutes: number;
}

export interface TaskSheetObjective {
  id: string;
  statement: string;
  success_criterion: string;
}

export interface TaskRecordTable {
  title: string;
  instructions: string;
  columns: string[];
  blank_rows: number;
}

export interface TaskSheetTask {
  id: string;
  title: string;
  phase: TaskSheetPhase;
  stage_id?: string | null;
  objective_ids: string[];
  knowledge_point_ids: string[];
  action: string;
  object: string;
  steps: string[];
  student_output: string;
  completion_criterion: string;
  estimated_minutes: number;
  collaboration_mode: TaskSheetCollaboration;
  scaffolds: string[];
  record_table?: TaskRecordTable | null;
}

export interface TaskSheetQuestion {
  id: string;
  prompt: string;
  objective_ids: string[];
  stage_id: string;
}

export interface TaskSheetSelfAssessment {
  id: string;
  statement: string;
  objective_ids: string[];
}

export interface TaskSheetContent {
  schema_version: '2.0';
  course_info: TaskSheetCourseInfo;
  learning_objectives: TaskSheetObjective[];
  preparation: string[];
  tasks: TaskSheetTask[];
  record_table?: TaskRecordTable | null;
  learning_questions: TaskSheetQuestion[];
  self_assessment_scale: string[];
  self_assessment: TaskSheetSelfAssessment[];
  extension: string[];
}

export type ExerciseQuestionType = 'single_choice' | 'multiple_choice' | 'true_false' | 'fill_blank' | 'short_answer' | 'calculation' | 'case_analysis' | 'practical_task';
export type ExerciseCognitiveLevel = 'remember' | 'understand' | 'apply' | 'analyze' | 'transfer' | 'evaluate' | 'create';

export interface ExerciseOption {
  id: string;
  text: string;
}

export interface ExerciseScoringPoint {
  id: string;
  criterion: string;
  points: number;
  acceptable_evidence: string;
}

export interface ExerciseVisual {
  visual_id: string;
  mode: 'generated_image' | 'deterministic_diagram';
  purpose: string;
  alt_text: string;
  caption: string;
  fallback_stimulus: string;
  generation_prompt: string;
  size: '1024x1024' | '1536x1024' | '1024x1536';
  diagram_type?: 'coordinate' | 'force' | 'geometry' | 'flow' | null;
  diagram_spec: Record<string, unknown>;
  asset_id?: string | null;
  status: 'requested' | 'generating' | 'reviewing' | 'approved' | 'degraded';
  provider: string;
  model_name: string;
  review_notes: string[];
}

export interface ExerciseStimulus {
  id: string;
  kind: 'text' | 'table' | 'visual';
  title: string;
  text: string;
  columns: string[];
  rows: string[][];
  visual?: ExerciseVisual | null;
}

export interface ExerciseQuestion {
  kind: 'question';
  id: string;
  question_type: ExerciseQuestionType;
  stem: string;
  options: ExerciseOption[];
  score: number;
  estimated_minutes: number;
  objective_ids: string[];
  knowledge_point_ids: string[];
  source_refs: string[];
  difficulty: 'basic' | 'intermediate' | 'advanced';
  cognitive_level: ExerciseCognitiveLevel;
  answer_key: {
    correct_option_ids: string[];
    accepted_answers: string[];
    reference_answer: string;
  };
  analysis: string;
  scoring_points: ExerciseScoringPoint[];
  answer_space: {
    mode: 'none' | 'lines' | 'grid' | 'table';
    lines: number;
    columns: string[];
    blank_rows: number;
  };
  common_errors: string[];
}

export interface ExerciseQuestionGroup {
  kind: 'question_group';
  id: string;
  title: string;
  instructions: string;
  stimuli: ExerciseStimulus[];
  sub_questions: ExerciseQuestion[];
}

export interface ExerciseContent {
  schema_version: '2.0';
  course_info: {
    course_title: string;
    subject: string;
    grade_level: string;
    audience: string;
    duration_minutes: number;
  };
  paper_settings: {
    title: string;
    student_instructions: string[];
    total_score: number;
    estimated_minutes: number;
    answer_requirements: string;
  };
  sections: Array<{
    id: 'basic_consolidation' | 'understanding_application' | 'transfer_challenge';
    title: string;
    score: number;
    blocks: Array<ExerciseQuestion | ExerciseQuestionGroup>;
  }>;
  review_summary: {
    rules_status: 'pending' | 'passed' | 'needs_attention';
    text_review_status: 'pending' | 'passed' | 'needs_attention';
    visual_review_status: 'not_required' | 'pending' | 'passed' | 'degraded' | 'needs_attention';
    needs_teacher_attention: boolean;
    notes: string[];
  };
}

export type VideoPedagogicalRole = '导入' | '目标' | '情境' | '概念讲解' | '示范' | '练习' | '检查点' | '总结' | '过渡';
export type VideoPedagogicalAction =
  | 'hook' | 'objective_guide' | 'scenario_connect' | 'metaphor_explain'
  | 'misconception_alert' | 'step_demonstration' | 'check_in' | 'summary_recap';
export type VideoAnimationAction = '显示' | '高亮' | '缩放' | '平移' | '标注' | '转场';

export interface VideoAnimationCue {
  offset_seconds: number;
  target: string;
  action: VideoAnimationAction;
  instruction: string;
}

export interface VideoPauseCue {
  offset_seconds: number;
  duration_seconds: number;
  purpose: string;
}

export interface VideoSoundCue {
  offset_seconds: number;
  description: string;
}

export interface VideoSubtitleChunk {
  start_offset_seconds: number;
  end_offset_seconds: number;
  text: string;
}

export interface VideoInteraction {
  prompt: string;
  wait_seconds: number;
  expected_response: string;
  feedback_transition: string;
}

export interface VideoScene {
  id: string;
  sequence: number;
  title: string;
  pedagogical_role: VideoPedagogicalRole;
  lesson_stage_id: string;
  slide_id: string;
  objective_ids: string[];
  knowledge_point_ids: string[];
  start_seconds: number;
  end_seconds: number;
  learning_purpose: string;
  visual_track: {
    composition: string;
    animation_cues: VideoAnimationCue[];
  };
  audio_track: {
    narration_text: string;
    delivery_tone: string;
    pedagogical_action?: VideoPedagogicalAction;
    speaking_rate_cps?: number;
    emphasis_terms: string[];
    pause_cues: VideoPauseCue[];
    sound_cues: VideoSoundCue[];
  };
  text_track: {
    on_screen_text: string[];
    subtitle_chunks: VideoSubtitleChunk[];
  };
  interaction?: VideoInteraction | null;
  production_notes: string[];
}

export interface VideoScriptContent {
  schema_version: '2.0';
  course_info: {
    course_title: string;
    subject: string;
    grade_level: string;
    audience: string;
    duration_seconds: number;
  };
  production_settings: {
    mode: 'ppt_screen_recording';
    aspect_ratio: '16:9';
    target_duration_seconds: number;
    narration_chars_per_minute: number;
    subtitle_max_chars_per_line: number;
    subtitle_max_lines: number;
  };
  scenes: VideoScene[];
}

export interface VideoGenerationSettings {
  aspect_ratio: '16:9';
  resolution: '1920x1080' | '1280x720' | '640x360';
  subtitle_enabled: boolean;
  voice_style: string;
  background_music_enabled: boolean;
}

export interface VideoGenerationScene {
  id: string;
  script_scene_id: string;
  sequence: number;
  start_seconds: number;
  end_seconds: number;
  visual_prompt: string;
  visual_style: string;
  narration_text: string;
  subtitle_text: string;
  production_notes: string[];
  status: 'pending' | 'generating' | 'ready' | 'failed';
  video_asset_id?: string | null;
  audio_asset_id?: string | null;
  thumbnail_asset_id?: string | null;
  provider_job_id?: string | null;
  error?: Record<string, unknown> | null;
}

export interface VideoGenerationContent {
  schema_version: '1.0';
  mode: 'hybrid';
  production_settings: VideoGenerationSettings;
  source_versions: Record<string, number>;
  scenes: VideoGenerationScene[];
  outputs: {
    preview_asset_id?: string | null;
    final_asset_id?: string | null;
    subtitle_asset_id?: string | null;
    thumbnail_asset_id?: string | null;
    duration_seconds: number;
  };
}

export interface VerbatimSegment {
  time_marker: string;
  slide_ref: number;
  speech_text: string;
  pedagogical_tip?: string;
}

export interface VerbatimContent {
  segments: VerbatimSegment[];
}

export interface QualityIssue {
  id?: string;
  report_id?: string;
  severity: 'critical' | 'major' | 'minor';
  artifact_type: string;
  field_path: string;
  issue_description: string;
  evidence: string;
  suggestion: string;
  status?: string;
}

export interface QualityReportContent {
  score: number;
  summary: string;
  issues: QualityIssue[];
  dimensions?: Record<string, number>;
}
