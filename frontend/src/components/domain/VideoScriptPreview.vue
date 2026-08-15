<script setup lang="ts">
import { computed } from 'vue';
import type { VideoScriptContent } from '../../types';

const props = defineProps<{ content: VideoScriptContent; sourceVersions?: Record<string, number> }>();
const total = computed(() => props.content.production_settings.target_duration_seconds);
const words = computed(() => props.content.scenes.reduce((sum, scene) => sum + scene.spoken_text.length, 0));
const groups = computed(() => new Set(props.content.scenes.map(scene => scene.continuity_group)).size);
const timecode = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
</script>

<template>
  <div class="seedance-script">
    <header class="masthead">
      <div><span>VIDEO SCRIPT / V3</span><h1>{{ content.course_info.course_title }}</h1><p>Doubao-Seedance-2.5 原生有声分段脚本</p></div>
      <dl>
        <div><dt>总时长</dt><dd>{{ timecode(total) }}</dd></div>
        <div><dt>原生片段</dt><dd>{{ content.scenes.length }}</dd></div>
        <div><dt>连续性组</dt><dd>{{ groups }}</dd></div>
        <div><dt>口播字数</dt><dd>{{ words }}</dd></div>
      </dl>
    </header>

    <section class="contract">
      <b>生产契约</b><span>16:9</span><span>720p</span><span>{{ content.production_settings.min_clip_seconds }}–{{ content.production_settings.max_clip_seconds }} 秒/段</span><span>模型原生语音</span><span>字幕由 ASR 生成</span><small>教学设计 V{{ sourceVersions?.lesson_plan || '—' }}</small>
    </section>

    <div class="timeline">
      <div v-for="scene in content.scenes" :key="scene.id" :style="{ flexGrow: scene.end_seconds - scene.start_seconds }">
        <b>{{ String(scene.sequence).padStart(2, '0') }}</b><span>{{ scene.pedagogical_role }}</span><small>{{ (scene.end_seconds - scene.start_seconds).toFixed(0) }}s</small>
      </div>
    </div>

    <section class="scene-grid">
      <article v-for="scene in content.scenes" :key="scene.id">
        <header><span>{{ scene.id }} / {{ scene.continuity_group }}</span><b>{{ timecode(scene.start_seconds) }}—{{ timecode(scene.end_seconds) }}</b></header>
        <h2>{{ scene.title }}</h2>
        <div class="scene-body">
          <div><label>画面与动作</label><p>{{ scene.visual_prompt }}</p></div>
          <div><label>模型原生口播</label><p>{{ scene.spoken_text }}</p></div>
        </div>
        <footer>
          <span v-for="term in scene.required_terms" :key="term">术语 · {{ term }}</span>
          <span v-for="number in scene.required_numbers" :key="number">数字 · {{ number }}</span>
          <span>声音 · {{ scene.voice_direction }}</span>
        </footer>
      </article>
    </section>
  </div>
</template>

<style scoped>
.seedance-script { min-height: 100%; padding: 24px; box-sizing: border-box; color: #111318; background: #f5f5f3; font-family: Helvetica Neue, Helvetica, Arial, sans-serif; }
.masthead { display: grid; grid-template-columns: 1.2fr 1fr; background: #fff; border: 1px solid #babdc4; }
.masthead > div { padding: 28px; border-right: 1px solid #babdc4; }.masthead span,.contract b,article header span,label { color: #002fa7; font-size: 10px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
.masthead h1 { margin: 9px 0 5px; font-size: 30px; line-height: 1.05; letter-spacing: -.04em; }.masthead p { margin: 0; color: #656a73; font-size: 13px; }
.masthead dl { display: grid; grid-template-columns: 1fr 1fr; margin: 0; }.masthead dl div { padding: 17px; border-right: 1px solid #d9dbe0; border-bottom: 1px solid #d9dbe0; }.masthead dl div:nth-child(2n){border-right:0}.masthead dl div:nth-child(n+3){border-bottom:0}.masthead dt{color:#6b7079;font-size:10px}.masthead dd{margin:4px 0 0;font-size:18px;font-weight:800;font-variant-numeric:tabular-nums}
.contract { display: flex; align-items: center; gap: 8px; margin-top: 14px; padding: 12px 14px; border: 1px solid #babdc4; background: #fff; flex-wrap: wrap; }.contract span { padding: 4px 8px; color:#18377d;background:#e7edff;font-size:11px;font-weight:700}.contract small{margin-left:auto;color:#6b7079}
.timeline { display:flex; min-height:66px; margin-top:14px; border:1px solid #8f949e; background:#fff; overflow:auto}.timeline div{min-width:62px;padding:9px;border-right:1px solid #fff;background:#dfe8ff;color:#18377d}.timeline div:nth-child(even){background:#cbd9ff}.timeline b,.timeline span,.timeline small{display:block}.timeline span{margin:5px 0;font-size:10px}.timeline small{font-size:10px}
.scene-grid { display:grid; gap:12px; margin-top:14px }.scene-grid article{border:1px solid #babdc4;background:#fff}.scene-grid article>header{display:flex;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #d9dbe0}.scene-grid article>header b{font-size:11px;font-variant-numeric:tabular-nums}.scene-grid h2{margin:0;padding:14px 16px 0;font-size:18px}.scene-body{display:grid;grid-template-columns:1fr 1fr}.scene-body>div{padding:14px 16px}.scene-body>div+div{border-left:1px solid #d9dbe0}.scene-body p{margin:7px 0 0;color:#3f4652;font-size:13px;line-height:1.65}.scene-grid footer{display:flex;gap:6px;padding:10px 14px;border-top:1px solid #d9dbe0;flex-wrap:wrap}.scene-grid footer span{padding:3px 7px;background:#f0f1f3;color:#565d67;font-size:10px}
@media(max-width:820px){.masthead,.scene-body{grid-template-columns:1fr}.masthead>div{border-right:0;border-bottom:1px solid #babdc4}.scene-body>div+div{border-left:0;border-top:1px solid #d9dbe0}}
</style>
