<script setup lang="ts">
import { ref, computed } from 'vue';
import type { AgentStreamEvent } from '../../types';

const props = defineProps<{
  events: AgentStreamEvent[];
}>();

const filterType = ref<'all' | 'nodes' | 'issues'>('all');

const filteredEvents = computed(() => {
  if (filterType.value === 'nodes') {
    return props.events.filter(e => ['node_started', 'node_completed', 'node_failed'].includes(e.type));
  }
  if (filterType.value === 'issues') {
    return props.events.filter(e => ['quality_issue_found', 'node_failed'].includes(e.type));
  }
  return props.events;
});

function formatTime(timestamp?: string) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}
</script>

<template>
  <div class="agent-event-log lf-card">
    <div class="log-header">
      <div class="log-title">
        <h3>Agent 运行记录</h3>
        <span class="log-count">共 {{ events.length }} 条事件</span>
      </div>
      <div class="log-filters">
        <el-radio-group v-model="filterType" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="nodes">节点变迁</el-radio-button>
          <el-radio-button value="issues">质量与异常</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <div class="log-body">
      <div v-if="!filteredEvents.length" class="empty-log">
        暂无对应运行事件...
      </div>
      <div 
        v-for="(event, idx) in filteredEvents" 
        :key="event.id || idx" 
        class="log-item"
        :class="[event.type]"
      >
        <span class="log-time">{{ formatTime(event.timestamp) }}</span>
        <span class="log-type-tag" :class="[event.type]">{{ event.type }}</span>
        <div class="log-content">
          <span v-if="event.nodeId" class="log-node">[{{ event.nodeId }}]</span>
          <span class="log-msg">{{ event.message || event.delta || '处理完成' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-event-log {
  padding: 20px;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}

.log-title h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;

  display: inline-block;
  margin-right: 10px;
}

.log-count {
  font-size: 12px;
  color: var(--text-muted);
}

.log-body {
  max-height: 280px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-log {
  text-align: center;
  padding: 30px;
  color: var(--text-muted);
  font-size: 13px;
}

.log-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--bg-page);
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-family: monospace;
}

.log-time {
  color: var(--text-muted);
  min-width: 65px;
}

.log-type-tag {
  padding: 2px 6px;
  border-radius: var(--radius-xs);
  font-weight: 600;
  font-size: 10px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.log-type-tag.node_started { background: var(--color-primary-soft); color: var(--color-primary); }
.log-type-tag.node_completed { background: var(--color-success-soft); color: var(--color-success); }
.log-type-tag.node_failed, .log-type-tag.quality_issue_found { background: var(--color-danger-soft); color: var(--color-danger); }

.log-content {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-node {
  font-weight: 700;
  color: var(--color-primary);
  margin-right: 6px;
}

.log-msg {
  color: var(--text-primary);
}
</style>
