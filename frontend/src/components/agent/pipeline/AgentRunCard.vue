<script setup lang="ts">
import { computed } from 'vue';
import { Loading, CircleCheck, CircleClose, User } from '@element-plus/icons-vue';
import { AGENT_PIPELINE_LABELS } from '../../../types/agentPipeline';

const props = defineProps<{
  agentKey: string;
  status: 'running' | 'completed' | 'failed';
  summary?: string;
  message?: string;
}>();

const label = computed(() => AGENT_PIPELINE_LABELS[props.agentKey] || props.agentKey || 'Agent');
</script>

<template>
  <div class="run-card" :class="status">
    <div class="run-head">
      <span class="agent-icon"><el-icon><User /></el-icon></span>
      <div class="run-info">
        <div class="run-title">
          {{ label }}
          <span v-if="status === 'running'" class="live-tag">执行中</span>
        </div>
        <div v-if="summary" class="run-summary">{{ summary }}</div>
        <div v-else-if="message" class="run-summary">{{ message }}</div>
      </div>
      <span class="run-status">
        <el-icon v-if="status === 'running'" class="spin" color="#4f46e5"><Loading /></el-icon>
        <el-icon v-else-if="status === 'completed'" color="#22c55e"><CircleCheck /></el-icon>
        <el-icon v-else color="#ef4444"><CircleClose /></el-icon>
      </span>
    </div>
    <div v-if="status === 'running'" class="run-progress"><div class="bar" /></div>
    <div class="run-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.run-card {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  background: var(--surface-primary, #fff);
  margin: 8px 0;
  overflow: hidden;
}
.run-card.running { border-color: rgba(79, 70, 229, 0.35); }
.run-card.failed { border-color: rgba(239, 68, 68, 0.4); }
.run-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; }
.agent-icon {
  width: 30px; height: 30px; border-radius: 8px;
  display: inline-flex; align-items: center; justify-content: center;
  background: #eef2ff; color: #4f46e5; flex-shrink: 0;
}
.run-info { flex: 1; min-width: 0; }
.run-title { font-size: 14px; font-weight: 600; color: #111827; display: flex; align-items: center; gap: 6px; }
.live-tag {
  font-size: 11px; color: #4f46e5; background: #eef2ff;
  padding: 1px 6px; border-radius: 999px; font-weight: 500;
}
.run-summary { font-size: 12px; color: #6b7280; margin-top: 2px; }
.run-status { color: #9ca3af; }
.run-progress { height: 2px; background: #eef2ff; }
.run-progress .bar {
  height: 100%; width: 100%; background: linear-gradient(90deg, #4f46e5, #8b5cf6);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.run-body { padding: 0 8px 8px; }
.spin { animation: rotate 1s linear infinite; }
@keyframes rotate { to { transform: rotate(360deg); } }
</style>
