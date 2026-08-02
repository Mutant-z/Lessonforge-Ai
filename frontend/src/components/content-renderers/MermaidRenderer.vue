<script setup lang="ts">
import { ref, onMounted, watch } from 'vue';

const props = defineProps<{
  content: string;
  isStreaming?: boolean;
}>();

const svgCode = ref<string>('');
const error = ref<string>('');

async function renderDiagram() {
  if (!props.content || !props.content.trim()) return;
  if (props.isStreaming) return;

  const mermaid = (window as any).mermaid;
  if (!mermaid) return;

  try {
    error.value = '';
    const id = `mermaid-svg-${Math.random().toString(36).substr(2, 9)}`;
    const { svg } = await mermaid.render(id, props.content);
    svgCode.value = svg;
  } catch (err: any) {
    error.value = err.message || 'Mermaid 流程图解析错误';
  }
}

onMounted(() => {
  renderDiagram();
});

watch(() => props.content, () => {
  renderDiagram();
});
</script>

<template>
  <div class="mermaid-container lf-card">
    <div class="mermaid-header">
      <span class="mermaid-title">架构与流程图 (Mermaid)</span>
    </div>

    <div v-if="error" class="mermaid-error">
      <p>流程图未闭合或存在语法问题:</p>
      <pre>{{ content }}</pre>
    </div>
    <div v-else-if="svgCode" class="mermaid-svg-box" v-html="svgCode"></div>
    <div v-else class="mermaid-raw">
      <pre>{{ content }}</pre>
    </div>
  </div>
</template>

<style scoped>
.mermaid-container {
  margin: 16px 0;
  text-align: center;
}

.mermaid-header {
  text-align: left;
  margin-bottom: 12px;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-primary);
}

.mermaid-svg-box {
  overflow-x: auto;
  padding: 16px;
}

.mermaid-error, .mermaid-raw {
  text-align: left;
  background: var(--bg-subtle);
  padding: 12px;
  border-radius: var(--radius-sm);
  font-family: monospace;
  font-size: 12px;
}
</style>
