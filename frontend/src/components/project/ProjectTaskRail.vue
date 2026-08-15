<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { CircleCheck, Clock, Loading, RefreshRight, VideoCamera, Warning } from '@element-plus/icons-vue';
import type { CourseTask } from '../../types';

const props = defineProps<{ courseId: string; tasks: CourseTask[]; activeType?: string }>();
const router = useRouter();

const statusMeta = computed(() => ({
  waiting_dependency: { label: '待生成', icon: Clock },
  ready_to_generate: { label: '可生成', icon: VideoCamera },
  queued: { label: '排队中', icon: Clock },
  running: { label: '生成中', icon: Loading },
  pausing: { label: '暂停中', icon: Loading },
  paused: { label: '已暂停', icon: Clock },
  review: { label: '待确认', icon: CircleCheck },
  approved: { label: '已确认', icon: CircleCheck },
  stale: { label: '记忆已更新', icon: RefreshRight },
  failed: { label: '需要重试', icon: Warning },
  cancelled: { label: '已取消', icon: Warning },
}));

function openTask(type: string) {
  router.push(`/courses/${props.courseId}/tasks/${type}`);
}

function taskStatusLabel(task: CourseTask) {
  if (task.task_type === 'video_generation' && task.status === 'running' && task.progress >= 10) {
    return `部分完成 ${task.progress}%`;
  }
  return statusMeta.value[task.status].label;
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
        <span v-if="['running', 'queued', 'pausing'].includes(task.status) && task.progress" class="step-mini-bar" aria-hidden="true">
          <i :style="{ width: `${task.progress}%` }" />
        </span>
      </button>
      <span v-if="idx < tasks.length - 1" class="step-chevron" aria-hidden="true">›</span>
    </div>
  </nav>
</template>

<style scoped>
.pipeline-track {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 2px;
  background: #f1f5f9;
  padding: 3px 4px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
  box-sizing: border-box;
}

.pipeline-step-item {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.pipeline-btn {
  height: 28px;
  padding: 0 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  position: relative;
  border: 1.5px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: #475569;
  text-align: left;
  cursor: pointer;
  transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
  white-space: nowrap;
  font-size: 11.5px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.pipeline-btn:hover {
  background: #ffffff;
  color: #0f172a;
  border-color: #cbd5e1;
}

.pipeline-btn.active {
  background: #ffffff;
  color: #4f46e5;
  font-weight: 800;
  border-color: #c7d2fe;
  box-shadow: 0 3px 10px rgba(79, 70, 229, 0.14);
}

.step-num {
  font-size: 10.5px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #4f46e5;
  background: #e0e7ff;
  padding: 1px 5px;
  border-radius: 999px;
  flex-shrink: 0;
}

.pipeline-btn.active .step-num {
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.3);
}

.step-name {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.step-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  padding: 1.5px 6px;
  border-radius: 999px;
  transition: all 180ms ease;
  flex-shrink: 0;
  white-space: nowrap;
}

.step-badge.approved:not(.active) {
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
}

.step-badge.review:not(.active) {
  color: #2563eb;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.step-badge.ready_to_generate:not(.active) {
  color: #002fa7;
  background: #eef3ff;
  border: 1px solid #b9c9f7;
}

.step-badge.stale:not(.active) {
  color: #d97706;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.step-badge.running:not(.active) {
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
}

.step-badge.failed:not(.active) {
  color: #dc2626;
  background: #fef2f2;
  border: 1px solid #fecdd3;
}

.step-badge.active {
  color: #4338ca;
  background: #eef2ff;
}

.step-chevron {
  color: #cbd5e1;
  font-size: 13px;
  font-weight: 800;
  user-select: none;
  flex-shrink: 0;
  margin: 0 1px;
}

.step-mini-bar {
  position: absolute;
  left: 6px;
  right: 6px;
  bottom: 1.5px;
  height: 2px;
  background: #dbe4ff;
  border-radius: 999px;
  overflow: hidden;
}

.step-mini-bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #4f46e5 0%, #7c3aed 100%);
  transition: width 240ms ease;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
