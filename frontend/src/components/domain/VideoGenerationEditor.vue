<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { Lock, RefreshRight, VideoCamera } from '@element-plus/icons-vue';
import type { VideoGenerationContent, VideoGenerationScene } from '../../types';

const props = defineProps<{
  content: VideoGenerationContent;
  selectedSceneId?: string;
  busy?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  lock: [scene: VideoGenerationScene];
  regenerate: [sceneId: string, payload: Record<string, unknown>];
}>();

const selectedId = computed(() => props.selectedSceneId || props.content.scenes[0]?.id || '');
const draft = reactive({
  visual_prompt: '', visual_style: '', narration_text: '', subtitle_text: '',
  production_notes: '', instruction: '', duration_seconds: 1, visual: true, audio: false, subtitle: false,
});

const scene = computed(() => props.content.scenes.find(item => item.id === selectedId.value) || props.content.scenes[0]);

function hydrate() {
  if (!scene.value) return;
  draft.visual_prompt = scene.value.visual_prompt;
  draft.visual_style = scene.value.visual_style;
  draft.narration_text = scene.value.narration_text;
  draft.subtitle_text = scene.value.subtitle_text;
  draft.production_notes = scene.value.production_notes.join('\n');
  draft.duration_seconds = Math.max(1, scene.value.end_seconds - scene.value.start_seconds);
  draft.instruction = '';
  draft.visual = true;
  draft.audio = false;
  draft.subtitle = false;
}

function submit() {
  if (!scene.value) return;
  emit('regenerate', scene.value.id, {
    instruction: draft.instruction.trim() || '按当前编辑内容重新生成该分镜',
    visual_prompt: draft.visual_prompt.trim(),
    visual_style: draft.visual_style.trim(),
    narration_text: draft.narration_text.trim(),
    subtitle_text: draft.subtitle_text.trim(),
    production_notes: draft.production_notes.split('\n').map(item => item.trim()).filter(Boolean),
    duration_seconds: draft.duration_seconds,
    regenerate_visual: draft.visual,
    regenerate_audio: draft.audio,
    regenerate_subtitle: draft.subtitle,
    preserve_locked_content: true,
  });
}

watch(selectedId, hydrate, { immediate: true });
</script>

<template>
  <div v-if="scene" class="video-generation-editor">
    <header>
      <div><span>{{ scene.id }} · {{ scene.script_scene_id }}</span><h2>调整分镜 {{ String(scene.sequence).padStart(2, '0') }}</h2></div>
      <div><el-button :icon="Lock" :disabled="busy" @click="emit('lock', scene)">锁定分镜</el-button><el-button @click="emit('close')">关闭</el-button></div>
    </header>
    <main>
      <section class="edit-section visual-section">
        <h3><el-icon><VideoCamera /></el-icon>画面生成</h3>
        <label><span>画面提示词</span><el-input v-model="draft.visual_prompt" type="textarea" :rows="7" /></label>
        <label><span>视觉风格</span><el-input v-model="draft.visual_style" /></label>
        <label><span>制作备注（每行一项）</span><el-input v-model="draft.production_notes" type="textarea" :rows="4" /></label>
        <label><span>分镜时长（秒）</span><el-input-number v-model="draft.duration_seconds" :min="1" :max="600" :step="1" /></label>
      </section>
      <section class="edit-section voice-section">
        <h3>旁白与字幕</h3>
        <label><span>旁白</span><el-input v-model="draft.narration_text" type="textarea" :rows="6" /></label>
        <label><span>字幕</span><el-input v-model="draft.subtitle_text" type="textarea" :rows="4" /></label>
        <label><span>补充调整要求</span><el-input v-model="draft.instruction" type="textarea" :rows="3" placeholder="例如：画面改成实验室近景，保持原旁白" /></label>
      </section>
    </main>
    <footer>
      <div class="generation-options">
        <el-checkbox v-model="draft.visual">重新生成画面</el-checkbox>
        <el-checkbox v-model="draft.audio">重新生成语音</el-checkbox>
        <el-checkbox v-model="draft.subtitle">重新生成字幕</el-checkbox>
      </div>
      <el-button type="primary" :icon="RefreshRight" :loading="busy" :disabled="!draft.visual && !draft.audio && !draft.subtitle" @click="submit">生成新版本</el-button>
    </footer>
  </div>
</template>

<style scoped>
.video-generation-editor { min-height: 100%; padding: 22px; color: #111827; background: #f7f7f8; font-family: Helvetica Neue, Helvetica, Arial, sans-serif; }
.video-generation-editor > header { display: flex; justify-content: space-between; align-items: flex-start; padding: 20px 22px; border: 1px solid #cfd2d9; background: #fff; }
.video-generation-editor > header > div:last-child { display: flex; gap: 8px; }.video-generation-editor header span { color: #002fa7; font-size: 11px; font-weight: 800; letter-spacing: .06em; }
.video-generation-editor h2 { margin: 7px 0 0; font-size: 25px; letter-spacing: -.03em; }.video-generation-editor main { display: grid; grid-template-columns: 1.1fr .9fr; margin-top: 14px; border: 1px solid #cfd2d9; background: #fff; }
.edit-section { padding: 20px; }.edit-section + .edit-section { border-left: 1px solid #cfd2d9; }.edit-section h3 { display: flex; align-items: center; gap: 7px; margin: 0 0 18px; padding-bottom: 10px; border-bottom: 1px solid #cfd2d9; font-size: 14px; }
.edit-section label { display: grid; gap: 6px; margin-bottom: 14px; }.edit-section label > span { color: #555d68; font-size: 11px; font-weight: 800; }
.video-generation-editor > footer { display: flex; justify-content: space-between; align-items: center; padding: 15px 18px; border: 1px solid #cfd2d9; border-top: 0; background: #fff; }.generation-options { display: flex; flex-wrap: wrap; gap: 14px; }
:deep(.el-input__wrapper), :deep(.el-textarea__inner), :deep(.el-button) { border-radius: 0 !important; }
@media (max-width: 900px) { .video-generation-editor main { grid-template-columns: 1fr; }.edit-section + .edit-section { border-left: 0; border-top: 1px solid #cfd2d9; }.video-generation-editor > header, .video-generation-editor > footer { gap: 12px; flex-direction: column; align-items: stretch; } }
</style>
