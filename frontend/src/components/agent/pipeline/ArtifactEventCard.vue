<script setup lang="ts">
import { computed } from 'vue';
import { Document, Picture, DataAnalysis, RefreshRight, Warning } from '@element-plus/icons-vue';
import { ARTIFACT_TYPE_LABELS } from '../../../types/agentPipeline';
import type { PPTPolishPageResult, PPTPolishResultStatus } from '../../../types/agentPipeline';

const props = defineProps<{
  type: string;
  data: Record<string, any>;
}>();

const isArtifact = computed(() => ['artifact_created', 'artifact_started', 'artifact_patch'].includes(props.type));
const isAsset = computed(() => props.type === 'asset_generated');
const eventData = computed<Record<string, any>>(() => ({
  ...(props.data || {}),
  ...(props.data?.payload && typeof props.data.payload === 'object' ? props.data.payload : {}),
}));
const isQa = computed(() => ['qa_completed', 'qa.completed'].includes(props.type));
const isRevision = computed(() => props.type === 'revision_started' || props.type === 'revision_completed');
const isPolish = computed(() => props.type === 'polish.result');
const isHuman = computed(() => props.type === 'human.required');

const eventLabelsMap: Record<string, string> = {
  pipeline_completed: '流水线推演完成',
  pipeline_failed: '流水线运行中断',
  artifact_started: '开始生成草稿',
  artifact_patch: '草稿页面已更新',
  qa_issue_found: '发现 QA 问题',
  task_paused: '任务已暂停',
  task_resumed: '任务已恢复运行',
  'polish.result': '页面润色结果',
  'human.required': '需要教师确认',
};

const artifactLabel = computed(() => ARTIFACT_TYPE_LABELS[eventData.value.artifact_type] || eventData.value.artifact_type || '');
const eventLabel = computed(() => eventLabelsMap[props.type] || props.type);
const icon = computed(() => (isAsset.value ? Picture : isQa.value ? DataAnalysis : isRevision.value ? RefreshRight : isHuman.value ? Warning : Document));
const qaLabel = computed(() => {
  if (eventData.value.qa_level === 'vision') return '视觉 QA';
  if (eventData.value.qa_level === 'raster') return '真实渲染 QA';
  return '几何 QA（降级）';
});
const pageResults = computed<PPTPolishPageResult[]>(() => Array.isArray(eventData.value.page_results) ? eventData.value.page_results : []);
const resultStatus = computed<PPTPolishResultStatus | ''>(() => {
  const value = String(eventData.value.result_status || '');
  return ['applied', 'partial', 'no_change', 'needs_confirmation'].includes(value)
    ? value as PPTPolishResultStatus
    : '';
});
const polishTitle = computed(() => {
  const applied = Array.isArray(eventData.value.applied_slide_ids) ? eventData.value.applied_slide_ids.length : 0;
  const preserved = Array.isArray(eventData.value.preserved_slide_ids) ? eventData.value.preserved_slide_ids.length : 0;
  if (resultStatus.value === 'partial') return `部分完成：更新 ${applied} 页，保留 ${preserved} 页`;
  if (resultStatus.value === 'no_change') return '没有可验证的安全改善，原版本保持不变';
  if (resultStatus.value === 'needs_confirmation') return '目标或候选方案需要确认';
  return applied ? `已安全润色 ${applied} 页` : '页面润色已完成';
});
const closeCandidatePage = computed(() => pageResults.value.find(page => page.requires_candidate_confirmation && (page.candidate_rankings?.length || 0) >= 2));
</script>

<template>
  <div class="event-card" :class="{ qa: isQa, revision: isRevision, asset: isAsset, polish: isPolish, human: isHuman }">
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
        <div class="event-title">
          {{ qaLabel }} · 几何 {{ eventData.geometry_score ?? eventData.score }}
          <span v-if="eventData.visual_quality_score != null"> · 视觉 {{ eventData.visual_quality_score }}</span>
          <span v-if="eventData.degraded || eventData.qa_level === 'geometry'" class="warn"> · 已降级，非视觉满分</span>
        </div>
        <div class="event-sub">
          严重 {{ eventData.severity_counts?.critical || 0 }} / 主要 {{ eventData.severity_counts?.major || 0 }} / 次要 {{ eventData.severity_counts?.minor || 0 }}
          <span v-if="eventData.issues?.length" class="issue-preview">{{ eventData.issues[0].message }}</span>
        </div>
      </template>
      <template v-else-if="isRevision">
        <div class="event-title">{{ type === 'revision_started' ? `自动修订（第 ${data.round}/${data.max_rounds} 轮）` : `修订完成（第 ${data.round} 轮）` }}</div>
        <div v-if="data.reason" class="event-sub">{{ data.reason }}</div>
        <div v-if="type === 'revision_completed' && data.applied_changes?.length" class="event-sub">
          {{ data.applied_changes.join('、') }}
        </div>
      </template>
      <template v-else-if="isPolish">
        <div class="event-title">{{ polishTitle }}</div>
        <div v-if="eventData.warnings?.length" class="event-sub warn">{{ eventData.warnings[0] }}</div>
        <div v-if="pageResults.length" class="result-pages">
          <span v-for="page in pageResults.slice(0, 4)" :key="page.slide_id" :class="page.status || page.compile_status">
            {{ page.slide_id }} · {{ (page.status || page.compile_status) === 'preserved' ? '保留' : `+${Number(page.quality_delta || 0).toFixed(1)}` }}
          </span>
        </div>
        <div v-if="closeCandidatePage" class="candidate-inline">
          <strong>{{ closeCandidatePage.slide_id }} 两个候选评分接近：</strong>
          <span v-for="candidate in closeCandidatePage.candidate_rankings?.slice(0, 2)" :key="candidate.candidate_id">
            {{ candidate.layout_type || candidate.candidate_id }} {{ candidate.quality_score ?? '—' }}
          </span>
        </div>
      </template>
      <template v-else-if="isHuman">
        <div class="event-title">{{ eventData.summary || eventData.message || '需要教师确认后继续' }}</div>
        <div v-if="eventData.options?.length" class="event-sub">可选：{{ eventData.options.map((option: any) => option.label).join('、') }}</div>
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
.event-card.polish .event-icon { color: #16a34a; }
.event-card.human .event-icon { color: #7c3aed; }
.event-body { flex: 1; min-width: 0; }
.event-title { font-weight: 500; color: #1f2937; }
.event-sub { color: #6b7280; margin-top: 1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ver { color: #4f46e5; font-weight: 600; }
.warn { color: #f59e0b; }
.issue-preview { color: #ef4444; }
.result-pages { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.result-pages span { padding: 1px 6px; border-radius: 999px; color: #166534; background: #dcfce7; font-size: 10px; }
.result-pages span.preserved { color: #475569; background: #e2e8f0; }
.candidate-inline { display: flex; flex-wrap: wrap; gap: 4px 8px; margin-top: 5px; color: #6d28d9; font-size: 10px; }
.candidate-inline span { padding: 1px 5px; border-radius: 5px; background: #ede9fe; }
</style>
