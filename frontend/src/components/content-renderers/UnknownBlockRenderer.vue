<script setup lang="ts">
import JsonTreeRenderer from './JsonTreeRenderer.vue';

defineProps<{
  block: any;
}>();
</script>

<template>
  <div class="unknown-block-fallback lf-card">
    <div class="unknown-header">
      <span>未识别的数据块格式 [{{ block.type || 'unknown' }}]</span>
    </div>
    <JsonTreeRenderer :content="block.content || block" />
  </div>
</template>

<style scoped>
.unknown-block-fallback {
  margin: 16px 0;
  border-left: 3px solid var(--color-warning);
}

.unknown-header {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-warning);
  margin-bottom: 8px;
}
</style>
