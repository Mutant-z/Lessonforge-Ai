<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ArrowDown, CircleCheck, Clock, Cpu, Edit, Lock, MagicStick, Promotion, RefreshRight, Setting, VideoPause, Warning } from '@element-plus/icons-vue';
import { api, errorMessage } from '../api/client';
import { pptTemplatesApi } from '../api/pptTemplates';
import { settingsApi } from '../api/settings';
import { pipelineApi } from '../api/pipeline';
import { useProjectStore } from '../stores/project';
import { useAutoScroll } from '../composables/useAutoScroll';
import type { Artifact, ExerciseContent, PPTTemplate, TaskSheetContent, VideoScriptContent } from '../types';
import ProjectShell from '../components/project/ProjectShell.vue';
import ModelSelector from '../components/agent/ModelSelector.vue';
import MarkdownRenderer from '../components/content-renderers/MarkdownRenderer.vue';
import SlidePreview from '../components/domain/SlidePreview.vue';
import SlideThumbnail from '../components/domain/SlideThumbnail.vue';
import TaskSheetEditor from '../components/domain/TaskSheetEditor.vue';
import TaskSheetPreview from '../components/domain/TaskSheetPreview.vue';
import ExerciseEditor from '../components/domain/ExerciseEditor.vue';
import ExercisePreview from '../components/domain/ExercisePreview.vue';
import VideoScriptEditor from '../components/domain/VideoScriptEditor.vue';
import VideoScriptPreview from '../components/domain/VideoScriptPreview.vue';
import VersionSelector from '../components/domain/VersionSelector.vue';
import AgentPipelineWorkbench from '../components/agent/pipeline/AgentPipelineWorkbench.vue';
import { DEFAULT_PPT_TEMPLATE } from '../utils/pptTemplate';

const route = useRoute();
const store = useProjectStore();
const courseId = computed(() => route.params.id as string);
const taskType = computed(() => route.params.taskType as string);
const isPpt = computed(() => taskType.value === 'ppt');
const input = ref('');
const sending = ref(false);
const pausing = ref(false);
const error = ref('');
const taskLoading = ref(false);
const selectedSlide = ref(0);
const mobilePane = ref<'agent' | 'file'>('agent');
const versions = ref<Artifact[]>([]);
const showVersions = ref(false);
const editing = ref(false);
const draftMarkdown = ref('');
const taskSheetDraft = ref<TaskSheetContent | null>(null);
const exerciseDraft = ref<ExerciseContent | null>(null);
const videoScriptDraft = ref<VideoScriptContent | null>(null);
const showProfile = ref(false);
const showActivities = ref(false);
const pptTemplates = ref<PPTTemplate[]>([]);
const templateCatalogVersion = ref('');
const defaultTemplateId = ref(DEFAULT_PPT_TEMPLATE.id);
const previewTemplateId = ref(DEFAULT_PPT_TEMPLATE.id);
const showTemplateDrawer = ref(false);
const applyingTemplate = ref(false);
const chatViewport = ref<HTMLElement | null>(null);
const containerRef = ref<HTMLElement | null>(null);
const inputRef = ref<HTMLTextAreaElement | null>(null);
const { isAutoScrollActive, unreadCount, notifyNewContent, scrollToBottom } = useAutoScroll(chatViewport);

function adjustInputHeight() {
  nextTick(() => {
    if (inputRef.value) {
      inputRef.value.style.height = 'auto';
      const scrollHeight = inputRef.value.scrollHeight;
      const targetHeight = Math.min(Math.max(scrollHeight, 56), 220);
      inputRef.value.style.height = `${targetHeight}px`;
    }
  });
}

watch(input, adjustInputHeight);

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    send();
  }
}

const leftPercent = ref(32);
const isDragging = ref(false);
const isMobile = ref(false);
let mobileMedia: MediaQueryList | null = null;

const task = computed(() => store.currentTask);
const artifact = computed(() => task.value?.current_artifact || null);
const isRunning = computed(() => ['queued', 'running'].includes(task.value?.status || ''));
const profileReady = computed(() => task.value?.agent_profile_status === 'ready');
const currentTemplateId = computed(() => {
  const requested = artifact.value?.content_json?.theme;
  return requested && pptTemplates.value.some(item => item.id === requested)
    ? requested
    : DEFAULT_PPT_TEMPLATE.id;
});
const currentTemplate = computed(() => pptTemplates.value.find(item => item.id === currentTemplateId.value) || DEFAULT_PPT_TEMPLATE);
const previewTemplate = computed(() => pptTemplates.value.find(item => item.id === previewTemplateId.value) || currentTemplate.value);
const templateDrawerDirection = computed(() => isMobile.value ? 'btt' : 'rtl');
const templateDrawerSize = computed(() => isMobile.value ? '82%' : '460px');
const contentUpdateSignature = computed(() => {
  const messages = task.value?.messages || [];
  const latest = messages[messages.length - 1];
  const activity = task.value?.current_activity;
  return [
    task.value?.task_type,
    messages.length,
    latest?.id,
    latest?.content?.length || 0,
    latest?.status,
    activity?.phase,
    activity?.status,
    activity?.progress,
    activity?.elapsed_ms,
  ].join(':');
});

function formatActivityTime(milliseconds: number) {
  if (!milliseconds) return '';
  const seconds = Math.max(1, Math.round(milliseconds / 1000));
  return `${seconds} 秒`;
}

function updateMobileBreakpoint() {
  isMobile.value = Boolean(mobileMedia?.matches);
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
  if (newPercent >= 20 && newPercent <= 70) {
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
  leftPercent.value = 32;
}

async function load() {
  taskLoading.value = true;
  error.value = '';
  selectedSlide.value = 0;
  editing.value = false;
  taskSheetDraft.value = null;
  exerciseDraft.value = null;
  videoScriptDraft.value = null;
  try {
    await store.openTask(courseId.value, taskType.value);
    await nextTick();
    scrollToBottom(false);
  } catch (cause) {
    error.value = errorMessage(cause);
  } finally {
    taskLoading.value = false;
  }
}

async function loadPptTemplates() {
  try {
    const [catalog, settings] = await Promise.all([
      pptTemplatesApi.getCatalog(),
      settingsApi.getSettings(),
    ]);
    pptTemplates.value = catalog.templates;
    templateCatalogVersion.value = catalog.version;
    defaultTemplateId.value = settings.preferences.default_ppt_template || DEFAULT_PPT_TEMPLATE.id;
  } catch (cause) {
    error.value = errorMessage(cause);
  }
}

function openTemplateDrawer() {
  previewTemplateId.value = currentTemplateId.value;
  showTemplateDrawer.value = true;
}

function closeTemplateDrawer() {
  previewTemplateId.value = currentTemplateId.value;
  showTemplateDrawer.value = false;
}

async function applyPptTemplate() {
  if (!artifact.value || previewTemplateId.value === currentTemplateId.value || applyingTemplate.value) return;
  applyingTemplate.value = true;
  error.value = '';
  try {
    const result = await pptTemplatesApi.applyTemplate(
      artifact.value.id,
      previewTemplateId.value,
      artifact.value.version,
    );
    if (task.value) task.value.current_artifact = result.artifact;
    showTemplateDrawer.value = false;
    await store.refreshTasks();
  } catch (cause) {
    error.value = errorMessage(cause);
  } finally {
    applyingTemplate.value = false;
  }
}

async function handleButtonClick() {
  if (isRunning.value) {
    if (pausing.value) return;
    pausing.value = true;
    error.value = '';
    try {
      await pipelineApi.pause(courseId.value, taskType.value);
    } catch (cause) {
      error.value = errorMessage(cause);
    } finally {
      pausing.value = false;
    }
    return;
  }
  await send();
}

async function send() {
  const content = input.value.trim();
  if (!content || sending.value) return;
  sending.value = true;
  error.value = '';
  input.value = '';
  try {
    await store.sendMessage(courseId.value, taskType.value, content);
    await nextTick();
    scrollToBottom(false);
  } catch (cause) {
    input.value = content;
    error.value = errorMessage(cause);
  } finally {
    sending.value = false;
  }
}

async function run(action: 'initial' | 'retry' | 'sync_dependencies' | 'sync_context') {
  error.value = '';
  try {
    await store.runTask(courseId.value, taskType.value, action);
  } catch (cause) {
    error.value = errorMessage(cause);
  }
}

async function approve() {
  try { await store.approveTask(courseId.value, taskType.value); }
  catch (cause) { error.value = errorMessage(cause); }
}

async function setModel(id: string) {
  try { await store.setTaskModel(courseId.value, taskType.value, id); }
  catch (cause) { error.value = errorMessage(cause); }
}

async function setImageModel(id: string) {
  try {
    const { data } = await api.patch(`/courses/${courseId.value}/tasks/${taskType.value}/model`, { image_model_config_id: id });
    if (task.value) task.value.image_model_config_id = data.image_model_config_id;
  } catch (cause) { error.value = errorMessage(cause); }
}

async function setVisionModel(id: string) {
  try {
    const { data } = await api.patch(`/courses/${courseId.value}/tasks/${taskType.value}/model`, { vision_model_config_id: id });
    if (task.value) task.value.vision_model_config_id = data.vision_model_config_id;
  } catch (cause) { error.value = errorMessage(cause); }
}

async function lockArtifact() {
  if (!artifact.value) return;
  try {
    await api.post(`/artifacts/${artifact.value.id}/lock`, { json_path: '$' });
    artifact.value.is_locked = true;
  } catch (cause) { error.value = errorMessage(cause); }
}

async function loadVersions() {
  if (!artifact.value) return;
  try {
    const { data } = await api.get<Artifact[]>(`/artifacts/${artifact.value.id}/versions`);
    versions.value = data;
    showVersions.value = true;
  } catch (cause) { error.value = errorMessage(cause); }
}

function selectVersion(version: Artifact) {
  if (task.value) task.value.current_artifact = version;
  showVersions.value = false;
}

function isTaskSheetV2(value: unknown): value is TaskSheetContent {
  return Boolean(value && typeof value === 'object' && (value as { schema_version?: string }).schema_version === '2.0');
}

function isExerciseV2(value: unknown): value is ExerciseContent {
  return Boolean(value && typeof value === 'object' && (value as { schema_version?: string }).schema_version === '2.0');
}

function isVideoScriptV2(value: unknown): value is VideoScriptContent {
  return Boolean(value && typeof value === 'object' && (value as { schema_version?: string }).schema_version === '2.0');
}

const editableTaskSheet = computed<TaskSheetContent>({
  get: () => taskSheetDraft.value as TaskSheetContent,
  set: value => { taskSheetDraft.value = value; },
});
const editableExercise = computed<ExerciseContent>({
  get: () => exerciseDraft.value as ExerciseContent,
  set: value => { exerciseDraft.value = value; },
});
const editableVideoScript = computed<VideoScriptContent>({
  get: () => videoScriptDraft.value as VideoScriptContent,
  set: value => { videoScriptDraft.value = value; },
});

function beginEdit() {
  error.value = '';
  if (taskType.value === 'task_sheet') {
    if (!isTaskSheetV2(artifact.value?.content_json)) {
      error.value = '这是旧版任务单。请在左侧对话中提出修改要求，Agent 会保留原版本并生成新的 V2 结构化任务单。';
      return;
    }
    taskSheetDraft.value = JSON.parse(JSON.stringify(artifact.value.content_json)) as TaskSheetContent;
  } else if (taskType.value === 'exercise') {
    if (!isExerciseV2(artifact.value?.content_json)) {
      error.value = '这是旧版课后练习。请在左侧对话中提出修改要求，Agent 会保留原版本并生成新的 V2 结构化练习。';
      return;
    }
    exerciseDraft.value = JSON.parse(JSON.stringify(artifact.value.content_json)) as ExerciseContent;
  } else if (taskType.value === 'video_script') {
    if (!isVideoScriptV2(artifact.value?.content_json)) {
      error.value = '这是旧版视频脚本。请在左侧对话中提出修改要求，Agent 会保留原版本并生成新的 V2 结构化脚本。';
      return;
    }
    videoScriptDraft.value = JSON.parse(JSON.stringify(artifact.value.content_json)) as VideoScriptContent;
  }
  draftMarkdown.value = artifact.value?.content_markdown || '';
  editing.value = true;
}

function cancelEdit() {
  editing.value = false;
  taskSheetDraft.value = null;
  exerciseDraft.value = null;
  videoScriptDraft.value = null;
}

function prepareSlideRevision(index: number) {
  input.value = `请重新设计第 ${index + 1} 页，保留课程目标并优化信息层级与视觉表达。`;
  mobilePane.value = 'agent';
}

async function saveEdit() {
  if (!artifact.value) return;
  try {
    const contentJson = taskType.value === 'task_sheet' && taskSheetDraft.value
      ? taskSheetDraft.value
      : taskType.value === 'exercise' && exerciseDraft.value
        ? exerciseDraft.value
        : taskType.value === 'video_script' && videoScriptDraft.value
          ? videoScriptDraft.value
        : artifact.value.content_json;
    const { data } = await api.patch<Artifact>(`/artifacts/${artifact.value.id}`, {
      content_json: contentJson,
      content_markdown: draftMarkdown.value,
      change_summary: '教师在线编辑',
    });
    if (task.value) task.value.current_artifact = data;
    editing.value = false;
    taskSheetDraft.value = null;
    exerciseDraft.value = null;
    videoScriptDraft.value = null;
    await store.refreshTasks();
  } catch (cause) { error.value = errorMessage(cause); }
}

const quickPromptsMap: Record<string, string[]> = {
  lesson_plan: ['增加课堂探究实验环节', '强化教学重难点拆解', '简化学情分析描述', '补充课后拓展延伸'],
  ppt: ['优化 PPT 页面排版视觉', '增加图表示意结构', '精简每页文字字数', '强化重点结论高亮'],
  task_sheet: ['对齐教学环节', '增加观察记录表', '优化完成标准', '增强任务梯度', '精简学生说明'],
  exercise: ['对齐教学目标', '优化难度梯度', '增加材料题组', '检查答案与评分点', '生成或替换必要配图', '精简题量与学生说明'],
  video_script: ['压缩旁白时长', '减少照读 PPT', '增强画面动效', '增加检查点', '优化字幕节奏', '同步教学设计', '校准逐页时长'],
  verbatim: ['调整口语表达更自然', '增加课堂互动提示音', '控制讲解语速与时长'],
};

const currentQuickPrompts = computed(() => quickPromptsMap[taskType.value] || ['优化语言表达', '补充案例说明', '调整结构层级']);

function applyQuickPrompt(prompt: string) {
  if (!artifact.value || isRunning.value || !profileReady.value) return;
  input.value = input.value
    ? `${input.value}，${prompt}`
    : `请帮我调整当前${task.value?.display_name || '文件'}：${prompt}`;
}

watch(taskType, load);
watch(() => artifact.value?.id, () => {
  mobilePane.value = 'file';
  previewTemplateId.value = currentTemplateId.value;
});
watch(contentUpdateSignature, async () => {
  await nextTick();
  notifyNewContent(!isRunning.value);
}, { flush: 'post' });

onMounted(() => {
  mobileMedia = window.matchMedia('(max-width: 900px)');
  updateMobileBreakpoint();
  mobileMedia.addEventListener('change', updateMobileBreakpoint);
  load();
  loadPptTemplates();
});

onUnmounted(() => {
  mobileMedia?.removeEventListener('change', updateMobileBreakpoint);
  stopResize();
  store.stopActiveTaskPolling();
  store.disconnect();
});
</script>

<template>
  <div v-if="store.loading && !store.project" class="task-loading"><el-skeleton :rows="8" animated /></div>
  <ProjectShell v-else-if="store.project" :active-type="taskType">
    <div v-if="taskLoading && (!task || task.task_type !== taskType)" class="task-subtask-loading" style="padding: 32px; max-width: 900px; margin: 20px auto;">
      <el-skeleton :rows="10" animated />
    </div>
    <div v-else-if="error && (!task || task.task_type !== taskType)" class="task-subtask-error" style="padding: 32px; max-width: 600px; margin: 40px auto;">
      <el-alert :title="error" type="error" show-icon :closable="false">
        <template #default>
          <p style="margin: 8px 0 12px; font-weight: 600;">无法加载当前【{{ taskType }}】任务数据。</p>
          <el-button size="small" type="primary" @click="load">重试加载</el-button>
        </template>
      </el-alert>
    </div>
    <AgentPipelineWorkbench v-else-if="isPpt && task && task.task_type === taskType" :course-id="courseId" :task-type="taskType" />
    <template v-else>
    <div v-if="task && task.task_type === taskType" ref="containerRef" class="task-workspace">
      <div class="mobile-pane-switch" role="tablist">
        <button :class="{ active: mobilePane === 'agent' }" @click="mobilePane = 'agent'">Agent 对话</button>
        <button :class="{ active: mobilePane === 'file' }" @click="mobilePane = 'file'">任务文件</button>
      </div>

      <aside
        class="agent-pane"
        :class="{ 'mobile-hidden': mobilePane !== 'agent' }"
        :style="{ width: isMobile ? '100%' : `${leftPercent}%` }"
      >
        <header class="agent-header">
          <div class="agent-header-left">
            <div class="agent-folio-badge">
              <el-icon><Cpu /></el-icon>
              <span class="folio-order">{{ String(task.display_order).padStart(2, '0') }}</span>
            </div>
            <div class="agent-header-meta">
              <div class="header-name-row">
                <h2>{{ task.agent_name }}</h2>
                <span class="status-live-chip">
                  <i class="live-dot" :class="{ offline: !profileReady }" />
                  {{ profileReady ? '在线' : task.agent_profile_status === 'failed' ? '初始化失败' : '准备中' }}
                </span>
              </div>
            </div>
          </div>
          <button
            v-if="task.agent_profile_summary"
            type="button"
            class="profile-toggle-btn"
            :class="{ active: showProfile }"
            title="查看 Agent 专属配置"
            @click="showProfile = !showProfile"
          >
            <el-icon><Setting /></el-icon>
            <span>配置</span>
          </button>
        </header>

        <div v-if="task.status === 'failed'" class="task-alert failed">
          <el-icon><Warning /></el-icon>
          <div>
            <strong>本次任务失败</strong>
            <p>{{ task.error?.message }}</p>
            <button type="button" @click="run('retry')">重试任务</button>
          </div>
        </div>
        <div v-else-if="task.status === 'stale'" class="task-alert stale">
          <el-icon><RefreshRight /></el-icon>
          <div>
            <strong>{{ task.stale_agent_profile ? '项目背景或 Agent 配置已更新' : '上游任务已有新版本' }}</strong>
            <p>当前文件仍然保留。确认后将基于最新项目上下文与上游内容生成下一版。</p>
            <button type="button" @click="run(task.stale_agent_profile ? 'sync_context' : 'sync_dependencies')">同步最新内容</button>
          </div>
        </div>

        <div v-else-if="task.agent_profile_status === 'failed'" class="task-alert failed">
          <el-icon><Warning /></el-icon>
          <div>
            <strong>项目专属 Agent 初始化失败</strong>
            <p>{{ task.agent_profile_error?.message || '请返回项目总览重新初始化六个 Agent。' }}</p>
          </div>
        </div>

        <div ref="chatViewport" class="chat-viewport">
          <!-- Collapsible Agent Profile Summary -->
          <transition name="expand-fade">
            <section v-if="showProfile && task.agent_profile_summary" class="profile-summary-card">
              <header>
                <strong>项目专属配置</strong>
                <span>V{{ task.agent_profile_version }} · 模板 V{{ task.agent_profile_template_version }}</span>
              </header>
              <p>{{ task.agent_profile_summary.mission }}</p>
              <div class="profile-tags">
                <span v-for="item in task.agent_profile_summary.knowledge_focus.slice(0, 3)" :key="item">{{ item }}</span>
              </div>
              <small>面向：{{ task.agent_profile_summary.audience }}</small>
              <dl class="profile-details">
                <div><dt>任务目标</dt><dd>{{ task.agent_profile_summary.task_goals.slice(0, 2).join('；') }}</dd></div>
                <div><dt>表达风格</dt><dd>{{ task.agent_profile_summary.style_guidelines.slice(0, 2).join('；') }}</dd></div>
                <div><dt>硬约束</dt><dd>{{ task.agent_profile_summary.hard_constraints.slice(0, 2).join('；') }}</dd></div>
                <div><dt>质量关注</dt><dd>{{ task.agent_profile_summary.quality_focus.slice(0, 2).join('；') }}</dd></div>
              </dl>
            </section>
          </transition>

          <div class="agent-introduction">
            <div class="intro-title-line">
              <strong>{{ task.agent_name }}</strong>
              <span v-if="artifact" class="version-chip">V{{ artifact.version }}</span>
            </div>
            <p v-if="artifact">
              老师您好！当前协助维护 <strong>{{ task.display_name }} V{{ artifact.version }}</strong>。请告诉我要调整的内容，我会精准推演生成新版本。
            </p>
            <p v-else>
              任务文件按依赖生成中，生成完成后可在这里输入修改指令。
            </p>
          </div>

          <article v-for="message in task.messages || []" :key="message.id" class="message" :class="message.role">
            <div class="role-line">
              <div class="mini-role-avatar" :class="message.role">
                <el-icon v-if="message.role !== 'user'"><Cpu /></el-icon>
                <span v-else>师</span>
              </div>
              <span class="role-name">{{ message.role === 'user' ? '教师' : task.agent_name }}</span>
            </div>
            <div class="message-content">
              <span v-if="message.status === 'streaming' && !message.content" class="reply-placeholder">正在组织回复</span>
              <MarkdownRenderer v-else :content="message.content" :is-streaming="message.status === 'streaming'" />
              <i v-if="message.status === 'streaming'" class="streaming-caret" aria-hidden="true" />
            </div>
            <small v-if="message.status === 'pending'" class="status-hint">等待 Agent 处理...</small>
            <small v-else-if="message.status === 'failed'" class="status-hint error">本次修改未完成</small>
          </article>

          <!-- Collapsible Activity Progress Card when Running -->
          <section v-if="isRunning && task.activities?.length" class="agent-activity-card">
            <header @click="showActivities = !showActivities">
              <span class="activity-pulse"><i /></span>
              <div class="activity-header-text">
                <strong>{{ task.current_activity?.label || 'Agent 正在工作' }}</strong>
                <p>{{ task.current_activity?.detail }}</p>
              </div>
              <div class="activity-header-right">
                <b>{{ task.progress }}%</b>
                <el-icon class="activity-arrow" :class="{ rotated: showActivities }"><ArrowDown /></el-icon>
              </div>
            </header>
            <div class="activity-progress"><i :style="{ width: `${task.progress}%` }" /></div>
            <ol v-if="showActivities">
              <li v-for="activity in task.activities" :key="activity.phase" :class="activity.status">
                <span class="activity-state">
                  <el-icon v-if="activity.status === 'completed'"><CircleCheck /></el-icon>
                  <i v-else />
                </span>
                <span>{{ activity.label }}</span>
                <small>{{ formatActivityTime(activity.elapsed_ms) }}</small>
              </li>
            </ol>
          </section>
          <div v-else-if="isRunning" class="agent-running">
            <i class="running-dot" />
            <span>{{ task.status === 'queued' ? 'Agent 已进入队列' : `Agent 正在准备新版本 · ${task.progress}%` }}</span>
          </div>
        </div>

        <button
          v-if="!isAutoScrollActive"
          type="button"
          class="back-to-latest"
          @click="scrollToBottom(true)"
        >
          <el-icon><ArrowDown /></el-icon>
          回到最新回复<span v-if="unreadCount"> · {{ unreadCount }}</span>
        </button>

        <form class="composer-floating-card" @submit.prevent="handleButtonClick">
          <!-- Quick Prompts Toolbar right inside Composer -->
          <div v-if="artifact && currentQuickPrompts.length" class="composer-quick-prompts">
            <span class="quick-prompts-label">
              <el-icon><MagicStick /></el-icon> 建议:
            </span>
            <div class="quick-chips-row">
              <button
                v-for="item in currentQuickPrompts"
                :key="item"
                type="button"
                class="quick-chip"
                :disabled="isRunning"
                @click="applyQuickPrompt(item)"
              >
                + {{ item }}
              </button>
            </div>
          </div>

          <textarea
            ref="inputRef"
            v-model="input"
            rows="2"
            :disabled="isRunning || !artifact || !profileReady"
            :placeholder="isRunning ? 'Agent 正在处理中，点击右下角按钮可暂停...' : (!profileReady ? '项目专属 Agent 初始化完成后可继续对话' : artifact ? `详细描述您希望如何修改 ${task.display_name}…` : '任务文件生成后可继续对话修改')"
            @keydown="onKeydown"
          />

          <div class="composer-card-footer">
            <div class="footer-left">
              <ModelSelector
                :model-value="task.model_config_id || null"
                compact
                label=""
                :disabled="isRunning"
                @change="setModel"
              />
            </div>
            <div class="footer-right">
              <span class="key-tip">Shift+Enter 换行</span>
              <button
                type="submit"
                class="composer-send-circle"
                :class="{ 'is-pausing': isRunning }"
                :disabled="isRunning ? pausing : (!input.trim() || !artifact || !profileReady)"
                :title="isRunning ? '暂停 Agent 推演' : '发送修改'"
              >
                <el-icon v-if="pausing || sending" class="is-loading"><Loading /></el-icon>
                <el-icon v-else-if="isRunning"><VideoPause /></el-icon>
                <el-icon v-else><Promotion /></el-icon>
              </button>
            </div>
          </div>
        </form>
      </aside>

      <!-- Draggable Splitter Divider -->
      <div
        v-if="!isMobile"
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
        class="file-pane"
        :class="{ 'mobile-hidden': mobilePane !== 'file' }"
        :style="{ width: isMobile ? '100%' : `${100 - leftPercent}%` }"
      >
        <header class="file-toolbar">
          <div class="toolbar-title-box">
            <span>当前任务文件</span>
            <h2>{{ task.display_name }} <small v-if="artifact">V{{ artifact.version }}</small></h2>
          </div>
          <div v-if="artifact" class="file-actions">
            <el-button
              v-if="taskType === 'ppt'"
              size="small"
              :icon="MagicStick"
              :disabled="artifact.is_locked || isRunning"
              @click="openTemplateDrawer"
            >模板 · {{ currentTemplate.short_name }}</el-button>
            <el-button size="small" :icon="Clock" @click="loadVersions">版本历史</el-button>
            <el-button size="small" :icon="RefreshRight" :disabled="artifact.is_locked || isRunning" @click="run('sync_context')">同步上下文</el-button>
            <el-button size="small" :icon="Lock" :disabled="artifact.is_locked" @click="lockArtifact">{{ artifact.is_locked ? '已锁定' : '锁定文件' }}</el-button>
            <el-button size="small" :icon="Edit" :disabled="artifact.is_locked" @click="beginEdit">编辑</el-button>
            <el-button size="small" type="primary" :icon="CircleCheck" :disabled="task.status === 'approved' || task.stale_agent_profile" @click="approve">{{ task.status === 'approved' ? '已确认' : '确认文件' }}</el-button>
          </div>
        </header>

        <div v-if="error" class="inline-error">{{ error }}</div>
        <div v-if="isRunning && artifact" class="nonblocking-progress">
          <span>{{ task.status === 'queued' ? 'Agent 已排队' : task.current_activity?.label || 'Agent 正在生成新版本' }}</span>
          <strong>{{ task.progress }}%</strong>
        </div>

        <div v-if="editing && taskType === 'task_sheet' && taskSheetDraft" class="structured-editor">
          <div class="structured-editor-scroll"><TaskSheetEditor v-model="editableTaskSheet" /></div>
          <footer><el-button size="small" @click="cancelEdit">取消</el-button><el-button size="small" type="primary" @click="saveEdit">保存为新版本</el-button></footer>
        </div>
        <div v-else-if="editing && taskType === 'exercise' && exerciseDraft" class="structured-editor">
          <div class="structured-editor-scroll"><ExerciseEditor v-model="editableExercise" /></div>
          <footer><el-button size="small" @click="cancelEdit">取消</el-button><el-button size="small" type="primary" @click="saveEdit">保存为新版本</el-button></footer>
        </div>
        <div v-else-if="editing && taskType === 'video_script' && videoScriptDraft" class="structured-editor">
          <div class="structured-editor-scroll"><VideoScriptEditor v-model="editableVideoScript" /></div>
          <footer><el-button size="small" @click="cancelEdit">取消</el-button><el-button size="small" type="primary" @click="saveEdit">保存为新版本</el-button></footer>
        </div>
        <div v-else-if="editing" class="editor">
          <textarea v-model="draftMarkdown" spellcheck="false" />
          <footer><el-button size="small" @click="cancelEdit">取消</el-button><el-button size="small" type="primary" @click="saveEdit">保存为新版本</el-button></footer>
        </div>
        <div v-else-if="artifact" class="artifact-viewport" :class="{ updated: artifact.id }">
          <div v-if="taskType === 'ppt' && artifact.content_json?.slides" class="ppt-layout">
            <div class="slide-list">
              <SlideThumbnail v-for="(slide, index) in artifact.content_json.slides" :key="slide.id || index" :slide="slide" :index="index" :total-slides="artifact.content_json.slides.length" :is-active="selectedSlide === index" :template="previewTemplate" @select="selectedSlide = $event" />
            </div>
            <div class="slide-preview"><SlidePreview :slide="artifact.content_json.slides[selectedSlide]" :slide-index="selectedSlide" :total-slides="artifact.content_json.slides.length" :template="previewTemplate" @regenerate-slide="prepareSlideRevision" /></div>
          </div>
          <TaskSheetPreview v-else-if="taskType === 'task_sheet' && isTaskSheetV2(artifact.content_json)" :content="artifact.content_json" :source-versions="artifact.source_versions_json" />
          <ExercisePreview v-else-if="taskType === 'exercise' && isExerciseV2(artifact.content_json)" :content="artifact.content_json" :source-versions="artifact.source_versions_json" />
          <VideoScriptPreview v-else-if="taskType === 'video_script' && isVideoScriptV2(artifact.content_json)" :content="artifact.content_json" :source-versions="artifact.source_versions_json" />
          <MarkdownRenderer v-else :content="artifact.content_markdown" />
        </div>
        <div v-else class="file-empty">
          <span>{{ String(task.display_order).padStart(2, '0') }}</span>
          <h3>{{ task.status === 'failed' ? '任务生成失败' : '任务文件正在准备' }}</h3>
          <p>{{ task.status === 'waiting_dependency' ? '上游任务完成后将自动启动当前 Agent。' : task.status === 'failed' ? task.error?.message : 'Agent 完成结构校验后，最新文件会自动显示在这里。' }}</p>
          <el-button v-if="task.status === 'failed'" type="primary" @click="run('retry')">重试任务</el-button>
        </div>
      </main>
    </div>
    </template>
    <VersionSelector v-if="showVersions" :versions="versions" :current-version="artifact?.version" @select="selectVersion" @close="showVersions = false" />
    <el-drawer
      v-model="showTemplateDrawer"
      class="ppt-template-drawer"
      :direction="templateDrawerDirection"
      :size="templateDrawerSize"
      :show-close="false"
      @closed="previewTemplateId = currentTemplateId"
    >
      <template #header>
        <div class="template-drawer-head">
          <div>
            <span>PPT 模板</span>
            <h3>选择课件视觉风格</h3>
          </div>
          <small>目录 V{{ templateCatalogVersion || '1.0.0' }}</small>
        </div>
      </template>

      <div class="template-drawer-body">
        <p class="template-drawer-intro">使用当前第 {{ selectedSlide + 1 }} 页内容比较模板。应用后只改变视觉，不修改页面内容和教师备注。</p>
        <div class="template-card-grid">
          <div
            v-for="item in pptTemplates"
            :key="item.id"
            class="template-choice-card"
            :class="{ selected: previewTemplateId === item.id }"
            role="button"
            tabindex="0"
            :aria-pressed="previewTemplateId === item.id"
            @click="previewTemplateId = item.id"
            @keydown.enter.prevent="previewTemplateId = item.id"
            @keydown.space.prevent="previewTemplateId = item.id"
          >
            <div class="template-card-preview">
              <SlideThumbnail
                v-if="artifact?.content_json?.slides?.[selectedSlide]"
                :slide="artifact.content_json.slides[selectedSlide]"
                :index="selectedSlide"
                :total-slides="artifact.content_json.slides.length"
                :is-active="false"
                :template="item"
              />
            </div>
            <div class="template-card-title-row">
              <strong>{{ item.name }}</strong>
              <span v-if="currentTemplateId === item.id">当前课件</span>
            </div>
            <p>{{ item.description }}</p>
            <div class="template-card-meta">
              <div class="palette-dots" aria-label="模板配色">
                <i :style="{ background: item.palette.primary }" />
                <i :style="{ background: item.palette.secondary }" />
                <i :style="{ background: item.palette.background }" />
              </div>
              <span v-if="defaultTemplateId === item.id">我的默认</span>
              <small v-else>{{ item.recommended_for.join('、') }}</small>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="template-drawer-footer">
          <div><strong>{{ previewTemplate.name }}</strong><span>将保存为新的 PPT 版本</span></div>
          <div><el-button @click="closeTemplateDrawer">取消</el-button><el-button type="primary" :loading="applyingTemplate" :disabled="previewTemplateId === currentTemplateId" @click="applyPptTemplate">应用此模板</el-button></div>
        </div>
      </template>
    </el-drawer>
  </ProjectShell>
</template>

<style scoped>
.task-loading { padding: 32px; }

.task-workspace {
  height: 100%;
  min-height: 0;
  display: flex;
  align-items: stretch;
  overflow: hidden;
  background: transparent;
}

/* Pane Resizer / Divider */
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
  flex-shrink: 0;
}

.pane-resizer:hover,
.pane-resizer.dragging {
  background: #e0e7ff;
}

.resizer-line {
  width: 2px;
  height: 24px;
  background: #cbd5e1;
  border-radius: 999px;
  transition: background 150ms ease;
}

.pane-resizer:hover .resizer-line,
.pane-resizer.dragging .resizer-line {
  background: #4f46e5;
}

.agent-pane {
  position: relative;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: 12px;
  background: #ffffff;
  box-shadow: var(--shadow-sm, 0 2px 8px rgba(15, 23, 42, 0.03));
  overflow: hidden;
  transition: box-shadow 200ms ease;
}

.agent-pane:focus-within {
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
}

.agent-header {
  min-height: 48px;
  padding: 8px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.agent-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.agent-folio-badge {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%);
  color: #ffffff;
  display: grid;
  place-items: center;
  position: relative;
  font-size: 14px;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.2);
  flex-shrink: 0;
}

.folio-order {
  position: absolute;
  bottom: -2px;
  right: -2px;
  background: #ffffff;
  color: var(--primary-700, #4338ca);
  font-size: 8px;
  font-weight: 900;
  padding: 0 3px;
  border-radius: 999px;
  border: 1px solid var(--primary-200, #c7d2fe);
}

.agent-header-meta {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.header-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.header-name-row h2 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
}

.status-live-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10.5px;
  font-weight: 700;
  color: var(--primary-700, #4338ca);
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--primary-200, #c7d2fe);
  padding: 1px 7px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.profile-toggle-btn {
  border: 1px solid #c7d2fe;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: all 150ms ease;
}

.profile-toggle-btn:hover, .profile-toggle-btn.active {
  background: #4338ca;
  color: #ffffff;
  border-color: #4338ca;
}

.live-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #10b981;
}

.live-dot.offline { background: #f59e0b; }

.profile-summary-card {
  padding: 12px 14px;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  background: #f8faff;
  margin-bottom: 8px;
}

.profile-summary-card header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #4338ca;
  font-size: 11.5px;
}

.profile-summary-card header span,
.profile-summary-card small { color: #64748b; }

.profile-summary-card p {
  margin: 6px 0;
  color: #334155;
  font-size: 11.5px;
  line-height: 1.5;
}

.profile-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.profile-tags span { padding: 1px 6px; border-radius: 999px; background: #eef2ff; color: #4338ca; font-size: 9.5px; }
.profile-details { margin: 6px 0 0; display: grid; gap: 4px; }
.profile-details div { display: grid; grid-template-columns: 50px minmax(0, 1fr); gap: 6px; font-size: 10.5px; line-height: 1.4; }
.profile-details dt { color: #64748b; font-weight: 700; }
.profile-details dd { margin: 0; color: #334155; }

.chat-viewport {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-introduction {
  padding: 10px 12px;
  border: 1px solid #c7d2fe;
  border-left: 3px solid var(--primary-600, #4f46e5);
  border-radius: 10px;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 60%, #eef2ff 100%);
}

.intro-title-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.intro-title-line strong {
  font-size: 12px;
  font-weight: 800;
  color: var(--primary-700, #4338ca);
}

.version-chip {
  font-size: 10px;
  font-weight: 800;
  color: var(--primary-700, #4338ca);
  background: #ffffff;
  border: 1px solid var(--primary-200, #c7d2fe);
  padding: 1px 6px;
  border-radius: 999px;
}

.agent-introduction p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #334155;
}

.message {
  display: flex;
  flex-direction: column;
  max-width: 90%;
  animation: fadeIn 200ms ease;
}

.message.assistant {
  align-self: flex-start;
}

.message.user {
  align-self: flex-end;
  align-items: flex-end;
}

.message.user .role-line {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 3px;
  flex-direction: row-reverse;
}

.role-line {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 3px;
}

.mini-role-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 9px;
  font-weight: 800;
}

.mini-role-avatar.assistant {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
}

.mini-role-avatar.user {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: #ffffff;
}

.role-name {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--text-muted, #64748b);
}

.message-content {
  margin: 0;
  padding: 9px 13px;
  font-size: 13px;
  line-height: 1.55;
  /* 由 MarkdownRenderer 统一排版，禁止保留块级标签之间的换行造成大段空白 */
  white-space: normal;
}

.message.assistant .message-content {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px 14px 14px 4px;
  color: var(--text-primary, #0f172a);
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.03);
}

.message.user .message-content {
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--primary-700, #4338ca) 100%);
  color: #ffffff;
  border-radius: 14px 14px 4px 14px;
  box-shadow: 0 3px 10px rgba(79, 70, 229, 0.2);
}

.message.user .message-content :deep(.markdown-rendered-body),
.message.user .message-content :deep(.markdown-rendered-body p),
.message.user .message-content :deep(.markdown-rendered-body span),
.message.user .message-content :deep(.markdown-rendered-body strong),
.message.user .message-content :deep(.markdown-rendered-body li) {
  color: #ffffff !important;
}

.message.user .message-content :deep(.markdown-rendered-body code) {
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
}

.status-hint {
  margin-top: 3px;
  font-size: 10px;
  color: var(--text-muted, #64748b);
}

.status-hint.error {
  color: #b91c1c;
}

.reply-placeholder {
  color: #64748b;
}

.reply-placeholder::after {
  content: '...';
  display: inline-block;
  width: 18px;
  overflow: hidden;
  vertical-align: bottom;
  animation: thinkingDots 1.15s steps(4, end) infinite;
}

.streaming-caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 3px;
  vertical-align: -2px;
  border-radius: 2px;
  background: #6366f1;
  animation: caretBlink 0.8s ease-in-out infinite;
}

.agent-activity-card {
  padding: 10px 12px;
  border: 1px solid #c7d2fe;
  border-radius: 12px;
  background: linear-gradient(135deg, #f8faff 0%, #eef2ff 100%);
  box-shadow: 0 3px 12px rgba(79, 70, 229, 0.06);
}

.agent-activity-card header {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.activity-header-text strong { display: block; color: #4338ca; font-size: 11.5px; }
.activity-header-text p { margin: 1px 0 0; color: #64748b; font-size: 10px; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.activity-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.activity-header-right b { color: #4f46e5; font-size: 11.5px; }

.activity-arrow {
  color: #6366f1;
  font-size: 12px;
  transition: transform 200ms ease;
}

.activity-arrow.rotated {
  transform: rotate(180deg);
}

.activity-pulse {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #e0e7ff;
}

.activity-pulse i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366f1;
  animation: activityPulse 1.2s ease-in-out infinite;
}

.activity-progress {
  height: 3px;
  margin: 6px 0;
  overflow: hidden;
  border-radius: 999px;
  background: #dbe4ff;
}

.activity-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  transition: width 350ms ease;
}

.agent-activity-card ol { margin: 6px 0 0; padding: 0; display: grid; gap: 4px; list-style: none; }
.agent-activity-card li { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; align-items: center; gap: 5px; color: #64748b; font-size: 10px; }
.agent-activity-card li.running { color: #4338ca; font-weight: 700; }
.agent-activity-card li.completed { color: #475569; }
.agent-activity-card li small { color: #94a3b8; }
.activity-state { width: 14px; height: 14px; display: grid; place-items: center; color: #10b981; }
.activity-state > i { width: 6px; height: 6px; border: 1.5px solid #a5b4fc; border-top-color: #4f46e5; border-radius: 50%; animation: spin 0.8s linear infinite; }

.back-to-latest {
  position: absolute;
  z-index: 4;
  right: 18px;
  bottom: 110px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid #c7d2fe;
  border-radius: 999px;
  color: #4338ca;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.15);
  font-size: 10.5px;
  font-weight: 700;
  cursor: pointer;
}

.agent-running {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--primary-700, #4338ca);
  background: var(--primary-50, #eef2ff);
  border-radius: 999px;
}

.running-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary-600, #4f46e5);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes caretBlink { 0%, 45% { opacity: 1; } 55%, 100% { opacity: 0.15; } }
@keyframes activityPulse { 0%, 100% { transform: scale(0.85); opacity: 0.65; } 50% { transform: scale(1.25); opacity: 1; } }
@keyframes thinkingDots { from { width: 0; } to { width: 18px; } }

.composer-floating-card {
  margin: 8px 12px 12px;
  padding: 10px 12px 8px;
  background: #ffffff;
  border: 1px solid var(--border-default, #cbd5e1);
  border-radius: 14px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  transition: all 200ms ease;
}

.composer-floating-card:focus-within {
  background: #ffffff;
  border-color: var(--primary-500, #6366f1);
  box-shadow: 0 4px 18px rgba(99, 102, 241, 0.15), 0 0 0 2px rgba(99, 102, 241, 0.12);
}

.composer-quick-prompts {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
  padding-bottom: 6px;
  border-bottom: 1px dashed #e2e8f0;
}

.composer-quick-prompts::-webkit-scrollbar { display: none; }

.quick-prompts-label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 700;
  color: var(--primary-600, #4f46e5);
  white-space: nowrap;
}

.quick-chips-row {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: nowrap;
}

.quick-chip {
  border: 1px solid #e0e7ff;
  background: #f8fafc;
  color: #4338ca;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 150ms ease;
}

.quick-chip:hover:not(:disabled) {
  border-color: #c7d2fe;
  background: #eef2ff;
}

.composer-floating-card textarea {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  color: var(--text-primary, #0f172a);
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.5;
  background: transparent;
  padding: 2px 0;
  min-height: 56px;
  max-height: 220px;
  overflow-y: auto;
  box-sizing: border-box;
  transition: height 100ms ease-out;
}

.composer-floating-card textarea::placeholder {
  color: #94a3b8;
  font-size: 12.5px;
}

.composer-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid #f1f5f9;
  min-width: 0;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: auto;
}

.key-tip {
  font-size: 11px;
  color: var(--text-muted, #94a3b8);
  font-weight: 500;
  white-space: nowrap;
}

.composer-send-circle {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 0;
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%);
  color: #ffffff;
  display: grid;
  place-items: center;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(79, 70, 229, 0.25);
  transition: all 200ms ease;
}

.composer-send-circle:hover:not(:disabled) {
  transform: scale(1.06) translateY(-1px);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.35);
}

.composer-send-circle.is-pausing {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  box-shadow: 0 3px 10px rgba(239, 68, 68, 0.3);
}

.composer-send-circle.is-pausing:hover:not(:disabled) {
  background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
  box-shadow: 0 4px 14px rgba(220, 38, 38, 0.4);
}

.composer-send-circle:disabled {
  background: #e2e8f0;
  color: #94a3b8;
  box-shadow: none;
  cursor: not-allowed;
}

.task-alert {
  margin: 8px 12px 0;
  padding: 10px 12px;
  display: grid;
  grid-template-columns: 18px 1fr;
  gap: 8px;
  border: 1px solid #fde68a;
  border-radius: 10px;
  background: #fffbeb;
}

.task-alert.failed {
  border-color: #fecdd3;
  background: #fff1f2;
}

.task-alert.stale {
  border-color: #fde68a;
  background: #fffbeb;
}

.task-alert strong { font-size: 12px; font-weight: 700; }
.task-alert p { margin: 2px 0 4px; font-size: 11px; color: #475569; }
.task-alert button { padding: 0; border: 0; background: transparent; color: var(--primary-600, #4f46e5); font-weight: 700; cursor: pointer; }

.file-pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: 12px;
  box-shadow: var(--shadow-sm, 0 2px 8px rgba(15, 23, 42, 0.03));
  overflow: hidden;
}

.file-toolbar {
  height: 48px;
  min-height: 48px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  flex-wrap: nowrap;
  white-space: nowrap;
  overflow: hidden;
}

.toolbar-title-box {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  white-space: nowrap;
  min-width: 0;
}

.toolbar-title-box span {
  font-size: 11px;
  color: var(--text-muted, #64748b);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.file-toolbar h2 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  flex-shrink: 0;
}

.file-toolbar h2 small {
  color: var(--primary-700, #4338ca);
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--primary-200, #c7d2fe);
  font-size: 10.5px;
  font-weight: 800;
  padding: 1px 6px;
  border-radius: var(--radius-pill, 999px);
  white-space: nowrap;
  flex-shrink: 0;
}

.file-actions {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 6px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow-x: auto;
  scrollbar-width: none;
}

.file-actions::-webkit-scrollbar {
  display: none;
}

.file-actions :deep(.el-button) {
  border-radius: var(--radius-pill, 999px) !important;
  font-weight: 600 !important;
  font-size: 12px !important;
  padding: 5px 10px !important;
  white-space: nowrap !important;
  flex-shrink: 0 !important;
}

.inline-error {
  padding: 8px 14px;
  color: #b91c1c;
  background: #fff1f2;
  border-bottom: 1px solid #fecdd3;
  font-size: 12px;
}

.nonblocking-progress {
  padding: 6px 16px;
  display: flex;
  justify-content: space-between;
  color: var(--primary-700, #4338ca);
  background: var(--primary-50, #eef2ff);
  border-bottom: 1px solid var(--primary-200, #c7d2fe);
  font-size: 11.5px;
  font-weight: 700;
}

.artifact-viewport {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 24px;
}

.ppt-layout {
  height: 100%;
  min-height: 460px;
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 16px;
}

.slide-list {
  min-height: 0;
  overflow-y: auto;
  padding-right: 6px;
}

.slide-preview {
  width: 100%;
  min-width: 0;
  display: grid;
  place-items: center;
  background: #f8fafc;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: 12px;
  padding: 18px;
  box-shadow: inset 0 1px 4px rgba(15, 23, 42, 0.02);
}

.template-drawer-head { width: 100%; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; }
.template-drawer-head span { display: block; margin-bottom: 4px; color: #4f46e5; font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.template-drawer-head h3 { margin: 0; color: #0f172a; font-size: 20px; font-weight: 800; line-height: 1.25; }
.template-drawer-head small { color: #64748b; font-size: 12.5px; font-weight: 600; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.template-drawer-body { min-height: 0; padding-top: 4px; }
.template-drawer-intro { margin: 0 0 18px; padding: 12px 16px; border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; color: #475569; font-size: 13.5px; line-height: 1.6; font-weight: 500; }
.template-card-title-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.template-card-title-row strong { color: #0f172a; font-size: 15px; font-weight: 800; line-height: 1.35; }
.template-card-title-row span { flex-shrink: 0; color: #4338ca; background: #eef2ff; border: 1px solid #c7d2fe; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; }
.template-card-meta > span { flex-shrink: 0; color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; }
.template-choice-card > p { min-height: 44px; margin: 6px 0 12px; color: #475569; font-size: 13px; line-height: 1.55; font-weight: 500; }
.template-card-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.template-card-meta small { overflow: hidden; color: #64748b; font-size: 11.5px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.palette-dots { display: flex; gap: 5px; }
.palette-dots i { width: 14px; height: 14px; border: 1.5px solid rgba(255, 255, 255, 0.9); box-shadow: 0 1px 4px rgba(15, 23, 42, 0.15); border-radius: 50%; }
.template-drawer-footer { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 16px; border-top: 1px solid #e2e8f0; }
.template-drawer-footer > div:first-child { min-width: 0; display: flex; flex-direction: column; gap: 2px; text-align: left; }
.template-drawer-footer strong { overflow: hidden; color: #0f172a; font-size: 15px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.template-drawer-footer span { color: #64748b; font-size: 12.5px; font-weight: 500; }
.template-drawer-footer > div:last-child { display: flex; flex-shrink: 0; gap: 10px; }
.template-drawer-footer :deep(.el-button) { border-radius: 999px !important; font-weight: 700 !important; }
.template-drawer-footer :deep(.el-button--primary) { background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important; border: 0 !important; box-shadow: 0 3px 12px rgba(79, 70, 229, 0.3) !important; padding: 9px 20px !important; font-size: 13.5px !important; }
.template-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.template-choice-card { min-width: 0; padding: 14px; border: 1.5px solid #e2e8f0; border-radius: 14px; background: #ffffff; cursor: pointer; outline: none; transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1); box-sizing: border-box; }
.template-choice-card:hover, .template-choice-card:focus-visible { border-color: #818cf8; transform: translateY(-2px); box-shadow: 0 8px 24px rgba(79, 70, 229, 0.12); }
.template-choice-card.selected { border-color: #4f46e5; box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.25), 0 8px 24px rgba(79, 70, 229, 0.14); background: #ffffff; }
.template-card-preview { pointer-events: none; margin: -6px -6px 12px; border-radius: 10px; overflow: hidden; border: 1px solid #f1f5f9; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04); }
.template-card-preview :deep(.slide-thumbnail-card) { padding: 0; border: 0; border-radius: 0; }
.template-card-meta small { overflow: hidden; color: #7a808a; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.palette-dots { display: flex; gap: 4px; }
.palette-dots i { width: 11px; height: 11px; border: 1px solid rgba(22, 26, 34, .14); border-radius: 50%; }
.template-drawer-footer { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 14px; border-top: 1px solid #d9dce3; }
.template-drawer-footer > div:first-child { min-width: 0; display: flex; flex-direction: column; gap: 3px; text-align: left; }
.template-drawer-footer strong { overflow: hidden; color: #161a22; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.template-drawer-footer span { color: #646b78; font-size: 10px; }
.template-drawer-footer > div:last-child { display: flex; flex-shrink: 0; gap: 8px; }

.editor {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px;
}

.editor textarea {
  flex: 1;
  resize: none;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: 12px;
  padding: 14px;
  font: 13.5px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
  outline: none;
}

.editor textarea:focus {
  border-color: var(--primary-500, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

.editor footer {
  padding-top: 10px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.editor footer :deep(.el-button) {
  border-radius: var(--radius-pill, 999px) !important;
}

.structured-editor {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #f4f4f5;
}

.structured-editor-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
}

.structured-editor footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid #cfd2d9;
  background: #ffffff;
}

.file-empty {
  flex: 1;
  display: grid;
  place-content: center;
  justify-items: start;
  max-width: 480px;
  margin: auto;
  padding: 24px;
}

.file-empty > span {
  color: var(--primary-600, #4f46e5);
  font-size: 48px;
  font-weight: 800;
}

.file-empty h3 {
  margin: 8px 0 4px;
  font-size: 20px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.file-empty p {
  color: var(--text-muted, #64748b);
  line-height: 1.5;
  font-size: 13px;
}

.mobile-pane-switch { display: none; }

.expand-fade-enter-active, .expand-fade-leave-active {
  transition: all 200ms ease;
}

.expand-fade-enter-from, .expand-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (max-width: 900px) {
  .task-workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    position: relative;
  }
  .mobile-pane-switch { display: grid; grid-template-columns: 1fr 1fr; border-bottom: 1px solid #e2e8f0; }
  .mobile-pane-switch button { height: 38px; border: 0; background: #ffffff; font-weight: 700; }
  .mobile-pane-switch button.active { background: var(--primary-600, #4f46e5); color: #ffffff; }
  .mobile-hidden { display: none; }
  .agent-pane, .file-pane { width: 100% !important; min-width: 0; min-height: 0; grid-row: 2; }
  .file-toolbar { align-items: flex-start; }
  .file-actions { max-width: 240px; }
  .ppt-layout { grid-template-columns: 120px minmax(0, 1fr); }
}

@media (max-width: 600px) {
  .file-toolbar { padding: 10px 12px; }
  .file-actions .el-button:nth-child(2), .file-actions .el-button:nth-child(3) { display: none; }
  .artifact-viewport { padding: 12px; }
  .ppt-layout { grid-template-columns: 1fr; }
  .slide-list { display: flex; overflow-x: auto; }
  .slide-preview { min-height: 300px; padding: 8px; }
  .template-card-grid { grid-template-columns: 1fr; }
  .template-drawer-footer { align-items: stretch; flex-direction: column; }
  .template-drawer-footer > div:last-child { justify-content: flex-end; }
}
</style>
