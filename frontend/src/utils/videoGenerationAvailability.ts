import type { CourseTask } from '../types/project';

type VideoCapabilities = CourseTask['video_generation_capabilities'];

export function canRequestVideoQuote(
  hasModel: boolean,
  capabilities: VideoCapabilities,
): boolean {
  return hasModel && capabilities?.available === true;
}

export function videoGenerationUnavailableReason(
  hasModel: boolean,
  capabilities: VideoCapabilities,
): string {
  if (!hasModel) return '请先选择视频模型。';
  if (!capabilities) return '正在检查视频模型是否可用。';
  if (!capabilities.available) {
    return capabilities.unavailable_reason || '当前视频模型暂不可生成，请检查运行配置。';
  }
  return '';
}
