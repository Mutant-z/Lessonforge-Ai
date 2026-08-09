<script setup lang="ts">
import type { TaskSheetTask } from '../../types';
import { Timer, CircleCheck, Aim, User } from '@element-plus/icons-vue';

defineProps<{
  task: TaskSheetTask;
  index: number;
}>();

const collaborationLabels: Record<string, string> = { 
  individual: '独立', 
  pair: '结对', 
  group: '小组', 
  whole_class: '全班' 
};
</script>

<template>
  <div class="task-sheet-card lf-card card-hover">
    <div class="task-header">
      <div class="task-title-group">
        <span class="task-num">{{ task.id || `T-${index + 1}` }}</span>
        <h4 class="task-title">{{ task.title }}</h4>
      </div>
      <div class="task-meta-pills">
        <span class="meta-pill"><el-icon><Timer /></el-icon> {{ task.estimated_minutes }} 分钟</span>
        <span class="meta-pill" v-if="task.collaboration_mode">
          <el-icon><User /></el-icon> {{ collaborationLabels[task.collaboration_mode] || task.collaboration_mode }}
        </span>
      </div>
    </div>

    <div class="task-objective-box" v-if="task.objective_ids && task.objective_ids.length">
      <el-icon><Aim /></el-icon>
      <span class="obj-label">对应目标：</span>
      <span class="obj-tags">
        <span v-for="id in task.objective_ids" :key="id" class="obj-tag">{{ id }}</span>
      </span>
    </div>

    <div class="task-steps" v-if="task.steps && task.steps.length">
      <h5>操作步骤与方法：</h5>
      <ol>
        <li v-for="(step, sIdx) in task.steps" :key="sIdx">{{ step }}</li>
      </ol>
    </div>

    <div class="task-output" v-if="task.student_output">
      <div class="output-row">
        <span class="output-label"><el-icon><CircleCheck /></el-icon> 成果要求：</span>
        <span class="output-text">{{ task.student_output }}</span>
      </div>
      <div class="output-row completion" v-if="task.completion_criterion">
        <span class="criterion-label">完成标准：</span>
        <span class="criterion-text">{{ task.completion_criterion }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-sheet-card {
  margin-bottom: 20px;
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
  padding: 20px;
  transition: all 0.2s ease;
}

.task-sheet-card:hover {
  border-color: var(--color-primary-light, #818cf8);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 14px;
}

.task-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.task-num {
  font-size: 12px;
  font-weight: 900;
  color: var(--color-primary, #4f46e5);
  background: var(--color-primary-soft, #eef2ff);
  border: 1px solid var(--color-primary-light, #c7d2fe);
  padding: 2px 9px;
  border-radius: 999px;
}

.task-title {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.task-meta-pills {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta-pill {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #64748b);
  background: var(--bg-page, #f8fafc);
  border: 1px solid var(--border-default, #e2e8f0);
  padding: 3px 10px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.task-objective-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-page, #f8fafc);
  border-radius: var(--radius-md, 8px);
  font-size: 12.5px;
  margin-bottom: 14px;
  color: var(--text-secondary, #475569);
}

.task-objective-box .el-icon {
  color: var(--color-primary, #4f46e5);
}

.obj-label {
  font-weight: 700;
  color: var(--text-primary, #1e293b);
}

.obj-tags {
  display: flex;
  gap: 6px;
}

.obj-tag {
  font-size: 11px;
  font-weight: 800;
  color: #ffffff;
  background: var(--color-primary, #4f46e5);
  padding: 1px 7px;
  border-radius: 4px;
}

.task-steps h5 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary, #0f172a);
}

.task-steps ol {
  padding-left: 20px;
  margin: 0 0 16px;
}

.task-steps li {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-primary, #334155);
  margin-bottom: 6px;
  font-weight: 500;
}

.task-output {
  padding-top: 12px;
  border-top: 1.5px dashed var(--border-default, #e2e8f0);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.output-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
}

.output-label {
  color: var(--color-primary, #4f46e5);
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.output-text {
  color: var(--text-primary, #1e293b);
  font-weight: 600;
}

.criterion-label {
  color: var(--text-secondary, #64748b);
  font-weight: 700;
  flex-shrink: 0;
}

.criterion-text {
  color: var(--text-secondary, #475569);
  font-weight: 500;
}
</style>

