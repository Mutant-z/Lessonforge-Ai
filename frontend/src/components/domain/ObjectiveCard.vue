<script setup lang="ts">
import { Aim } from '@element-plus/icons-vue';

defineProps<{
  objective: string;
  index: number;
}>();
</script>

<template>
  <div class="objective-card card-hover">
    <div class="obj-badge">
      <el-icon><Aim /></el-icon>
      <span>目标 {{ index + 1 }}</span>
    </div>
    <p class="obj-text">{{ objective }}</p>
  </div>
</template>

<style scoped>
.objective-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  margin-bottom: 12px;
}

.obj-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.obj-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  font-weight: 500;
}
</style>
