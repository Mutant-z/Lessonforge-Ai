<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { Close, Loading, MagicStick, Promotion, VideoPause } from '@element-plus/icons-vue';
import ModelSelector from '../ModelSelector.vue';

const props = defineProps<{
  targetSlide?: number | null;
  isRunning?: boolean;
  modelConfigId?: string | null;
  pauseLoading?: boolean;
}>();

const emit = defineEmits<{
  (e: 'send', text: string): void;
  (e: 'pause'): void;
  (e: 'clear-target-slide'): void;
  (e: 'change-model', modelId: string): void;
}>();

const input = ref('');
const inputRef = ref<HTMLTextAreaElement | null>(null);

const quickPrompts = [
  '优化教学目标与重难点表达',
  '增加课堂互动与提问环节设计',
  '精简课件页面文字与层级',
  '补充教学案例与情境导入',
  '润色 PPT 整体风格与排版配比',
];

function adjustHeight() {
  nextTick(() => {
    if (inputRef.value) {
      inputRef.value.style.height = 'auto';
      const scrollHeight = inputRef.value.scrollHeight;
      const targetHeight = Math.min(Math.max(scrollHeight, 48), 160);
      inputRef.value.style.height = `${targetHeight}px`;
    }
  });
}

watch(input, adjustHeight);

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSubmit();
  }
}

function applyQuickPrompt(promptText: string) {
  if (props.isRunning) return;
  if (input.value.trim()) {
    input.value = `${input.value.trim()}，${promptText}`;
  } else {
    input.value = promptText;
  }
  nextTick(() => {
    inputRef.value?.focus();
  });
}

function handleButtonClick() {
  if (props.isRunning) {
    if (props.pauseLoading) return;
    emit('pause');
    return;
  }
  handleSubmit();
}

function handleSubmit() {
  const rawText = input.value.trim();
  if (!rawText || props.isRunning) return;

  let finalText = rawText;
  if (props.targetSlide !== undefined && props.targetSlide !== null && props.targetSlide >= 0) {
    finalText = `[针对第 ${props.targetSlide + 1} 页] ${rawText}`;
  }

  emit('send', finalText);
  input.value = '';
  adjustHeight();
}

function clearSlideTarget() {
  emit('clear-target-slide');
}
</script>

<template>
  <div class="agent-composer-container" :class="{ disabled: isRunning }">
    <div class="composer-card">
      <!-- Quick Prompts Row (Top Suggestions) -->
      <div class="composer-quick-bar">
        <span class="quick-label">
          <el-icon><MagicStick /></el-icon> 建议：
        </span>
        <div class="quick-chips">
          <button
            v-for="chip in quickPrompts"
            :key="chip"
            type="button"
            class="quick-chip-btn"
            :disabled="isRunning"
            @click="applyQuickPrompt(chip)"
          >
            + {{ chip }}
          </button>
        </div>
      </div>

      <!-- Active Target Slide Context Chip -->
      <div v-if="targetSlide !== undefined && targetSlide !== null && targetSlide >= 0" class="slide-target-chip">
        <span class="chip-dot" />
        <span>已定位：<strong>第 {{ targetSlide + 1 }} 页</strong></span>
        <button type="button" class="clear-target-btn" title="清除页面定位" @click="clearSlideTarget">
          <el-icon><Close /></el-icon>
        </button>
      </div>

      <!-- Textarea Input Box (Middle) -->
      <div class="composer-input-wrapper">
        <textarea
          ref="inputRef"
          v-model="input"
          rows="2"
          :disabled="isRunning"
          :placeholder="isRunning ? 'Agent 正在推演 PPT 页面，请稍候…' : (targetSlide !== undefined && targetSlide !== null && targetSlide >= 0 ? `详细描述您希望如何修改 第 ${targetSlide + 1} 页 PPT 课件…` : '详细描述您希望如何修改 PPT 课件…')"
          @keydown="onKeydown"
        />
      </div>

      <!-- Bottom Actions Bar (Bottom Toolbar) -->
      <div class="composer-bottom-bar">
        <div class="bottom-left">
          <ModelSelector
            :model-value="modelConfigId || null"
            compact
            label=""
            :disabled="isRunning"
            @change="emit('change-model', $event)"
          />
        </div>
        <div class="bottom-right">
          <span class="tip-key">Shift+Enter 换行</span>
          <button
            type="button"
            class="send-circle-btn"
            :class="{ 'is-pausing': isRunning }"
            :disabled="isRunning ? pauseLoading : !input.trim()"
            :title="isRunning ? '暂停 Agent 推演' : '发送修改指令'"
            @click="handleButtonClick"
          >
            <el-icon v-if="pauseLoading" class="is-loading"><Loading /></el-icon>
            <el-icon v-else-if="isRunning"><VideoPause /></el-icon>
            <el-icon v-else><Promotion /></el-icon>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-composer-container {
  padding: 10px 14px;
  background: #f8fafc;
  border-top: 1px solid var(--border-default, #e2e8f0);
  position: relative;
  transition: opacity 200ms ease;
  flex-shrink: 0;
  box-sizing: border-box;
}

.agent-composer-container.disabled {
  opacity: 0.85;
}

.composer-card {
  background: #ffffff;
  border: 1.5px solid #e0e7ff;
  border-radius: 16px;
  padding: 10px 12px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 200ms ease;
}

.composer-card:focus-within {
  border-color: #6366f1;
  box-shadow: 0 4px 20px rgba(99, 102, 241, 0.12);
}

.composer-quick-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
  border-bottom: 1px dashed #e2e8f0;
  padding-bottom: 8px;
}

.composer-quick-bar::-webkit-scrollbar {
  display: none;
}

.quick-label {
  font-size: 12px;
  font-weight: 700;
  color: #6366f1;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
  flex-shrink: 0;
}

.quick-chips {
  display: flex;
  gap: 6px;
  align-items: center;
}

.quick-chip-btn {
  border: 1.5px solid #e0e7ff;
  background: #ffffff;
  color: #4f46e5;
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 150ms ease;
}

.quick-chip-btn:hover:not(:disabled) {
  background: #4f46e5;
  color: #ffffff;
  border-color: #4f46e5;
  transform: translateY(-1px);
}

.quick-chip-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.slide-target-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  align-self: flex-start;
}

.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2563eb;
  animation: pulse-ring 1.5s infinite;
}

@keyframes pulse-ring {
  0% { transform: scale(0.95); opacity: 1; }
  50% { transform: scale(1.2); opacity: 0.5; }
  100% { transform: scale(0.95); opacity: 1; }
}

.clear-target-btn {
  border: 0;
  background: transparent;
  color: #3b82f6;
  cursor: pointer;
  padding: 0;
  display: inline-flex;
  font-size: 12px;
}
.clear-target-btn:hover {
  color: #1d4ed8;
}

.composer-input-wrapper textarea {
  width: 100%;
  border: 0;
  outline: none;
  background: transparent;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-primary, #0f172a);
  resize: none;
  font-family: inherit;
  box-sizing: border-box;
}

.composer-input-wrapper textarea::placeholder {
  color: #94a3b8;
  font-size: 13px;
}

.composer-bottom-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.bottom-left, .bottom-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tip-key {
  font-size: 11px;
  color: var(--text-muted, #64748b);
  font-weight: 500;
}

.send-circle-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 0;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.25);
  transition: all 180ms ease;
  flex-shrink: 0;
}

.send-circle-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.05);
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.35);
}

.send-circle-btn.is-pausing {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3);
}

.send-circle-btn.is-pausing:hover:not(:disabled) {
  background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
  box-shadow: 0 4px 12px rgba(220, 38, 38, 0.4);
}

.send-circle-btn:disabled {
  background: #e2e8f0;
  color: #94a3b8;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}
</style>
