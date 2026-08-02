<script setup lang="ts">
import { computed } from 'vue';
import { Document, Download, View } from '@element-plus/icons-vue';

const props = defineProps<{
  fileName: string;
  fileType?: string;
  fileSize?: string | number;
  createdAt?: string;
  downloadUrl?: string;
}>();

const emit = defineEmits<{
  (e: 'download'): void;
  (e: 'preview'): void;
}>();

const iconType = computed(() => {
  const ext = (props.fileName.split('.').pop() || props.fileType || '').toLowerCase();
  if (['pptx', 'ppt'].includes(ext)) return 'ppt';
  if (['docx', 'doc'].includes(ext)) return 'doc';
  if (ext === 'pdf') return 'pdf';
  if (ext === 'zip') return 'zip';
  return 'file';
});
</script>

<template>
  <div class="file-output-card card-hover">
    <div class="file-icon-box" :class="[iconType]">
      <el-icon><Document /></el-icon>
      <span class="file-ext-tag">{{ iconType.toUpperCase() }}</span>
    </div>

    <div class="file-info">
      <h4 class="file-name">{{ fileName }}</h4>
      <div class="file-sub">
        <span>{{ fileSize ? `${fileSize}` : '可编辑交付物' }}</span>
        <span v-if="createdAt"> · {{ new Date(createdAt).toLocaleDateString('zh-CN') }}</span>
      </div>
    </div>

    <div class="file-actions">
      <el-button size="small" circle :icon="View" title="在线预览" @click="emit('preview')" />
      <el-button size="small" type="primary" circle :icon="Download" title="下载文件" @click="emit('download')" />
    </div>
  </div>
</template>

<style scoped>
.file-output-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  margin: 12px 0;
}

.file-icon-box {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.file-icon-box.ppt { background: #fff7ed; color: #ea580c; }
.file-icon-box.doc { background: #eff6ff; color: #2563eb; }
.file-icon-box.zip { background: #f5f3ff; color: #7c3aed; }
.file-icon-box.pdf { background: #fef2f2; color: #dc2626; }

.file-ext-tag {
  font-size: 9px;
  font-weight: 800;
  margin-top: 2px;
}

.file-info {
  flex: 1;
  overflow: hidden;
}

.file-name {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.file-actions {
  display: flex;
  gap: 8px;
}
</style>
