<script setup lang="ts">
/** 视频脚本 V4 工作台：左侧 Agent 执行摘要与发布前校验 + 右侧动态章节候选稿预览。
 *
 * 复用通用执行组件（AgentExecutionTimeline / AgentComposer / ModelSelector / pipeline store），
 * 消息走 /courses/{course_id}/tasks/video_script/runs（携带章节/分镜作用域与 mode）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { CircleCheck, VideoPause, VideoPlay } from '@element-plus/icons-vue';
import { errorMessage } from '../../../api/client';
import { pipelineApi } from '../../../api/pipeline';
import { useProjectStore } from '../../../stores/project';
import { usePipelineStore } from '../../../stores/pipeline';
import { useModelConfigStore } from '../../../stores/modelConfigs';
import { PIPELINE_STATUS_LABELS } from '../../../types/agentPipeline';
import type { VideoScriptContent, VideoScriptContentV4 } from '../../../types';
import type { ChatAttachment } from '../../../types/project';
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
const activeRunId = computed(() => task.value?.active_run_id || pipelineStore.run?.generation_run_id || '');
const pipelineMatchesActiveRun = computed(() => {
  if (task.value?.active_run_id) return task.value.active_run_id === pipelineStore.run?.generation_run_id;
  return true;
});
const status = computed(() => {
  if (task.value?.active_run_id && !pipelineMatchesActiveRun.value) return task.value?.status || 'queued';
  return pipelineStore.status || task.value?.status || '';
});
const paused = computed(() => status.value === 'paused');
const pausing = computed(() => status.value === 'pausing');
const isRunning = computed(() => ['queued', 'running', 'pausing'].includes(status.value));
const failureMessage = computed(() => (
  pipelineStore.run?.error?.message
  || task.value?.error?.message
  || '视频脚本修改失败，已保留原正式版本。'
));
const queuedCount = computed(() => (pipelineStore.detail?.instructions || []).filter(item => item.status === 'queued').length);
const humanResponsePending = ref('');
const approving = ref(false);
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
  const draftMatches = Boolean(
    pipelineStore.draftArtifact?.schema_version
    && pipelineStore.draftRunId
    && pipelineStore.draftRunId === (pipelineStore.run?.generation_run_id || task.value?.active_run_id)
    && !['completed', 'failed', 'cancelled'].includes(status.value),
  );
  const raw = draftMatches ? pipelineStore.draftArtifact : task.value?.current_artifact?.content_json;
  return (raw as VideoScriptContent | VideoScriptContentV4) ?? null;
});
const isDraft = computed(() => {
  return Boolean(pipelineStore.draftArtifact?.schema_version && !['completed', 'failed', 'cancelled'].includes(status.value));
});
const activeSceneId = computed(() => selectedSceneIds.value.length === 1 ? selectedSceneIds.value[0] : undefined);
const selectedScopeLabels = computed(() => {
  const content = artifactContent.value as any;
  const sections = Array.isArray(content?.outline?.sections) ? content.outline.sections : [];
  const scenes = Array.isArray(content?.scenes) ? content.scenes : [];
  const sectionLabels = selectedSectionIds.value.map(id => {
    const item = sections.find((section: any) => String(section.id) === id);
    return item ? `第 ${item.sequence} 章 · ${item.title}` : id;
  });
  const sceneLabels = selectedSceneIds.value.map(id => {
    const item = scenes.find((scene: any) => String(scene.id) === id);
    return item ? `分镜 ${item.sequence} · ${item.title}` : id;
  });
  return [...sectionLabels, ...sceneLabels];
});
const modeOptions: Array<{ value: VideoScriptMode; label: string }> = [
  { value: 'auto', label: '自动' },
  { value: 'structure', label: '章节结构' },
  { value: 'narration', label: '口播' },
  { value: 'visual', label: '画面与声音' },
  { value: 'continuity', label: '连续性' },
  { value: 'timing', label: '时长节奏' },
];

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
    if (['completed', 'failed', 'cancelled'].includes(detail.run?.status || '')) {
      pipelineStore.clearDraft();
      await projectStore.refreshCurrentTask().catch(() => undefined);
    }
    return detail;
  } finally {
    detailLoading = false;
  }
}

async function send(content: string, modality: string = 'auto', attachments: ChatAttachment[] = []) {
  const modeValue = (modality !== 'auto' ? modality : mode.value) as VideoScriptMode;
  const runId = activeRunId.value;
  try {
    if ((paused.value || isRunning.value) && runId) {
      if (!pipelineMatchesActiveRun.value) {
        await loadDetail();
      }
      if (!pipelineMatchesActiveRun.value) {
        throw new Error('当前执行进度正在同步，请稍后重试。');
      }
      const result = await pipelineApi.enqueueVideoScriptInstruction(
        props.courseId, runId, content, selectedSectionIds.value, selectedSceneIds.value,
        modeValue, paused.value, crypto.randomUUID(), activeSectionId.value || undefined, activeSceneId.value,
        attachments.map(item => item.id),
      );
      ElMessage.success(result.status === 'resumed' ? '已恢复运行并加入当前执行' : '指令已加入当前执行，将在安全边界合并');
      if (paused.value) {
        pipelineStore.beginRun();
        startPolling();
      }
      await loadDetail();
    } else {
      pipelineStore.beginRun();
      await projectStore.createVideoScriptRun(props.courseId, content, selectedSectionIds.value, selectedSceneIds.value, modeValue, attachments);
      await loadDetail();
      startPolling();
    }
    clearTargetSections();
  } catch (cause) {
    ElMessage.error(`指令未提交：${errorMessage(cause)}`);
    throw cause;
  }
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
    const result = await pipelineApi.videoScriptHumanResponse(props.courseId, runId, requestId, choice, data);
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

function setVisionModel(modelId: string) {
  void projectStore.setTaskVisionModel(props.courseId, props.taskType, modelId);
}

async function approveArtifact() {
  if (!task.value?.current_artifact || approving.value) return;
  approving.value = true;
  try {
    await projectStore.approveTask(props.courseId, props.taskType);
    ElMessage.success('视频脚本已标记为确认交付；视频生成始终使用最新有效版本。');
  } catch (cause) {
    ElMessage.error(errorMessage(cause));
  } finally {
    approving.value = false;
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
    const realtimeUnavailable = !projectStore.eventSource || Boolean(projectStore.connectionError);
    const snapshotPending = Boolean(activeRunId.value) && !pipelineMatchesActiveRun.value;
    const active = ['queued', 'running', 'pausing', 'paused'].includes(s || status.value);
    // SSE remains the low-latency path, but an active run is always reconciled with
    // the authoritative snapshot so a dropped terminal event cannot leave the UI stuck.
    if (active || pipelineStore.draftNeedsRefresh || snapshotPending || realtimeUnavailable) {
      void loadDetail();
    }
  }, 5000);
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
  else {
    stopPolling();
    if (['completed', 'failed', 'cancelled'].includes(newStatus)) {
      pipelineStore.clearDraft();
      void projectStore.refreshCurrentTask();
    }
  }
});

// SSE 实时思考增量 → 单调累加到 pipeline store（打字机渲染）
watch(
  () => projectStore.pipelineEvents,
  () => pipelineStore.syncThoughts(),
  { deep: true },
);

watch(() => pipelineStore.draftNeedsRefresh, needsRefresh => {
  if (needsRefresh) void loadDetail();
});
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
          <el-tag v-if="queuedCount" type="warning" size="small">待合并 {{ queuedCount }}</el-tag>
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

      <el-alert
        v-if="status === 'failed'"
        class="pipeline-failure-alert"
        type="error"
        :title="failureMessage"
        :closable="false"
        show-icon
      />

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

      <div v-if="selectedScopeLabels.length" class="video-scope-bar">
        <span class="video-scope-label">当前范围</span>
        <span v-for="label in selectedScopeLabels" :key="label" class="video-scope-chip">{{ label }}</span>
        <button type="button" class="video-scope-clear" @click="clearTargetSections">清除</button>
      </div>

      <div class="video-mode-bar" role="group" aria-label="视频脚本修改类型">
        <span class="video-mode-label">修改类型</span>
        <button
          v-for="option in modeOptions"
          :key="option.value"
          type="button"
          class="video-mode-button"
          :class="{ active: mode === option.value }"
          @click="mode = option.value"
        >
          {{ option.label }}
        </button>
      </div>

      <AgentComposer
        :course-id="props.courseId"
        :target-slide="activeSectionId as any"
        :target-slides="selectedSectionIds as any"
        :is-running="isRunning"
        :pausing="pausing || pipelineStore.pauseLoading"
        :model-config-id="task?.model_config_id"
        :vision-model-config-id="task?.vision_model_config_id"
        :show-vision-model="true"
        task-type="video_script"
        unit-name="镜"
        :submit="send"
        @send="send"
        @pause="pause"
        @clear-target-slide="clearTargetSections"
        @change-model="setModel"
        @change-vision-model="setVisionModel"
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
        class="script-preview"
        :content="artifactContent"
        :source-versions="task?.current_artifact?.source_versions_json"
        :draft="isDraft"
        :affected-section-ids="pipelineStore.lastAffectedSectionIds"
        :affected-scene-ids="pipelineStore.lastAffectedSceneIds"
        @select-section="selectSection"
        @select-scene="selectScene"
      />
      <div class="preview-footer">
        <el-button size="small" text :disabled="!task?.current_artifact" @click="emit('open-version-drawer')">版本历史</el-button>
        <el-button size="small" text :disabled="!task?.current_artifact || isRunning" @click="projectStore.runTask(courseId, taskType, 'sync_context')">同步项目上下文</el-button>
        <el-button
          size="small"
          type="primary"
          :icon="CircleCheck"
          :loading="approving"
          :disabled="!task?.current_artifact || isRunning || task?.status === 'approved' || task?.stale_agent_profile"
          @click="approveArtifact"
        >{{ task?.status === 'approved' ? '已确认' : '确认文件' }}</el-button>
      </div>
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

.video-mode-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px 0;
  border-top: 1px solid #e5e7eb;
  background: #ffffff;
  overflow-x: auto;
}

.video-scope-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px 0;
  border-top: 1px solid #e5e7eb;
  background: #ffffff;
  overflow-x: auto;
}

.video-scope-label {
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}

.video-scope-chip {
  padding: 4px 7px;
  border: 1px solid #bfdbfe;
  border-radius: 5px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 11px;
  white-space: nowrap;
}

.video-scope-clear {
  border: 0;
  background: transparent;
  color: #64748b;
  font-size: 11px;
  cursor: pointer;
}

.video-mode-label {
  flex: 0 0 auto;
  color: #64748b;
  font-size: 12px;
}

.video-mode-button {
  flex: 0 0 auto;
  padding: 5px 9px;
  border: 1px solid #dbe3ef;
  border-radius: 6px;
  background: #ffffff;
  color: #475569;
  font-size: 12px;
  cursor: pointer;
}

.video-mode-button.active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
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

.pipeline-failure-alert {
  margin: 10px 14px 0;
  width: auto;
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
  display: flex;
  flex-direction: column;
}

.script-preview {
  flex: 1;
  min-height: 0;
}

.preview-footer {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding: 8px 14px;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
  flex-shrink: 0;
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
