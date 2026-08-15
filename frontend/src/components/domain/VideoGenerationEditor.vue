<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { RefreshRight } from '@element-plus/icons-vue';
import type { VideoGenerationContent, VideoGenerationScene } from '../../types';

const props = defineProps<{ content: VideoGenerationContent; selectedSceneId?: string; busy?: boolean }>();
const emit = defineEmits<{ close: []; regenerate: [sceneId: string, payload: Record<string, unknown>] }>();
const scene = computed(() => props.content.scenes.find(item => item.id === props.selectedSceneId) || props.content.scenes[0]);
const draft = reactive({ visual_prompt:'',spoken_text:'',voice_direction:'',instruction:'',duration_seconds:8,include_dependents:false });
function hydrate(){if(!scene.value)return;draft.visual_prompt=scene.value.visual_prompt;draft.spoken_text=scene.value.spoken_text;draft.voice_direction=scene.value.voice_direction;draft.duration_seconds=scene.value.end_seconds-scene.value.start_seconds;draft.instruction='';draft.include_dependents=false}
function submit(){if(!scene.value)return;emit('regenerate',scene.value.id,{instruction:draft.instruction.trim()||'按当前编辑内容重新生成完整原生音视频片段',visual_prompt:draft.visual_prompt.trim(),spoken_text:draft.spoken_text.trim(),voice_direction:draft.voice_direction.trim(),duration_seconds:draft.duration_seconds,include_dependents:draft.include_dependents})}
watch(()=>props.selectedSceneId,hydrate,{immediate:true});
</script>

<template>
  <div v-if="scene" class="native-editor">
    <header><div><span>{{ scene.id }} / {{ scene.script_scene_id }}</span><h2>调整完整原生音视频片段</h2></div><el-button @click="emit('close')">关闭</el-button></header>
    <div class="notice"><b>计费边界</b><p>保存前会重新报价。仅当前片段生成新的 Seedance 任务；画面与语音必须一起重生，字幕会从新音轨重新转写。</p></div>
    <main>
      <label><span>画面提示词</span><el-input v-model="draft.visual_prompt" type="textarea" :rows="7" /></label>
      <label><span>模型原生口播</span><el-input v-model="draft.spoken_text" type="textarea" :rows="6" /></label>
      <label><span>声音指导</span><el-input v-model="draft.voice_direction" type="textarea" :rows="3" /></label>
      <div class="row"><label><span>片段时长</span><el-input-number v-model="draft.duration_seconds" :min="4" :max="15" :step="1" /></label><label><span>连续性</span><el-checkbox v-model="draft.include_dependents">同时重生同组后续依赖片段</el-checkbox></label></div>
      <label><span>补充要求</span><el-input v-model="draft.instruction" type="textarea" :rows="3" placeholder="例如：教师动作更克制，数字和单位必须清楚说出" /></label>
    </main>
    <footer><span>原资源会保留，可从版本历史回滚。</span><el-button type="primary" :icon="RefreshRight" :loading="busy" @click="submit">估算本次修改费用</el-button></footer>
  </div>
</template>

<style scoped>
.native-editor{min-height:100%;padding:22px;box-sizing:border-box;color:#111318;background:#f5f5f3;font-family:Helvetica Neue,Helvetica,Arial,sans-serif}.native-editor>header{display:flex;justify-content:space-between;align-items:flex-start;padding:20px;border:1px solid #b9bdc5;background:#fff}.native-editor header span,.native-editor label>span,.notice b{color:#002fa7;font-size:10px;font-weight:800;letter-spacing:.09em;text-transform:uppercase}.native-editor h2{margin:7px 0 0;font-size:24px}.notice{display:grid;grid-template-columns:110px 1fr;margin-top:12px;padding:13px 16px;border:1px solid #9eb2e9;background:#eef3ff}.notice p{margin:0;color:#33425f;font-size:12px;line-height:1.6}.native-editor main{display:grid;gap:15px;margin-top:12px;padding:20px;border:1px solid #b9bdc5;background:#fff}.native-editor label{display:grid;gap:6px}.row{display:grid;grid-template-columns:1fr 1fr;gap:16px}.native-editor>footer{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;border:1px solid #b9bdc5;border-top:0;background:#fff}.native-editor>footer span{color:#656a73;font-size:11px}:deep(.el-input__wrapper),:deep(.el-textarea__inner),:deep(.el-button),:deep(.el-input-number){border-radius:0!important}.el-input-number{width:100%}@media(max-width:720px){.row{grid-template-columns:1fr}.native-editor>footer{align-items:stretch;flex-direction:column;gap:10px}}
</style>
