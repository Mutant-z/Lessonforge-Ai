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
.scene-card { margin-bottom: 18px; border: 1px solid #d8dde7; background: #fff; }
.scene-header { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 18px; padding: 20px; border-bottom: 1px solid #d8dde7; }
.scene-index { font-size: 34px; line-height: 1; font-weight: 800; color: #002fa7; font-variant-numeric: tabular-nums; }
.scene-labels { display: flex; gap: 8px; align-items: center; color: #6b7280; font-size: 11px; }
.scene-labels b { padding: 3px 7px; color: #002fa7; border: 1px solid #9eb4ea; background: #eef3ff; }
.scene-heading h3 { margin: 7px 0 4px; color: #111827; font-size: 18px; }
.scene-heading p { margin: 0; color: #5b6472; font-size: 13px; }
.scene-time { display: grid; grid-template-columns: auto auto; align-content: center; gap: 4px 7px; color: #24324a; font-variant-numeric: tabular-nums; }
.scene-time small { grid-column: 2; color: #7c8492; text-align: right; }
.scene-ruler { height: 3px; background: #e8ebf1; }
.scene-ruler i { display: block; height: 100%; background: #002fa7; }
.track-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.track { min-width: 0; padding: 18px 20px; border-right: 1px solid #e1e5ec; border-bottom: 1px solid #e1e5ec; }
.track:nth-child(2n) { border-right: 0; }
.track h4 { display: flex; align-items: center; gap: 7px; margin: 0 0 12px; color: #24324a; font-size: 12px; letter-spacing: .04em; }
.track > p, blockquote { margin: 0; color: #3e4653; font-size: 13px; line-height: 1.75; }
blockquote { padding-left: 14px; border-left: 3px solid #002fa7; color: #162750; }
.cue-list, .plain-list { margin: 13px 0 0; padding: 0; list-style: none; }
.cue-list li { display: grid; grid-template-columns: 52px 1fr; gap: 3px 8px; padding: 8px 0; border-top: 1px solid #edf0f4; font-size: 12px; }
.cue-list time { color: #002fa7; font-variant-numeric: tabular-nums; }
.cue-list span { grid-column: 2; color: #737b88; }
.track-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 12px; color: #687181; font-size: 12px; }
.plain-list li { padding: 4px 0; color: #687181; font-size: 12px; line-height: 1.5; }
.subtitle-stack p { display: grid; grid-template-columns: 94px 1fr; margin: 0; padding: 7px 0; border-bottom: 1px solid #edf0f4; font-size: 12px; }
.subtitle-stack time { color: #7b8492; font-variant-numeric: tabular-nums; }
.subtitle-stack span { color: #202938; }
.screen-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.screen-tags span { padding: 4px 7px; border: 1px solid #ccd5e6; color: #31415f; font-size: 11px; }
dl { margin: 0; }
dl div { display: grid; grid-template-columns: 72px 1fr; gap: 8px; padding: 6px 0; border-bottom: 1px solid #edf0f4; font-size: 12px; }
dt { color: #7b8492; } dd { margin: 0; color: #25324a; }
.interaction-box { margin-top: 12px; padding: 12px; border-left: 3px solid #002fa7; background: #f4f7ff; }
.interaction-box b, .interaction-box p, .interaction-box small { display: block; margin: 0 0 5px; color: #24324a; font-size: 12px; line-height: 1.55; }
.interaction-box span { color: #002fa7; font-size: 11px; }
.interaction-box small { margin: 5px 0 0; color: #687181; }
.notes { padding-top: 8px; border-top: 1px solid #edf0f4; }
@media (max-width: 900px) {
  .scene-header { grid-template-columns: 48px 1fr; }
  .scene-time { grid-column: 2; justify-content: start; }
  .track-grid { grid-template-columns: 1fr; }
  .track { border-right: 0; }
}
</style>
