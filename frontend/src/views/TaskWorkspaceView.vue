<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { CircleCheck, Clock, Edit, Lock, Promotion, RefreshRight, Warning } from '@element-plus/icons-vue';
import { api, errorMessage } from '../api/client';
import { useProjectStore } from '../stores/project';
import type { Artifact } from '../types';
import ProjectShell from '../components/project/ProjectShell.vue';
import ModelSelector from '../components/agent/ModelSelector.vue';
import MarkdownRenderer from '../components/content-renderers/MarkdownRenderer.vue';
import SlidePreview from '../components/domain/SlidePreview.vue';
import SlideThumbnail from '../components/domain/SlideThumbnail.vue';
import VersionSelector from '../components/domain/VersionSelector.vue';

const route = useRoute();
const store = useProjectStore();
const courseId = route.params.id as string;
const taskType = computed(() => route.params.taskType as string);
const input = ref('');
const sending = ref(false);
const error = ref('');
const selectedSlide = ref(0);
const mobilePane = ref<'agent' | 'file'>('agent');
const versions = ref<Artifact[]>([]);
const showVersions = ref(false);
const editing = ref(false);
const draftMarkdown = ref('');
const chatViewport = ref<HTMLElement | null>(null);

const task = computed(() => store.currentTask);
const artifact = computed(() => task.value?.current_artifact || null);
const isRunning = computed(() => ['queued', 'running'].includes(task.value?.status || ''));

async function load() {
  error.value = '';
  selectedSlide.value = 0;
  try {
    await store.openTask(courseId, taskType.value);
    await nextTick();
    if (chatViewport.value) chatViewport.value.scrollTop = chatViewport.value.scrollHeight;
  } catch (cause) {
    error.value = errorMessage(cause);
  }
}

async function send() {
  const content = input.value.trim();
  if (!content || sending.value) return;
  sending.value = true;
  error.value = '';
  input.value = '';
  try {
    await store.sendMessage(courseId, taskType.value, content);
    await nextTick();
    if (chatViewport.value) chatViewport.value.scrollTop = chatViewport.value.scrollHeight;
  } catch (cause) {
    input.value = content;
    error.value = errorMessage(cause);
  } finally {
    sending.value = false;
  }
}

async function run(action: 'initial' | 'retry' | 'sync_dependencies') {
  error.value = '';
  try {
    await store.runTask(courseId, taskType.value, action);
  } catch (cause) {
    error.value = errorMessage(cause);
  }
}

async function approve() {
  try { await store.approveTask(courseId, taskType.value); }
  catch (cause) { error.value = errorMessage(cause); }
}

async function setModel(id: string) {
  try { await store.setTaskModel(courseId, taskType.value, id); }
  catch (cause) { error.value = errorMessage(cause); }
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

function beginEdit() {
  draftMarkdown.value = artifact.value?.content_markdown || '';
  editing.value = true;
}

function prepareSlideRevision(index: number) {
  input.value = `请重新设计第 ${index + 1} 页，保留课程目标并优化信息层级与视觉表达。`;
  mobilePane.value = 'agent';
}

async function saveEdit() {
  if (!artifact.value) return;
  try {
    const { data } = await api.patch<Artifact>(`/artifacts/${artifact.value.id}`, {
      content_json: artifact.value.content_json,
      content_markdown: draftMarkdown.value,
      change_summary: '教师在线编辑',
    });
    if (task.value) task.value.current_artifact = data;
    editing.value = false;
    await store.refreshTasks();
  } catch (cause) { error.value = errorMessage(cause); }
}

watch(taskType, load);
watch(() => artifact.value?.id, () => { mobilePane.value = 'file'; });
onMounted(load);
onUnmounted(() => store.disconnect());
</script>

<template>
  <div v-if="store.loading && !store.project" class="task-loading"><el-skeleton :rows="8" animated /></div>
  <ProjectShell v-else-if="store.project" :active-type="taskType">
    <div v-if="task" class="task-workspace">
      <div class="mobile-pane-switch" role="tablist">
        <button :class="{ active: mobilePane === 'agent' }" @click="mobilePane = 'agent'">Agent 对话</button>
        <button :class="{ active: mobilePane === 'file' }" @click="mobilePane = 'file'">任务文件</button>
      </div>

      <aside class="agent-pane" :class="{ 'mobile-hidden': mobilePane !== 'agent' }">
        <header class="agent-header">
          <div class="agent-folio">{{ String(task.display_order).padStart(2, '0') }}</div>
          <div><h2>{{ task.agent_name }}</h2><p>只负责{{ task.display_name }}的生成、修改与版本维护</p></div>
        </header>

        <div v-if="task.status === 'failed'" class="task-alert failed">
          <el-icon><Warning /></el-icon><div><strong>本次任务失败</strong><p>{{ task.error?.message }}</p><button @click="run('retry')">重试任务</button></div>
        </div>
        <div v-else-if="task.status === 'stale'" class="task-alert stale">
          <el-icon><RefreshRight /></el-icon><div><strong>上游任务已有新版本</strong><p>当前文件仍然保留。确认后将基于最新上游内容生成下一版。</p><button @click="run('sync_dependencies')">同步最新内容</button></div>
        </div>

        <div ref="chatViewport" class="chat-viewport">
          <div class="agent-introduction">
            <strong>{{ task.agent_name }}</strong>
            <p v-if="artifact">当前正在维护 {{ task.display_name }} V{{ artifact.version }}。告诉我需要调整的内容，我会保留旧版本并生成新版本。</p>
            <p v-else>任务文件正在按依赖生成。完成后即可在这里继续修改。</p>
          </div>
          <article v-for="message in task.messages || []" :key="message.id" class="message" :class="message.role">
            <span>{{ message.role === 'user' ? '教师' : task.agent_name }}</span>
            <p>{{ message.content }}</p>
            <small v-if="message.status === 'pending'">等待 Agent 处理</small>
            <small v-else-if="message.status === 'failed'">本次修改未完成</small>
          </article>
          <div v-if="isRunning" class="agent-running"><i /><span>{{ task.status === 'queued' ? 'Agent 已进入队列' : `正在生成并校验新版本 · ${task.progress}%` }}</span></div>
        </div>

        <form class="composer" @submit.prevent="send">
          <ModelSelector
            :model-value="task.model_config_id || null"
            compact
            label=""
            :disabled="isRunning"
            @change="setModel"
          />
          <el-input v-model="input" type="textarea" :rows="3" :disabled="isRunning || !artifact" :placeholder="artifact ? `描述你希望如何修改${task.display_name}` : '任务文件生成后可继续对话修改'" />
          <div class="composer-actions"><span>Enter 发送，Shift+Enter 换行</span><el-button type="primary" native-type="submit" :icon="Promotion" :disabled="!input.trim() || isRunning || !artifact">发送修改</el-button></div>
        </form>
      </aside>

      <main class="file-pane" :class="{ 'mobile-hidden': mobilePane !== 'file' }">
        <header class="file-toolbar">
          <div><span>当前任务文件</span><h2>{{ task.display_name }}<small v-if="artifact">V{{ artifact.version }}</small></h2></div>
          <div v-if="artifact" class="file-actions">
            <el-button :icon="Clock" @click="loadVersions">版本历史</el-button>
            <el-button :icon="Lock" :disabled="artifact.is_locked" @click="lockArtifact">{{ artifact.is_locked ? '已锁定' : '锁定文件' }}</el-button>
            <el-button :icon="Edit" :disabled="artifact.is_locked" @click="beginEdit">编辑</el-button>
            <el-button type="primary" :icon="CircleCheck" :disabled="task.status === 'approved'" @click="approve">{{ task.status === 'approved' ? '已确认' : '确认文件' }}</el-button>
          </div>
        </header>

        <div v-if="error" class="inline-error">{{ error }}</div>
        <div v-if="isRunning && artifact" class="nonblocking-progress"><span>{{ task.status === 'queued' ? 'Agent 已排队' : 'Agent 正在生成新版本' }}</span><strong>{{ task.progress }}%</strong></div>

        <div v-if="editing" class="editor">
          <textarea v-model="draftMarkdown" spellcheck="false" />
          <footer><el-button @click="editing = false">取消</el-button><el-button type="primary" @click="saveEdit">保存为新版本</el-button></footer>
        </div>
        <div v-else-if="artifact" class="artifact-viewport" :class="{ updated: artifact.id }">
          <div v-if="taskType === 'ppt' && artifact.content_json?.slides" class="ppt-layout">
            <div class="slide-list">
              <SlideThumbnail v-for="(slide, index) in artifact.content_json.slides" :key="slide.id || index" :slide="slide" :index="index" :is-active="selectedSlide === index" @select="selectedSlide = $event" />
            </div>
            <div class="slide-preview"><SlidePreview :slide="artifact.content_json.slides[selectedSlide]" :slide-index="selectedSlide" :total-slides="artifact.content_json.slides.length" @regenerate-slide="prepareSlideRevision" /></div>
          </div>
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
    <VersionSelector v-if="showVersions" :versions="versions" :current-version="artifact?.version" @select="selectVersion" @close="showVersions = false" />
  </ProjectShell>
</template>

<style scoped>
.task-loading { padding: 32px; }
.task-workspace { height: 100%; min-height: 0; display: grid; grid-template-columns: 360px minmax(0,1fr); background: #fff; }
.agent-pane { min-height: 0; display: flex; flex-direction: column; border-right: 1px solid #cfd2d9; background: #f7f7f8; }
.agent-header { min-height: 78px; padding: 14px 18px; display: grid; grid-template-columns: 46px 1fr; align-items: center; gap: 12px; border-bottom: 1px solid #cfd2d9; background: #fff; }
.agent-folio { color: #002fa7; font-size: 28px; font-weight: 800; font-variant-numeric: tabular-nums; }
.agent-header h2 { margin: 0; font-size: 17px; }.agent-header p { margin: 4px 0 0; color: #656a73; font-size: 11px; }
.chat-viewport { flex: 1; min-height: 0; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.agent-introduction, .message { padding: 12px 14px; border: 1px solid #cfd2d9; background: #fff; }
.agent-introduction { border-left: 3px solid #002fa7; }.agent-introduction strong, .message span { font-size: 12px; color: #002fa7; }.agent-introduction p, .message p { margin: 6px 0 0; font-size: 13px; line-height: 1.55; white-space: pre-wrap; }
.message.user { margin-left: 34px; background: #002fa7; color: #fff; border-color: #002fa7; }.message.user span, .message.user small { color: rgba(255,255,255,.78); }.message small { display: block; margin-top: 6px; color: #656a73; }
.agent-running { display: flex; align-items: center; gap: 8px; padding: 10px 12px; font-size: 12px; color: #51545b; }.agent-running i { width: 7px; height: 7px; background: #002fa7; border-radius: 50%; animation: pulse 1.2s ease infinite; }
@keyframes pulse { 50% { opacity: .3; } }
.composer { padding: 12px; border-top: 1px solid #cfd2d9; background: #fff; display: grid; gap: 8px; }.composer-actions { display:flex; align-items:center; justify-content:space-between; gap:10px; }.composer-actions span { font-size: 10px; color:#777b84; }
.task-alert { margin: 12px 12px 0; padding: 12px; display:grid; grid-template-columns:20px 1fr; gap:8px; border:1px solid #d0d3da; background:#fff; }.task-alert.failed { border-left:3px solid #b42318; }.task-alert.stale { border-left:3px solid #9a6700; }.task-alert strong { font-size:12px; }.task-alert p { margin:3px 0 6px; font-size:11px; color:#656a73; }.task-alert button { padding:0; border:0; background:transparent; color:#002fa7; font-weight:700; cursor:pointer; }
.file-pane { min-width: 0; min-height: 0; display:flex; flex-direction:column; background:#fff; }.file-toolbar { min-height:78px; padding:12px 20px; display:flex; align-items:center; justify-content:space-between; gap:20px; border-bottom:1px solid #cfd2d9; }.file-toolbar span { font-size:11px; color:#656a73; }.file-toolbar h2 { margin:3px 0 0; font-size:19px; }.file-toolbar h2 small { margin-left:8px; color:#002fa7; font-size:11px; }.file-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }
.inline-error { padding:10px 16px; color:#b42318; background:#fff5f4; border-bottom:1px solid #f0c8c4; font-size:12px; }.nonblocking-progress { padding:8px 16px; display:flex; justify-content:space-between; color:#002fa7; background:#f2f5ff; border-bottom:1px solid #c5d1f0; font-size:12px; }
.artifact-viewport { flex:1; min-height:0; overflow:auto; padding:24px clamp(20px,4vw,60px); }.ppt-layout { height:100%; min-height:460px; display:grid; grid-template-columns:170px minmax(0,1fr); gap:20px; }.slide-list { min-height:0; overflow-y:auto; padding-right:6px; }.slide-preview { min-width:0; display:grid; place-items:center; background:#f7f7f8; border:1px solid #cfd2d9; padding:24px; }
.editor { flex:1; min-height:0; display:flex; flex-direction:column; padding:18px; }.editor textarea { flex:1; resize:none; border:1px solid #cfd2d9; padding:16px; font:14px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; }.editor footer { padding-top:10px; display:flex; justify-content:flex-end; gap:8px; }
.file-empty { flex:1; display:grid; place-content:center; justify-items:start; max-width:520px; margin:auto; padding:30px; }.file-empty > span { color:#002fa7; font-size:54px; font-weight:800; }.file-empty h3 { margin:10px 0 4px; font-size:24px; }.file-empty p { color:#656a73; line-height:1.6; }
.mobile-pane-switch { display:none; }
@media (max-width: 900px) { .task-workspace { grid-template-columns:1fr; position:relative; }.mobile-pane-switch { display:grid; grid-template-columns:1fr 1fr; border-bottom:1px solid #cfd2d9; }.mobile-pane-switch button { height:38px; border:0; background:#fff; }.mobile-pane-switch button.active { background:#002fa7; color:#fff; }.mobile-hidden { display:none; }.agent-pane,.file-pane { min-height:0; }.file-toolbar { align-items:flex-start; }.file-actions { max-width:260px; }.ppt-layout { grid-template-columns:120px minmax(0,1fr); } }
@media (max-width: 600px) { .file-toolbar { padding:10px 12px; }.file-actions .el-button:nth-child(2),.file-actions .el-button:nth-child(3) { display:none; }.artifact-viewport { padding:14px; }.ppt-layout { grid-template-columns:1fr; }.slide-list { display:flex; overflow-x:auto; }.slide-preview { min-height:320px; padding:10px; } }
</style>
