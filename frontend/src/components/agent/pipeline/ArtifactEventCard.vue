<script setup lang="ts">
import { computed } from 'vue';
import { Document, Picture, DataAnalysis, RefreshRight, Warning } from '@element-plus/icons-vue';
import { ARTIFACT_TYPE_LABELS } from '../../../types/agentPipeline';

const props = defineProps<{
  type: string;
  data: Record<string, any>;
}>();

const isArtifact = computed(() => ['artifact_created', 'artifact_started', 'artifact_patch'].includes(props.type));
const isAsset = computed(() => props.type === 'asset_generated');
const isQa = computed(() => props.type === 'qa_completed');
const isRevision = computed(() => props.type === 'revision_started' || props.type === 'revision_completed');

const eventLabelsMap: Record<string, string> = {
  pipeline_completed: '流水线推演完成',
  pipeline_failed: '流水线运行中断',
  artifact_started: '开始生成草稿',
  artifact_patch: '草稿页面已更新',
  qa_issue_found: '发现 QA 问题',
  task_paused: '任务已暂停',
  task_resumed: '任务已恢复运行',
};

const artifactLabel = computed(() => ARTIFACT_TYPE_LABELS[props.data.artifact_type] || props.data.artifact_type || '');
const eventLabel = computed(() => eventLabelsMap[props.type] || props.type);
const icon = computed(() => (isAsset.value ? Picture : isQa.value ? DataAnalysis : isRevision.value ? RefreshRight : Document));
</script>

<template>
  <div class="event-card" :class="{ qa: isQa, revision: isRevision, asset: isAsset }">
    <el-icon class="event-icon"><component :is="icon" /></el-icon>
    <div class="event-body">
      <template v-if="isArtifact">
        <div class="event-title">{{ eventLabel }}：{{ artifactLabel }} <span v-if="data.version" class="ver">v{{ data.version }}</span></div>
        <div v-if="data.producer_agent" class="event-sub">由 {{ data.producer_agent }} 生成</div>
        <div v-if="data.summary" class="event-sub">{{ data.summary }}</div>
      </template>
      <template v-else-if="isAsset">
        <div class="event-title">生成视觉素材</div>
        <div class="event-sub">{{ data.file_path || '' }}</div>
      </template>
      <template v-else-if="isQa">
        <div class="event-title">视觉 QA 评分 {{ data.score }}<span v-if="data.degraded" class="warn"> · 几何模式</span></div>
        <div class="event-sub">
          严重 {{ data.severity_counts?.critical || 0 }} / 主要 {{ data.severity_counts?.major || 0 }} / 次要 {{ data.severity_counts?.minor || 0 }}
          <span v-if="data.issues?.length" class="issue-preview">{{ data.issues[0].message }}</span>
        </div>
      </template>
      <template v-else-if="isRevision">
        <div class="event-title">{{ type === 'revision_started' ? `自动修订（第 ${data.round}/${data.max_rounds} 轮）` : `修订完成（第 ${data.round} 轮）` }}</div>
        <div v-if="data.reason" class="event-sub">{{ data.reason }}</div>
        <div v-if="type === 'revision_completed' && data.applied_changes?.length" class="event-sub">
          {{ data.applied_changes.join('、') }}
        </div>
      </template>
      <template v-else>
        <div class="event-title">{{ eventLabel }}</div>
        <div v-if="data.summary || data.message || data.reason" class="event-sub">{{ data.summary || data.message || data.reason }}</div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.event-card {
  display: flex; gap: 8px; align-items: flex-start;
  padding: 6px 12px 6px 8px; font-size: 12px; color: #374151;
}
.event-icon { color: #9ca3af; margin-top: 2px; }
.event-card.qa .event-icon { color: #8b5cf6; }
.event-card.revision .event-icon { color: #f59e0b; }
.event-card.asset .event-icon { color: #0ea5e9; }
.event-body { flex: 1; min-width: 0; }
.event-title { font-weight: 500; color: #1f2937; }
.event-sub { color: #6b7280; margin-top: 1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ver { color: #4f46e5; font-weight: 600; }
.warn { color: #f59e0b; }
.issue-preview { color: #ef4444; }
</style>
