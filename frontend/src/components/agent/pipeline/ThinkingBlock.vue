<script setup lang="ts">
import { ref, watch } from 'vue';
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';

const props = defineProps<{
  text: string;
  active: boolean;
}>();

/** 服务器已经按增量发送；这里只做轻量 Markdown 更新，不再二次延迟输出。 */
const displayed = ref('');

watch(
  () => props.text,
  () => {
    displayed.value = props.text;
  },
  { immediate: true },
);
</script>

<template>
  <div class="thinking-block" :class="{ active }">
    <div v-if="displayed" class="thinking-label">
      <span class="pulse-dot" /> 执行摘要
    </div>
    <MarkdownRenderer :content="displayed" is-streaming />
    <span v-if="active" class="typing-cursor" />
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
