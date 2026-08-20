import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import type { ModelCategory, ModelConfigItem, ModelPurpose } from '../types/settings';
import { useModelConfigStore } from './modelConfigs';

function config(id: string, category: ModelCategory, purpose: ModelPurpose, active = false): ModelConfigItem {
  return {
    id, name: id, provider: 'openai_compatible', base_url: 'https://example.test/v1', model_name: id,
    timeout_seconds: 30, context_window_tokens: 1000, supports_multimodal: purpose === 'vision_chat',
    capabilities: purpose === 'vision_chat' ? ['text_generation', 'structured_output', 'vision_review']
      : purpose === 'native_audio_video_generation' ? ['video_generation', 'native_audio_video_generation']
        : ['text_generation', 'structured_output'],
    api_mode: purpose === 'native_audio_video_generation' ? 'gemini_interactions_video' : 'text_chat',
    adapter_config: {}, model_category: category, model_purpose: purpose,
    api_key_configured: false, api_key_masked: '', is_active: active,
  };
}

describe('model category defaults', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('tracks text, vision, and video defaults independently', () => {
    const store = useModelConfigStore();
    store.setConfigs([
      config('text', 'text', 'text_chat', true),
      config('vision', 'vision', 'vision_chat', true),
      config('video', 'video', 'native_audio_video_generation', true),
    ], { text: 'text', vision: 'vision', video: 'video' });

    expect(store.activeConfig?.id).toBe('text');
    expect(store.activeConfigFor('vision')?.id).toBe('vision');
    expect(store.activeConfigFor('video')?.id).toBe('video');
  });

  it('derives defaults from is_active for an older settings response', () => {
    const store = useModelConfigStore();
    store.setConfigs([config('text', 'text', 'text_chat', true), config('vision', 'vision', 'vision_chat', true)]);
    expect(store.activeConfigIds).toEqual({ text: 'text', vision: 'vision', video: null });
  });
});
