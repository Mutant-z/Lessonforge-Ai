<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue';
import { Cpu, VideoPause, VideoPlay, Close } from '@element-plus/icons-vue';
import { NODE_LABEL_MAP, NODE_DUTY_MAP } from '../../types';

const props = defineProps<{
  currentNode?: string;
  progress?: number;
  status?: string;
  message?: string;
  startedAt?: string;
}>();

const emit = defineEmits<{
  (e: 'cancel'): void;
  (e: 'pause'): void;
  (e: 'resume'): void;
  (e: 'background'): void;
}>();

const elapsedTime = ref(0);
let timer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  timer = setInterval(() => {
    elapsedTime.value++;
  }, 1000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});

const nodeName = computed(() => NODE_LABEL_MAP[props.currentNode || 'supervisor'] || props.currentNode || 'Agent 服务');
const nodeDuty = computed(() => NODE_DUTY_MAP[props.currentNode || 'supervisor'] || '处理微课资源构建任务');

const formatTime = computed(() => {
  const mins = Math.floor(elapsedTime.value / 60);
  const secs = elapsedTime.value % 60;
  return mins > 0 ? `${mins} 分 ${secs} 秒` : `${secs} 秒`;
});
</script>

<template>
  <div class="agent-activity-card animate-fade-in">
    <div class="card-top">
      <div class="agent-avatar">
        <el-icon><Cpu /></el-icon>
      </div>
      <div class="agent-meta">
        <div class="agent-header-row">
          <h3 class="agent-name">{{ nodeName }}</h3>
          <span class="elapsed-badge">已运行 {{ formatTime }}</span>
        </div>
        <p class="agent-duty">{{ nodeDuty }}</p>
      </div>
    </div>

    <div class="task-status-row">
      <div class="task-info">
        <span class="task-label">当前阶段:</span>
        <span class="task-value">{{ message || '正在协同多 Agent 生成并校验内容...' }}</span>
      </div>
      <span class="progress-percent">{{ progress || 0 }}%</span>
    </div>

    <div class="progress-bar-track">
      <div class="progress-bar-fill" :style="{ width: `${progress || 0}%` }"></div>
    </div>

    <div class="card-actions">
      <div class="status-hints">
        <span class="live-dot animate-pulse"></span>
        <span>Agent 正在实时响应中</span>
      </div>
      <div class="btn-group">
        <el-button v-if="status === 'running'" size="small" :icon="VideoPause" @click="emit('pause')">暂停</el-button>
        <el-button v-else-if="status === 'paused'" size="small" type="primary" :icon="VideoPlay" @click="emit('resume')">继续</el-button>
        <el-button size="small" @click="emit('background')">后台运行</el-button>
        <el-button size="small" type="danger" plain :icon="Close" @click="emit('cancel')">取消任务</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-activity-card {
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid var(--border-active);
  border-radius: var(--radius-xl);
  padding: 24px;
  box-shadow: var(--shadow-md);
  margin-bottom: 24px;
}

.card-top {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-agent) 100%);
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 24px;
  box-shadow: var(--shadow-sm);
}

.agent-meta {
  flex: 1;
}

.agent-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.agent-name {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.elapsed-badge {
  font-size: 12px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-weight: 600;
}

.agent-duty {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.task-status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
}

.task-label {
  color: var(--text-muted);
  margin-right: 6px;
}

.task-value {
  font-weight: 600;
  color: var(--text-primary);
}

.progress-percent {
  font-weight: 800;
  color: var(--color-primary);
  font-size: 15px;
}

.progress-bar-track {
  height: 8px;
  background: var(--bg-subtle);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: 18px;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary) 0%, var(--color-agent) 100%);
  border-radius: var(--radius-full);
  transition: width 0.3s ease;
}

.card-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 14px;
  border-top: 1px solid var(--border-light);
}

.status-hints {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--color-success);
}

.btn-group {
  display: flex;
  gap: 8px;
}
</style>
