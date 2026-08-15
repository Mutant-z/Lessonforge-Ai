<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { Cpu, Microphone, Picture, VideoCamera } from '@element-plus/icons-vue';
import { useModelConfigStore } from '../../stores/modelConfigs';

const props = withDefaults(defineProps<{
  modelValue?: string | null;
  disabled?: boolean;
  compact?: boolean;
  label?: string;
  capability?: 'text_generation' | 'structured_output' | 'vision_review' | 'image_generation' | 'video_generation' | 'native_audio_video_generation' | 'speech_generation' | 'speech_recognition' | 'media_composition' | null;
}>(), {
  modelValue: null,
  disabled: false,
  compact: false,
  label: '文本',
  capability: null,
});

const emit = defineEmits<{
  'update:modelValue': [value: string | null];
  change: [value: string];
}>();

const store = useModelConfigStore();
const selected = computed(() => store.configs.find(item => item.id === props.modelValue) || null);
const mediaTransportModes: Partial<Record<NonNullable<typeof props.capability>, string[]>> = {
  image_generation: ['openai_images', 'google_gemini_image', 'custom_image_http', 'mock_media'],
  video_generation: ['custom_video_async_http', 'volcengine_ark_video', 'gemini_interactions_video', 'mock_media'],
  native_audio_video_generation: ['volcengine_ark_video', 'gemini_interactions_video'],
  speech_recognition: ['volcengine_asr'],
  speech_generation: ['custom_speech_http', 'mock_media'],
  media_composition: ['local_ffmpeg', 'mock_media'],
};

function hasCompatibleTransport(item: typeof store.configs[number]) {
  if (props.capability === 'native_audio_video_generation') {
    return ['volcengine_ark_video', 'gemini_interactions_video'].includes(item.api_mode);
  }
  if (!props.capability || item.provider === 'mock') return true;
  const modes = mediaTransportModes[props.capability];
  return !modes || modes.includes(item.api_mode || 'text_chat');
}

const availableConfigs = computed(() => {
  if (!props.capability) return store.configs;
  // 能力型选择器不能回退展示不具备该能力的模型，否则会造成“选了图片模型但实际只能生成文本”的假象。
  return store.configs.filter(item => (
    item.capabilities?.includes(props.capability!) && hasCompatibleTransport(item)
  ));
});
const effectiveModelValue = computed(() => (
  availableConfigs.value.some(item => item.id === props.modelValue) ? props.modelValue : undefined
));

function formatTokens(value: number) {
  if (value >= 1_000_000 && value % 1_000_000 === 0) return `${value / 1_000_000}M`;
  if (value >= 1_000 && value % 1_000 === 0) return `${value / 1_000}K`;
  return value.toLocaleString('zh-CN');
}

function providerLabel(provider: string) {
  if (provider === 'openai_compatible') return 'OpenAI Compatible';
  if (provider === 'anthropic') return 'Anthropic';
  if (provider === 'mock') return 'Mock';
  return provider;
}

function nativeVideoRange(apiMode: string) {
  if (apiMode === 'gemini_interactions_video') return '3–10 秒/段';
  if (apiMode === 'volcengine_ark_video') return '4–15 秒/段';
  return '';
}

function selectModel(value: string) {
  emit('update:modelValue', value);
  emit('change', value);
}

watch(
  () => [store.loaded, store.configs.length, props.modelValue] as const,
  () => {
    if (!props.modelValue && availableConfigs.value.length) {
      const eligibleActive = availableConfigs.value.find(item => item.id === store.activeConfig?.id);
      emit('update:modelValue', (eligibleActive || availableConfigs.value[0]).id);
    }
  },
  { immediate: true },
);

onMounted(() => {
  store.load().catch(() => undefined);
});
</script>

<template>
  <div class="model-selector" :class="{ compact }">
    <span v-if="label && !compact" class="selector-label">{{ label }}</span>
    <div v-if="availableConfigs.length" class="selector-control">
      <el-select
        :model-value="effectiveModelValue"
        :disabled="disabled"
        :loading="store.loading"
        filterable
        placement="top-start"
        popper-class="model-select-popper"
        class="model-select"
        :class="{ 'has-label-tag': Boolean(label) }"
        placeholder="选择模型"
        @update:model-value="selectModel"
      >
        <template #prefix>
          <div class="prefix-wrap">
            <el-icon class="select-prefix-icon">
              <Picture v-if="capability === 'image_generation'" />
              <VideoCamera v-else-if="capability === 'video_generation' || capability === 'native_audio_video_generation'" />
              <Microphone v-else-if="capability === 'speech_generation'" />
              <Cpu v-else />
            </el-icon>
            <span v-if="label" class="select-prefix-tag" :class="capability === 'image_generation' ? 'tag-purple' : (capability === 'video_generation' ? 'tag-blue' : (capability === 'speech_generation' ? 'tag-emerald' : 'tag-indigo'))">{{ label }}</span>
          </div>
        </template>
        <el-option
          v-for="config in availableConfigs"
          :key="config.id"
          :value="config.id"
          :label="config.name || config.model_name"
        >
          <div class="model-option">
            <div class="option-main">
              <strong>{{ config.name || config.model_name }}</strong>
              <span>{{ providerLabel(config.provider) }} · {{ config.model_name }}<template v-if="nativeVideoRange(config.api_mode)"> · {{ nativeVideoRange(config.api_mode) }}</template></span>
            </div>
            <div class="option-tags">
              <span>{{ formatTokens(config.context_window_tokens) }}</span>
              <span v-if="config.supports_multimodal" class="multimodal"><el-icon><Picture /></el-icon> 多模态</span>
              <span v-else>纯文本</span>
              <span v-if="config.is_active" class="default-tag">默认</span>
            </div>
          </div>
        </el-option>
      </el-select>
      <div v-if="selected" class="capability-tags" aria-label="模型能力">
        <span>{{ formatTokens(selected.context_window_tokens) }}</span>
        <span :class="{ multimodal: selected.supports_multimodal }">
          {{ selected.supports_multimodal ? '多模态' : '纯文本' }}
        </span>
      </div>
    </div>
    <div v-else class="system-default">
      <el-icon class="select-prefix-icon">
        <Picture v-if="capability === 'image_generation'" />
        <VideoCamera v-else-if="capability === 'video_generation' || capability === 'native_audio_video_generation'" />
        <Microphone v-else-if="capability === 'speech_generation'" />
        <Cpu v-else />
      </el-icon>
      <span v-if="label" class="select-prefix-tag" :class="capability === 'image_generation' ? 'tag-purple' : (capability === 'video_generation' ? 'tag-blue' : (capability === 'speech_generation' ? 'tag-emerald' : 'tag-indigo'))">{{ label }}</span>
      <span>{{ store.loading ? '正在加载模型...' : '系统默认模型' }}</span>
      <RouterLink v-if="!store.loading" to="/settings">配置模型</RouterLink>
    </div>
    <span v-if="store.error" class="selector-error">{{ store.error }}</span>
  </div>
</template>

<style scoped>
.model-selector {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  min-width: 0;
}

.selector-label {
  color: var(--text-muted, #64748b);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.selector-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-width: 0;
}

.model-select {
  width: 190px;
  max-width: 100%;
}

.compact .model-select {
  width: 170px;
  max-width: 100%;
}

.compact .model-select.has-label-tag {
  width: 195px;
  max-width: 100%;
}

:deep(.model-select .el-input__wrapper),
:deep(.model-select .el-select__wrapper),
:deep(.model-select.el-select .el-select__wrapper) {
  border-radius: 999px !important;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 60%, #eef2ff 100%) !important;
  box-shadow: 0 0 0 1px #c7d2fe inset, 0 1px 4px rgba(99, 102, 241, 0.08) !important;
  padding: 3px 10px !important;
  transition: all 200ms ease !important;
}

:deep(.model-select .el-input__wrapper:hover),
:deep(.model-select .el-input__wrapper.is-focus),
:deep(.model-select .el-select__wrapper:hover),
:deep(.model-select .el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1.5px #6366f1 inset, 0 4px 14px rgba(99, 102, 241, 0.18) !important;
  background: #ffffff !important;
}

:deep(.prefix-wrap) {
  display: flex;
  align-items: center;
  gap: 4px;
}

:deep(.select-prefix-tag) {
  font-size: 10.5px;
  font-weight: 800;
  padding: 1px 5px;
  border-radius: 4px;
  line-height: 1;
  white-space: nowrap;
  flex-shrink: 0;
}

:deep(.select-prefix-tag.tag-indigo) {
  color: #4338ca;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
}

:deep(.select-prefix-tag.tag-purple) {
  color: #7e22ce;
  background: #f3e8ff;
  border: 1px solid #e9d5ff;
}

:deep(.select-prefix-icon),
:deep(.model-select .el-select__prefix) {
  color: var(--primary-600, #4f46e5) !important;
  font-size: 14px !important;
  margin-right: 1px !important;
}

:deep(.model-select .el-input__inner),
:deep(.model-select .el-select__placeholder),
:deep(.model-select .el-select__selected-item) {
  font-size: 12.5px !important;
  font-weight: 700 !important;
  color: var(--primary-700, #4338ca) !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
}

.capability-tags, .option-tags {
  display: flex;
  align-items: center;
  gap: 4px;
}

.capability-tags {
  flex-shrink: 0;
}

.capability-tags span, .option-tags span {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px;
  border-radius: var(--radius-pill, 999px);
  color: var(--text-muted, #64748b);
  background: #f1f5f9;
  font-size: 10.5px;
  font-weight: 700;
  white-space: nowrap;
}

.capability-tags .multimodal, .option-tags .multimodal {
  color: var(--accent-violet, #7c3aed);
  background: #f3e8ff;
  border: 1px solid #e9d5ff;
}

.model-option {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
}

.option-main {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  overflow: hidden;
}

.option-main strong {
  color: var(--text-primary, #0f172a);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.option-main span {
  color: var(--text-muted, #64748b);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.option-tags {
  flex-shrink: 0;
}

.option-tags .default-tag {
  color: var(--primary-700, #4338ca);
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--primary-200, #c7d2fe);
}

.system-default {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary, #334155);
  font-size: 12px;
  font-weight: 700;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: var(--radius-pill, 999px);
  white-space: nowrap;
  flex-shrink: 0;
}

.system-default a {
  color: var(--primary-600, #4f46e5);
  text-decoration: none;
}

.selector-error {
  color: var(--danger, #dc2626);
  font-size: 11px;
}

.compact .selector-label,
.compact .capability-tags {
  display: none;
}

@media (max-width: 640px) {
  .model-selector, .selector-control { width: 100%; }
  .model-select { flex: 1; width: auto; }
  .capability-tags { display: none; }
}
</style>

<style>
/* Global Popper Styles to prevent Model Selector overflow */
.el-popper.model-select-popper {
  max-width: min(310px, 90vw) !important;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.15) !important;
  border-radius: 12px !important;
  overflow: hidden !important;
}

.el-popper.model-select-popper .el-select-dropdown__item {
  height: auto !important;
  padding: 8px 12px !important;
}
</style>
