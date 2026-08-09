<script setup lang="ts">
import { computed } from 'vue';
import { ChatDotRound, Connection, Microphone, Monitor, Timer } from '@element-plus/icons-vue';
import type { VideoScene } from '../../types';

const props = defineProps<{ scene: VideoScene; totalSeconds: number }>();

const duration = computed(() => props.scene.end_seconds - props.scene.start_seconds);
const width = computed(() => `${Math.max(4, (duration.value / Math.max(1, props.totalSeconds)) * 100)}%`);

function timecode(seconds: number) {
  const value = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}
</script>

<template>
  <article class="scene-card">
    <header class="scene-header">
      <div class="scene-index">{{ String(scene.sequence).padStart(2, '0') }}</div>
      <div class="scene-heading">
        <div class="scene-labels">
          <span>{{ scene.id }}</span>
          <b>{{ scene.pedagogical_role }}</b>
          <span>{{ scene.slide_id }}</span>
        </div>
        <h3>{{ scene.title }}</h3>
        <p>{{ scene.learning_purpose }}</p>
      </div>
      <div class="scene-time">
        <el-icon><Timer /></el-icon>
        <strong>{{ timecode(scene.start_seconds) }}—{{ timecode(scene.end_seconds) }}</strong>
        <small>{{ duration.toFixed(0) }} 秒</small>
      </div>
    </header>

    <div class="scene-ruler" aria-hidden="true"><i :style="{ width }" /></div>

    <div class="track-grid">
      <section class="track visual-track">
        <h4><el-icon><Monitor /></el-icon>画面与动效</h4>
        <p>{{ scene.visual_track.composition }}</p>
        <ol v-if="scene.visual_track.animation_cues.length" class="cue-list">
          <li v-for="cue in scene.visual_track.animation_cues" :key="`${cue.offset_seconds}-${cue.target}`">
            <time>+{{ cue.offset_seconds }}s</time>
            <b>{{ cue.action }} · {{ cue.target }}</b>
            <span>{{ cue.instruction }}</span>
          </li>
        </ol>
      </section>

      <section class="track narration-track">
        <h4><el-icon><Microphone /></el-icon>旁白与声音</h4>
        <blockquote>{{ scene.audio_track.narration_text }}</blockquote>
        <div class="track-meta">
          <span>语气：{{ scene.audio_track.delivery_tone }}</span>
          <span v-if="scene.audio_track.emphasis_terms.length">强调：{{ scene.audio_track.emphasis_terms.join('、') }}</span>
        </div>
        <ul v-if="scene.audio_track.pause_cues.length || scene.audio_track.sound_cues.length" class="plain-list">
          <li v-for="cue in scene.audio_track.pause_cues" :key="`pause-${cue.offset_seconds}`">+{{ cue.offset_seconds }}s · 停顿 {{ cue.duration_seconds }}s · {{ cue.purpose }}</li>
          <li v-for="cue in scene.audio_track.sound_cues" :key="`sound-${cue.offset_seconds}`">+{{ cue.offset_seconds }}s · {{ cue.description }}</li>
        </ul>
      </section>

      <section class="track text-track">
        <h4><el-icon><ChatDotRound /></el-icon>字幕与屏显</h4>
        <div class="subtitle-stack">
          <p v-for="cue in scene.text_track.subtitle_chunks" :key="`${cue.start_offset_seconds}-${cue.end_offset_seconds}`">
            <time>{{ cue.start_offset_seconds }}—{{ cue.end_offset_seconds }}s</time>
            <span>{{ cue.text }}</span>
          </p>
        </div>
        <div v-if="scene.text_track.on_screen_text.length" class="screen-tags">
          <span v-for="item in scene.text_track.on_screen_text" :key="item">{{ item }}</span>
        </div>
      </section>

      <section class="track mapping-track">
        <h4><el-icon><Connection /></el-icon>教学映射</h4>
        <dl>
          <div><dt>教学环节</dt><dd>{{ scene.lesson_stage_id }}</dd></div>
          <div><dt>课程目标</dt><dd>{{ scene.objective_ids.join('、') }}</dd></div>
          <div><dt>知识点</dt><dd>{{ scene.knowledge_point_ids.join('、') }}</dd></div>
        </dl>
        <div v-if="scene.interaction" class="interaction-box">
          <b>{{ scene.interaction.prompt }}</b>
          <span>等待 {{ scene.interaction.wait_seconds }} 秒</span>
          <p>{{ scene.interaction.expected_response }}</p>
          <small>{{ scene.interaction.feedback_transition }}</small>
        </div>
        <ul v-if="scene.production_notes.length" class="plain-list notes">
          <li v-for="note in scene.production_notes" :key="note">{{ note }}</li>
        </ul>
      </section>
    </div>
  </article>
</template>

<style scoped>
.scene-card {
  margin-bottom: 22px;
  border: 1.5px solid #cbd5e1;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 4px 16px -4px rgba(15, 23, 42, 0.05);
  overflow: hidden;
  transition: all 0.2s ease;
}

.scene-card:hover {
  border-color: #94a3b8;
  box-shadow: 0 8px 24px -6px rgba(15, 23, 42, 0.08);
}

.scene-header {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr) auto;
  gap: 20px;
  padding: 22px 24px;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  border-bottom: 1px solid #e2e8f0;
}

.scene-index-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  border-radius: 12px;
  padding: 8px;
}

.index-num {
  font-size: 26px;
  line-height: 1;
  font-weight: 900;
  color: #4f46e5;
  font-variant-numeric: tabular-nums;
}

.index-label {
  font-size: 10px;
  font-weight: 800;
  color: #6366f1;
  margin-top: 2px;
}

.scene-labels {
  display: flex;
  gap: 8px;
  align-items: center;
}

.scene-id-pill {
  font-size: 11px;
  font-weight: 800;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}

.role-pill {
  padding: 3px 10px;
  color: #4f46e5;
  border: 1px solid #c7d2fe;
  background: #eef2ff;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 800;
}

.slide-pill {
  font-size: 11.5px;
  font-weight: 700;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 2px 8px;
  border-radius: 6px;
}

.scene-heading h3 {
  margin: 6px 0 4px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 900;
}

.learning-purpose {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
}

.scene-time {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  gap: 6px;
}

.time-range-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #0f172a;
  color: #ffffff;
  padding: 5px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.duration-tag {
  font-size: 11.5px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}

.scene-ruler {
  height: 4px;
  background: #e2e8f0;
}

.scene-ruler i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #6366f1 0%, #4f46e5 100%);
}

.track-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.track {
  min-width: 0;
  padding: 20px 24px;
  border-right: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
}

.track:nth-child(2n) { border-right: 0; }
.track:nth-child(3), .track:nth-child(4) { border-bottom: 0; }

.track h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.02em;
}

.composition-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
  color: #334155;
  font-size: 13px;
  line-height: 1.6;
  font-weight: 500;
}

blockquote {
  margin: 0;
  padding: 12px 16px;
  background: #eef2ff;
  border-left: 4px solid #4f46e5;
  border-radius: 0 8px 8px 0;
  color: #1e1b4b;
  font-size: 13.5px;
  line-height: 1.7;
  font-weight: 600;
}

.cue-list, .plain-list {
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.cue-list li {
  display: grid;
  grid-template-columns: 56px 1fr;
  gap: 4px 10px;
  padding: 8px 0;
  border-top: 1px dashed #e2e8f0;
  font-size: 12.5px;
}

.cue-list time {
  color: #4f46e5;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.cue-content b {
  color: #0f172a;
  font-weight: 700;
}

.cue-content span {
  display: block;
  color: #64748b;
  font-size: 12px;
  margin-top: 2px;
}

.track-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.meta-tag {
  font-size: 11.5px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
}

.meta-tag.tone {
  color: #0369a1;
  background: #e0f2fe;
  border: 1px solid #bae6fd;
}

.meta-tag.emphasis {
  color: #c2410c;
  background: #ffedd5;
  border: 1px solid #fed7aa;
}

.audio-cue-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
  margin-right: 6px;
}

.audio-cue-badge.pause {
  color: #7c2d12;
  background: #ffedd5;
}

.audio-cue-badge.sound {
  color: #431407;
  background: #fef3c7;
}

.subtitle-stack p {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 12px;
  margin: 0;
  padding: 8px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 12.5px;
}

.subtitle-stack time {
  color: #64748b;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.subtitle-stack span {
  color: #0f172a;
  font-weight: 600;
}

.screen-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
}

.tag-title {
  font-size: 11.5px;
  font-weight: 700;
  color: #64748b;
}

.on-screen-tag {
  padding: 3px 10px;
  border: 1.5px solid #cbd5e1;
  background: #ffffff;
  color: #1e293b;
  font-size: 11.5px;
  font-weight: 700;
  border-radius: 6px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.mapping-dl div {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 12.5px;
}

.mapping-dl dt { color: #64748b; font-weight: 600; }
.mapping-dl dd { margin: 0; color: #0f172a; font-weight: 700; }

.mapping-chip {
  background: #f1f5f9;
  color: #334155;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11.5px;
}

.interaction-box {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #f0fdf4;
  border: 1.5px solid #bbf7d0;
}

.interaction-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.interaction-head b {
  color: #166534;
  font-size: 13px;
}

.interaction-head span {
  color: #15803d;
  font-size: 11px;
  font-weight: 700;
  background: #dcfce7;
  padding: 2px 8px;
  border-radius: 6px;
}

.interaction-prompt {
  margin: 0 0 6px;
  color: #14532d;
  font-size: 13px;
  font-weight: 800;
}

.interaction-expected {
  margin: 0 0 4px;
  color: #166534;
  font-size: 12px;
}

.interaction-feedback {
  display: block;
  color: #15803d;
  font-size: 11.5px;
  font-style: italic;
}

.notes {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
}

@media (max-width: 900px) {
  .scene-header { grid-template-columns: 1fr; }
  .scene-time { align-items: flex-start; }
  .track-grid { grid-template-columns: 1fr; }
  .track { border-right: 0; border-bottom: 1px solid #e2e8f0; }
}
</style>
