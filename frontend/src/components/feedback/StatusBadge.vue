<script setup lang="ts">
import { computed } from 'vue';
import { statusLabel, statusTagType } from '../../types';

const props = defineProps<{
  status: string;
  size?: 'small' | 'default' | 'large';
}>();

const label = computed(() => statusLabel[props.status] || props.status);
const tagType = computed(() => statusTagType[props.status] || 'info');
</script>

<template>
  <el-tag :type="tagType" :size="size || 'default'" effect="light" class="status-badge">
    <span class="status-dot" :class="tagType"></span>
    {{ label }}
  </el-tag>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px !important;
  font-weight: 700 !important;
  border-radius: 999px !important;
  padding: 3px 10px !important;
  border: 1px solid transparent !important;
}

.status-badge.el-tag--warning {
  background: #fff7ed !important;
  color: #c2410c !important;
  border-color: #fed7aa !important;
}

.status-badge.el-tag--success {
  background: #ecfdf5 !important;
  color: #047857 !important;
  border-color: #a7f3d0 !important;
}

.status-badge.el-tag--primary {
  background: #eef2ff !important;
  color: #4f46e5 !important;
  border-color: #c7d2fe !important;
}

.status-badge.el-tag--info {
  background: #f1f5f9 !important;
  color: #475569 !important;
  border-color: #e2e8f0 !important;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: currentColor;
}

.status-dot.primary { background-color: #4f46e5; }
.status-dot.success { background-color: #10b981; }
.status-dot.warning { background-color: #f97316; }
.status-dot.danger { background-color: #ef4444; }
.status-dot.info { background-color: #64748b; }
</style>
