<script setup lang="ts">
import { computed, ref } from 'vue';
import { CopyDocument, Check } from '@element-plus/icons-vue';

const props = defineProps<{
  code: string;
  language?: string;
}>();

const copied = ref(false);

const highlightedCode = computed(() => {
  const hljs = (window as any).hljs;
  if (!hljs) return props.code;

  const lang = props.language && hljs.getLanguage(props.language) ? props.language : 'plaintext';
  try {
    return hljs.highlight(props.code || '', { language: lang }).value;
  } catch {
    return props.code;
  }
});

async function copyCode() {
  await navigator.clipboard.writeText(props.code);
  copied.value = true;
  setTimeout(() => { copied.value = false; }, 2000);
}
</script>

<template>
  <div class="code-block-wrapper">
    <div class="code-header">
      <span class="code-lang">{{ language || 'code' }}</span>
      <el-button size="small" link type="primary" :icon="copied ? Check : CopyDocument" @click="copyCode">
        {{ copied ? '已复制' : '复制代码' }}
      </el-button>
    </div>
    <pre class="hljs"><code v-html="highlightedCode"></code></pre>
  </div>
</template>

<style scoped>
.code-block-wrapper {
  border-radius: var(--radius-lg);
  overflow: hidden;
  margin: 16px 0;
  box-shadow: var(--shadow-sm);
}

.code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
}

.code-lang {
  font-family: monospace;
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
}

pre.hljs {
  margin: 0;
  padding: 16px;
  background: #1e293b;
  color: #f8fafc;
  font-family: SFMono-Regular, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
  overflow-x: auto;
}
</style>
