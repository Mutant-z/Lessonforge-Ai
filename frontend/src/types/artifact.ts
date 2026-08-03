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

export interface PPTSlide {
  slide_number: number;
  title: string;
  layout_type: string;
  bullet_points: string[];
  visual_suggestion: string;
  speaker_notes: string;
}

export interface PPTContent {
  slides: PPTSlide[];
}

export interface TaskSheetItem {
  task_id: string;
  title: string;
  objective: string;
  steps: string[];
  output_requirement: string;
  estimated_minutes: number;
}

export interface TaskSheetContent {
  tasks: TaskSheetItem[];
}

export interface ExerciseItem {
  id: string;
  type: 'single_choice' | 'multiple_choice' | 'fill_blank' | 'short_answer';
  difficulty: 'easy' | 'medium' | 'hard';
  question: string;
  options?: string[];
  answer: string;
  explanation: string;
  target_objective?: string;
}

export interface ExerciseContent {
  exercises: ExerciseItem[];
}

export interface StoryboardItem {
  scene_number: number;
  time_range: string;
  visual_description: string;
  narration: string;
  subtitle: string;
  on_screen_graphic: string;
}

export interface VideoScriptContent {
  scenes: StoryboardItem[];
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
