<script setup lang="ts">
import type { QualityIssue } from '../../types';
import { Warning, MagicStick, Check } from '@element-plus/icons-vue';

defineProps<{
  issue: QualityIssue;
}>();

const emit = defineEmits<{
  (e: 'fix', issue: QualityIssue): void;
  (e: 'locate', issue: QualityIssue): void;
}>();

function getSeverityBadge(sev: string) {
  if (sev === 'critical') return { label: '严重缺陷', type: 'danger' };
  if (sev === 'major') return { label: '主要规范', type: 'warning' };
  return { label: '次要建议', type: 'info' };
}
</script>

<template>
  <div class="quality-issue-card card-hover" :class="[issue.severity]">
    <div class="issue-header">
      <div class="issue-meta">
        <el-icon class="issue-icon"><Warning /></el-icon>
        <el-tag size="small" :type="getSeverityBadge(issue.severity).type as any">
          {{ getSeverityBadge(issue.severity).label }}
        </el-tag>
        <span class="artifact-type-tag">[{{ issue.artifact_type }}]</span>
      </div>
      <span class="field-path">{{ issue.field_path }}</span>
    </div>

    <p class="issue-desc">{{ issue.issue_description }}</p>

    <div v-if="issue.evidence" class="issue-evidence">
      <strong>分析依据:</strong> {{ issue.evidence }}
    </div>

    <div class="issue-suggestion">
      <strong>💡 AI 修改建议:</strong> {{ issue.suggestion }}
    </div>

    <div class="issue-actions">
      <el-button size="small" link @click="emit('locate', issue)">在页面中定位</el-button>
      <el-button size="small" type="primary" :icon="MagicStick" @click="emit('fix', issue)">AI 一键修复</el-button>
    </div>
  </div>
</template>

<style scoped>
.quality-issue-card {
  padding: 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-left: 4px solid var(--text-muted);
  border-radius: var(--radius-md);
  margin-bottom: 12px;
}

.quality-issue-card.critical { border-left-color: var(--color-danger); }
.quality-issue-card.major { border-left-color: var(--color-warning); }

.issue-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.issue-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.issue-icon {
  font-size: 16px;
}

.critical .issue-icon { color: var(--color-danger); }
.major .issue-icon { color: var(--color-warning); }

.artifact-type-tag {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}

.field-path {
  font-size: 11px;
  color: var(--text-muted);
  font-family: monospace;
}

.issue-desc {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.issue-evidence {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.issue-suggestion {
  font-size: 12px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 6px 10px;
  border-radius: var(--radius-xs);
  margin-bottom: 12px;
}

.issue-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
