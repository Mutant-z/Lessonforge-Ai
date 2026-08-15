const SCENE_EDIT_MARKERS = /(第\s*[一二三四五六七八九十\d]+\s*(个)?(片段|分镜)|片段|分镜|口播|镜头|连续性|节奏|调整|修改|修正|替换)/i;

/** True only for a request to start a whole-video generation run. */
export function isWholeVideoGenerationIntent(value: string): boolean {
  const text = value.trim().replace(/\s+/g, ' ');
  if (!text || SCENE_EDIT_MARKERS.test(text)) return false;
  const compact = text.replace(/\s+/g, '');
  return /^(请|麻烦)?(帮我)?(现在|立即)?(开始|重新)?(生成|制作|创建)(一条|一个|完整的?|整条|整部)?(微课)?视频(成片)?[吧。！!]*$/i.test(compact)
    || /^(开始|确认)?生成(视频)?[吧。！!]*$/i.test(compact)
    || /^(start|generate|create)(the)?(whole|full)?video[.!]*$/i.test(compact);
}
