import { describe, expect, it } from 'vitest';
import { canRequestVideoQuote, videoGenerationUnavailableReason } from './videoGenerationAvailability';

const ready = {
  model_name: 'gemini-omni-flash-preview',
  supported_resolutions: [{ value: '1280x720' as const, label: '720p' }],
  available: true,
  unavailable_reason: null,
};

describe('video generation availability', () => {
  it('requires both a selected model and a ready runtime', () => {
    expect(canRequestVideoQuote(true, ready)).toBe(true);
    expect(canRequestVideoQuote(false, ready)).toBe(false);
    expect(canRequestVideoQuote(true, { ...ready, available: false })).toBe(false);
  });

  it('surfaces the backend preflight reason', () => {
    const unavailable = {
      ...ready,
      available: false,
      unavailable_reason: '当前视频模型暂不可用。',
    };
    expect(videoGenerationUnavailableReason(true, unavailable)).toBe('当前视频模型暂不可用。');
    expect(videoGenerationUnavailableReason(false, unavailable)).toContain('选择视频模型');
  });
});
