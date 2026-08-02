export type IntakeStatus = 'collecting' | 'ready' | 'processing' | 'converting' | 'completed' | 'failed' | 'abandoned';

export interface IntakeDraft {
  title?: string;
  subject?: string;
  grade_level?: string;
  audience?: string;
  duration_minutes?: number;
  scenario?: string;
  language?: string;
  course_task?: string;
  teaching_objectives?: string;
  key_points?: string;
  difficulty_points?: string;
  teaching_method?: string;
  style_requirements?: string;
}

export interface IntakeAssumption {
  field: keyof IntakeDraft | string;
  value: unknown;
  reason: string;
}

export interface IntakeConflict {
  field: keyof IntakeDraft | string;
  severity: 'warning' | 'blocking';
  description: string;
  suggestion: string;
}

export interface IntakeSession {
  id: string;
  status: IntakeStatus;
  current_revision: number;
  draft: IntakeDraft;
  field_sources: Record<string, 'user' | 'material' | 'manual' | 'assumption'>;
  missing_fields: string[];
  assumptions: IntakeAssumption[];
  conflicts: IntakeConflict[];
  course_id?: string | null;
  active_turn_id?: string | null;
  model_config_id?: string | null;
  last_failure?: IntakeTurnFailure | null;
}

export interface IntakeTurnFailure {
  turn_id: string;
  code: string;
  message: string;
  retryable: boolean;
  session_status?: Extract<IntakeStatus, 'collecting' | 'ready' | 'failed'>;
}

export interface IntakeMessage {
  id: string;
  turn_id?: string | null;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
}

export interface IntakeMaterial {
  id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  parse_status: 'pending' | 'completed' | 'failed';
  summary: string;
  error_message?: string;
}

export interface IntakeDraftUpdatedEvent {
  revision: number;
  draft: IntakeDraft;
  field_sources: IntakeSession['field_sources'];
  missing_fields: string[];
  assumptions: IntakeAssumption[];
  conflicts: IntakeConflict[];
  ready_to_confirm: boolean;
}
