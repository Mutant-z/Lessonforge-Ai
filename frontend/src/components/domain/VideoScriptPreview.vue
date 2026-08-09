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
.video-preview {
  padding: 24px;
  color: #0f172a;
  background: #f8fafc;
  min-height: 100%;
}

.script-masthead {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) minmax(440px, 1.2fr);
  border: 1.5px solid #cbd5e1;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 4px 20px -4px rgba(15, 23, 42, 0.06);
  overflow: hidden;
  margin-bottom: 22px;
}

.title-block {
  padding: 28px 32px;
  border-right: 1.5px solid #e2e8f0;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
}

.kicker-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.badge-v2 {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  font-size: 11.5px;
  font-weight: 800;
  padding: 3px 12px;
  border-radius: 999px;
  letter-spacing: 0.03em;
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366f1;
}

.ratio-pill {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}

.title-block h1 {
  margin: 6px 0 8px;
  color: #0f172a;
  font-size: 26px;
  font-weight: 900;
  line-height: 1.25;
  letter-spacing: -0.02em;
}

.title-block p {
  margin: 0;
  color: #64748b;
  font-size: 13.5px;
  font-weight: 600;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 0;
}

.summary-grid div {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto;
  gap: 2px 10px;
  padding: 20px 22px;
  border-right: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
  transition: background 0.15s ease;
}

.summary-grid div:hover {
  background: #f8fafc;
}

.summary-grid div:nth-child(2n) { border-right: 0; }
.summary-grid div:nth-child(n+3) { border-bottom: 0; }

.summary-grid .el-icon {
  grid-row: 1 / 3;
  align-self: center;
  color: #4f46e5;
  font-size: 22px;
  background: #eef2ff;
  padding: 8px;
  border-radius: 10px;
}

.summary-grid dt {
  color: #64748b;
  font-size: 11.5px;
  font-weight: 600;
}

.summary-grid dd {
  margin: 0;
  color: #0f172a;
  font-size: 14px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.timeline-panel {
  margin: 0 0 24px;
  padding: 20px 24px 18px;
  border: 1.5px solid #cbd5e1;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 4px 20px -4px rgba(15, 23, 42, 0.04);
}

.timeline-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}

.tl-title-group h2 {
  margin: 0 0 2px;
  font-size: 15px;
  font-weight: 900;
  color: #0f172a;
}

.tl-subtitle {
  color: #64748b;
  font-size: 11.5px;
}

.meta-tag {
  font-size: 11.5px;
  font-weight: 700;
  color: #475569;
  background: #f1f5f9;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.timeline {
  display: flex;
  min-height: 64px;
  overflow: hidden;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.03);
}

.timeline-scene {
  min-width: 44px;
  padding: 8px 10px;
  border-right: 1.5px solid #ffffff;
  background: #e0e7ff;
  color: #3730a3;
  transition: all 0.15s ease;
  cursor: pointer;
}

.timeline-scene:hover {
  filter: brightness(0.95);
  transform: scaleY(1.03);
}

.timeline-scene:nth-child(3n+2) { background: #c7d2fe; color: #312e81; }
.timeline-scene:nth-child(3n) { background: #a5b4fc; color: #1e1b4b; }

.timeline-scene b,
.timeline-scene span,
.timeline-scene small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-scene b {
  font-size: 13px;
  font-weight: 900;
}

.timeline-scene span {
  font-size: 10.5px;
  font-weight: 800;
  opacity: 0.9;
}

.timeline-scene small {
  margin-top: 2px;
  font-size: 9.5px;
  font-weight: 700;
  opacity: 0.75;
}

.timeline-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.scene-list {
  min-width: 0;
}

@media (max-width: 900px) {
  .video-preview { padding: 14px; }
  .script-masthead { grid-template-columns: 1fr; }
  .title-block { border-right: 0; border-bottom: 1.5px solid #e2e8f0; }
  .timeline { overflow-x: auto; }
  .timeline-scene { min-width: 76px; }
}
</style>
