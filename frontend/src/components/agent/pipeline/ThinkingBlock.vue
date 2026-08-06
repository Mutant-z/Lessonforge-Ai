<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue';
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';

const props = defineProps<{
  text: string;
  active: boolean;
}>();

/** 打字机：逐步揭示目标文本；流式期间每帧揭示若干字符，结束后一次性补全。 */
const displayed = ref('');
let timer: number | null = null;
let targetLength = 0;

function tick() {
  if (targetLength < props.text.length) {
    targetLength = Math.min(props.text.length, targetLength + 4);
    displayed.value = props.text.slice(0, targetLength);
  } else {
    stop();
  }
}

function start() {
  if (timer !== null) return;
  timer = window.setInterval(tick, 18);
}

function stop() {
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
}

watch(
  () => props.text,
  () => {
    if (props.active) {
      // 流式：继续逐字揭示；若首次到达则启动定时器
      if (timer === null) start();
    } else {
      // 结束：一次性补全
      displayed.value = props.text;
      stop();
    }
  },
  { immediate: true },
);

onUnmounted(stop);
</script>

<template>
  <div class="thinking-block" :class="{ active }">
    <div v-if="displayed" class="thinking-label">
      <span class="pulse-dot" /> 思考过程
    </div>
    <MarkdownRenderer :content="displayed" is-streaming />
    <span v-if="active && targetLength < text.length" class="typing-cursor" />
  </div>
</template>

<style scoped>
.thinking-block {
  border-left: 2px solid #c7d2fe;
  background: #f5f7ff;
  border-radius: 8px;
  margin: 8px 0 4px;
  padding: 8px 12px 4px;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}
.thinking-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 800;
  color: #6366f1;
  margin-bottom: 4px;
}
.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366f1;
  animation: pulse 1s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: #6366f1;
  animation: blink 0.8s step-end infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
.thinking-block :deep(p) { margin: 2px 0; }
.thinking-block :deep(pre) { font-size: 12px; }
</style>
