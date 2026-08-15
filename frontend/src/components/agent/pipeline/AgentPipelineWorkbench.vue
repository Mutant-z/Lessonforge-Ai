<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { Check, MagicStick, Switch, VideoPause, VideoPlay } from '@element-plus/icons-vue';
import { pptTemplatesApi } from '../../../api/pptTemplates';
import { pipelineApi } from '../../../api/pipeline';
import { useProjectStore } from '../../../stores/project';
import { usePipelineStore } from '../../../stores/pipeline';
import { useModelConfigStore } from '../../../stores/modelConfigs';
import type { PPTContent, PPTTemplate } from '../../../types';
import type { PPTPolishModality } from '../../../types/project';
import type { PPTPolishPageResult, PPTPolishResult } from '../../../types/agentPipeline';
import { PIPELINE_STATUS_LABELS } from '../../../types/agentPipeline';
import AgentExecutionTimeline from './AgentExecutionTimeline.vue';
import AgentComposer from './AgentComposer.vue';
import PPTPreviewWorkbench from './PPTPreviewWorkbench.vue';
import { normalizeSlideIndex, updateSlideSelection } from '../../../utils/slideNavigation';
import { imageGenerationModels, uniqueImageModelId } from '../../../utils/imageModelSelection';

const props = defineProps<{
  courseId: string;
  taskType: string;
}>();
const emit = defineEmits<{ (event: 'open-version-drawer'): void }>();

const projectStore = useProjectStore();
const pipelineStore = usePipelineStore();
const modelConfigStore = useModelConfigStore();

const task = computed(() => projectStore.currentTask);
const pipelineMatchesActiveRun = computed(() => {
  const activeRunId = task.value?.active_run_id;
  const detailRunId = pipelineStore.run?.generation_run_id;
  if (activeRunId) return activeRunId === detailRunId;
  return true;
});
const status = computed(() => {
  if (task.value?.active_run_id && !pipelineMatchesActiveRun.value) return task.value?.status || 'queued';
  return pipelineStore.status || task.value?.status || '';
});
const paused = computed(() => status.value === 'paused');
const pausing = computed(() => status.value === 'pausing');
const isRunning = computed(() => ['queued', 'running', 'pausing'].includes(status.value));
const imageModelCandidates = computed(() => imageGenerationModels(modelConfigStore.configs));
const bindingImageModel = ref(false);
const humanResponsePending = ref('');

function polishResultFrom(value: unknown): PPTPolishResult | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, any>;
  const resultStatus = String(record.result_status || '');
  if (!['applied', 'partial', 'no_change', 'needs_confirmation'].includes(resultStatus)) return null;
  return {
    result_status: resultStatus as PPTPolishResult['result_status'],
    page_results: Array.isArray(record.page_results) ? record.page_results : [],
    applied_slide_ids: Array.isArray(record.applied_slide_ids) ? record.applied_slide_ids : undefined,
    preserved_slide_ids: Array.isArray(record.preserved_slide_ids) ? record.preserved_slide_ids : undefined,
    warnings: Array.isArray(record.warnings) ? record.warnings : undefined,
  };
}

const latestPolishResult = computed<PPTPolishResult | null>(() => {
  const runId = String(pipelineStore.run?.generation_run_id || task.value?.active_run_id || '');
  for (let index = pipelineStore.timeline.length - 1; index >= 0; index -= 1) {
    const event = pipelineStore.timeline[index];
    if (event.type !== 'polish.result') continue;
    if (runId && event.data?.run_id && String(event.data.run_id) !== runId) continue;
    const parsed = polishResultFrom(event.data?.payload || event.data);
    if (parsed) return parsed;
  }
  return polishResultFrom(pipelineStore.run?.plan);
});

const latestQa = computed<Record<string, any> | null>(() => {
  const runId = String(pipelineStore.run?.generation_run_id || task.value?.active_run_id || '');
  for (let index = pipelineStore.timeline.length - 1; index >= 0; index -= 1) {
    const event = pipelineStore.timeline[index];
    if (!['qa_completed', 'qa.completed'].includes(event.type)) continue;
    if (runId && event.data?.run_id && String(event.data.run_id) !== runId) continue;
    return { ...(event.data || {}), ...((event.data?.payload as Record<string, any>) || {}) };
  }
  return null;
});

const polishSummary = computed(() => {
  const result = latestPolishResult.value;
  if (!result) return null;
  const pages = result.page_results || [];
  const applied = result.applied_slide_ids?.length
    ?? pages.filter(page => !['preserved'].includes(String(page.status || page.compile_status))).length;
  const preserved = result.preserved_slide_ids?.length
    ?? pages.filter(page => String(page.status || page.compile_status) === 'preserved').length;
  const qaLevel = String(latestQa.value?.qa_level || '');
  const degraded = Boolean(latestQa.value?.degraded)
    || qaLevel === 'geometry'
    || pages.some(page => page.degraded || page.qa_level === 'geometry');
  const labels: Record<PPTPolishResult['result_status'], string> = {
    applied: applied ? `已安全润色 ${applied} 页` : '页面润色已完成',
    partial: `已润色 ${applied} 页，${preserved} 页保留原状`,
    no_change: '未发现可验证的安全改善，原版本保持不变',
    needs_confirmation: pages.some(page => page.requires_candidate_confirmation)
      ? '安全候选等待选择，确认前未创建新版本'
      : '修改目标需要确认，本轮未创建新版本',
    rejected: '本轮修改未通过安全门禁，原版本保持不变',
    answer_only: '仅回答问题，未修改设计',
  };
  return {
    status: result.result_status,
    label: labels[result.result_status],
    degraded,
    qaLabel: qaLevel === 'vision' ? '视觉 QA' : qaLevel === 'raster' ? '真实渲染 QA' : degraded ? '几何 QA（降级）' : '',
    pages,
  };
});

function metricNumber(page: PPTPolishPageResult, key: string, side: 'baseline' | 'final'): number | null {
  const metrics = side === 'baseline'
    ? page.baseline_metrics
    : page.decision === 'preserved' && page.best_candidate_metrics
      ? page.best_candidate_metrics
      : page.final_metrics;
  const value = metrics?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function polishPageLabel(page: PPTPolishPageResult): string {
  return page.display_label || (page.page_number ? `第 ${page.page_number} 页` : page.slide_id);
}

function polishPageDelta(page: PPTPolishPageResult): number {
  return Number(
    page.decision === 'preserved'
      ? page.best_candidate_quality_delta ?? page.quality_delta ?? 0
      : page.quality_delta ?? 0,
  );
}

function formatMetric(value: number | null, percent = false): string {
  if (value == null) return '—';
  if (!percent) return Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `${Math.round((Math.abs(value) <= 1 ? value * 100 : value))}%`;
}

async function ensureImageModelBinding() {
  if (!task.value || task.value.image_model_config_id || bindingImageModel.value) return;
  const modelId = uniqueImageModelId(task.value.image_model_config_id, modelConfigStore.configs);
  if (!modelId) return;
  bindingImageModel.value = true;
  try {
    await projectStore.setTaskImageModel(props.courseId, props.taskType, modelId);
    await projectStore.refreshCurrentTask();
  } finally {
    bindingImageModel.value = false;
  }
}

const templates = ref<PPTTemplate[]>([]);
const showTemplateDrawer = ref(false);
const applyingTemplate = ref(false);

const activeSlideIndex = ref(0);
const targetSlideContext = ref<number | null>(null);
const selectedSlideIndexes = ref<Set<number>>(new Set());
const restoringPreview = ref(true);
const selectedSlideIds = computed(() => [...selectedSlideIndexes.value].map(index => String(previewContent.value?.slides?.[index]?.id || `S${String(index + 1).padStart(2, '0')}`)));

// Resizable splitter proportion
const leftPercent = ref(38);
const isDragging = ref(false);
const containerRef = ref<HTMLElement | null>(null);

// Mobile pane tab switcher
const mobilePane = ref<'agent' | 'preview'>('agent');

const statusType = computed(() => {
  if (status.value === 'running') return 'primary';
  if (status.value === 'completed') return 'success';
  if (['pausing', 'paused'].includes(status.value)) return 'warning';
  if (status.value === 'failed') return 'danger';
  return 'info';
});

const pptContent = computed(() => {
  const official = projectStore.officialArtifact?.artifact_type === 'ppt'
    ? projectStore.officialArtifact
    : task.value?.current_artifact;
  const content = official?.content_json;
  return content && content.slides ? content : null;
});

const viewedContent = computed(() => {
  const content = projectStore.viewedArtifact?.artifact_type === 'ppt'
    ? projectStore.viewedArtifact.content_json
    : null;
  return content?.slides ? content as PPTContent : null;
});

const officialTemplateId = computed(() => pptContent.value?.theme || 'default');

const previewContent = computed(() => {
  if (viewedContent.value) return viewedContent.value;
  const draft = pipelineStore.draftArtifact;
  const draftMatches = Boolean(
    draft?.slides?.length
    && pipelineStore.draftRunId
    && pipelineStore.draftRunId === pipelineStore.run?.generation_run_id
    && pipelineStore.draftCourseId === task.value?.course_id
    && pipelineStore.draftTaskId === task.value?.id
    && !['completed', 'failed', 'cancelled'].includes(status.value),
  );
  if (!draft || !draftMatches) return pptContent.value;
  const baseSlides = [...((pptContent.value?.slides || []) as any[])];
  for (const [index, slide] of draft.slides.entries()) {
    if (slide) baseSlides[index] = slide;
  }
  return { ...(pptContent.value || {}), ...draft, slides: baseSlides, theme: pptContent.value?.theme || officialTemplateId.value } as PPTContent;
});
const currentTemplateId = computed(() => previewContent.value?.theme || officialTemplateId.value);
const draftSlideIndex = computed(() => {
  const path = pipelineStore.draftArtifact?.last_patch?.[0]?.path;
  const match = typeof path === 'string' ? path.match(/^\/slides\/(\d+)$/) : null;
  return match ? Number(match[1]) : undefined;
});
const template = computed(() => {
  return templates.value.find(item => item.id === currentTemplateId.value) || null;
});
const previewLoading = computed(() => restoringPreview.value || (!previewContent.value && (
  pipelineStore.loading || ['queued', 'running', 'pausing'].includes(status.value)
)));
const visiblePreviewContent = computed(() => restoringPreview.value ? null : previewContent.value);

let detailLoading = false;
async function loadDetail() {
  if (detailLoading) return null;
  detailLoading = true;
  try {
    const detail = await pipelineStore.load(props.courseId, props.taskType);
    if (!detail) return null;
    pipelineStore.restoreThoughtsFromHistory();
    pipelineStore.syncThoughts();
    return detail;
  } finally {
    detailLoading = false;
  }
}

async function loadTemplates() {
  try {
    const catalog = await pptTemplatesApi.getCatalog();
    templates.value = catalog.templates;
  } catch {
    templates.value = [];
  }
}

async function send(content: string, modality: PPTPolishModality = 'auto') {
  const runId = pipelineStore.run?.generation_run_id || task.value?.active_run_id;
  const activeSlideId = String(previewContent.value?.slides?.[activeSlideIndex.value]?.id || '');
  if (paused.value && runId) {
    const result = await projectStore.enqueuePPTInstruction(runId, content, selectedSlideIds.value, true, modality, activeSlideId);
    if (result.status === 'resumed' && pipelineStore.detail?.run) {
      pipelineStore.detail.run.status = 'queued';
    }
    await loadDetail();
    startPolling();
  }
  else if (isRunning.value && runId) {
    await projectStore.enqueuePPTInstruction(runId, content, selectedSlideIds.value, false, modality, activeSlideId);
    await loadDetail();
  }
  else {
    pipelineStore.beginRun();
    await projectStore.createPPTRun(props.courseId, content, selectedSlideIds.value, modality, activeSlideId);
    await loadDetail();
  }
  targetSlideContext.value = null;
  selectedSlideIndexes.value = new Set();
}

async function pause() {
  if (pausing.value || pipelineStore.pauseLoading) return;
  await pipelineStore.pause(props.courseId, props.taskType);
  await loadDetail();
  startPolling();
}

async function resume() {
  await pipelineStore.resume(props.courseId, props.taskType);
  await loadDetail();
}

async function handleHumanResponse(requestId: string, choice: string, data: Record<string, unknown> = {}) {
  const runId = pipelineStore.run?.generation_run_id;
  if (!runId || !requestId || humanResponsePending.value) return;
  humanResponsePending.value = requestId;
  try {
    const result = await pipelineApi.humanResponse(runId, requestId, choice, data);
    if (result.continuation_run_id) {
      ElMessage.success('已确认方案，正在继续生成');
      pipelineStore.beginRun();
      await projectStore.refreshCurrentTask();
      await loadDetail();
      startPolling();
    } else {
      ElMessage.info(result.result_status === 'no_change' ? '已保留原版本' : '已记录你的选择');
      await loadDetail();
    }
  } finally {
    humanResponsePending.value = '';
  }
}

function setModel(modelId: string) {
  void projectStore.setTaskModel(props.courseId, props.taskType, modelId);
}

async function setImageModel(modelId: string) {
  await projectStore.setTaskImageModel(props.courseId, props.taskType, modelId);
  await projectStore.refreshCurrentTask();
}

function requireImageModel() {
  ElMessage.warning(
    imageModelCandidates.value.length > 1
      ? '请先在输入框下方选择一个图片模型，再发送图片生成指令。'
      : '请先在模型设置中配置具备 image_generation 能力的图片模型。',
  );
}

function handleSelectSlide(index: number, additive = false) {
  const safeIndex = normalizeSlideIndex(index, previewContent.value?.slides?.length || 0);
  activeSlideIndex.value = safeIndex;
  // Ordinary navigation changes only the browsed page. Cmd/Ctrl additive
  // selection is an explicit targeting gesture; "修改本页" is the primary
  // single-page targeting action.
  if (additive) {
    const next = updateSlideSelection(selectedSlideIndexes.value, safeIndex, true);
    selectedSlideIndexes.value = next;
    targetSlideContext.value = next.size === 1 ? [...next][0] : null;
  }
  mobilePane.value = 'preview';
}

function handleModifySlide(index: number) {
  // “修改本页”路径：把该页收进多选范围（selected_slide_ids），让后端只改这一页。
  const safeIndex = normalizeSlideIndex(index, previewContent.value?.slides?.length || 0);
  selectedSlideIndexes.value = new Set([safeIndex]);
  targetSlideContext.value = safeIndex;
  mobilePane.value = 'agent';
}

function handleShowRepairDetail(index: number) {
  handleSelectSlide(index, false);
  // 胶片徽标点击 → 定位到该页并切到 Agent 侧（桌面两侧同屏时即时间线上下文）。
  mobilePane.value = 'agent';
}

function clearTargetSlides() {
  targetSlideContext.value = null;
  selectedSlideIndexes.value = new Set();
}

async function handleApplyTemplate(templateId: string) {
  const artifact = task.value?.current_artifact;
  if (!artifact || applyingTemplate.value) return;
  applyingTemplate.value = true;
  try {
    await pipelineApi.switchTemplate(artifact.id, templateId, selectedSlideIds.value);
    showTemplateDrawer.value = false;
    await loadDetail();
  } catch {
    // handled in API
  } finally {
    applyingTemplate.value = false;
  }
}

// Splitter resizing logic
function startResize(e: MouseEvent | TouchEvent) {
  isDragging.value = true;
  document.addEventListener('mousemove', handleResize);
  document.addEventListener('mouseup', stopResize);
  document.addEventListener('touchmove', handleResize);
  document.addEventListener('touchend', stopResize);
  document.body.style.userSelect = 'none';
  document.body.style.cursor = 'col-resize';
}

function handleResize(e: MouseEvent | TouchEvent) {
  if (!isDragging.value || !containerRef.value) return;
  const containerRect = containerRef.value.getBoundingClientRect();
  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX;
  const offset = clientX - containerRect.left;
  const newPercent = (offset / containerRect.width) * 100;
  if (newPercent >= 25 && newPercent <= 65) {
    leftPercent.value = newPercent;
  }
}

function stopResize() {
  if (!isDragging.value) return;
  isDragging.value = false;
  document.removeEventListener('mousemove', handleResize);
  document.removeEventListener('mouseup', stopResize);
  document.removeEventListener('touchmove', handleResize);
  document.removeEventListener('touchend', stopResize);
  document.body.style.userSelect = '';
  document.body.style.cursor = '';
}

function resetSplitter() {
  leftPercent.value = 38;
}

let pollTimer: number | null = null;
function startPolling() {
  stopPolling();
  pollTimer = window.setInterval(() => {
    const s = pipelineStore.run?.status;
    if (s && ['queued', 'running', 'pausing', 'paused'].includes(s)) void loadDetail();
    else if (['running', 'pausing'].includes(status.value)) void loadDetail();
  }, 2000);
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = null;
}

onMounted(async () => {
  try {
    projectStore.setHydrationStatus('loading_pipeline_snapshot');
    const [, detail] = await Promise.all([
      loadTemplates(), loadDetail(), modelConfigStore.load().catch(() => []),
    ]);
    await ensureImageModelBinding();
    if (!detail && task.value?.active_run_id) {
      await projectStore.refreshCurrentTask();
      await loadDetail();
    }
    projectStore.setHydrationStatus('applying_current_run_events');
    pipelineStore.syncThoughts();
    // A backend restart can briefly restore the run before the task endpoint has
    // returned its formal artifact. Re-fetch once instead of rendering a false
    // "not generated" state.
    if (!pptContent.value) await projectStore.refreshCurrentTask();
  } finally {
    restoringPreview.value = false;
    projectStore.setHydrationStatus('ready');
  }
  startPolling();
});

onUnmounted(() => {
  stopPolling();
  pipelineStore.reset();
});

watch(() => status.value, newStatus => {
  if (['queued', 'running', 'pausing', 'paused'].includes(newStatus)) startPolling();
  else stopPolling();
});

watch(() => task.value?.current_artifact?.id, (artifactId, previousId) => {
  if (artifactId && previousId && artifactId !== previousId && status.value === 'completed') {
    pipelineStore.clearDraft();
  }
});

watch(
  () => [task.value?.id, task.value?.image_model_config_id, imageModelCandidates.value.length] as const,
  () => { void ensureImageModelBinding(); },
);

// SSE 实时思考增量 → 单调累加到 pipeline store（打字机渲染）
watch(
  () => projectStore.pipelineEvents,
  () => pipelineStore.syncThoughts(),
  { deep: true },
);
</script>

<template>
  <div ref="containerRef" class="ppt-agent-workbench">
    <!-- 移动端视口视图切换 Tab -->
    <div class="mobile-pane-switcher" role="tablist">
      <button
        type="button"
        :class="{ active: mobilePane === 'agent' }"
        @click="mobilePane = 'agent'"
      >
        Agent 推演过程
      </button>
      <button
        type="button"
        :class="{ active: mobilePane === 'preview' }"
        @click="mobilePane = 'preview'"
      >
        PPT 课件预览
      </button>
    </div>

    <!-- 左侧：Agent 执行过程与 Composer -->
    <aside
      class="pane-agent"
      :class="{ 'mobile-hidden': mobilePane !== 'agent' }"
      :style="{ width: `${leftPercent}%` }"
    >
      <header class="pane-header">
        <div class="pane-title">
          <span>教学 Agent 协同推演</span>
          <el-tag :type="statusType" size="small" class="status-tag">
            {{ PIPELINE_STATUS_LABELS[status] || status || '未运行' }}
          </el-tag>
        </div>
        <div class="pane-controls">
          <el-button v-if="['running', 'queued'].includes(status) && !pausing" size="small" :loading="pipelineStore.pauseLoading" @click="pause">
            <el-icon><VideoPause /></el-icon>&nbsp;暂停
          </el-button>
          <el-button v-else-if="pausing" size="small" loading disabled>暂停中</el-button>
          <el-button v-else-if="paused" size="small" type="primary" @click="resume">
            <el-icon><VideoPlay /></el-icon>&nbsp;继续
          </el-button>
        </div>
      </header>

      <section
        v-if="polishSummary"
        class="polish-result-summary"
        :class="[`status-${polishSummary.status}`, { degraded: polishSummary.degraded }]"
        aria-live="polite"
      >
        <div class="polish-result-head">
          <span class="polish-result-dot" aria-hidden="true" />
          <strong>{{ polishSummary.label }}</strong>
          <span v-if="polishSummary.qaLabel" class="polish-qa-level">{{ polishSummary.qaLabel }}</span>
        </div>
        <div v-if="polishSummary.degraded" class="polish-degraded-note">
          视觉 QA 已降级；结果未被当作视觉满分。
        </div>
        <div v-if="polishSummary.pages.length" class="polish-page-metrics">
          <div v-for="page in polishSummary.pages.slice(0, 3)" :key="page.slide_id" class="polish-page-row">
            <span class="polish-page-id">{{ polishPageLabel(page) }}</span>
            <span v-if="metricNumber(page, 'quality_score', 'baseline') != null || metricNumber(page, 'quality_score', 'final') != null">
              质量 {{ formatMetric(metricNumber(page, 'quality_score', 'baseline')) }} → {{ formatMetric(metricNumber(page, 'quality_score', 'final')) }}
            </span>
            <span v-if="metricNumber(page, 'vertical_utilization', 'baseline') != null || metricNumber(page, 'vertical_utilization', 'final') != null">
              纵向利用 {{ formatMetric(metricNumber(page, 'vertical_utilization', 'baseline'), true) }} → {{ formatMetric(metricNumber(page, 'vertical_utilization', 'final'), true) }}
            </span>
            <span :class="polishPageDelta(page) > 0 ? 'metric-positive' : 'metric-neutral'">
              {{ polishPageDelta(page) > 0 ? '+' : '' }}{{ polishPageDelta(page).toFixed(1) }}
            </span>
            <span v-if="page.decision === 'preserved' && page.rejection_reasons?.length" class="metric-neutral">
              {{ page.rejection_reasons[0] }}
            </span>
          </div>
          <div v-if="polishSummary.pages.length > 3" class="polish-page-more">
            另有 {{ polishSummary.pages.length - 3 }} 页结果可在执行明细中查看
          </div>
        </div>
      </section>

      <AgentExecutionTimeline
        :items="pipelineStore.timeline"
        :task="task"
        :tool-calls="pipelineStore.toolCalls"
        :is-running="isRunning"
        :agent-thoughts="pipelineStore.agentThoughts"
        :agent-status-texts="pipelineStore.agentStatusTexts"
        :human-response-pending="humanResponsePending"
        @select-slide="handleSelectSlide"
        @human-response="handleHumanResponse"
      />

      <AgentComposer
        :target-slide="targetSlideContext"
        :target-slides="[...selectedSlideIndexes]"
        :is-running="isRunning"
        :pausing="pausing || pipelineStore.pauseLoading"
        :model-config-id="task?.model_config_id"
        :image-model-config-id="task?.image_model_config_id"
        :image-model-available-count="imageModelCandidates.length"
        :show-image-model="true"
        :show-modality="true"
        task-type="ppt"
        unit-name="页"
        @send="send"
        @pause="pause"
        @clear-target-slide="clearTargetSlides"
        @change-model="setModel"
        @change-image-model="setImageModel"
        @image-model-required="requireImageModel"
      />
    </aside>

    <!-- 可拖拽中缝分隔条 -->
    <div
      class="pane-resizer"
      :class="{ dragging: isDragging }"
      title="按住鼠标左右拖拽调整比例，双击重置"
      @mousedown="startResize"
      @touchstart="startResize"
      @dblclick="resetSplitter"
    >
      <div class="resizer-line" />
    </div>

    <!-- 右侧：PPT 主预览与胶片导航 -->
    <main
      class="pane-preview"
      :class="{ 'mobile-hidden': mobilePane !== 'preview' }"
      :style="{ width: `${100 - leftPercent}%` }"
    >
      <PPTPreviewWorkbench
        :ppt-content="visiblePreviewContent"
        :template="template"
        :is-running="isRunning"
        :active-slide-index="activeSlideIndex"
        :draft-slide-index="draftSlideIndex"
        :selected-slides="selectedSlideIndexes"
        :slide-repair-notes="projectStore.slideRepairNotes"
        :loading="previewLoading"
        @select-slide="handleSelectSlide"
        @modify-slide="handleModifySlide"
        @show-repair-detail="handleShowRepairDetail"
        @open-template-drawer="showTemplateDrawer = true"
        @open-version-drawer="emit('open-version-drawer')"
        @sync-context="projectStore.runTask(courseId, taskType, 'sync_context')"
      />
    </main>

    <!-- 模板选择 Drawer -->
    <el-drawer
      v-model="showTemplateDrawer"
      title="选择 PPT 模版与视觉主题"
      direction="rtl"
      size="420px"
    >
      <div class="templates-drawer-content">
        <div
          v-for="tpl in templates"
          :key="tpl.id"
          class="template-card"
          :class="{ active: currentTemplateId === tpl.id }"
          @click="handleApplyTemplate(tpl.id)"
        >
          <div class="template-card-header">
            <strong>{{ tpl.name }}</strong>
            <span v-if="currentTemplateId === tpl.id" class="active-badge">
              <el-icon><Check /></el-icon> 当前应用
            </span>
          </div>
          <p>{{ tpl.description }}</p>
          <div class="template-color-preview">
            <span
              v-for="color in [tpl.palette.primary, tpl.palette.secondary, tpl.palette.surface]"
              :key="color"
              :style="{ background: color }"
              class="color-dot"
            />
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.ppt-agent-workbench {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #f8fafc;
  position: relative;
}

.mobile-pane-switcher {
  display: none;
}

.pane-agent {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-right: 1px solid var(--border-default, #e2e8f0);
  min-width: 320px;
  overflow: hidden;
}

.pane-header {
  height: 44px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border-default, #e2e8f0);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  flex-shrink: 0;
}

.pane-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
  display: flex;
  align-items: center;
  gap: 8px;
}

.polish-result-summary {
  flex-shrink: 0;
  margin: 9px 12px 0;
  padding: 9px 11px;
  border: 1px solid #bbf7d0;
  border-radius: 10px;
  background: #f0fdf4;
  color: #166534;
  font-size: 11px;
}

.polish-result-summary.status-partial,
.polish-result-summary.degraded {
  border-color: #fde68a;
  background: #fffbeb;
  color: #92400e;
}

.polish-result-summary.status-no_change {
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #475569;
}

.polish-result-summary.status-needs_confirmation {
  border-color: #c4b5fd;
  background: #f5f3ff;
  color: #5b21b6;
}

.polish-result-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.polish-result-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.polish-qa-level {
  margin-left: auto;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  font-weight: 700;
  white-space: nowrap;
}

.polish-degraded-note {
  margin: 4px 0 0 13px;
  color: #b45309;
}

.polish-page-metrics {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(100, 116, 139, 0.18);
}

.polish-page-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 9px;
  color: #64748b;
}

.polish-page-id {
  color: #334155;
  font-weight: 800;
}

.metric-positive { color: #15803d; font-weight: 800; }
.metric-neutral { color: #64748b; font-weight: 700; }
.polish-page-more { color: #94a3b8; }

.pane-resizer {
  width: 7px;
  cursor: col-resize;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 10;
  transition: background 150ms ease;
  user-select: none;
}

.pane-resizer:hover, .pane-resizer.dragging {
  background: #e0e7ff;
}

.resizer-line {
  width: 2px;
  height: 24px;
  background: #cbd5e1;
  border-radius: 999px;
  transition: background 150ms ease;
}

.pane-resizer:hover .resizer-line, .pane-resizer.dragging .resizer-line {
  background: #4f46e5;
}

.pane-preview {
  height: 100%;
  flex: 1;
  min-width: 400px;
  overflow: hidden;
  background: #ffffff;
}

/* Template Drawer Styling */
.templates-drawer-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.template-card {
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  cursor: pointer;
  transition: all 150ms ease;
}

.template-card:hover {
  border-color: #818cf8;
  transform: translateY(-1px);
}

.template-card.active {
  border-color: #4f46e5;
  background: #f5f3ff;
}

.template-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.template-card-header strong {
  font-size: 13px;
  color: #0f172a;
}

.active-badge {
  font-size: 11px;
  font-weight: 700;
  color: #4f46e5;
  display: flex;
  align-items: center;
  gap: 4px;
}

.template-card p {
  margin: 0 0 8px 0;
  font-size: 11px;
  color: #64748b;
  line-height: 1.4;
}

.template-color-preview {
  display: flex;
  gap: 6px;
}

.color-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid rgba(0, 0, 0, 0.1);
}

@media (max-width: 900px) {
  .mobile-pane-switcher {
    display: flex;
    width: 100%;
    height: 40px;
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
  }
  .mobile-pane-switcher button {
    flex: 1;
    border: 0;
    background: transparent;
    font-size: 13px;
    font-weight: 700;
    color: #64748b;
    border-bottom: 2px solid transparent;
    cursor: pointer;
  }
  .mobile-pane-switcher button.active {
    color: #4f46e5;
    border-bottom-color: #4f46e5;
  }
  .pane-agent, .pane-preview {
    width: 100% !important;
  }
  .mobile-hidden {
    display: none !important;
  }
  .pane-resizer {
    display: none;
  }
}
</style>
