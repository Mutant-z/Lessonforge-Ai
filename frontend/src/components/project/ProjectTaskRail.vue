<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { CircleCheck, Clock, Loading, RefreshRight, Warning } from '@element-plus/icons-vue';
import type { CourseTask } from '../../types';

const props = defineProps<{ courseId: string; tasks: CourseTask[]; activeType?: string }>();
const router = useRouter();

const statusMeta = computed(() => ({
  waiting_dependency: { label: '等待依赖', icon: Clock },
  queued: { label: '排队中', icon: Clock },
  running: { label: '生成中', icon: Loading },
  review: { label: '待确认', icon: CircleCheck },
  approved: { label: '已确认', icon: CircleCheck },
  stale: { label: '上游已更新', icon: RefreshRight },
  failed: { label: '需要重试', icon: Warning },
  cancelled: { label: '已取消', icon: Warning },
}));

function openTask(type: string) {
  router.push(`/courses/${props.courseId}/tasks/${type}`);
}
</script>

<template>
  <nav class="pipeline-track" aria-label="课程交付流程">
    <div
      v-for="(task, idx) in tasks"
      :key="task.id"
      class="pipeline-step-item"
    >
      <button
        type="button"
        class="pipeline-btn"
        :class="[task.status, { active: activeType === task.task_type }]"
        :aria-current="activeType === task.task_type ? 'page' : undefined"
        @click="openTask(task.task_type)"
      >
        <span class="step-num">{{ String(task.display_order).padStart(2, '0') }}</span>
        <span class="step-name">{{ task.display_name }}</span>
        <span class="step-badge" :class="[task.status, { active: activeType === task.task_type }]">
          <el-icon :class="{ spinning: task.status === 'running' }"><component :is="statusMeta[task.status].icon" /></el-icon>
          <span>{{ task.agent_profile_status === 'initializing' ? '专属化中' : task.agent_profile_status === 'failed' ? '失败' : statusMeta[task.status].label }}</span>
        </span>
        <span v-if="['running', 'queued'].includes(task.status) && task.progress" class="step-mini-bar" aria-hidden="true">
          <i :style="{ width: `${task.progress}%` }" />
        </span>
      </button>
      <span v-if="idx < tasks.length - 1" class="step-chevron" aria-hidden="true">›</span>
    </div>
  </nav>
</template>

<style scoped>
.pipeline-track {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: #f1f5f9;
  padding: 3px 4px;
  border-radius: var(--radius-pill, 999px);
  border: 1px solid #e2e8f0;
}

.pipeline-step-item {
  display: flex;
  align-items: center;
  gap: 3px;
}

.pipeline-btn {
  height: 32px;
  padding: 0 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  position: relative;
  border: 0;
  border-radius: var(--radius-pill, 999px);
  background: transparent;
  color: #475569;
  text-align: left;
  cursor: pointer;
  transition: all 180ms ease;
  white-space: nowrap;
  font-size: 12px;
}

.pipeline-btn:hover {
  background: rgba(255, 255, 255, 0.7);
  color: var(--text-primary, #0f172a);
}

.pipeline-btn.active {
  background: #ffffff;
  color: var(--primary-700, #4338ca);
  font-weight: 800;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.16), 0 0 0 1px rgba(79, 70, 229, 0.12);
}

.step-num {
  font-size: 10.5px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  color: var(--primary-600, #4f46e5);
  background: #e0e7ff;
  padding: 1px 5px;
  border-radius: 999px;
  flex-shrink: 0;
}

.pipeline-btn.active .step-num {
  color: #ffffff;
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%);
}

.step-name {
  font-size: 12px;
  font-weight: 700;
}

.step-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  padding: 1px 6px;
  border-radius: 999px;
}

.step-badge.approved:not(.active) {
  color: #059669;
  background: #ecfdf5;
}

.step-badge.review:not(.active) {
  color: #2563eb;
  background: #eff6ff;
}

.step-badge.stale:not(.active) {
  color: #d97706;
  background: #fffbeb;
}

.step-badge.running:not(.active) {
  color: #4f46e5;
  background: #eef2ff;
}

.step-badge.failed:not(.active) {
  color: #dc2626;
  background: #fef2f2;
}

.step-badge.active {
  color: #4338ca;
  background: #eef2ff;
}

.step-chevron {
  color: #cbd5e1;
  font-size: 14px;
  font-weight: 700;
  user-select: none;
}

.step-mini-bar {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 1px;
  height: 2px;
  background: #dbe4ff;
  border-radius: 999px;
  overflow: hidden;
}

.step-mini-bar i {
  display: block;
  height: 100%;
  background: var(--primary-600, #4f46e5);
  transition: width 240ms ease;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>


