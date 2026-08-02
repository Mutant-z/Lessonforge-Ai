<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  math: string;
  displayMode?: boolean;
}>();

const renderedMath = computed(() => {
  const katex = (window as any).katex;
  if (!katex) return props.math;

  try {
    return katex.renderToString(props.math || '', {
      displayMode: props.displayMode !== false,
      throwOnError: false
    });
  } catch {
    return props.math;
  }
});
</script>

<template>
  <div :class="['math-rendered-container', { display: displayMode !== false }]" v-html="renderedMath"></div>
</template>

<style scoped>
.math-rendered-container {
  display: inline-block;
  margin: 4px 0;
}

.math-rendered-container.display {
  display: block;
  text-align: center;
  margin: 16px 0;
  overflow-x: auto;
}
</style>
