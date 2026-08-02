<script setup lang="ts">
import { computed } from 'vue';
import { Cpu, CircleCheck, Loading, Clock, Document, Platform, Edit, Checked } from '@element-plus/icons-vue';

const props = withDefaults(defineProps<{
  name: string;
  role: string;
  status: 'running' | 'completed' | 'pending' | 'reviewing';
  color?: 'primary' | 'cyan' | 'violet' | 'mint' | 'amber';
  iconName?: string;
  detail?: string;
}>(), {
  color: 'violet',
  detail: ''
});

const colorClassMap = {
  primary: 'node-primary',
  cyan: 'node-cyan',
  violet: 'node-violet',
  mint: 'node-mint',
  amber: 'node-amber'
};
</script>

<template>
  <div class="agent-node-card" :class="[colorClassMap[props.color], props.status]">
    <div class="node-icon-box">
      <el-icon v-if="status === 'running'" class="is-loading"><Loading /></el-icon>
      <el-icon v-else-if="status === 'completed'"><CircleCheck /></el-icon>
      <el-icon v-else-if="status === 'reviewing'"><Checked /></el-icon>
      <el-icon v-else><Cpu /></el-icon>
    </div>

    <div class="node-info">
      <div class="node-header">
        <span class="node-name">{{ props.name }}</span>
        <span class="status-indicator" :class="props.status">
          <span v-if="props.status === 'running'" class="pulse-dot"></span>
          {{ props.status === 'running' ? '生成中' : props.status === 'completed' ? '已就绪' : props.status === 'reviewing' ? '质检中' : '等待中' }}
        </span>
      </div>
      <span class="node-role">{{ props.role }}</span>
      <span v-if="props.detail" class="node-detail">{{ props.detail }}</span>
    </div>
  </div>
</template>

<style scoped>
.agent-node-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm);
  transition: all var(--motion-normal) var(--ease-out-smooth);
  position: relative;
  overflow: hidden;
}

.agent-node-card.running {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-glow-primary);
}

.agent-node-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.node-icon-box {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-control);
  display: grid;
  place-items: center;
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 2px;
}

.node-primary .node-icon-box { background: var(--color-primary-soft); color: var(--color-primary); }
.node-cyan .node-icon-box { background: var(--accent-cyan-soft); color: var(--accent-cyan); }
.node-violet .node-icon-box { background: var(--accent-violet-soft); color: var(--accent-violet); }
.node-mint .node-icon-box { background: var(--accent-mint-soft); color: var(--accent-mint); }
.node-amber .node-icon-box { background: var(--accent-amber-soft); color: var(--accent-amber); }

.node-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.node-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.node-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-role {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 1px;
}

.node-detail {
  font-size: 10.5px;
  color: var(--color-primary);
  background: var(--surface-emphasis);
  padding: 2px 6px;
  border-radius: var(--radius-xs);
  margin-top: 6px;
  width: fit-content;
}

.status-indicator {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.status-indicator.running {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.status-indicator.completed {
  background: var(--accent-mint-soft);
  color: var(--accent-mint);
}

.status-indicator.reviewing {
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
}

.status-indicator.pending {
  background: var(--bg-subtle);
  color: var(--text-muted);
}

.pulse-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-primary);
  animation: pulseGlow 1.5s infinite;
}
</style>
