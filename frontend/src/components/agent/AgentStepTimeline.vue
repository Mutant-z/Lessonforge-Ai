<script setup lang="ts">
import { computed } from 'vue';
import { Check, Loading, Clock, Warning } from '@element-plus/icons-vue';
import { NODE_LABEL_MAP } from '../../types';

interface StepNode {
  key: string;
  label: string;
}

const props = defineProps<{
  currentNode?: string;
  completedNodes?: string[];
  failedNode?: string;
}>();

const steps: StepNode[] = [
  { key: 'lesson_plan_agent', label: '教学设计' },
  { key: 'ppt_agent', label: 'PPT 页面规划' },
  { key: 'task_sheet_agent', label: '学习任务单' },
  { key: 'exercise_agent', label: '课后练习' },
  { key: 'video_script_agent', label: '微课脚本' },
  { key: 'verbatim_agent', label: '教师逐字稿' },
  { key: 'quality_assurance_agent', label: '质量检查' }
];

function getNodeStatus(key: string) {
  if (props.failedNode === key) return 'failed';
  if (props.completedNodes?.includes(key)) return 'completed';
  if (props.currentNode === key) return 'running';
  return 'pending';
}
</script>

<template>
  <div class="agent-step-timeline">
    <div 
      v-for="(step, index) in steps" 
      :key="step.key"
      class="timeline-item"
      :class="[getNodeStatus(step.key)]"
    >
      <div class="node-icon-wrapper">
        <el-icon v-if="getNodeStatus(step.key) === 'completed'"><Check /></el-icon>
        <el-icon v-else-if="getNodeStatus(step.key) === 'running'" class="is-loading"><Loading /></el-icon>
        <el-icon v-else-if="getNodeStatus(step.key) === 'failed'"><Warning /></el-icon>
        <el-icon v-else><Clock /></el-icon>
      </div>

      <div class="node-content">
        <span class="node-index">0{{ index + 1 }}</span>
        <h4 class="node-title">{{ step.label }}</h4>
        <span class="node-status-text">
          {{ 
            getNodeStatus(step.key) === 'completed' ? '已完成' : 
            getNodeStatus(step.key) === 'running' ? '生成中' : 
            getNodeStatus(step.key) === 'failed' ? '生成失败' : '排队等待'
          }}
        </span>
      </div>

      <div v-if="index < steps.length - 1" class="timeline-line"></div>
    </div>
  </div>
</template>

<style scoped>
.agent-step-timeline {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

@media (max-width: 1024px) {
  .agent-step-timeline {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 640px) {
  .agent-step-timeline {
    grid-template-columns: repeat(2, 1fr);
  }
}

.timeline-item {
  position: relative;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  transition: all var(--motion-normal);
}

.timeline-item.running {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
  background: var(--bg-agent-card);
}

.timeline-item.completed {
  border-color: var(--color-success);
  background: #f0fdf4;
}

.timeline-item.failed {
  border-color: var(--color-danger);
  background: var(--color-danger-soft);
}

.node-icon-wrapper {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-subtle);
  color: var(--text-muted);
  display: grid;
  place-items: center;
  font-size: 16px;
  margin-bottom: 12px;
}

.running .node-icon-wrapper {
  background: var(--color-primary);
  color: #fff;
}

.completed .node-icon-wrapper {
  background: var(--color-success);
  color: #fff;
}

.failed .node-icon-wrapper {
  background: var(--color-danger);
  color: #fff;
}

.node-index {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
}

.node-title {
  margin: 4px 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.node-status-text {
  font-size: 11px;
  color: var(--text-secondary);
}

.running .node-status-text {
  color: var(--color-primary);
  font-weight: 600;
}

.completed .node-status-text {
  color: var(--color-success);
  font-weight: 600;
}

.failed .node-status-text {
  color: var(--color-danger);
  font-weight: 600;
}
</style>
