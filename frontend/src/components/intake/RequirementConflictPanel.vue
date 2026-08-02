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
.conflict-panel { display: grid; gap: 10px; }
.conflict { display: flex; gap: 9px; padding: 11px; border: 1px solid #fde68a; background: #fffbeb; color: #92400e; }
.conflict.blocking { border-color: #fecaca; background: #fef2f2; color: #991b1b; }
.conflict p { margin: 2px 0; font-size: 13px; line-height: 1.45; }
.conflict span { font-size: 12px; opacity: .85; }
</style>
