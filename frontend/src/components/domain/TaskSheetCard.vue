<script setup lang="ts">
import type { TaskSheetItem } from '../../types';
import { Timer, Check } from '@element-plus/icons-vue';

defineProps<{
  task: TaskSheetItem;
  index: number;
}>();
</script>

<template>
  <div class="task-sheet-card lf-card card-hover">
    <div class="task-header">
      <div class="task-title-group">
        <span class="task-num">任务 {{ index + 1 }}</span>
        <h4 class="task-title">{{ task.title }}</h4>
      </div>
      <span class="task-duration">
        <el-icon><Timer /></el-icon> 预计 {{ task.estimated_minutes }} 分钟
      </span>
    </div>

    <div class="task-objective-box">
      <strong>🎯 学习探究目标:</strong> {{ task.objective }}
    </div>

    <div class="task-steps">
      <h5>📋 操作步骤与方法:</h5>
      <ol>
        <li v-for="(step, sIdx) in task.steps" :key="sIdx">{{ step }}</li>
      </ol>
    </div>

    <div class="task-output">
      <strong><el-icon><Check /></el-icon> 成果输出要求:</strong> {{ task.output_requirement }}
    </div>
  </div>
</template>

<style scoped>
.task-sheet-card {
  margin-bottom: 20px;
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.task-num {
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 3px 8px;
  border-radius: var(--radius-xs);
  margin-right: 8px;
}

.task-title {
  display: inline;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.task-duration {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}

.task-objective-box {
  padding: 10px 14px;
  background: var(--bg-page);
  border-radius: var(--radius-md);
  font-size: 13px;
  margin-bottom: 14px;
}

.task-steps h5 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.task-steps ol {
  padding-left: 20px;
  margin: 0 0 14px;
}

.task-steps li {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.task-output {
  padding-top: 10px;
  border-top: 1px dashed var(--border-default);
  font-size: 13px;
  color: var(--color-primary);
  font-weight: 600;
}
</style>
