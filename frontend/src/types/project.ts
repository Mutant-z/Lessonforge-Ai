import type { Artifact } from './artifact';

export interface ProjectCourse {
  id: string;
  title: string;
  subject: string;
  grade_level: string;
  audience: string;
  duration_minutes: number;
  scenario: string;
  language: string;
  status: string;
  current_blueprint_version: number;
  created_at: string;
  updated_at: string;
}

export type CourseTaskStatus =
  | 'waiting_dependency'
  | 'queued'
  | 'running'
  | 'review'
  | 'approved'
  | 'stale'
  | 'failed'
  | 'cancelled';

export interface CourseTaskError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface CourseTask {
  id: string;
  course_id: string;
  task_type: string;
  display_name: string;
  agent_name: string;
  agent_type: string;
  display_order: number;
  status: CourseTaskStatus;
  progress: number;
  dependency_types: string[];
  stale_dependencies: string[];
  agent_profile_status: 'pending' | 'initializing' | 'ready' | 'failed' | 'stale';
  agent_profile_version: number;
  agent_profile_template_version?: string | null;
  agent_profile_summary?: AgentProfileSummary | null;
  stale_agent_profile: boolean;
  agent_profile_error?: CourseTaskError | null;
  current_artifact: Artifact | null;
  active_run_id: string | null;
  error: CourseTaskError | null;
  updated_at: string;
  messages?: ProjectAgentMessage[];
  model_config_id?: string | null;
  activity_run_id?: string | null;
  activities?: TaskActivity[];
  current_activity?: TaskActivity | null;
}

export type TaskActivityPhase =
  | 'preparing'
  | 'analyzing'
  | 'generating'
  | 'validating'
  | 'replying'
  | 'saving'
  | 'completed';

export interface TaskActivity {
  phase: TaskActivityPhase;
  label: string;
  detail: string;
  status: 'running' | 'completed' | 'failed';
  progress: number;
  elapsed_ms: number;
}

export interface AgentProfileSummary {
  mission: string;
  audience: string;
  task_goals: string[];
  knowledge_focus: string[];
  style_guidelines: string[];
  hard_constraints: string[];
  quality_focus: string[];
}

export interface AgentInitializationState {
  status: 'not_initialized' | 'queued' | 'running' | 'ready' | 'failed';
  version: number;
  progress: number;
  error: CourseTaskError | null;
}

export interface ProjectAgentMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  status?: 'pending' | 'streaming' | 'completed' | 'failed';
  artifact_id?: string | null;
  run_id?: string | null;
  created_at?: string;
}

export interface TeachingIntent {
  headline: string;
  title: string;
  subject: string;
  grade_level: string;
  audience: string;
  duration_minutes: number;
  scenario: string;
  course_task: string;
  teaching_objectives: string;
  key_points: string;
  difficulty_points: string;
  teaching_method: string;
  style_requirements: string;
  assumptions: Array<{ field: string; value: unknown; reason: string }>;
  deliverables: string[];
}

export interface ProjectQuality {
  score: number | null;
  summary: string;
  open_issues: number;
  issues: Array<{
    id: string;
    artifact_type: string;
    severity: string;
    location: string;
    description: string;
    suggestion: string;
  }>;
}

export interface CourseProjectWorkspace {
  course: ProjectCourse;
  intent: TeachingIntent;
  planning: { status: string; progress: number; error: CourseTaskError | null };
  agent_initialization: AgentInitializationState;
  tasks: CourseTask[];
  quality: ProjectQuality;
}

export interface ProjectTaskEvent {
  event_id: number;
  course_id: string;
  run_id?: string;
  task_id?: string;
  task_type?: string;
  status?: CourseTaskStatus | 'ready' | 'planning';
  progress?: number;
  artifact?: Artifact;
  message?: ProjectAgentMessage;
  error?: CourseTaskError;
  version?: number;
  phase?: TaskActivityPhase;
  phase_label?: string;
  detail?: string;
  phase_status?: TaskActivity['status'];
  elapsed_ms?: number;
  message_id?: string;
  delta?: string;
  reset?: boolean;
}
