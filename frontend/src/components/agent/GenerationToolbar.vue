<script setup lang="ts">
import { 
  VideoPause, 
  VideoPlay, 
  Close, 
  Refresh, 
  CopyDocument, 
  FolderChecked, 
  Monitor 
} from '@element-plus/icons-vue';

const props = defineProps<{
  status: string;
  isStreaming?: boolean;
  hasContent?: boolean;
}>();

const emit = defineEmits<{
  (e: 'pause'): void;
  (e: 'resume'): void;
  (e: 'cancel'): void;
  (e: 'reconnect'): void;
  (e: 'retry'): void;
  (e: 'copy'): void;
  (e: 'save'): void;
  (e: 'background'): void;
}>();
</script>

<template>
  <div class="generation-toolbar animate-fade-in">
    <div class="toolbar-status-summary">
      <span class="status-indicator-dot" :class="[status]"></span>
      <span class="status-title">
        {{ 
          status === 'running' ? 'Agent 正在生成资源...' : 
          status === 'paused' ? '任务已暂停' : 
          status === 'waiting_human' ? '生成完成，等待终审' : 
          status === 'failed' ? '生成中断/失败' : '状态: ' + status
        }}
      </span>
    </div>

    <div class="toolbar-actions">
      <!-- Running State Controls -->
      <template v-if="status === 'running' || isStreaming">
        <el-button size="small" :icon="VideoPause" @click="emit('pause')">暂停生成</el-button>
        <el-button size="small" :icon="Monitor" @click="emit('background')">后台运行</el-button>
        <el-button size="small" type="danger" plain :icon="Close" @click="emit('cancel')">取消任务</el-button>
      </template>

      <!-- Paused State Controls -->
      <template v-else-if="status === 'paused'">
        <el-button size="small" type="primary" :icon="VideoPlay" @click="emit('resume')">继续生成</el-button>
        <el-button size="small" type="danger" plain :icon="Close" @click="emit('cancel')">终止任务</el-button>
      </template>

      <!-- Failed State Controls -->
      <template v-else-if="status === 'failed'">
        <el-button size="small" type="primary" :icon="Refresh" @click="emit('retry')">重试当前节点</el-button>
        <el-button size="small" :icon="Refresh" @click="emit('reconnect')">重新连接</el-button>
      </template>

      <!-- Completed / Content Actions -->
      <template v-if="hasContent">
        <el-button size="small" :icon="CopyDocument" @click="emit('copy')">复制内容</el-button>
        <el-button size="small" type="success" :icon="FolderChecked" @click="emit('save')">保存草稿</el-button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.generation-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  margin-bottom: 16px;
  box-shadow: var(--shadow-xs);
}

.toolbar-status-summary {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-indicator-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text-muted);
}

.status-indicator-dot.running {
  background: var(--color-primary);
  animation: pulseGlow 1.5s infinite;
}

.status-indicator-dot.paused {
  background: var(--color-warning);
}

.status-indicator-dot.waiting_human, .status-indicator-dot.completed {
  background: var(--color-success);
}

.status-indicator-dot.failed {
  background: var(--color-danger);
}

.status-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}
</style>
