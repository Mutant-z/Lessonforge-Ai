<script setup lang="ts">
import { FolderOpened } from '@element-plus/icons-vue';

defineProps<{
  title?: string;
  description?: string;
  actionText?: string;
}>();

const emit = defineEmits<{
  (e: 'action'): void;
}>();
</script>

<template>
  <div class="empty-state-card animate-fade-in">
    <div class="empty-icon-wrapper">
      <slot name="icon">
        <el-icon :size="40" class="empty-icon"><FolderOpened /></el-icon>
      </slot>
    </div>
    <h3 class="empty-title">{{ title || '暂无内容' }}</h3>
    <p class="empty-desc">{{ description || '当前区域尚未生成或暂无可展示的数据。' }}</p>
    <div v-if="$slots.action || actionText" class="empty-action">
      <slot name="action">
        <el-button type="primary" @click="emit('action')">{{ actionText }}</el-button>
      </slot>
    </div>
  </div>
</template>

<style scoped>
.empty-state-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  text-align: center;
}

.empty-icon-wrapper {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  margin-bottom: 16px;
}

.empty-title {
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.empty-desc {
  font-size: 14.5px;
  color: var(--text-secondary);
  max-width: 440px;
  margin: 0 0 20px;
  line-height: 1.6;
}
</style>

