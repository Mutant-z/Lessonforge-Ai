<script setup lang="ts">
import { ref, computed } from 'vue';
import CodeBlockRenderer from './CodeBlockRenderer.vue';

const props = defineProps<{
  content: string | object;
}>();

const mode = ref<'formatted' | 'raw'>('formatted');

const parsedObject = computed(() => {
  if (typeof props.content === 'object') return props.content;
  try {
    return JSON.parse(props.content);
  } catch {
    return null;
  }
});

const jsonString = computed(() => {
  if (typeof props.content === 'string') return props.content;
  return JSON.stringify(props.content, null, 2);
});
</script>

<template>
  <div class="json-tree-renderer">
    <div class="json-toolbar">
      <span class="json-tag">JSON 数据结构</span>
      <div class="view-switch">
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="formatted">结构视图</el-radio-button>
          <el-radio-button value="raw">原始 JSON</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <div v-if="mode === 'formatted' && parsedObject" class="json-tree-box">
      <pre class="json-pretty">{{ JSON.stringify(parsedObject, null, 2) }}</pre>
    </div>
    <div v-else>
      <CodeBlockRenderer :code="jsonString" language="json" />
    </div>
  </div>
</template>

<style scoped>
.json-tree-renderer {
  margin: 16px 0;
}

.json-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.json-tag {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-primary);
}

.json-pretty {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 16px;
  font-family: monospace;
  font-size: 13px;
  overflow-x: auto;
  color: var(--text-primary);
}
</style>
