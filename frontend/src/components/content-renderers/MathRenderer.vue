<script setup lang="ts">
import { computed } from 'vue';
import { renderMathHtml } from '../../services/markdownText';

const props = defineProps<{
  math: string;
  displayMode?: boolean;
}>();

const renderedMath = computed(() => {
  const math = props.math || '';
  if (!math.trim()) return '';
  // 优先 katex；解析失败时回退为可读普通文本，禁止暴露 LaTeX 源码
  return renderMathHtml(math, props.displayMode !== false);
});
</script>

<template>
  <div
    :class="['math-rendered-container', { display: displayMode !== false }]"
    v-html="renderedMath"
  ></div>
</template>

<style scoped>
.math-rendered-container {
  display: inline-block;
  margin: 4px 0;
  overflow-x: auto;
  max-width: 100%;
}

.math-rendered-container.display {
  display: block;
  text-align: center;
  margin: 16px 0;
}
</style>

<!-- 兜底公式样式需全局生效（v-html 注入的内容无法命中 scoped 选择器） -->
<style>
.math-rendered-container .math-inline-fallback {
  font-style: italic;
  background: #eef2ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
  padding: 0 4px;
  border-radius: 4px;
}

.math-rendered-container .math-display-fallback {
  font-style: italic;
  text-align: center;
  background: #f5f3ff;
  color: #3730a3;
  border: 1px solid #e0e7ff;
  padding: 8px 12px;
  margin: 0.5em 0;
  border-radius: 8px;
  overflow-x: auto;
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
