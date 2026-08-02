<script setup lang="ts">
import { computed } from 'vue';
import type { StreamConnectionStatus } from '../../composables/useAgentStream';

const props = defineProps<{
  status: StreamConnectionStatus;
}>();

const config = computed(() => {
  switch (props.status) {
    case 'connected':
      return { text: '连接正常', type: 'success', animate: false };
    case 'connecting':
      return { text: '正在连接 Agent 服务', type: 'warning', animate: true };
    case 'reconnecting':
      return { text: '正在重新连接网络...', type: 'warning', animate: true };
    case 'failed':
      return { text: '网络中断', type: 'danger', animate: false };
    case 'closed':
      return { text: '会话已关', type: 'info', animate: false };
    default:
      return { text: '未连接', type: 'info', animate: false };
  }
});
</script>

<template>
  <div class="connection-status-badge" :class="[config.type]">
    <span class="status-ping" :class="{ animate: config.animate }"></span>
    <span class="status-text">{{ config.text }}</span>
  </div>
</template>

<style scoped>
.connection-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 500;
  border: 1px solid transparent;
}

.connection-status-badge.success {
  background: var(--color-success-soft);
  color: var(--color-success);
  border-color: rgba(22, 163, 74, 0.2);
}

.connection-status-badge.warning {
  background: var(--color-warning-soft);
  color: var(--color-warning);
  border-color: rgba(217, 119, 6, 0.2);
}

.connection-status-badge.danger {
  background: var(--color-danger-soft);
  color: var(--color-danger);
  border-color: rgba(220, 38, 38, 0.2);
}

.connection-status-badge.info {
  background: var(--bg-subtle);
  color: var(--text-muted);
  border-color: var(--border-default);
}

.status-ping {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: currentColor;
}

.status-ping.animate {
  animation: pulseGlow 1.5s infinite ease-in-out;
}
</style>
