<script setup lang="ts">
defineProps<{
  text?: string;
  agentName?: string;
}>();
</script>

<template>
  <div class="agent-thinking-indicator">
    <div class="pulse-dots">
      <span class="dot dot-1"></span>
      <span class="dot dot-2"></span>
      <span class="dot dot-3"></span>
    </div>
    <span class="thinking-text">
      <strong v-if="agentName">{{ agentName }}: </strong>
      {{ text || '正在分析教学要求并推理生成内容...' }}
    </span>
  </div>
</template>

<style scoped>
.agent-thinking-indicator {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: var(--color-primary-soft);
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-lg);
  font-size: 13px;
  color: var(--color-primary);
  margin: 12px 0;
}

.pulse-dots {
  display: flex;
  align-items: center;
  gap: 4px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--color-primary);
  display: inline-block;
  animation: pulseGlow 1.4s infinite ease-in-out;
}

.dot-2 { animation-delay: 0.2s; }
.dot-3 { animation-delay: 0.4s; }

.thinking-text {
  font-weight: 500;
}

.thinking-text strong {
  font-weight: 700;
}
</style>
