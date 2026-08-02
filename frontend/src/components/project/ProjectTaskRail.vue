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
  <nav class="task-rail" aria-label="课程交付任务">
    <button
      v-for="task in tasks"
      :key="task.id"
      type="button"
      class="task-segment"
      :class="[task.status, { active: activeType === task.task_type }]"
      :aria-current="activeType === task.task_type ? 'page' : undefined"
      @click="openTask(task.task_type)"
    >
      <span class="task-number">{{ String(task.display_order).padStart(2, '0') }}</span>
      <span class="task-copy">
        <strong>{{ task.display_name }}</strong>
        <span class="task-state">
          <el-icon :class="{ spinning: task.status === 'running' }"><component :is="statusMeta[task.status].icon" /></el-icon>
          {{ statusMeta[task.status].label }}
        </span>
      </span>
      <span class="task-progress" aria-hidden="true"><i :style="{ width: `${task.progress}%` }" /></span>
    </button>
  </nav>
</template>

<style scoped>
.task-rail {
  display: grid;
  grid-template-columns: repeat(6, minmax(150px, 1fr));
  min-width: 900px;
  background: #fff;
  border-top: 1px solid #d9dce3;
  border-bottom: 1px solid #d9dce3;
}

.task-segment {
  min-width: 0;
  min-height: 76px;
  padding: 12px 14px 10px;
  display: grid;
  grid-template-columns: 30px 1fr;
  gap: 8px;
  position: relative;
  border: 0;
  border-right: 1px solid #d9dce3;
  background: #fff;
  color: #18191d;
  text-align: left;
  cursor: pointer;
  transition: background 150ms ease, color 150ms ease;
}

.task-segment:last-child { border-right: 0; }
.task-segment:hover { background: #f7f7f8; }
.task-segment.active { background: #002fa7; color: #fff; }

.task-number {
  font-size: 20px;
  line-height: 1;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  color: #002fa7;
}

.active .task-number { color: #fff; }
.task-copy { min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.task-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.task-state { display: flex; align-items: center; gap: 4px; font-size: 12px; color: #656a73; }
.active .task-state { color: rgba(255,255,255,.82); }
.failed:not(.active) .task-state { color: #b42318; }
.stale:not(.active) .task-state { color: #9a6700; }
.approved:not(.active) .task-state { color: #067647; }
.task-progress { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: #eceef2; }
.task-progress i { display: block; height: 100%; background: #002fa7; transition: width 240ms ease; }
.active .task-progress { background: rgba(255,255,255,.24); }
.active .task-progress i { background: #fff; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
