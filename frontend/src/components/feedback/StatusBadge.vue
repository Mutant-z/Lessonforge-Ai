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
  gap: 6px;
  font-weight: 600;
  border-radius: var(--radius-full);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: currentColor;
}

.status-dot.primary { background-color: var(--color-primary); }
.status-dot.success { background-color: var(--color-success); }
.status-dot.warning { background-color: var(--color-warning); }
.status-dot.danger { background-color: var(--color-danger); }
.status-dot.info { background-color: var(--text-muted); }
</style>
