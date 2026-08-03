export interface ModelConfigItem {
  id: string;
  name: string;
  provider: 'openai_compatible' | 'anthropic' | 'mock' | string;
  base_url: string;
  model_name: string;
  timeout_seconds: number;
  context_window_tokens: number;
  supports_multimodal: boolean;
  capabilities: Array<'text_generation' | 'structured_output' | 'vision_review' | 'image_generation'>;
  api_mode: string;
  adapter_config: Record<string, unknown>;
  api_key_configured: boolean;
  api_key_masked: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ModelConfigPayload {
  name?: string;
  provider: string;
  base_url: string;
  model_name: string;
  api_key?: string;
  timeout_seconds: number;
  context_window_tokens: number;
  supports_multimodal: boolean;
  capabilities: Array<'text_generation' | 'structured_output' | 'vision_review' | 'image_generation'>;
  api_mode: string;
  adapter_config: Record<string, unknown>;
  is_active?: boolean;
}

export interface TestConnectionPayload {
  config_id?: string;
  provider?: string;
  base_url?: string;
  model_name?: string;
  api_key?: string;
  timeout_seconds?: number;
}

export interface UserPreferencesPayload {
  default_language: string;
  default_grade_level: string;
  default_ppt_template: string;
}

export interface FullSettingsResponse {
  configs: ModelConfigItem[];
  active_config_id: string | null;
  preferences: UserPreferencesPayload;
  // 旧字段兼容
  provider: string;
  base_url: string;
  model_name: string;
  api_key_configured: boolean;
  api_key_masked: string;
  timeout_seconds: number;
  default_language: string;
  default_grade_level: string;
  default_ppt_template: string;
}
