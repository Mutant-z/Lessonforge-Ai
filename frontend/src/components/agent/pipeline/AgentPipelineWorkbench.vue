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
  return !activeRunId || activeRunId === detailRunId;
});
const status = computed(() => {
  if (!pipelineMatchesActiveRun.value) return projectStore.pipelineStatus || task.value?.status || 'queued';
  return pipelineStore.status || projectStore.pipelineStatus || task.value?.status || '';
});
const paused = computed(() => status.value === 'paused');
const pausing = computed(() => status.value === 'pausing');
const isRunning = computed(() => ['queued', 'running', 'pausing'].includes(status.value));
const imageModelCandidates = computed(() => imageGenerationModels(modelConfigStore.configs));
const bindingImageModel = ref(false);

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
  if (paused.value && runId) {
    const result = await projectStore.enqueuePPTInstruction(runId, content, selectedSlideIds.value, true, modality);
    if (result.status === 'resumed' && pipelineStore.detail?.run) {
      pipelineStore.detail.run.status = 'queued';
    }
    await loadDetail();
    startPolling();
  }
  else if (isRunning.value && runId) {
    await projectStore.enqueuePPTInstruction(runId, content, selectedSlideIds.value, false, modality);
    await loadDetail();
  }
  else {
    pipelineStore.beginRun();
    await projectStore.createPPTRun(props.courseId, content, selectedSlideIds.value, modality);
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

async function handleHumanResponse(requestId: string, choice: string) {
  const runId = pipelineStore.run?.generation_run_id;
  if (!runId || !requestId) return;
  await pipelineApi.humanResponse(runId, requestId, choice);
  await loadDetail();
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
  const next = updateSlideSelection(selectedSlideIndexes.value, safeIndex, additive);
  selectedSlideIndexes.value = next;
  targetSlideContext.value = next.size === 1 ? [...next][0] : null;
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

onUnmounted(stopPolling);

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

      <AgentExecutionTimeline
        :items="pipelineStore.timeline"
        :task="task"
        :tool-calls="pipelineStore.toolCalls"
        :is-running="isRunning"
        :agent-thoughts="pipelineStore.agentThoughts"
        :agent-status-texts="pipelineStore.agentStatusTexts"
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
        @send="send"
        @pause="pause"
        @clear-target-slide="targetSlideContext = null"
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
