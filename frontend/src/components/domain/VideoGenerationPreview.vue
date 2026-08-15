<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { Download, Edit, RefreshRight, VideoCamera } from '@element-plus/icons-vue';
import { api, errorMessage } from '../../api/client';
import type { VideoGenerationContent, VideoGenerationScene } from '../../types';

const props=defineProps<{content:VideoGenerationContent;version:number;disabled?:boolean}>();
const emit=defineEmits<{edit:[scene:VideoGenerationScene];recompose:[]}>();
const player=ref<HTMLVideoElement|null>(null),videoUrl=ref(''),subtitleUrl=ref(''),activeSceneId=ref(props.content.scenes[0]?.id||''),loading=ref(false),mediaError=ref('');
const activeScene=computed(()=>props.content.scenes.find(s=>s.id===activeSceneId.value)||props.content.scenes[0]);
const duration=computed(()=>props.content.outputs.duration_seconds||props.content.scenes.at(-1)?.end_seconds||0);
const money=(fen:number|undefined)=>`¥${((fen||0)/100).toFixed(2)}`;
const timecode=(seconds:number)=>`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.round(seconds%60)).padStart(2,'0')}`;
async function signedUrl(id?:string|null){if(!id)return '';const{data}=await api.post<{token:string}>(`/video-assets/${id}/token`);return `/api/v1/video-assets/${id}/stream?token=${encodeURIComponent(data.token)}`}
async function loadMedia(){loading.value=true;mediaError.value='';try{[videoUrl.value,subtitleUrl.value]=await Promise.all([signedUrl(props.content.outputs.preview_asset_id||props.content.outputs.final_asset_id),signedUrl(props.content.outputs.subtitle_asset_id)]);await nextTick();player.value?.load()}catch(e){mediaError.value=errorMessage(e)}finally{loading.value=false}}
function select(scene:VideoGenerationScene){activeSceneId.value=scene.id;if(player.value)player.value.currentTime=scene.start_seconds}
function sync(){const current=player.value?.currentTime||0;const found=props.content.scenes.find(s=>current>=s.start_seconds&&current<s.end_seconds);if(found)activeSceneId.value=found.id}
async function download(){const id=props.content.outputs.final_asset_id;if(!id)return;const{data}=await api.get(`/video-assets/${id}/download`,{responseType:'blob'});const url=URL.createObjectURL(data);const a=document.createElement('a');a.href=url;a.download=`Seedance微课_V${props.version}.mp4`;a.click();URL.revokeObjectURL(url)}
watch(()=>[props.content.outputs.preview_asset_id,props.content.outputs.final_asset_id],loadMedia);onMounted(loadMedia);
</script>

<template>
  <div class="native-preview">
    <header class="masthead"><div><span>SEEDANCE NATIVE / V{{ version }}</span><h1>原生有声分段微课</h1><p>视频脚本 V{{ content.source_versions.video_script }} · {{ content.production_settings.model_name }}</p></div><dl><div><dt>时长</dt><dd>{{ timecode(duration) }}</dd></div><div><dt>片段</dt><dd>{{ content.scenes.length }}</dd></div><div><dt>实耗</dt><dd>{{ money(Number(content.cost_summary.actual_cost_fen)) }}</dd></div><div><dt>规格</dt><dd>720p / 25fps</dd></div></dl></header>
    <section class="player-grid">
      <div class="player"><div v-if="loading" class="state"><el-icon class="is-loading"><VideoCamera/></el-icon>加载视频</div><video v-else-if="videoUrl" ref="player" controls playsinline @timeupdate="sync"><source :src="videoUrl" type="video/mp4"/><track v-if="subtitleUrl" kind="subtitles" srclang="zh" label="中文" :src="subtitleUrl" default/></video><div v-else class="state">{{ mediaError||'视频资源不可用' }}</div></div>
      <aside v-if="activeScene"><span>{{ activeScene.id }} / {{ activeScene.continuity_group }}</span><h2>片段 {{ String(activeScene.sequence).padStart(2,'0') }}</h2><div class="status" :class="activeScene.qa?.status">{{ activeScene.qa?.status==='passed'?'事实 QA 通过':'事实 QA 待处理' }}</div><label>计划口播</label><p>{{ activeScene.spoken_text }}</p><label>ASR 实际文本</label><p>{{ activeScene.actual_transcript||'尚未转写' }}</p><dl><div><dt>Provider 任务</dt><dd>{{ activeScene.provider_job_id||'复用缓存' }}</dd></div><div><dt>片段实耗</dt><dd>{{ money(activeScene.actual_cost_fen) }}</dd></div><div><dt>连续性依赖</dt><dd>{{ activeScene.reference_scene_ids.join('、')||'无' }}</dd></div></dl><el-button :icon="Edit" :disabled="disabled" @click="emit('edit',activeScene)">修改完整片段</el-button></aside>
    </section>
    <section class="cost-ruler"><header><div><span>COST-AWARE TIMELINE</span><b>费用确认尺</b></div><div><el-button size="small" :icon="RefreshRight" :disabled="disabled" @click="emit('recompose')">仅重新拼接 · ¥0</el-button><el-button size="small" type="primary" :icon="Download" @click="download">下载 MP4</el-button></div></header><div class="track"><button v-for="scene in content.scenes" :key="scene.id" :class="[scene.status,{active:scene.id===activeSceneId}]" :style="{flexGrow:Math.max(1,scene.end_seconds-scene.start_seconds)}" @click="select(scene)"><b>{{ String(scene.sequence).padStart(2,'0') }}</b><span>{{ (scene.end_seconds-scene.start_seconds).toFixed(1) }}s</span><em>{{ money(scene.actual_cost_fen) }}</em><small>{{ scene.qa?.status==='passed'?'QA ✓':scene.status }}</small></button></div></section>
  </div>
</template>

<style scoped>
.native-preview {
  min-height: 100%;
  padding: 24px;
  box-sizing: border-box;
  color: #1e293b;
  background: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

.masthead {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #1e293b 100%);
  border-radius: 18px;
  color: #ffffff;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
}

.masthead > div {
  padding: 24px 28px;
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}

.masthead span,
.cost-ruler header span,
aside > span,
aside label {
  color: #818cf8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.masthead h1 {
  margin: 6px 0 8px;
  font-size: 24px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.02em;
}

.masthead p {
  margin: 0;
  color: #94a3b8;
  font-size: 13px;
}

.masthead dl {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 0;
  background: rgba(255, 255, 255, 0.03);
}

.masthead dl div {
  padding: 16px 20px;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.masthead dl div:nth-child(2n) {
  border-right: 0;
}

.masthead dl div:nth-child(n+3) {
  border-bottom: 0;
}

dt {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

dd {
  margin: 4px 0 0;
  font-size: 16px;
  font-weight: 900;
  color: #f8fafc;
  word-break: break-all;
  font-variant-numeric: tabular-nums;
}

.player-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  margin-top: 18px;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  background: #ffffff;
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
}

.player {
  aspect-ratio: 16/9;
  background: #090d16;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.player video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.state {
  display: flex;
  height: 100%;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
}

.player-grid aside {
  padding: 20px 24px;
  border-left: 1.5px solid #e2e8f0;
  background: #fafbfc;
  display: flex;
  flex-direction: column;
}

.player-grid aside h2 {
  margin: 6px 0 10px;
  font-size: 18px;
  font-weight: 900;
  color: #0f172a;
}

.status {
  display: inline-block;
  margin-bottom: 14px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #fff1e8;
  color: #9b4514;
  font-size: 11px;
  font-weight: 800;
  width: fit-content;
}

.status.passed {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.player-grid aside label {
  display: block;
  margin-top: 10px;
  font-size: 10.5px;
  color: #64748b;
  font-weight: 800;
}

.player-grid aside p {
  margin: 4px 0 12px;
  color: #334155;
  font-size: 13px;
  line-height: 1.6;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  padding: 8px 12px;
  border-radius: 8px;
}

.player-grid aside dl {
  display: grid;
  gap: 8px;
  margin: 0 0 16px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}

.player-grid aside dl div {
  display: grid;
  grid-template-columns: 85px 1fr;
  gap: 8px;
  align-items: center;
}

.player-grid aside dd {
  font-size: 12px;
  color: #1e293b;
  font-weight: 700;
}

.cost-ruler {
  margin-top: 18px;
  padding: 18px 22px;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
}

.cost-ruler header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.cost-ruler header b {
  margin-left: 8px;
  font-size: 15px;
  font-weight: 900;
  color: #0f172a;
}

.track {
  display: flex;
  min-height: 84px;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  overflow: hidden;
  background: #f1f5f9;
}

.track button {
  min-width: 72px;
  padding: 10px 12px;
  border: 0;
  border-right: 1.5px solid #ffffff;
  background: #e0e7ff;
  color: #1e3a8a;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.track button:hover {
  background: #c7d2fe;
}

.track button.active {
  background: #4338ca;
  color: #ffffff;
  box-shadow: inset 0 0 0 2px #818cf8;
}

.track button.active span,
.track button.active small {
  color: #c7d2fe;
}

.track button.active em {
  color: #fef08a;
}

.track button.qa_failed,
.track button.failed {
  background: #fee2e2;
  color: #991b1b;
}

.track b,
.track span,
.track em,
.track small {
  display: block;
}

.track b {
  font-size: 13px;
  font-weight: 900;
}

.track span {
  margin: 4px 0 2px;
  font-size: 10.5px;
  font-weight: 700;
  opacity: 0.85;
}

.track em {
  font-size: 12px;
  font-style: normal;
  font-weight: 900;
  color: #1e40af;
}

.track small {
  margin-top: 4px;
  font-size: 9.5px;
  font-weight: 800;
  opacity: 0.85;
}

:deep(.el-button) {
  border-radius: 8px;
}

@media (max-width: 850px) {
  .masthead,
  .player-grid {
    grid-template-columns: 1fr;
  }
  .masthead > div {
    border-right: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  }
  .player-grid aside {
    border-left: 0;
    border-top: 1.5px solid #e2e8f0;
  }
}
</style>
