<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { Check, MagicStick, Switch, VideoPause, VideoPlay } from '@element-plus/icons-vue';
import { pptTemplatesApi } from '../../../api/pptTemplates';
import { useProjectStore } from '../../../stores/project';
import { usePipelineStore } from '../../../stores/pipeline';
import type { PPTTemplate } from '../../../types';
import { PIPELINE_STATUS_LABELS } from '../../../types/agentPipeline';
import AgentExecutionTimeline from './AgentExecutionTimeline.vue';
import AgentComposer from './AgentComposer.vue';
import PPTPreviewWorkbench from './PPTPreviewWorkbench.vue';

const props = defineProps<{
  courseId: string;
  taskType: string;
}>();

const projectStore = useProjectStore();
const pipelineStore = usePipelineStore();

const task = computed(() => projectStore.currentTask);
const status = computed(() => pipelineStore.status || projectStore.pipelineStatus || task.value?.status || '');
const paused = computed(() => status.value === 'paused');
const isRunning = computed(() => ['queued', 'running'].includes(status.value));

const templates = ref<PPTTemplate[]>([]);
const showTemplateDrawer = ref(false);
const applyingTemplate = ref(false);

const activeSlideIndex = ref(0);
const targetSlideContext = ref<number | null>(null);

// Resizable splitter proportion
const leftPercent = ref(38);
const isDragging = ref(false);
const containerRef = ref<HTMLElement | null>(null);

// Mobile pane tab switcher
const mobilePane = ref<'agent' | 'preview'>('agent');

const statusType = computed(() => {
  if (status.value === 'running') return 'primary';
  if (status.value === 'completed') return 'success';
  if (status.value === 'paused') return 'warning';
  if (status.value === 'failed') return 'danger';
  return 'info';
});

const pptContent = computed(() => {
  const content = task.value?.current_artifact?.content_json;
  return content && content.slides ? content : null;
});

const currentTemplateId = computed(() => pptContent.value?.theme || 'default');
const template = computed(() => {
  return templates.value.find(item => item.id === currentTemplateId.value) || null;
});

async function loadDetail() {
  await pipelineStore.load(props.courseId, props.taskType);
  pipelineStore.restoreThoughtsFromHistory();
  pipelineStore.syncThoughts();
}

async function loadTemplates() {
  try {
    const catalog = await pptTemplatesApi.getCatalog();
    templates.value = catalog.templates;
  } catch {
    templates.value = [];
  }
}

function send(content: string) {
  void projectStore.sendMessage(props.courseId, props.taskType, content);
  targetSlideContext.value = null;
  void loadDetail();
}

async function pause() {
  await pipelineStore.pause(props.courseId, props.taskType);
  await loadDetail();
}

async function resume() {
  await pipelineStore.resume(props.courseId, props.taskType);
  await loadDetail();
}

function setModel(modelId: string) {
  void projectStore.setTaskModel(props.courseId, props.taskType, modelId);
}

function handleSelectSlide(index: number) {
  activeSlideIndex.value = index;
  mobilePane.value = 'preview';
}

function handleModifySlide(index: number) {
  targetSlideContext.value = index;
  mobilePane.value = 'agent';
}

async function handleApplyTemplate(templateId: string) {
  const artifact = task.value?.current_artifact;
  if (!artifact || applyingTemplate.value) return;
  applyingTemplate.value = true;
  try {
    const result = await pptTemplatesApi.applyTemplate(artifact.id, templateId, artifact.version);
    if (task.value) task.value.current_artifact = result.artifact;
    showTemplateDrawer.value = false;
    await projectStore.refreshTasks();
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
    if (s && ['queued', 'running', 'paused'].includes(s)) void loadDetail();
    else if (status.value === 'running') void loadDetail();
  }, 2000);
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = null;
}

onMounted(async () => {
  await loadTemplates();
  await loadDetail();
  startPolling();
});

onUnmounted(stopPolling);

watch(() => status.value, newStatus => {
  if (['queued', 'running', 'paused'].includes(newStatus)) startPolling();
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
          <el-button v-if="!paused && status === 'running'" size="small" @click="pause">
            <el-icon><VideoPause /></el-icon>&nbsp;暂停
          </el-button>
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
        @select-slide="handleSelectSlide"
      />

      <AgentComposer
        :target-slide="targetSlideContext"
        :is-running="isRunning"
        :model-config-id="task?.model_config_id"
        @send="send"
        @pause="pause"
        @clear-target-slide="targetSlideContext = null"
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

    <!-- 右侧：PPT 主预览与胶片导航 -->
    <main
      class="pane-preview"
      :class="{ 'mobile-hidden': mobilePane !== 'preview' }"
      :style="{ width: `${100 - leftPercent}%` }"
    >
      <PPTPreviewWorkbench
        :ppt-content="pptContent"
        :template="template"
        :is-running="isRunning"
        :active-slide-index="activeSlideIndex"
        @select-slide="activeSlideIndex = $event"
        @modify-slide="handleModifySlide"
        @open-template-drawer="showTemplateDrawer = true"
        @open-version-drawer="projectStore.refreshCurrentTask()"
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
