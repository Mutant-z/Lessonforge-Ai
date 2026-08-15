<script setup lang="ts">
import type { Artifact } from '../../types';
import { Clock, RefreshRight } from '@element-plus/icons-vue';

defineProps<{
  versions: Artifact[];
  currentVersion?: number;
  allowRestore?: boolean;
}>();

const emit = defineEmits<{
  (e: 'select', version: Artifact): void;
  (e: 'restore', version: Artifact): void;
  (e: 'close'): void;
}>();

function isContentAnomalous(version: Artifact): boolean {
  if (version.artifact_type !== 'lesson_plan' || version.content_json?.schema_version !== '2.0') return false;
  const sections = (version.content_json?.outline as { sections?: Array<Record<string, unknown>> } | undefined)?.sections || [];
  let leafCount = 0;
  let visibleLeafCount = 0;
  const visit = (items: Array<Record<string, unknown>>) => {
    for (const item of items) {
      const children = Array.isArray(item.children) ? item.children as Array<Record<string, unknown>> : [];
      if (children.length) visit(children);
      else {
        leafCount += 1;
        const blocks = Array.isArray(item.blocks) ? item.blocks : [];
        if (blocks.length || String(item.summary || '').trim()) visibleLeafCount += 1;
      }
    }
  };
  visit(sections);
  return leafCount > 0 && visibleLeafCount === 0;
}
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
          <span v-else-if="isContentAnomalous(v)" class="anomaly-badge">正文异常，建议勿用</span>
        </div>
        <p class="v-summary">{{ v.change_summary || '编辑修改产物' }}</p>
        <span class="v-time">
          <el-icon><Clock /></el-icon> {{ new Date(v.created_at).toLocaleString('zh-CN') }}
        </span>
        <el-button
          v-if="allowRestore && v.version !== currentVersion"
          size="small"
          plain
          :icon="RefreshRight"
          class="restore-button"
          @click.stop="emit('restore', v)"
        >恢复为新版本</el-button>
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

.anomaly-badge {
  font-size: 11px;
  color: var(--color-danger);
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

.restore-button { width: 100%; margin-top: 10px; border-radius: 0; }
</style>
