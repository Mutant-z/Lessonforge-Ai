<script setup lang="ts">
import { Warning } from '@element-plus/icons-vue';
import type { IntakeConflict } from '../../types';

defineProps<{ conflicts: IntakeConflict[] }>();
</script>

<template>
  <div v-if="conflicts.length" class="conflict-panel">
    <div v-for="item in conflicts" :key="`${item.field}-${item.description}`" class="conflict" :class="item.severity">
      <el-icon><Warning /></el-icon>
      <div>
        <strong>{{ item.severity === 'blocking' ? '需要先处理' : '建议核对' }}</strong>
        <p>{{ item.description }}</p>
        <span v-if="item.suggestion">{{ item.suggestion }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.conflict-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 16px 0;
}

.conflict {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: var(--radius-control, 12px);
  border: 1px solid #fde68a;
  background: #fffbeb;
  color: #92400e;
  font-size: 13px;
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(0,0,0,0.04));
  transition: all var(--motion-normal, 200ms);
}

.conflict.blocking {
  border-color: #fecdd3;
  background: #fff1f2;
  color: #991b1b;
}

.conflict .el-icon {
  font-size: 16px;
  margin-top: 2px;
  flex-shrink: 0;
}

.conflict strong {
  font-size: 13px;
  font-weight: 700;
}

.conflict p {
  margin: 3px 0 2px;
  font-size: 12.5px;
  line-height: 1.5;
}

.conflict span {
  font-size: 11.5px;
  opacity: 0.85;
  font-style: italic;
}
</style>
