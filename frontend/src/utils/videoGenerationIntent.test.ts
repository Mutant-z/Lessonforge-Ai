import { describe, expect, it } from 'vitest';
import { isWholeVideoGenerationIntent } from './videoGenerationIntent';

describe('isWholeVideoGenerationIntent', () => {
  it.each(['帮我生成视频', '请开始生成完整视频', '生成视频', '制作微课视频吧', 'generate full video'])(
    'recognizes whole-video request: %s',
    (value) => expect(isWholeVideoGenerationIntent(value)).toBe(true),
  );

  it.each(['调整第 1 个完整片段', '修正第 2 个片段口播', '增强片段连续性', '重新生成第3个分镜'])(
    'keeps scene edits in the editor flow: %s',
    (value) => expect(isWholeVideoGenerationIntent(value)).toBe(false),
  );
});
