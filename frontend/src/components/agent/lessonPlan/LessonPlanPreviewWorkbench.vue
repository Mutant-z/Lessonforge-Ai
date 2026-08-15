<script setup lang="ts">
/** 教学设计预览工作台：文档预览。 */
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';
import type { CourseTask } from '../../../types/project';

const props = defineProps<{
  task?: CourseTask | null;
  markdown?: string | null;
  loading?: boolean;
}>();
const emit = defineEmits<{
  (event: 'open-version-drawer'): void;
  (event: 'sync-context'): void;
}>();
</script>

<template>
  <div class="lesson-plan-preview-workbench">
    <header class="lp-preview-header">
      <div class="lp-preview-title">
        <span>教学设计预览</span>
      </div>
      <div class="lp-preview-actions">
        <button type="button" class="lp-text-btn" @click="emit('open-version-drawer')">版本历史</button>
        <button
          v-if="task"
          type="button"
          class="lp-text-btn"
          @click="$emit('sync-context')"
        >同步上下文</button>
      </div>
    </header>

    <div v-if="loading && !markdown" class="lp-preview-loading">
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else-if="!markdown && !task?.current_artifact" class="lp-preview-empty">
      <p>尚未生成教学设计。发送指令或等待首稿生成。</p>
    </div>

    <div v-else class="lp-preview-document">
      <MarkdownRenderer v-if="markdown" :content="markdown" />
      <p v-else class="lp-preview-empty">文档预览暂不可用。</p>
    </div>
  </div>
</template>

<style scoped>
.lesson-plan-preview-workbench {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: #ffffff;
}

.lp-preview-header {
  height: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-default, #e2e8f0);
}

.lp-preview-title {
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

.lp-preview-actions {
  display: flex;
  gap: 8px;
}

.lp-text-btn {
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.lp-text-btn:hover {
  border-color: #c7d2fe;
  color: #4f46e5;
}

.lp-preview-loading,
.lp-preview-empty {
  padding: 32px;
  color: #64748b;
  font-size: 13px;
}

.lp-preview-document {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 24px 32px;
}
</style>
