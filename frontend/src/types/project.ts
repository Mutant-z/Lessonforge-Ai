import type { Artifact, NativeVideoResolution } from './artifact';

export type HydrationStatus =
  | 'idle'
  | 'loading_project'
  | 'loading_task_snapshot'
  | 'loading_pipeline_snapshot'
  | 'applying_current_run_events'
  | 'ready'
  | 'failed';

export type ArtifactUpdateSource = 'project_snapshot' | 'task_snapshot' | 'poll' | 'refresh' | 'event' | 'approve';

export interface ArtifactPreviewState {
  officialArtifact: Artifact | null;
  viewedArtifact: Artifact | null;
  hydrationStatus: HydrationStatus;
  eventCursor: number;
}

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
  | 'ready_to_generate'
  | 'queued'
  | 'running'
  | 'pausing'
  | 'paused'
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

export interface ChatAttachment {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  parse_status?: string;
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
  optional_reference_types?: string[];
  required_input_contract?: Record<string, string>;
  /** 该任务最近一次运行实际读取的项目记忆版本（旧客户端可忽略）。 */
  memory_revision?: number;
  last_context_revision?: number;
  /** 共享项目记忆中当前可读取的参考产物（类型 → 版本/状态），不阻塞启动。 */
  available_sources?: Record<string, { version: number; status: string }>;
  missing_optional_sources?: string[];
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
  image_model_config_id?: string | null;
  vision_model_config_id?: string | null;
  video_model_config_id?: string | null;
  speech_model_config_id?: string | null;
  /** 视频生成任务：课程级偏好分辨率（由视频脚本 Agent 保存）。 */
  preferred_video_resolution?: NativeVideoResolution | null;
  video_generation_capabilities?: {
    model_name: string;
    supported_resolutions: Array<{ value: NativeVideoResolution; label: string }>;
    available: boolean;
    unavailable_reason: string | null;
    verification_status?: 'unverified' | 'verified' | 'failed';
    output_spec?: { resolution: NativeVideoResolution | null; native_audio: boolean };
  } | null;
  activity_run_id?: string | null;
  activities?: TaskActivity[];
  current_activity?: TaskActivity | null;
  event_cursor?: number;
  snapshot_at?: string;
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
  metadata?: Record<string, any> & { attachments?: ChatAttachment[] };
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

/** 共享项目记忆条目（需求/蓝图/材料/Artifact/决策/QA/对话摘要的索引）。 */
export interface MemoryItem {
  id: string;
  course_id: string;
  source_type: 'requirement' | 'blueprint' | 'material' | 'artifact' | 'decision' | 'qa' | 'dialogue';
  source_id: string;
  source_version: number;
  artifact_type?: string;
  summary?: Record<string, any>;
  content_ref?: string;
  keywords?: string[];
  trust_level?: string;
  memory_revision: number;
  created_by?: string;
  updated_at?: string | null;
}

/** 项目记忆摘要（项目总览与记忆面板共用）。 */
export interface ProjectMemorySummary {
  revision: number;
  item_count: number;
  items: MemoryItem[];
}

/** Agent 运行上下文快照清单（本次读取的记忆版本 + 可用来源 + 缺失来源）。 */
export interface ContextManifest {
  memory_revision: number;
  available_sources?: Record<string, { version: number; status: string }>;
  missing_optional_sources?: string[];
  decisions?: Array<Record<string, any>>;
  qa_findings?: Array<Record<string, any>>;
}

export interface CourseProjectWorkspace {
  event_cursor?: number;
  snapshot_at?: string;
  course: ProjectCourse;
  intent: TeachingIntent;
  planning: { status: string; progress: number; error: CourseTaskError | null };
  agent_initialization: AgentInitializationState;
  tasks: CourseTask[];
  quality: ProjectQuality;
  /** 共享项目记忆摘要（只读回填后返回）。 */
  memory?: ProjectMemorySummary;
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
  agent_key?: string;
  text?: string;
  delta?: string;
  reset?: boolean;
  issue?: Record<string, any>;
  payload?: Record<string, any>;
  /** 共享项目记忆事件字段（context.snapshot_created / project_memory.updated）。 */
  memory_revision?: number;
  context_manifest?: ContextManifest;
  context_hash?: string;
  change_reason?: string;
}

/** 润色范围：auto（自动）| layout（只改布局）| text（只改文字）| image（只改图片） */
export type PPTPolishModality = 'auto' | 'layout' | 'text' | 'image';

/** slide_id → 该页修复原因（从 qa.issue / repair.started 事件累计，已去重） */
export type SlideRepairNotes = Record<string, string[]>;
