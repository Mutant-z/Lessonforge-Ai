<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { Close, Film, InfoFilled, Microphone, RefreshRight, VideoCamera } from '@element-plus/icons-vue';
import type { VideoGenerationContent, VideoGenerationScene } from '../../types';

const props = defineProps<{ 
  content: VideoGenerationContent; 
  selectedSceneId?: string; 
  busy?: boolean 
}>();

const emit = defineEmits<{ 
  close: []; 
  regenerate: [sceneId: string, payload: Record<string, unknown>] 
}>();

const scene = computed(() => 
  props.content.scenes.find(item => item.id === props.selectedSceneId) || props.content.scenes[0]
);

const draft = reactive({ 
  visual_prompt: '',
  spoken_text: '',
  voice_direction: '',
  instruction: '',
  duration_seconds: 8,
  include_dependents: false 
});

function hydrate() {
  if (!scene.value) return;
  draft.visual_prompt = scene.value.visual_prompt;
  draft.spoken_text = scene.value.spoken_text;
  draft.voice_direction = scene.value.voice_direction;
  draft.duration_seconds = scene.value.end_seconds - scene.value.start_seconds;
  draft.instruction = '';
  draft.include_dependents = false;
}

function submit() {
  if (!scene.value) return;
  emit('regenerate', scene.value.id, {
    instruction: draft.instruction.trim() || '按当前编辑内容重新生成完整原生音视频片段',
    visual_prompt: draft.visual_prompt.trim(),
    spoken_text: draft.spoken_text.trim(),
    voice_direction: draft.voice_direction.trim(),
    duration_seconds: draft.duration_seconds,
    include_dependents: draft.include_dependents
  });
}

watch(() => props.selectedSceneId, hydrate, { immediate: true });
</script>

<template>
  <div v-if="scene" class="native-editor">
    <!-- Header -->
    <header class="editor-header">
      <div class="header-info">
        <span class="scene-badge">
          <el-icon><Film /></el-icon>
          分镜 #{{ scene.sequence }}
        </span>
        <h2>调整分镜画面与口播</h2>
      </div>
      <el-button class="btn-close" :icon="Close" circle @click="emit('close')" />
    </header>

    <!-- Notice Banner -->
    <div class="editor-notice">
      <el-icon class="notice-icon"><InfoFilled /></el-icon>
      <div class="notice-text">
        <b>重构说明</b>
        <p>确认修改后，本片段的画面与伴生语音将一并重新生成，中文字幕将自动对齐更新。</p>
      </div>
    </div>

    <!-- Form Main Content -->
    <main class="editor-form">
      <div class="form-item">
        <label class="form-label">
          <el-icon><VideoCamera /></el-icon>
          <span>画面视觉提示词 (Visual Prompt)</span>
        </label>
        <el-input 
          v-model="draft.visual_prompt" 
          type="textarea" 
          :rows="5" 
          placeholder="描述分镜中的主体、场景布置、运镜方式、动作与板书设计…"
        />
      </div>

      <div class="form-item">
        <label class="form-label">
          <el-icon><Microphone /></el-icon>
          <span>口播台词内容 (Spoken Text)</span>
        </label>
        <el-input 
          v-model="draft.spoken_text" 
          type="textarea" 
          :rows="4" 
          placeholder="教师在当前分镜中的口播台词…"
        />
      </div>

      <div class="form-item">
        <label class="form-label">
          <span>声音指导与语气 (Voice Direction)</span>
        </label>
        <el-input 
          v-model="draft.voice_direction" 
          type="textarea" 
          :rows="2" 
          placeholder="例如：沉稳自信，重点公式处语速放慢，语气充满启发性"
        />
      </div>

      <div class="form-row-dual">
        <div class="form-item">
          <label class="form-label">
            <span>分镜预定时长 (秒)</span>
          </label>
          <el-input-number 
            v-model="draft.duration_seconds" 
            :min="4" 
            :max="15" 
            :step="1" 
            class="duration-input"
          />
        </div>

        <div class="form-item checkbox-wrap">
          <label class="form-label">
            <span>连贯性处理</span>
          </label>
          <div class="checkbox-container">
            <el-checkbox v-model="draft.include_dependents">
              同步重新生成同组依赖的后续镜头
            </el-checkbox>
          </div>
        </div>
      </div>

      <div class="form-item">
        <label class="form-label">
          <span>补充指令或调整说明</span>
        </label>
        <el-input 
          v-model="draft.instruction" 
          type="textarea" 
          :rows="2" 
          placeholder="例如：教师手势更克制，数字与单位清晰发音" 
        />
      </div>
    </main>

    <!-- Footer Action Bar -->
    <footer class="editor-footer">
      <span class="footer-tip">💡 原视频资源将保留在版本历史中，随时可恢复回滚。</span>
      <div class="footer-actions">
        <el-button @click="emit('close')">取消</el-button>
        <el-button 
          type="primary" 
          :icon="RefreshRight" 
          :loading="busy" 
          class="btn-submit"
          @click="submit"
        >
          确认修改并重新生成
        </el-button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.native-editor {
  min-height: 100%;
  padding: 20px 24px 36px;
  box-sizing: border-box;
  color: var(--text-primary, #0f172a);
  background: var(--bg-page, #f5f7fa);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Header */
.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
}

.header-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.scene-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 800;
  color: var(--primary-600, #4f46e5);
  background: var(--primary-50, #eef2ff);
  padding: 3px 10px;
  border-radius: var(--radius-pill, 999px);
  border: 1px solid var(--color-primary-border, #c7d2fe);
}

.editor-header h2 {
  margin: 0;
  font-size: 16.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.btn-close {
  background: #f1f5f9;
  border: none;
  color: #64748b;
}

.btn-close:hover {
  background: #e2e8f0;
  color: #0f172a;
}

/* Notice */
.editor-notice {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 16px;
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--color-primary-border, #c7d2fe);
  border-radius: var(--radius-control, 12px);
}

.notice-icon {
  font-size: 18px;
  color: var(--primary-600, #4f46e5);
  margin-top: 2px;
  flex-shrink: 0;
}

.notice-text b {
  display: block;
  font-size: 12px;
  color: var(--primary-700, #4338ca);
  margin-bottom: 2px;
}

.notice-text p {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary, #475569);
  line-height: 1.5;
}

/* Form */
.editor-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary, #334155);
}

.form-row-dual {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.duration-input {
  width: 100%;
}

.checkbox-wrap {
  justify-content: flex-end;
}

.checkbox-container {
  height: 40px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-control, 12px);
}

:deep(.el-textarea__inner),
:deep(.el-input__wrapper) {
  border-radius: var(--radius-control, 12px) !important;
  box-shadow: 0 0 0 1px var(--border-default, #e2e8f0) inset !important;
}

:deep(.el-textarea__inner:focus),
:deep(.el-input__wrapper.is-focused) {
  box-shadow: 0 0 0 2px var(--primary-500, #6366f1) inset !important;
}

/* Footer */
.editor-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
  flex-wrap: wrap;
  gap: 12px;
}

.footer-tip {
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.footer-actions :deep(.el-button) {
  border-radius: var(--radius-pill, 999px) !important;
}

.btn-submit {
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%) !important;
  border: none !important;
}

@media (max-width: 720px) {
  .form-row-dual {
    grid-template-columns: 1fr;
  }
  .editor-footer {
    flex-direction: column;
    align-items: stretch;
  }
  .footer-actions {
    justify-content: flex-end;
  }
}
</style>

