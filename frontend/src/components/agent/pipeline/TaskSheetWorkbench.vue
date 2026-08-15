<script setup lang="ts">
/** 学习任务单 V3 工作台（方案 §4）：左侧按 turn 分组时间线（意图/工具/QA/返修流式显示）
 * + 右侧结构化预览。
 *
 * 与 PPT/教学设计共用通用执行组件与事件消费（AgentExecutionTimeline / AgentComposer /
 * pipeline store），运行中指令走排队接口（run.instruction.queued/merged），
 * 人工确认从同一 GenerationRun 的 checkpoint 恢复（human-responses）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { VideoPause, VideoPlay } from '@element-plus/icons-vue';
import { pipelineApi } from '../../../api/pipeline';
import type { LessonPlanMode } from '../../../api/pipeline';
import { useProjectStore } from '../../../stores/project';
import { usePipelineStore } from '../../../stores/pipeline';
import { useModelConfigStore } from '../../../stores/modelConfigs';
import { PIPELINE_STATUS_LABELS } from '../../../types/agentPipeline';
import type { TaskSheetContent } from '../../../types/artifact';
import AgentExecutionTimeline from './AgentExecutionTimeline.vue';
import AgentComposer from './AgentComposer.vue';
import TaskSheetPreview from '../../domain/TaskSheetPreview.vue';
import TaskSheetDraftPreview from '../../domain/TaskSheetDraftPreview.vue';
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';

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
const humanResponsePending = ref('');
const leftPercent = ref(38);
const isDragging = ref(false);
const containerRef = ref<HTMLElement | null>(null);
const mobilePane = ref<'agent' | 'preview'>('agent');
const queuedCount = ref(0);

const statusType = computed(() => {
  if (status.value === 'running') return 'primary';
  if (status.value === 'completed') return 'success';
  if (['pausing', 'paused'].includes(status.value)) return 'warning';
  if (status.value === 'failed') return 'danger';
  return 'info';
});

const selectedSectionIds = ref<string[]>([]);
const activeSectionId = ref<string | null>(null);
const mode = ref<LessonPlanMode>('auto');

const artifact = computed(() => task.value?.current_artifact || null);
const isTaskSheetV2 = (value: unknown): value is TaskSheetContent =>
  !!value && typeof value === 'object' && (value as TaskSheetContent).schema_version === '2.0';
const isTaskSheetV3 = (value: unknown): boolean =>
  !!value && typeof value === 'object' && (value as { schema_version?: string }).schema_version === '3.0';
const previewContent = computed(() => artifact.value?.content_json || null);
const sourceVersions = computed(() => artifact.value?.source_versions_json || {});

function selectSection(sectionId: string | null) {
  activeSectionId.value = sectionId;
  if (sectionId && !selectedSectionIds.value.includes(sectionId)) {
    selectedSectionIds.value = [sectionId];
  } else if (!sectionId) {
    selectedSectionIds.value = [];
  }
}

function clearTargetSections() {
  selectedSectionIds.value = [];
  activeSectionId.value = null;
}

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

/** 方案 §4：运行中保持输入框可用——运行中指令排队（queued/merged 展示），
 * 不伪装成新的独立运行。 */
async function send(content: string, modality: string = 'auto') {
  const modeValue = (['auto', 'content', 'structure', 'timing', 'qa'].includes(modality) ? modality : 'auto') as LessonPlanMode;
  const runId = pipelineStore.run?.generation_run_id || task.value?.active_run_id;
  if (isRunning.value && runId) {
    const result = await pipelineApi.enqueueTaskSheetInstruction(
      props.courseId, runId, content, selectedSectionIds.value, modeValue, false,
    );
    queuedCount.value += 1;
    ElMessage.success(result.status === 'resumed' ? '已恢复运行并加入队列' : '指令已加入执行队列，将在安全边界合并');
    clearTargetSections();
    await loadDetail();
    return;
  }
  if (paused.value && runId) {
    // 暂停后发送：先恢复运行，再排队合并到当前 Run（同一 checkpoint 恢复）。
    const result = await pipelineApi.enqueueTaskSheetInstruction(
      props.courseId, runId, content, selectedSectionIds.value, modeValue, true,
    );
    queuedCount.value += 1;
    ElMessage.success('已恢复运行并加入队列');
    pipelineStore.beginRun();
    clearTargetSections();
    await loadDetail();
    startPolling();
    return;
  }
  pipelineStore.beginRun();
  await projectStore.createTaskSheetRun(props.courseId, content, selectedSectionIds.value, modeValue);
  await loadDetail();
  clearTargetSections();
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

/** 方案 §3.3：人工确认从原 GenerationRun 恢复（不再创建 continuation Run）。 */
async function handleHumanResponse(requestId: string, choice: string, data: Record<string, unknown> = {}) {
  const runId = pipelineStore.run?.generation_run_id;
  if (!runId || !requestId || humanResponsePending.value) return;
  humanResponsePending.value = requestId;
  try {
    const result = await pipelineApi.taskSheetHumanResponse(props.courseId, runId, requestId, choice, data);
    if (result.continuation_run_id) {
      ElMessage.success('已确认方案，正在继续执行');
      pipelineStore.beginRun();
      await loadDetail();
      startPolling();
    } else {
      ElMessage.info(result.result_status === 'no_change' ? '已取消本轮，保留原版本' : '已记录你的选择');
      await loadDetail();
    }
  } finally {
    humanResponsePending.value = '';
  }
}

function setModel(modelId: string) {
  void projectStore.setTaskModel(props.courseId, props.taskType, modelId);
}

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
    const detail = await loadDetail();
    await modelConfigStore.load().catch(() => []);
    if (!detail && task.value?.active_run_id) {
      await projectStore.refreshCurrentTask();
      await loadDetail();
    }
    projectStore.setHydrationStatus('applying_current_run_events');
    pipelineStore.syncThoughts();
  } finally {
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

watch(
  () => projectStore.pipelineEvents,
  () => pipelineStore.syncThoughts(),
  { deep: true },
);
</script>

<template>
  <div ref="containerRef" class="task-sheet-workbench">
    <div class="mobile-pane-switcher" role="tablist">
      <button type="button" :class="{ active: mobilePane === 'agent' }" @click="mobilePane = 'agent'">
        Agent 执行过程
      </button>
      <button type="button" :class="{ active: mobilePane === 'preview' }" @click="mobilePane = 'preview'">
        任务单预览
      </button>
    </div>

    <aside
      class="pane-agent"
      :class="{ 'mobile-hidden': mobilePane !== 'agent' }"
      :style="{ width: `${leftPercent}%` }"
    >
      <header class="pane-header">
        <div class="pane-title">
          <span>任务单 Agent 协同推演</span>
          <el-tag :type="statusType" size="small" class="status-tag">
            {{ PIPELINE_STATUS_LABELS[status] || status || '未运行' }}
          </el-tag>
          <el-tag v-if="queuedCount > 0" type="warning" size="small">已排队 {{ queuedCount }}</el-tag>
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
        :human-response-pending="humanResponsePending"
        @human-response="handleHumanResponse"
      />

      <AgentComposer
        :target-slide="activeSectionId as any"
        :target-slides="selectedSectionIds as any"
        :is-running="isRunning"
        :pausing="pausing || pipelineStore.pauseLoading"
        :model-config-id="task?.model_config_id"
        task-type="task_sheet"
        unit-name="题"
        @send="send"
        @pause="pause"
        @clear-target-slide="clearTargetSections"
        @change-model="setModel"
      />
    </aside>

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

    <main
      class="pane-preview"
      :class="{ 'mobile-hidden': mobilePane !== 'preview' }"
      :style="{ width: `${100 - leftPercent}%` }"
    >
      <div class="preview-scroll">
        <div v-if="!artifact" class="preview-empty">任务单尚未生成，发送指令开始创作。</div>
        <TaskSheetPreview
          v-else-if="isTaskSheetV2(previewContent)"
          :content="previewContent"
          :source-versions="sourceVersions"
        />
        <TaskSheetDraftPreview
          v-else-if="isTaskSheetV3(previewContent)"
          :draft="previewContent as any"
          :is-running="isRunning"
          :published="!isRunning"
          mode="document"
        />
        <MarkdownRenderer
          v-else-if="artifact?.content_markdown"
          :content="artifact.content_markdown"
        />
        <div v-else class="preview-empty">正在生成任务单…</div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.task-sheet-workbench {
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

.preview-scroll {
  height: 100%;
  overflow-y: auto;
  padding: 16px 20px;
}

.preview-empty {
  padding: 48px 24px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
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
