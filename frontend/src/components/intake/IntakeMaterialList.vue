<script setup lang="ts">
import { Document, CircleCheck, Warning } from '@element-plus/icons-vue';
import type { IntakeMaterial } from '../../types';

defineProps<{ materials: IntakeMaterial[] }>();
</script>

<template>
  <div v-if="materials.length" class="material-list">
    <div class="list-label">参考材料</div>
    <div v-for="item in materials" :key="item.id" class="material-item">
      <el-icon class="file-icon"><Document /></el-icon>
      <div class="material-main">
        <strong>{{ item.original_filename }}</strong>
        <span>{{ (item.size_bytes / 1024 / 1024).toFixed(2) }} MB</span>
      </div>
      <el-icon v-if="item.parse_status === 'completed'" class="success"><CircleCheck /></el-icon>
      <el-tooltip v-else :content="item.error_message || '材料解析失败'">
        <el-icon class="failed"><Warning /></el-icon>
      </el-tooltip>
    </div>
  </div>
</template>

<style scoped>
.material-list { display: grid; gap: 8px; }
.list-label { color: #64748b; font-size: 12px; font-weight: 800; }
.material-item { display: flex; align-items: center; gap: 9px; padding: 9px 11px; border: 1px solid #e2e8f0; background: #f7f7f8; }
.file-icon { color: #002fa7; }
.material-main { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.material-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.material-main span { color: #64748b; font-size: 11px; }
.success { color: #16a34a; }
.failed { color: #dc2626; }
</style>
