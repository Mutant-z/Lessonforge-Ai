<script setup lang="ts">
import { ref } from 'vue';
import { Warning } from '@element-plus/icons-vue';

defineProps<{
  title?: string;
  error?: string;
  detail?: string;
  showRetry?: boolean;
}>();

const emit = defineEmits<{
  (e: 'retry'): void;
}>();

const showDetails = ref(false);
</script>

<template>
  <div class="error-state-card animate-fade-in">
    <div class="error-header">
      <el-icon class="error-icon"><Warning /></el-icon>
      <div class="error-titles">
        <h4>{{ title || '发生错误' }}</h4>
        <p>{{ error || '请检查您的网络连接或后端服务状态。' }}</p>
      </div>
    </div>

    <div v-if="detail" class="error-details-wrapper">
      <el-button link type="danger" size="small" @click="showDetails = !showDetails">
        {{ showDetails ? '隐藏技术细节' : '查看技术细节' }}
      </el-button>
      <pre v-if="showDetails" class="error-code-block">{{ detail }}</pre>
    </div>

    <div v-if="showRetry !== false" class="error-actions">
      <el-button type="primary" size="small" @click="emit('retry')">重试操作</el-button>
    </div>
  </div>
</template>

<style scoped>
.error-state-card {
  padding: 20px 24px;
  background: var(--color-danger-soft);
  border: 1px solid rgba(220, 38, 38, 0.2);
  border-radius: var(--radius-lg);
  margin-bottom: 20px;
}

.error-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.error-icon {
  font-size: 22px;
  color: var(--color-danger);
  margin-top: 2px;
}

.error-titles h4 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-danger);
}

.error-titles p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.error-details-wrapper {
  margin-top: 12px;
}

.error-code-block {
  margin-top: 8px;
  padding: 12px;
  background: #1e293b;
  color: #f8fafc;
  font-family: monospace;
  font-size: 12px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
}

.error-actions {
  margin-top: 14px;
}
</style>
