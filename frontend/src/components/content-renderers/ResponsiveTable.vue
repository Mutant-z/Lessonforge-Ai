<script setup lang="ts">
import { Download } from '@element-plus/icons-vue';

const props = defineProps<{
  headers: string[];
  rows: string[][];
  title?: string;
}>();

function exportCSV() {
  const content = [props.headers, ...props.rows]
    .map(row => row.map(cell => `"${(cell || '').replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${props.title || 'table'}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div class="responsive-table-card lf-card">
    <div v-if="title || rows.length" class="table-toolbar">
      <h4 class="table-title">{{ title || '数据表格' }}</h4>
      <el-button size="small" :icon="Download" @click="exportCSV">导出 CSV</el-button>
    </div>

    <div class="table-scroll-wrapper">
      <table class="lf-custom-table">
        <thead>
          <tr>
            <th v-for="(h, i) in headers" :key="i">{{ h }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rIdx) in rows" :key="rIdx">
            <td v-for="(cell, cIdx) in row" :key="cIdx">{{ cell }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.responsive-table-card {
  margin: 16px 0;
  padding: 16px;
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.table-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.table-scroll-wrapper {
  overflow-x: auto;
  max-width: 100%;
}

.lf-custom-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.lf-custom-table th,
.lf-custom-table td {
  padding: 10px 14px;
  border: 1px solid var(--border-default);
  text-align: left;
  white-space: nowrap;
}

.lf-custom-table th {
  background: var(--bg-subtle);
  font-weight: 700;
  color: var(--text-primary);
}

.lf-custom-table tr:nth-child(even) {
  background: var(--bg-page);
}

.lf-custom-table tr:hover {
  background: var(--color-primary-soft);
}
</style>
