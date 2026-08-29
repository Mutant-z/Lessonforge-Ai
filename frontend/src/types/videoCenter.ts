import type { CourseTask } from './project';

export type VideoProjectStatus =
  | 'not_ready' | 'ready' | 'queued' | 'generating' | 'review'
  | 'completed' | 'partial' | 'failed' | 'cancelled';

export interface VideoProjectSummary {
  course: { id: string; title: string; subject: string; grade_level: string; duration_minutes: number };
  status: VideoProjectStatus;
  raw_task_status: string;
  progress: number;
  script: { id: string; version: number; schema_version: string; updated_at: string } | null;
  video: { id: string; version: number; status: string; updated_at: string } | null;
  ready_scene_count: number;
  scene_count: number;
  duration_seconds: number;
  thumbnail_asset_id: string | null;
  memory_revision: number;
  updated_at: string;
}

export interface VideoWorkspaceSnapshot {
  summary: VideoProjectSummary;
  task: CourseTask;
  pending_action?: VideoAgentPendingAction | null;
}

export interface VideoAgentDecision {
  intent: 'consult' | 'generate_full' | 'regenerate_scene' | 'regenerate_dependents' | 'recompose' | 'handoff_script' | 'clarify';
  answer: string;
  target_scene_ids: string[];
  instruction: string;
  confidence: number;
}

export interface VideoAgentPendingAction {
  request_id: string;
  intent: VideoAgentDecision['intent'];
  quote: {
    quote_id: string;
    expires_at: string;
    model_name: string;
    resolution: string;
    scene_count: number;
    duration_seconds: number;
    estimated_cost_fen: number;
    maximum_cost_fen: number;
    currency: 'CNY';
  } | null;
}
