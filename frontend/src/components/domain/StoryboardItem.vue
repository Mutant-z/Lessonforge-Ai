<script setup lang="ts">
import { computed } from 'vue';
import type { VideoScene } from '../../types';
const props=defineProps<{scene:VideoScene;totalSeconds:number}>();
const duration=computed(()=>props.scene.end_seconds-props.scene.start_seconds);
const width=computed(()=>`${Math.max(4,duration.value/Math.max(1,props.totalSeconds)*100)}%`);
const timecode=(seconds:number)=>`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.round(seconds%60)).padStart(2,'0')}`;
</script>
<template>
  <article class="scene-card">
    <header><b>{{ String(scene.sequence).padStart(2,'0') }}</b><div><span>{{ scene.id }} / {{ scene.continuity_group }}</span><h3>{{ scene.title }}</h3></div><strong>{{ timecode(scene.start_seconds) }}—{{ timecode(scene.end_seconds) }}</strong></header>
    <div class="ruler"><i :style="{width}"/></div>
    <main><section><label>画面提示词</label><p>{{ scene.visual_prompt }}</p><ol><li v-for="beat in scene.camera_beats" :key="beat.start_offset_seconds">+{{ beat.start_offset_seconds }}–{{ beat.end_offset_seconds }}s · {{ beat.instruction }}</li></ol></section><section><label>模型原生口播</label><blockquote>{{ scene.spoken_text }}</blockquote><small>{{ scene.voice_direction }}</small></section><section><label>教学事实基准</label><p>{{ scene.required_facts.join('；') }}</p><div><span v-for="term in scene.required_terms" :key="term">{{ term }}</span><span v-for="number in scene.required_numbers" :key="number">{{ number }}</span></div></section></main>
  </article>
</template>
<style scoped>
.scene-card{margin-bottom:14px;border:1px solid #bec1c7;background:#fff;color:#15171b}.scene-card>header{display:grid;grid-template-columns:50px 1fr auto;gap:14px;align-items:center;padding:14px;border-bottom:1px solid #d9dbe0}.scene-card>header>b{color:#002fa7;font-size:22px}.scene-card header span,label{color:#002fa7;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.scene-card h3{margin:4px 0 0}.scene-card>header strong{font-size:11px}.ruler{height:3px;background:#e5e7eb}.ruler i{display:block;height:100%;background:#002fa7}.scene-card main{display:grid;grid-template-columns:1.1fr 1fr 1fr}.scene-card section{padding:15px}.scene-card section+section{border-left:1px solid #d9dbe0}.scene-card p,.scene-card blockquote{margin:7px 0;color:#434a54;font-size:12px;line-height:1.6}.scene-card blockquote{padding-left:10px;border-left:2px solid #002fa7}.scene-card ol{padding-left:18px;color:#646a73;font-size:10px}.scene-card section div{display:flex;gap:5px;flex-wrap:wrap}.scene-card section div span{padding:3px 6px;background:#e8eeff;color:#18377d;font-size:9px}@media(max-width:750px){.scene-card main{grid-template-columns:1fr}.scene-card section+section{border-left:0;border-top:1px solid #d9dbe0}}
</style>
