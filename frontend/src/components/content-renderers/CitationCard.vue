<script setup lang="ts">
import { Connection } from '@element-plus/icons-vue';

defineProps<{
  sourceName: string;
  section?: string;
  excerpt?: string;
  isUploadedMaterial?: boolean;
}>();
</script>

<template>
  <div class="citation-card card-hover">
    <div class="citation-header">
      <el-icon class="citation-icon"><Connection /></el-icon>
      <span class="source-title">{{ sourceName }}</span>
      <el-tag size="small" :type="isUploadedMaterial ? 'success' : 'info'">
        {{ isUploadedMaterial ? '上传参考材料' : '系统基准语料' }}
      </el-tag>
    </div>
    <div v-if="section" class="citation-section">定位: {{ section }}</div>
    <p v-if="excerpt" class="citation-excerpt">"{{ excerpt }}"</p>
  </div>
</template>

<style scoped>
.citation-card {
  padding: 14px 18px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-md);
  margin: 10px 0;
}

.citation-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.citation-icon {
  color: var(--color-primary);
  font-size: 16px;
}

.source-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  flex: 1;
}

.citation-section {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.citation-excerpt {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  font-style: italic;
  line-height: 1.5;
  background: var(--bg-page);
  padding: 8px 12px;
  border-radius: var(--radius-xs);
}
</style>
