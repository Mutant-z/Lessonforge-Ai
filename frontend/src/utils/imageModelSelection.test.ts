import { describe, expect, it } from 'vitest';
import type { ModelConfigItem } from '../types/settings';
import {
  imageGenerationModels,
  isImageGenerationInstruction,
  uniqueImageModelId,
} from './imageModelSelection';

function config(id: string, capabilities: ModelConfigItem['capabilities'], provider = 'openai_compatible'): ModelConfigItem {
  return {
    id, name: id, provider, base_url: '', model_name: id, timeout_seconds: 30,
    context_window_tokens: 1000, supports_multimodal: false, capabilities,
    api_mode: 'text_chat', adapter_config: {}, api_key_configured: false,
    api_key_masked: '', is_active: false,
  };
}

describe('image model selection', () => {
  it('auto-selects only one real image model', () => {
    const configs = [
      config('text', ['text_generation']),
      config('mock-image', ['image_generation'], 'mock'),
      config('image', ['image_generation']),
    ];
    expect(imageGenerationModels(configs).map(item => item.id)).toEqual(['image']);
    expect(uniqueImageModelId(null, configs)).toBe('image');
    expect(uniqueImageModelId('selected', configs)).toBeNull();
  });

  it('requires manual choice when multiple image models exist', () => {
    const configs = [config('one', ['image_generation']), config('two', ['image_generation'])];
    expect(uniqueImageModelId(null, configs)).toBeNull();
  });

  it('detects explicit image instructions', () => {
    expect(isImageGenerationInstruction('为首页生成一张潜水艇图片')).toBe(true);
    expect(isImageGenerationInstruction('只润色标题')).toBe(false);
  });
});
