<script setup lang="ts">
import { useTaskCenterStore } from '../../stores/taskCenter';
import { useRouter } from 'vue-router';
import { Cpu, ArrowRight, Check, Warning } from '@element-plus/icons-vue';
import StatusBadge from '../feedback/StatusBadge.vue';

const taskCenter = useTaskCenterStore();
const router = useRouter();

function openTask(task: any) {
  taskCenter.isDrawerOpen = false;
  router.push(`/courses/${task.course_id}/generation/${task.id}`);
}
</script>

<template>
  <el-drawer
    v-model="taskCenter.isDrawerOpen"
    title="全局 Agent 任务中心"
    direction="rtl"
    size="400px"
  >
    <div class="task-center-body">
      <div v-if="!taskCenter.activeTasks.length" class="empty-tasks">
        <el-icon :size="36" class="empty-icon"><Cpu /></el-icon>
        <p>当前没有正在运行的后台 Agent 任务。</p>
      </div>

      <div 
        v-for="task in taskCenter.activeTasks" 
        :key="task.id"
        class="task-card lf-card card-hover"
        @click="openTask(task)"
      >
        <div class="task-card-header">
          <h4 class="task-course-title">{{ task.course_title || '课程生成任务' }}</h4>
          <StatusBadge :status="task.status" size="small" />
        </div>

        <div class="task-card-body">
          <div class="progress-row">
            <span>当前进度:</span>
            <strong>{{ task.progress }}%</strong>
          </div>
          <div class="mini-progress-track">
            <div class="mini-progress-fill" :style="{ width: `${task.progress}%` }"></div>
          </div>
        </div>

        <div class="task-card-footer">
          <span class="view-detail-link">
            查看生成详情 <el-icon><ArrowRight /></el-icon>
          </span>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.task-center-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.empty-tasks {
  text-align: center;
  padding: 48px 16px;
  color: var(--text-muted);
}

.empty-icon {
  margin-bottom: 12px;
  color: var(--color-primary);
}

.task-card {
  cursor: pointer;
  padding: 16px;
}

.task-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.task-course-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.progress-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 6px;
  color: var(--text-secondary);
}

.mini-progress-track {
  height: 6px;
  background: var(--bg-subtle);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: 12px;
}

.mini-progress-fill {
  height: 100%;
  background: var(--color-primary);
  border-radius: var(--radius-full);
}

.task-card-footer {
  display: flex;
  justify-content: flex-end;
}

.view-detail-link {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
