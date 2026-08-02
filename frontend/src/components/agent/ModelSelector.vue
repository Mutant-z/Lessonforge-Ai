<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { Cpu, Picture } from '@element-plus/icons-vue';
import { useModelConfigStore } from '../../stores/modelConfigs';

const props = withDefaults(defineProps<{
  modelValue?: string | null;
  disabled?: boolean;
  compact?: boolean;
  label?: string;
}>(), {
  modelValue: null,
  disabled: false,
  compact: false,
  label: '对话模型',
});

const emit = defineEmits<{
  'update:modelValue': [value: string | null];
  change: [value: string];
}>();

const store = useModelConfigStore();
const selected = computed(() => store.configs.find(item => item.id === props.modelValue) || null);

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

function selectModel(value: string) {
  emit('update:modelValue', value);
  emit('change', value);
}

watch(
  () => [store.loaded, store.configs.length, props.modelValue] as const,
  () => {
    if (!props.modelValue && store.activeConfig) emit('update:modelValue', store.activeConfig.id);
  },
  { immediate: true },
);

onMounted(() => {
  store.load().catch(() => undefined);
});
</script>

<template>
  <div class="model-selector" :class="{ compact }">
    <span v-if="label" class="selector-label">{{ label }}</span>
    <div v-if="store.configs.length" class="selector-control">
      <el-select
        :model-value="modelValue || undefined"
        :disabled="disabled"
        :loading="store.loading"
        filterable
        placement="top-start"
        popper-class="model-select-popper"
        class="model-select"
        placeholder="选择模型"
        @update:model-value="selectModel"
      >
        <el-option
          v-for="config in store.configs"
          :key="config.id"
          :value="config.id"
          :label="config.name || config.model_name"
        >
          <div class="model-option">
            <div class="option-main">
              <strong>{{ config.name || config.model_name }}</strong>
              <span>{{ providerLabel(config.provider) }} · {{ config.model_name }}</span>
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
      <el-icon><Cpu /></el-icon>
      <span>{{ store.loading ? '正在加载模型...' : '系统默认模型' }}</span>
      <RouterLink v-if="!store.loading" to="/settings">配置模型</RouterLink>
    </div>
    <span v-if="store.error" class="selector-error">{{ store.error }}</span>
  </div>
</template>

<style scoped>
.model-selector { display: flex; align-items: center; gap: 8px; min-width: 0; }
.selector-label { color: var(--text-muted); font-size: 12px; font-weight: 700; white-space: nowrap; }
.selector-control { display: flex; align-items: center; gap: 6px; min-width: 0; }
.model-select { width: 210px; }
.capability-tags, .option-tags { display: flex; align-items: center; gap: 4px; }
.capability-tags span, .option-tags span {
  display: inline-flex; align-items: center; gap: 3px; padding: 2px 6px;
  border: 1px solid var(--border-default); border-radius: var(--radius-pill);
  color: var(--text-muted); background: var(--surface-secondary); font-size: 10.5px; font-weight: 700;
}
.capability-tags .multimodal, .option-tags .multimodal { color: var(--accent-violet); background: var(--accent-violet-soft); border-color: #ddd6fe; }
.model-option { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.option-main { min-width: 0; display: flex; flex-direction: column; line-height: 1.25; }
.option-main strong { color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.option-main span { color: var(--text-muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.option-tags { flex-shrink: 0; }
.option-tags .default-tag { color: var(--color-primary); background: var(--color-primary-soft); border-color: var(--color-primary-border); }
.system-default { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 700; }
.system-default a { color: var(--color-primary); text-decoration: none; }
.selector-error { color: var(--color-danger); font-size: 11px; }
.compact .selector-label { display: none; }
.compact .model-select { width: 180px; }
@media (max-width: 640px) {
  .model-selector, .selector-control { width: 100%; }
  .model-select { flex: 1; width: auto; }
  .capability-tags { flex-shrink: 0; }
}
</style>
