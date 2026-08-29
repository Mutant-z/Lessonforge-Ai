<script setup lang="ts">
import { nextTick, ref, watch } from 'vue';
import { Paperclip, Promotion, MagicStick } from '@element-plus/icons-vue';
import ModelSelector from '../agent/ModelSelector.vue';

const props = withDefaults(defineProps<{
  disabled?: boolean;
  compact?: boolean;
  placeholder?: string;
  suggestions?: string[];
  modelConfigId?: string | null;
  modelDisabled?: boolean;
}>(), {
  disabled: false,
  compact: false,
  placeholder: '用自然语言描述微课主题、授课对象、时长和重点…',
  suggestions: () => [],
  modelConfigId: null,
  modelDisabled: false,
});

const emit = defineEmits<{
  send: [content: string, files: File[]];
  'update:modelConfigId': [value: string | null];
  modelChange: [value: string];
}>();

const content = ref('');
const files = ref<File[]>([]);
const inputRef = ref<HTMLInputElement>();
const textareaRef = ref<HTMLTextAreaElement>();

function adjustHeight() {
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto';
      const scrollHeight = textareaRef.value.scrollHeight;
      const targetHeight = Math.min(Math.max(scrollHeight, 38), 220);
      textareaRef.value.style.height = `${targetHeight}px`;
    }
  });
}

watch(content, adjustHeight);

function chooseFiles() {
  inputRef.value?.click();
}

function onFiles(event: Event) {
  const target = event.target as HTMLInputElement;
  if (target.files) files.value.push(...Array.from(target.files));
  target.value = '';
}

function submit() {
  const value = content.value.trim();
  if (!value || props.disabled) return;
  emit('send', value, [...files.value]);
  content.value = '';
  files.value = [];
  adjustHeight();
}

function applySuggestion(value: string) {
  content.value = content.value ? `${content.value}，${value}` : value;
  adjustHeight();
}

function setText(text: string) {
  content.value = text;
  adjustHeight();
}

function onKeydown(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    submit();
  }
}

defineExpose({
  setText,
});
</script>

<template>
  <div class="agent-composer" :class="{ compact, 'has-files': files.length > 0 }">
    <div v-if="suggestions.length" class="suggestion-row">
      <span class="sug-hint"><el-icon><MagicStick /></el-icon> 推荐对白:</span>
      <button v-for="item in suggestions" :key="item" type="button" :disabled="disabled" @click="applySuggestion(item)">
        + {{ item }}
      </button>
    </div>

    <textarea
      ref="textareaRef"
      v-model="content"
      :disabled="disabled"
      :placeholder="placeholder"
      rows="1"
      aria-label="描述微课需求"
      @keydown="onKeydown"
    />

    <div v-if="files.length" class="pending-files" aria-label="待上传附件">
      <span v-for="(file, index) in files" :key="`${file.name}-${index}`">
        <el-icon><Paperclip /></el-icon>
        {{ file.name }}
        <button type="button" aria-label="移除附件" @click="files.splice(index, 1)">×</button>
      </span>
    </div>

    <div class="composer-footer">
      <div class="composer-left">
        <ModelSelector
          :model-value="modelConfigId"
          :disabled="disabled || modelDisabled"
          compact
          label="主模型"
          @update:model-value="emit('update:modelConfigId', $event)"
          @change="emit('modelChange', $event)"
        />
        <input
          ref="inputRef"
          type="file"
          multiple
          accept=".pdf,.docx,.pptx,.txt,.md,.markdown"
          hidden
          @change="onFiles"
        />
        <button type="button" class="attach-btn" :disabled="disabled" @click="chooseFiles">
          <el-icon><Paperclip /></el-icon>
          <span>上传教案/材料</span>
        </button>
      </div>

      <div class="composer-right">
        <span class="key-hint">Shift+Enter 换行 | Enter 发送</span>
        <el-button
          type="primary"
          class="send-btn"
          :icon="Promotion"
          :disabled="disabled || !content.trim()"
          @click="submit"
        >
          发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-composer {
  background: #ffffff;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  padding: 12px 16px;
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.05));
  transition: all var(--motion-normal, 240ms) var(--ease-out-smooth, ease);
}

.agent-composer:focus-within {
  border-color: var(--primary-500, #6366f1);
  box-shadow: var(--shadow-glow-primary, 0 8px 24px rgba(99, 102, 241, 0.15)), 0 0 0 2px rgba(99, 102, 241, 0.2);
}

textarea {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  color: var(--text-primary, #0f172a);
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  background: transparent;
  padding: 4px 0;
  min-height: 38px;
  max-height: 220px;
  overflow-y: auto;
  box-sizing: border-box;
  transition: height 120ms ease-out;
}

textarea::placeholder {
  color: #94a3b8;
  font-weight: 400;
}

.compact textarea { min-height: 44px; }

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 10px;
  margin-top: 6px;
  border-top: 1px solid #f1f5f9;
}

.composer-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}

.composer-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.attach-btn {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: var(--radius-pill, 999px);
  cursor: pointer;
  font-weight: 600;
  font-size: 12px;
  transition: all var(--motion-fast, 150ms);
}

.attach-btn:hover {
  color: var(--primary-600, #4f46e5);
  background: var(--primary-50, #eef2ff);
  border-color: var(--primary-200, #c7d2fe);
}

.key-hint {
  color: #94a3b8;
  font-size: 11.5px;
  font-weight: 500;
}

.send-btn {
  border-radius: var(--radius-pill, 999px) !important;
  font-weight: 700 !important;
  padding: 8px 20px !important;
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%) !important;
  border: 0 !important;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25) !important;
  transition: all 200ms ease !important;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(79, 70, 229, 0.35) !important;
}

.pending-files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  margin-bottom: 4px;
}

.pending-files span {
  border: 1px solid #c7d2fe;
  background: #eef2ff;
  color: #3730a3;
  border-radius: var(--radius-pill, 999px);
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.pending-files button {
  border: 0;
  background: rgba(99, 102, 241, 0.2);
  color: #3730a3;
  cursor: pointer;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  line-height: 1;
}

.suggestion-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.sug-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--primary-600, #4f46e5);
}

.suggestion-row button {
  border: 1px solid #e0e7ff;
  background: #f8fafc;
  color: #4338ca;
  border-radius: var(--radius-pill, 999px);
  padding: 3px 12px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--motion-fast, 150ms);
}

.suggestion-row button:hover {
  border-color: #c7d2fe;
  color: #4338ca;
  background: #eef2ff;
  transform: translateY(-1px);
}

@media (max-width: 640px) {
  .key-hint { display: none; }
  .composer-footer { flex-direction: column; align-items: stretch; }
  .composer-right { justify-content: flex-end; }
}
</style>
