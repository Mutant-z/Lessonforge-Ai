<script setup lang="ts">
import type { Artifact } from '../../types';
import { Clock } from '@element-plus/icons-vue';

defineProps<{
  versions: Artifact[];
  currentVersion?: number;
}>();

const emit = defineEmits<{
  (e: 'select', version: Artifact): void;
  (e: 'close'): void;
}>();
</script>

<template>
  <el-drawer
    title="历史版本管理"
    model-value
    direction="rtl"
    size="360px"
    @close="emit('close')"
  >
    <div class="versions-list">
      <div 
        v-for="v in versions" 
        :key="v.id"
        class="version-item-card"
        :class="{ active: v.version === currentVersion }"
        @click="emit('select', v)"
      >
        <div class="v-meta">
          <span class="v-tag">Version {{ v.version }}</span>
          <span v-if="v.version === currentVersion" class="current-badge">当前使用中</span>
        </div>
        <p class="v-summary">{{ v.change_summary || '编辑修改产物' }}</p>
        <span class="v-time">
          <el-icon><Clock /></el-icon> {{ new Date(v.created_at).toLocaleString('zh-CN') }}
        </span>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.versions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.version-item-card {
  padding: 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--motion-fast);
}

.version-item-card:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.version-item-card.active {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-soft);
}

.v-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.v-tag {
  font-size: 13px;
  font-weight: 800;
  color: var(--color-primary);
}

.current-badge {
  font-size: 11px;
  color: var(--color-success);
  font-weight: 700;
}

.v-summary {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--text-primary);
}

.v-time {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
