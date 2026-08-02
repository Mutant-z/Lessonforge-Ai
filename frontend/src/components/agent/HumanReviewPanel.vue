<script setup lang="ts">
import { CircleCheck, Edit, Close } from '@element-plus/icons-vue';

defineProps<{
  title?: string;
  message?: string;
  busy?: boolean;
  primaryActionText?: string;
  showSecondaryActions?: boolean;
}>();

const emit = defineEmits<{
  (e: 'approve'): void;
  (e: 'edit'): void;
  (e: 'reject'): void;
}>();
</script>

<template>
  <div class="human-review-panel animate-fade-in">
    <div class="review-icon-box">
      <el-icon><CircleCheck /></el-icon>
    </div>
    <div class="review-content">
      <h4>{{ title || '等待教师审核' }}</h4>
      <p>{{ message || 'AI Agent 已完成多维微课资源生成与质量自动化检查。请审阅内容并确认，或直接进行人工调整。' }}</p>
    </div>
    <div class="review-actions">
      <el-button type="primary" size="large" :icon="CircleCheck" :loading="busy" @click="emit('approve')">
        {{ primaryActionText || '确认无误，启动打包导出' }}
      </el-button>
      <el-button v-if="showSecondaryActions !== false" size="large" :icon="Edit" @click="emit('edit')">
        进入工作台微调
      </el-button>
      <el-button v-if="showSecondaryActions !== false" size="large" type="danger" plain :icon="Close" @click="emit('reject')">
        退回重生成
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.human-review-panel {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 24px;
  background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
  border: 1.5px solid var(--color-success);
  border-radius: var(--radius-xl);
  margin-top: 24px;
  box-shadow: var(--shadow-md);
}

@media (max-width: 900px) {
  .human-review-panel {
    flex-direction: column;
    align-items: flex-start;
  }
}

.review-icon-box {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--color-success);
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 28px;
  flex-shrink: 0;
}

.review-content {
  flex: 1;
}

.review-content h4 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #14532d;
}

.review-content p {
  margin: 6px 0 0;
  font-size: 13px;
  color: #166534;
  line-height: 1.6;
}

.review-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
</style>
