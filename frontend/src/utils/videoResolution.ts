import type { NativeVideoResolution } from '../types/artifact';

export const NATIVE_VIDEO_RESOLUTIONS: readonly NativeVideoResolution[] = ['1280x720', '854x480'];

export const VIDEO_RESOLUTION_LABELS: Record<NativeVideoResolution, string> = {
  '1280x720': '720p',
  '854x480': '480p',
};

export function isNativeVideoResolution(value: unknown): value is NativeVideoResolution {
  return typeof value === 'string' && NATIVE_VIDEO_RESOLUTIONS.includes(value as NativeVideoResolution);
}

export function videoResolutionLabel(value: unknown): string {
  return isNativeVideoResolution(value) ? VIDEO_RESOLUTION_LABELS[value] : '未知规格';
}
