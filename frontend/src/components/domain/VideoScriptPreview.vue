<script setup lang="ts">
import { computed } from 'vue';
import { Clock, Document, Microphone, Monitor } from '@element-plus/icons-vue';
import type { VideoScriptContent } from '../../types';
import StoryboardItem from './StoryboardItem.vue';

const props = defineProps<{
  content: VideoScriptContent;
  sourceVersions?: Record<string, number>;
}>();

const total = computed(() => props.content.production_settings.target_duration_seconds);
const narrationCharacters = computed(() => props.content.scenes.reduce((sum, scene) => (
  sum + (scene.audio_track.narration_text.match(/[\u4e00-\u9fffA-Za-z0-9]/g)?.length || 0)
), 0));
const slideCount = computed(() => new Set(props.content.scenes.map(scene => scene.slide_id)).size);

function timecode(seconds: number) {
  const value = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}
</script>

<template>
  <div class="video-preview">
    <header class="script-masthead">
      <div class="title-block">
        <span>视频脚本 V2 · PPT 录屏制作版</span>
        <h1>{{ content.course_info.course_title }}</h1>
        <p>{{ content.course_info.subject }} · {{ content.course_info.grade_level || content.course_info.audience }}</p>
      </div>
      <dl class="summary-grid">
        <div><el-icon><Clock /></el-icon><dt>总时长</dt><dd>{{ timecode(total) }}</dd></div>
        <div><el-icon><Document /></el-icon><dt>分镜 / 页面</dt><dd>{{ content.scenes.length }} / {{ slideCount }}</dd></div>
        <div><el-icon><Microphone /></el-icon><dt>旁白字数</dt><dd>{{ narrationCharacters }}</dd></div>
        <div><el-icon><Monitor /></el-icon><dt>上游版本</dt><dd>教案 V{{ sourceVersions?.lesson_plan || '—' }} · PPT V{{ sourceVersions?.ppt || '—' }}</dd></div>
      </dl>
    </header>

    <section class="timeline-panel">
      <div class="timeline-head">
        <h2>制作时间轨</h2>
        <span>{{ content.production_settings.aspect_ratio }} · {{ content.production_settings.narration_chars_per_minute }} 字/分钟</span>
      </div>
      <div class="timeline">
        <div
          v-for="scene in content.scenes"
          :key="scene.id"
          class="timeline-scene"
          :style="{ flexGrow: Math.max(1, scene.end_seconds - scene.start_seconds) }"
          :title="`${scene.id} · ${scene.title}`"
        >
          <b>{{ scene.sequence }}</b>
          <span>{{ scene.pedagogical_role }}</span>
          <small>{{ scene.slide_id }}</small>
        </div>
      </div>
      <div class="timeline-scale"><span>00:00</span><span>{{ timecode(total / 2) }}</span><span>{{ timecode(total) }}</span></div>
    </section>

    <section class="scene-list">
      <StoryboardItem
        v-for="scene in content.scenes"
        :key="scene.id"
        :scene="scene"
        :total-seconds="total"
      />
    </section>
  </div>
</template>

<style scoped>
.video-preview { padding: 24px; color: #171b23; background: #f7f7f8; }
.script-masthead { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(420px, 1.3fr); border: 1px solid #cfd5df; background: #fff; }
.title-block { padding: 26px 28px; border-right: 1px solid #cfd5df; }
.title-block > span { color: #002fa7; font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.title-block h1 { margin: 10px 0 8px; color: #10151e; font-size: 28px; line-height: 1.18; }
.title-block p { margin: 0; color: #697180; font-size: 13px; }
.summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; }
.summary-grid div { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto; gap: 2px 9px; padding: 17px 19px; border-right: 1px solid #e1e5eb; border-bottom: 1px solid #e1e5eb; }
.summary-grid div:nth-child(2n) { border-right: 0; }
.summary-grid div:nth-child(n+3) { border-bottom: 0; }
.summary-grid .el-icon { grid-row: 1 / 3; align-self: center; color: #002fa7; font-size: 18px; }
.summary-grid dt { color: #7a8391; font-size: 11px; }
.summary-grid dd { margin: 0; color: #1d293d; font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
.timeline-panel { margin: 18px 0; padding: 18px 20px 14px; border: 1px solid #cfd5df; background: #fff; }
.timeline-head { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; margin-bottom: 13px; }
.timeline-head h2 { margin: 0; font-size: 14px; }
.timeline-head span { color: #747d8b; font-size: 11px; }
.timeline { display: flex; min-height: 58px; overflow: hidden; border: 1px solid #bfc7d4; }
.timeline-scene { min-width: 38px; padding: 8px; border-right: 1px solid #fff; background: #eaf0ff; color: #16316c; }
.timeline-scene:nth-child(3n+2) { background: #dce7ff; }
.timeline-scene:nth-child(3n) { background: #cfdcff; }
.timeline-scene b, .timeline-scene span, .timeline-scene small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.timeline-scene b { font-size: 15px; }
.timeline-scene span { font-size: 10px; font-weight: 700; }
.timeline-scene small { margin-top: 3px; color: #52688f; font-size: 9px; }
.timeline-scale { display: flex; justify-content: space-between; margin-top: 6px; color: #788190; font-size: 10px; font-variant-numeric: tabular-nums; }
.scene-list { min-width: 0; }
@media (max-width: 900px) {
  .video-preview { padding: 14px; }
  .script-masthead { grid-template-columns: 1fr; }
  .title-block { border-right: 0; border-bottom: 1px solid #cfd5df; }
  .timeline { overflow-x: auto; }
  .timeline-scene { min-width: 72px; }
}
</style>
