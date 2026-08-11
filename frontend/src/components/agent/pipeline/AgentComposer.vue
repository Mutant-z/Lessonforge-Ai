<script setup lang="ts">
import { nextTick, ref, watch } from 'vue';
import { Close, Loading, MagicStick, Picture, Promotion, VideoPause } from '@element-plus/icons-vue';
import ModelSelector from '../ModelSelector.vue';
import { isImageGenerationInstruction } from '../../../utils/imageModelSelection';
import type { PPTPolishModality } from '../../../types/project';

const props = defineProps<{
  targetSlide?: number | null;
  targetSlides?: number[];
  isRunning?: boolean;
  pausing?: boolean;
  modelConfigId?: string | null;
  imageModelConfigId?: string | null;
  imageModelAvailableCount?: number;
}>();

const emit = defineEmits<{
  (e: 'send', text: string, modality: PPTPolishModality): void;
  (e: 'pause'): void;
  (e: 'clear-target-slide'): void;
  (e: 'change-model', modelId: string): void;
  (e: 'change-image-model', modelId: string): void;
  (e: 'image-model-required'): void;
}>();

const input = ref('');
const inputRef = ref<HTMLTextAreaElement | null>(null);

/** 润色范围选择：auto（自动）| layout（只改布局）| text（只改文字）| image（只改图片） */
const modality = ref<PPTPolishModality>('auto');
const modalityOptions: Array<{ value: PPTPolishModality; label: string; tip: string }> = [
  { value: 'auto', label: '自动', tip: '由 Agent 按指令自动判断润色范围' },
  { value: 'layout', label: '只改布局', tip: '只调整页面排版，不改文字与图片' },
  { value: 'text', label: '只改文字', tip: '只优化文字表达，不动布局与图片' },
  { value: 'image', label: '只改图片', tip: '只处理图片素材，不动文字与布局' },
];

const quickPrompts = [
  '润色本页文字表达',
  '调整本页排版与页面分布',
  '优化教学目标与重难点表达',
  '增加课堂互动与提问环节设计',
  '精简课件页面文字与层级',
  '补充教学案例与情境导入',
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
  if (input.value.trim()) {
    input.value = `${input.value.trim()}，${promptText}`;
  } else {
    input.value = promptText;
  }
  nextTick(() => {
    inputRef.value?.focus();
  });
}

function handleGenerateImage() {
  if (props.isRunning) return;
  
  // 特殊指令触发图片生成
  const imagePrompt = '生成一张高清图片，风格专业，适合PPT插入';
  const finalText = `[图片生成] ${imagePrompt}`;

  emit('send', finalText, modality.value);
  input.value = '';
  adjustHeight();
}

function handleSubmit() {
  const rawText = input.value.trim();
  if (!rawText) return;
  if (isImageGenerationInstruction(rawText) && !props.imageModelConfigId) {
    emit('image-model-required');
    return;
  }

  let finalText = rawText;
  if (props.targetSlides?.length) {
    finalText = `[针对第 ${props.targetSlides.map(index => index + 1).join('、')} 页] ${rawText}`;
  } else if (props.targetSlide !== undefined && props.targetSlide !== null && props.targetSlide >= 0) {
    finalText = `[针对第 ${props.targetSlide + 1} 页] ${rawText}`;
  }

  emit('send', finalText, modality.value);
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
            @click="applyQuickPrompt(chip)"
          >
            + {{ chip }}
          </button>
        </div>
      </div>

      <!-- Active Target Slide Context Chip -->
      <div v-if="targetSlides?.length || (targetSlide !== undefined && targetSlide !== null && targetSlide >= 0)" class="slide-target-chip">
        <span class="chip-dot" />
        <span v-if="targetSlides?.length">修改范围：<strong>{{ targetSlides.map(index => index + 1).join('、') }} 页</strong></span>
        <span v-else>已定位：<strong>第 {{ (targetSlide ?? 0) + 1 }} 页</strong></span>
        <button type="button" class="clear-target-btn" title="清除页面定位" @click="clearSlideTarget">
          <el-icon><Close /></el-icon>
        </button>
      </div>

      <!-- 润色范围选择 -->
      <div class="polish-modality" role="group" aria-label="润色范围">
        <span class="modality-label">润色范围</span>
        <button
          v-for="m in modalityOptions"
          :key="m.value"
          type="button"
          class="modality-btn"
          :class="{ active: modality === m.value }"
          :disabled="isRunning"
          :title="m.tip"
          @click="modality = m.value"
        >
          {{ m.label }}
        </button>
      </div>

      <!-- Textarea Input Box (Middle) -->
      <div class="composer-input-wrapper">
        <textarea
          ref="inputRef"
          v-model="input"
          rows="2"
          :placeholder="isRunning ? 'Agent 正在推演；输入新要求后可加入执行队列…' : (targetSlide !== undefined && targetSlide !== null && targetSlide >= 0 ? `详细描述您希望如何修改 第 ${targetSlide + 1} 页 PPT 课件…` : '详细描述您希望如何修改 PPT 课件…')"
          @keydown="onKeydown"
        />
      </div>

      <!-- Bottom Actions Bar (Bottom Toolbar) -->
      <div class="composer-bottom-bar">
        <div class="bottom-left">
          <ModelSelector
            :model-value="modelConfigId || null"
            compact
            label="文本"
            :disabled="isRunning"
            @change="emit('change-model', $event)"
          />
          <ModelSelector
            :model-value="imageModelConfigId || null"
            capability="image_generation"
            compact
            label="绘图"
            :disabled="isRunning"
            @change="emit('change-image-model', $event)"
          />
          <RouterLink
            v-if="!imageModelConfigId"
            class="image-model-warning"
            to="/settings"
            title="图片生成采用严格模式；请先配置并选择具备 image_generation 能力的模型"
          >
            {{ imageModelAvailableCount ? '请选择图片模型' : '未配置图片模型' }}
          </RouterLink>
        </div>
        <div class="bottom-right">
          <span class="tip-key">Shift+Enter 换行</span>
          <button v-if="isRunning && input.trim()" type="button" class="queue-btn" @click="handleSubmit">
            加入队列
          </button>
          <button
            v-if="isRunning"
            type="button"
            class="send-circle-btn is-pausing"
            :disabled="props.pausing"
            :title="props.pausing ? '暂停中...' : '暂停 Agent 推演'"
            @click="emit('pause')"
          >
            <el-icon v-if="props.pausing" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><VideoPause /></el-icon>
          </button>
          <button
            v-if="!isRunning && !props.imageModelConfigId"
            type="button"
            class="send-circle-btn"
            title="一键生成图片"
            @click="handleGenerateImage()"
          >
            <el-icon><Picture /></el-icon>
          </button>

          <button
            v-if="!isRunning"
            type="button"
            class="send-circle-btn"
            :disabled="!input.trim()"
            title="发送修改指令"
            @click="handleSubmit"
          >
            <el-icon><Promotion /></el-icon>
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

/* —— 润色范围选择 —— */
.polish-modality {
  display: flex;
  align-items: center;
  gap: 4px;
}

.modality-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted, #64748b);
  margin-right: 2px;
  white-space: nowrap;
}

.modality-btn {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 150ms ease;
}

.modality-btn:hover:not(:disabled) {
  border-color: #a5b4fc;
  color: #4f46e5;
}

.modality-btn.active {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #ffffff;
}

.modality-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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

.bottom-left {
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.bottom-left::-webkit-scrollbar {
  display: none;
}

.image-model-warning {
  flex-shrink: 0;
  color: #b45309;
  font-size: 11px;
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}

.image-model-warning:hover {
  color: #92400e;
  text-decoration: underline;
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
