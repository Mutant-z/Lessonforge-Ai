<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useTaskCenterStore } from '../../stores/taskCenter';
import { Cpu, ArrowRight, VideoPlay } from '@element-plus/icons-vue';
import StatusBadge from '../feedback/StatusBadge.vue';

const taskCenter = useTaskCenterStore();
const router = useRouter();

function openTask(task: any) {
  if (task.run_type === 'blueprint' && task.status === 'waiting_human') {
    router.push(`/courses/${task.course_id}/blueprint`);
    return;
  }
  router.push(`/courses/${task.course_id}/generation/${task.id}`);
}
</script>

<template>
  <div class="active-agent-tasks-card">
    <div class="card-header-compact">
      <div class="header-left">
        <div class="icon-wrap violet">
          <el-icon><Cpu /></el-icon>
        </div>
        <div class="header-text">
          <h3 class="card-title">Agent 任务监视</h3>
          <span class="sub-text">多节点实时推理与协同</span>
        </div>
      </div>
      <span v-if="taskCenter.activeTasks.length" class="live-count-badge">
        <span class="pulse-dot animate-pulse"></span>
        {{ taskCenter.activeTasks.length }} 运行中
      </span>
      <span v-else class="idle-count-badge">
        <span class="idle-dot"></span>
        节点就绪
      </span>
    </div>

    <!-- Compact Empty / Idle State -->
    <div v-if="!taskCenter.activeTasks.length" class="empty-agent-tasks">
      <div class="idle-status-inline">
        <div class="idle-pulse-wrapper">
          <span class="idle-pulse animate-ping"></span>
          <span class="idle-pulse-core"></span>
        </div>
        <div class="idle-text-wrap">
          <span class="idle-title">所有 Agent 节点正处就绪状态</span>
          <p class="idle-desc">提交需求后在此实时展示多 Agent 并发推理与生成。</p>
        </div>
      </div>
    </div>

    <!-- Active Tasks Stream -->
    <div v-else class="tasks-list-scroll">
      <div 
        v-for="task in taskCenter.activeTasks" 
        :key="task.id" 
        class="task-item card-hover"
        @click="openTask(task)"
      >
        <div class="task-item-top">
          <div class="task-info">
            <h4 class="task-title">{{ task.course_title || '微课生成任务' }}</h4>
            <span class="node-tag">
              <el-icon><VideoPlay /></el-icon>
              {{ task.current_node || '智能处理中' }}
            </span>
          </div>
          <StatusBadge :status="task.status" size="small" />
        </div>

        <div class="task-progress-box">
          <div class="progress-labels">
            <span class="stage-name">生成进度</span>
            <span class="percentage">{{ task.progress }}%</span>
          </div>
          <div class="progress-track">
            <div class="progress-bar" :style="{ width: `${task.progress}%` }"></div>
          </div>
        </div>

        <div class="task-item-foot">
          <span class="time-elapsed">任务 ID: {{ task.id.slice(0, 8) }}</span>
          <el-button type="primary" link size="small" class="enter-task-btn">
            <span>实时监视</span>
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.active-agent-tasks-card {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
  padding: 12px 14px;
  background: var(--surface-primary);
  border-radius: var(--radius-control);
}

.card-header-compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon-wrap {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  font-size: 15px;
  flex-shrink: 0;
}

.icon-wrap.violet {
  background: var(--accent-violet-soft);
  color: var(--accent-violet);
}

.header-text {
  display: flex;
  flex-direction: column;
}

.card-title {
  margin: 0;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
}

.sub-text {
  font-size: 11.5px;
  color: var(--text-muted);
}

.live-count-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.idle-count-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 800;
  color: var(--accent-mint);
  background: var(--accent-mint-soft);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.idle-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-mint);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
}

.empty-agent-tasks {
  padding: 10px 12px;
  background: var(--surface-secondary);
  border-radius: var(--radius-sm);
  border: 1px dashed var(--border-soft);
}

.idle-status-inline {
  display: flex;
  align-items: center;
  gap: 10px;
}

.idle-pulse-wrapper {
  position: relative;
  width: 12px;
  height: 12px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.idle-pulse {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--accent-mint);
  opacity: 0.75;
}

.idle-pulse-core {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-mint);
  box-shadow: 0 0 6px var(--accent-mint);
}

.idle-text-wrap {
  display: flex;
  flex-direction: column;
}

.idle-title {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--text-primary);
}

.idle-desc {
  margin: 1px 0 0;
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.35;
}

.tasks-list-scroll {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 2px;
}

.task-item {
  background: var(--surface-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  cursor: pointer;
}

.task-item-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 4px;
}

.task-info {
  min-width: 0;
}

.task-title {
  margin: 0 0 2px;
  font-size: 13.5px;
  font-weight: 800;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-tag {
  font-size: 11.5px;
  color: var(--accent-violet);
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.task-progress-box {
  margin-bottom: 4px;
}

.progress-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 2px;
}

.percentage {
  font-weight: 800;
  color: var(--text-primary);
}

.progress-track {
  height: 5px;
  background: var(--border-default);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  border-radius: var(--radius-pill);
}

.task-item-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11.5px;
}

.time-elapsed {
  color: var(--text-muted);
}

.enter-task-btn {
  font-size: 12px !important;
  font-weight: 800 !important;
}
</style>


