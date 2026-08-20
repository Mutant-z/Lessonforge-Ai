import type { ModelConfigItem } from '../types/settings';

export function imageGenerationModels(configs: ModelConfigItem[]): ModelConfigItem[] {
  return configs.filter(
    item => item.provider !== 'mock'
      && item.model_category === 'vision'
      && item.model_purpose === 'image_generation'
      && item.capabilities?.includes('image_generation'),
  );
}

export function uniqueImageModelId(
  currentId: string | null | undefined,
  configs: ModelConfigItem[],
): string | null {
  if (currentId) return null;
  const candidates = imageGenerationModels(configs);
  return candidates.length === 1 ? candidates[0].id : null;
}

export function isImageGenerationInstruction(text: string): boolean {
  return /(图片|插图|配图|image)/i.test(text);
}
