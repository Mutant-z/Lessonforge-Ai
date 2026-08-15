<script setup lang="ts">
/** 视频脚本 V4 工作台：左侧 Agent 执行时间线（意图/工具/QA/返修流式显示）+ 右侧动态章节预览。
 *
 * 复用通用执行组件（AgentExecutionTimeline / AgentComposer / ModelSelector / pipeline store），
 * 消息走 /courses/{course_id}/tasks/video_script/runs（携带章节/分镜作用域与 mode）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { VideoPause, VideoPlay } from '@element-plus/icons-vue';
import { pipelineApi } from '../../../api/pipeline';
import { useProjectStore } from '../../../stores/project';
import { usePipelineStore } from '../../../stores/pipeline';
import { useModelConfigStore } from '../../../stores/modelConfigs';
import { PIPELINE_STATUS_LABELS } from '../../../types/agentPipeline';
import type { VideoScriptContent, VideoScriptContentV4 } from '../../../types';
import AgentExecutionTimeline from './AgentExecutionTimeline.vue';
import AgentComposer from './AgentComposer.vue';
import VideoScriptPreviewWorkbench from '../videoScript/VideoScriptPreviewWorkbench.vue';
import type { VideoScriptMode } from '../../../api/pipeline';

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

const statusType = computed(() => {
  if (status.value === 'running') return 'primary';
  if (status.value === 'completed') return 'success';
  if (['pausing', 'paused'].includes(status.value)) return 'warning';
  if (status.value === 'failed') return 'danger';
  return 'info';
});

// 选中的章节/分镜作用域（对应 selected_section_ids / selected_scene_ids）
const selectedSectionIds = ref<string[]>([]);
const selectedSceneIds = ref<string[]>([]);
const activeSectionId = ref<string | null>(null);
const mode = ref<VideoScriptMode>('auto');

const artifactContent = computed<VideoScriptContent | VideoScriptContentV4 | null>(() => {
  const raw = task.value?.current_artifact?.content_json;
  return (raw as VideoScriptContent | VideoScriptContentV4) ?? null;
});
const isDraft = computed(() => {
  const draft = pipelineStore.draftArtifact;
  return Boolean(draft && draft.content_json && draft.content_json.schema_version);
});

function selectSection(sectionId: string | null) {
  activeSectionId.value = sectionId;
  if (sectionId && !selectedSectionIds.value.includes(sectionId)) {
    selectedSectionIds.value = [sectionId];
  } else if (!sectionId) {
    selectedSectionIds.value = [];
  }
}

function selectScene(sceneIds: string[]) {
  selectedSceneIds.value = sceneIds;
}

function clearTargetSections() {
  selectedSectionIds.value = [];
  selectedSceneIds.value = [];
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

async function send(content: string, modality: string = 'auto') {
  const modeValue = (['auto', 'content', 'structure', 'timing', 'qa'].includes(modality) ? modality : 'auto') as VideoScriptMode;
  const runId = pipelineStore.run?.generation_run_id || task.value?.active_run_id;
  if (paused.value && runId) {
    await resume();
    pipelineStore.beginRun();
    await projectStore.createVideoScriptRun(props.courseId, content, selectedSectionIds.value, selectedSceneIds.value, modeValue);
    await loadDetail();
    startPolling();
  } else if (isRunning.value) {
    // 运行中的指令排队由后端 create_task_run 拦截（409），这里给出明确提示。
    ElMessage.info('Agent 正在执行中，请等待当前任务完成后再发送新指令，或先暂停。');
    return;
  } else {
    pipelineStore.beginRun();
    await projectStore.createVideoScriptRun(props.courseId, content, selectedSectionIds.value, selectedSceneIds.value, modeValue);
    await loadDetail();
  }
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

async function handleHumanResponse(requestId: string, choice: string, data: Record<string, unknown> = {}) {
  const runId = pipelineStore.run?.generation_run_id;
  if (!runId || !requestId || humanResponsePending.value) return;
  humanResponsePending.value = requestId;
  try {
    const result = await pipelineApi.agentRunHumanResponse(runId, requestId, choice, data);
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

// SSE 实时思考增量 → 单调累加到 pipeline store（打字机渲染）
watch(
  () => projectStore.pipelineEvents,
  () => pipelineStore.syncThoughts(),
  { deep: true },
);
</script>

<template>
  <div ref="containerRef" class="video-script-workbench">
    <!-- 移动端视口视图切换 Tab -->
    <div class="mobile-pane-switcher" role="tablist">
      <button type="button" :class="{ active: mobilePane === 'agent' }" @click="mobilePane = 'agent'">
        Agent 执行过程
      </button>
      <button type="button" :class="{ active: mobilePane === 'preview' }" @click="mobilePane = 'preview'">
        脚本预览
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
          <span>视频脚本 Agent 协同推演</span>
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
        :human-response-pending="humanResponsePending"
        @human-response="handleHumanResponse"
      />

      <AgentComposer
        :target-slide="activeSectionId as any"
        :target-slides="selectedSectionIds as any"
        :is-running="isRunning"
        :pausing="pausing || pipelineStore.pauseLoading"
        :model-config-id="task?.model_config_id"
        task-type="video_script"
        unit-name="镜"
        @send="send"
        @pause="pause"
        @clear-target-slide="clearTargetSections"
        @change-model="setModel"
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

    <!-- 右侧：动态章节预览 -->
    <main
      class="pane-preview"
      :class="{ 'mobile-hidden': mobilePane !== 'preview' }"
      :style="{ width: `${100 - leftPercent}%` }"
    >
      <VideoScriptPreviewWorkbench
        :content="artifactContent"
        :source-versions="task?.current_artifact?.source_versions_json"
        :draft="isDraft"
        @select-section="selectSection"
        @select-scene="selectScene"
      />
    </main>
  </div>
</template>

<style scoped>
.video-script-workbench {
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
