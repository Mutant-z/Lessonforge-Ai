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
  border: 1px solid #cfd2d9;
  border-radius: 0;
  padding: 12px 16px;
  box-shadow: none;
  transition: all 200ms var(--ease-out-smooth);
}

.agent-composer:focus-within {
  border-color: #002fa7;
  box-shadow: inset 3px 0 0 #002fa7;
}

textarea {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  color: var(--text-primary);
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
  padding: 6px 12px;
  border-radius: 0;
  cursor: pointer;
  font-weight: 700;
  font-size: 12px;
  transition: all var(--motion-fast);
}

.attach-btn:hover {
  color: #002fa7;
  background: #f2f5ff;
  border-color: #002fa7;
}

.key-hint {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 500;
}

.send-btn {
  border-radius: 0 !important;
  font-weight: 800 !important;
  padding: 8px 18px !important;
  background: #002fa7 !important;
  box-shadow: none !important;
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
  border-radius: 0;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 700;
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
  color: #002fa7;
}

.suggestion-row button {
  border: 1px solid #e0e7ff;
  background: #f5f3ff;
  color: #002fa7;
  border-radius: 0;
  padding: 2px 10px;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.suggestion-row button:hover {
  border-color: #002fa7;
  color: #ffffff;
  background: #002fa7;
}

@media (max-width: 640px) {
  .key-hint { display: none; }
  .composer-footer { flex-direction: column; align-items: stretch; }
  .composer-right { justify-content: flex-end; }
}
</style>
