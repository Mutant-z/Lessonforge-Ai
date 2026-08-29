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

/** 教学设计 V2：稳定教学内核 + 动态展示目录（schema_version === '2.0'）。 */
export interface LessonPlanContentV2 {
  schema_version: '2.0';
  course_info: {
    title: string;
    subject: string;
    grade_level: string;
    audience: string;
    duration_minutes: number;
    scenario: string;
    language: string;
  };
  pedagogical_core: {
    objectives: Array<{
      id: string;
      statement: string;
      behavior: string;
      criterion: string;
      blueprint_objective_id: string;
      evidence: string;
    }>;
    knowledge_points: Array<{ id: string; name: string }>;
    key_points: string[];
    difficulty_points: string[];
    methods: string[];
    resources: string[];
    stages: Array<{
      id: string;
      title: string;
      duration_minutes: number;
      teacher_activity: string;
      learner_activity: string;
      design_intent: string;
      assessment: string;
      objective_ids: string[];
      knowledge_point_ids: string[];
    }>;
    assessment_plan: Array<{
      objective_id: string;
      method: string;
      evidence: string;
      criterion: string;
    }>;
    homework: string;
    board_design: string;
    reflection: string;
  };
  outline: {
    sections: Array<Record<string, any>>;
  };
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
export interface SeedanceCameraBeat {
  start_offset_seconds: number;
  end_offset_seconds: number;
  instruction: string;
}

export interface VideoScene {
  id: string;
  sequence: number;
  title: string;
  pedagogical_role: VideoPedagogicalRole;
  lesson_stage_id: string;
  objective_ids: string[];
  knowledge_point_ids: string[];
  start_seconds: number;
  end_seconds: number;
  continuity_group: string;
  visual_prompt: string;
  camera_beats: SeedanceCameraBeat[];
  spoken_text: string;
  required_terms: string[];
  required_numbers: string[];
  required_facts: string[];
  voice_direction: string;
  sound_design: string[];
  negative_constraints: string[];
  production_notes: string[];
}

export interface VideoScriptContent {
  schema_version: '3.0';
  course_info: {
    course_title: string;
    subject: string;
    grade_level: string;
    audience: string;
    duration_seconds: number;
  };
  production_settings: {
    mode: 'seedance_native';
    aspect_ratio: '16:9';
    target_duration_seconds: number;
    target_clip_seconds: number;
    min_clip_seconds: number;
    max_clip_seconds: number;
    global_visual_style: string;
    global_voice_direction: string;
  };
  scenes: VideoScene[];
}

/** V4 动态章节：章节数量、标题、顺序与分镜归属由 AI 动态决定，无固定目录。 */
export interface VideoScriptSection {
  id: string;
  sequence: number;
  title: string;
  purpose: string;
  objective_ids: string[];
  knowledge_point_ids: string[];
}

/** V4 分镜：在 V3 基础上绑定所属动态章节。 */
export interface VideoSceneV4 extends VideoScene {
  section_id: string;
}

/** V4 视频脚本：outline.sections（动态章节）+ scenes（每镜归属章节）。 */
export interface VideoScriptContentV4 {
  schema_version: '4.0';
  course_info: VideoScriptContent['course_info'];
  production_settings: VideoScriptContent['production_settings'];
  outline: {
    sections: VideoScriptSection[];
  };
  scenes: VideoSceneV4[];
}

export type NativeVideoResolution = '1280x720' | '854x480';

export interface VideoGenerationSettings {
  aspect_ratio: '16:9';
  resolution: NativeVideoResolution;
  subtitle_enabled: boolean;
  native_audio: true;
  continuity_policy: 'grouped';
  model_config_id: string;
  model_name: string;
  quote_id: string;
  approved_max_cost_fen: number;
  provider?: string | null;
  api_mode?: string | null;
  interaction_ids?: string[];
}

export interface VideoGenerationScene {
  id: string;
  script_scene_id: string;
  sequence: number;
  start_seconds: number;
  end_seconds: number;
  continuity_group: string;
  visual_prompt: string;
  spoken_text: string;
  voice_direction: string;
  sound_design: string[];
  required_terms: string[];
  required_numbers: string[];
  required_facts: string[];
  request_hash: string;
  reference_scene_ids: string[];
  status: 'pending' | 'generating' | 'ready' | 'failed' | 'qa_failed';
  video_asset_id?: string | null;
  thumbnail_asset_id?: string | null;
  provider_job_id: string;
  actual_transcript: string;
  subtitle_segments: Array<Record<string, any>>;
  qa: Record<string, any>;
  usage: Record<string, any>;
  estimated_tokens: number;
  actual_tokens: number;
  estimated_cost_fen: number;
  actual_cost_fen: number;
  error?: Record<string, unknown> | null;
}

export interface VideoGenerationContent {
  schema_version: '3.0';
  mode: 'seedance_native';
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
  cost_summary: Record<string, number | string>;
  audio_qa?: {
    status: 'passed' | 'warning' | 'skipped';
    passed_scenes: number;
    warning_scenes: number;
    skipped_scenes: number;
  };
  generation_warnings?: string[];
}

export interface VideoGenerationQuote {
  quote_id: string;
  expires_at: string;
  script_version: number;
  model_config_id: string;
  model_name: string;
  provider: string;
  api_mode: string;
  resolution: NativeVideoResolution;
  scene_count: number;
  reusable_scene_count: number;
  duration_seconds: number;
  estimated_tokens: number;
  estimated_cost_fen: number;
  maximum_cost_fen: number;
  currency: 'CNY';
  scenes: Array<{
    scene_id: string;
    duration_seconds: number;
    request_hash: string;
    reusable: boolean;
    estimated_tokens: number;
    estimated_cost_fen: number;
  }>;
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

// ===================== 学习任务单 V3：动态目录 + 强类型 Block =====================
export interface TaskSheetCourseInfoV3 {
  course_title: string;
  subject: string;
  grade_level: string;
  audience: string;
  duration_minutes: number;
}

export interface TaskSheetObjectiveCatalogItem {
  id: string;
  statement: string;
  success_criterion: string;
}

export interface TaskSheetTaskRecordTable {
  title: string;
  instructions: string;
  columns: string[];
  blank_rows: number;
}

export interface TaskSheetTextBlock {
  kind: 'text';
  id: string;
  text: string;
}

export interface TaskSheetObjectiveListBlock {
  kind: 'objective_list';
  id: string;
  title?: string;
  objective_ids: string[];
}

export interface TaskSheetLearningTaskBlock {
  kind: 'learning_task';
  id: string;
  title: string;
  action: string;
  object: string;
  steps: string[];
  student_output: string;
  completion_criterion: string;
  estimated_minutes: number;
  collaboration_mode: TaskSheetCollaboration;
  objective_ids: string[];
  knowledge_point_ids: string[];
  stage_id?: string | null;
  scaffolds: string[];
  record_table?: TaskSheetTaskRecordTable | null;
}

export interface TaskSheetRecordTableBlock {
  kind: 'record_table';
  id: string;
  title: string;
  instructions: string;
  columns: string[];
  blank_rows: number;
}

export interface TaskSheetQuestionItem {
  id: string;
  prompt: string;
  objective_ids: string[];
  stage_id?: string | null;
}

export interface TaskSheetQuestionSetBlock {
  kind: 'question_set';
  id: string;
  title?: string;
  questions: TaskSheetQuestionItem[];
}

export interface TaskSheetAssessmentItem {
  id: string;
  statement: string;
  objective_ids: string[];
}

export interface TaskSheetAssessmentBlock {
  kind: 'assessment';
  id: string;
  title?: string;
  scale: string[];
  items: TaskSheetAssessmentItem[];
}

export interface TaskSheetChecklistItem {
  text: string;
}

export interface TaskSheetChecklistBlock {
  kind: 'checklist';
  id: string;
  title?: string;
  items: TaskSheetChecklistItem[];
}

export type TaskSheetBlock =
  | TaskSheetTextBlock
  | TaskSheetObjectiveListBlock
  | TaskSheetLearningTaskBlock
  | TaskSheetRecordTableBlock
  | TaskSheetQuestionSetBlock
  | TaskSheetAssessmentBlock
  | TaskSheetChecklistBlock;

export interface TaskSheetSectionV3 {
  id: string;
  parent_id: string;
  order: number;
  title: string;
  purpose: string;
  objective_ids: string[];
  blocks: TaskSheetBlock[];
}

export interface TaskSheetContentV3 {
  schema_version: '3.0';
  course_info: TaskSheetCourseInfoV3;
  objective_catalog: TaskSheetObjectiveCatalogItem[];
  sections: TaskSheetSectionV3[];
}

/** V2 / V3 判别 */
export function isTaskSheetV3(value: unknown): value is TaskSheetContentV3 {
  return Boolean(value) && typeof value === 'object' && (value as any).schema_version === '3.0';
}

/** V3 深度优先有序章节（parent_id + order） */
export function orderTaskSheetSections(sections: TaskSheetSectionV3[]): Array<TaskSheetSectionV3 & { depth: number }> {
  const depthMap: Record<string, number> = {};
  for (const section of sections) {
    depthMap[section.id] = section.parent_id ? (depthMap[section.parent_id] || 0) + 1 : 0;
  }
  return [...sections]
    .sort((a, b) => `${a.parent_id || ''}:${a.order}`.localeCompare(`${b.parent_id || ''}:${b.order}`, undefined, { numeric: true }))
    .map(section => ({ ...section, depth: depthMap[section.id] || 0 }));
}
