<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { 
  ArrowLeft, 
  Check, 
  CircleCheck, 
  Clock, 
  CollectionTag, 
  Cpu, 
  Film, 
  Lock, 
  MagicStick, 
  Money, 
  Promotion, 
  VideoCamera, 
  VideoPause, 
  Warning 
} from '@element-plus/icons-vue';
import { api, errorMessage } from '../api/client';
import { videoProjectsApi } from '../api/videoProjects';
import { useProjectStore } from '../stores/project';
import type { Artifact, VideoAgentPendingAction, VideoGenerationContent, VideoGenerationScene, VideoProjectSummary } from '../types';
import ModelSelector from '../components/agent/ModelSelector.vue';
import VideoGenerationPreview from '../components/domain/VideoGenerationPreview.vue';
import VideoGenerationEditor from '../components/domain/VideoGenerationEditor.vue';
import VersionSelector from '../components/domain/VersionSelector.vue';

const route = useRoute();
const router = useRouter();
const store = useProjectStore();
const courseId = computed(() => String(route.params.courseId));
const summary = ref<VideoProjectSummary | null>(null);
const loading = ref(true);
const error = ref('');
const input = ref('');
const sending = ref(false);
const resolving = ref(false);
const pendingAction = ref<VideoAgentPendingAction | null>(null);
const selectedSceneId = ref('');
const editing = ref(false);
const regenerating = ref(false);
const versions = ref<Artifact[]>([]);
const showVersions = ref(false);
const mobilePane = ref<'agent' | 'video'>('agent');
const chatViewport = ref<HTMLElement | null>(null);
let refreshTimer: number | undefined;

const task = computed(() => store.currentTask?.task_type === 'video_generation' ? store.currentTask : null);
const artifact = computed(() => task.value?.current_artifact || null);
const content = computed(() => artifact.value?.content_json?.schema_version === '3.0' ? artifact.value.content_json as VideoGenerationContent : null);
const messages = computed(() => task.value?.messages || []);
const isRunning = computed(() => ['queued', 'running'].includes(task.value?.status || ''));
const sourceLabels = computed(() => {
  const values = Object.keys(task.value?.available_sources || {});
  const labels: Record<string, string> = { 
    lesson_plan: '教学设计', 
    ppt: 'PPT', 
    task_sheet: '任务单', 
    exercise: '练习', 
    video_script: '视频脚本', 
    verbatim: '逐字稿' 
  };
  return values.map(item => labels[item] || item);
});

async function load(silent = false) {
  if (!silent) loading.value = true;
  error.value = '';
  try {
    const [, snapshot] = await Promise.all([
      store.openTask(courseId.value, 'video_generation'),
      videoProjectsApi.get(courseId.value),
    ]);
    summary.value = snapshot.summary;
    pendingAction.value = snapshot.pending_action || null;
    await nextTick();
    if (chatViewport.value) chatViewport.value.scrollTop = chatViewport.value.scrollHeight;
  } catch (cause) {
    error.value = errorMessage(cause);
  } finally {
    loading.value = false;
  }
}

async function send(text?: string) {
  const contentValue = (text ?? input.value).trim();
  if (!contentValue || sending.value) return;
  sending.value = true;
  error.value = '';
  if (!text) input.value = '';
  try {
    const result = await videoProjectsApi.message(courseId.value, contentValue, selectedSceneId.value ? [selectedSceneId.value] : []);
    pendingAction.value = result.pending_action;
    await load(true);
    mobilePane.value = 'agent';
  } catch (cause) {
    if (!text) input.value = contentValue;
    error.value = errorMessage(cause);
  } finally {
    sending.value = false;
  }
}

async function resolvePending(choice: 'confirm' | 'cancel') {
  if (!pendingAction.value || resolving.value) return;
  resolving.value = true;
  try {
    await videoProjectsApi.resolveAction(courseId.value, pendingAction.value.request_id, choice);
    pendingAction.value = null;
    ElMessage.success(choice === 'confirm' ? '视频任务已提交' : '已取消本次操作');
    await load(true);
  } catch (cause) {
    error.value = errorMessage(cause);
    if ((cause as any)?.response?.status === 409) pendingAction.value = null;
  } finally {
    resolving.value = false;
  }
}

async function setVideoModel(id: string) {
  try {
    await api.patch(`/courses/${courseId.value}/tasks/video_generation/model`, { video_model_config_id: id });
    await load(true);
  } catch (cause) { error.value = errorMessage(cause); }
}

async function cancelRun() {
  try { 
    await store.cancelTask(courseId.value, 'video_generation'); 
    await load(true); 
  } catch (cause) { 
    error.value = errorMessage(cause); 
  }
}

async function approve() {
  try { 
    await store.approveTask(courseId.value, 'video_generation'); 
    ElMessage.success('视频已确认交付'); 
    await load(true); 
  } catch (cause) { 
    error.value = errorMessage(cause); 
  }
}

async function lockArtifact() {
  if (!artifact.value) return;
  try { 
    await api.post(`/artifacts/${artifact.value.id}/lock`, { json_path: '$' }); 
    artifact.value.is_locked = true; 
    ElMessage.success('视频已锁定');
  } catch (cause) { 
    error.value = errorMessage(cause); 
  }
}

async function loadVersions() {
  if (!artifact.value) return;
  try { 
    const { data } = await api.get<Artifact[]>(`/artifacts/${artifact.value.id}/versions`); 
    versions.value = data; 
    showVersions.value = true; 
  } catch (cause) { 
    error.value = errorMessage(cause); 
  }
}

async function restoreVersion(version: Artifact) {
  try {
    await ElMessageBox.confirm(`确定基于 V${version.version} 创建新的当前版本吗？`, '恢复历史版本', { type: 'warning' });
    const { data } = await api.post<Artifact>(`/artifacts/${version.id}/restore`);
    store.acceptCurrentArtifact(data, 'refresh'); 
    showVersions.value = false; 
    await load(true);
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') error.value = errorMessage(cause);
  }
}

function editScene(scene: VideoGenerationScene) {
  selectedSceneId.value = scene.id;
  editing.value = true;
  mobilePane.value = 'video';
}

async function regenerateScene(sceneId: string, payload: Record<string, unknown>) {
  regenerating.value = true;
  try {
    const quote = (await api.post(`/courses/${courseId.value}/tasks/video_generation/quotes`, {
      target_scene_id: content.value?.scenes.find(item => item.id === sceneId)?.script_scene_id || sceneId,
      ...payload,
    })).data;
    await ElMessageBox.confirm(
      `将重新生成 ${quote.scene_count} 个片段，预计费用 ¥${(quote.maximum_cost_fen / 100).toFixed(2)}。`,
      '确认视频生成',
      { type: 'warning', confirmButtonText: '确认并生成', cancelButtonText: '取消' },
    );
    await api.post(`/courses/${courseId.value}/tasks/video_generation/scenes/${sceneId}/regenerate`, {
      ...payload, quote_id: quote.quote_id, approved_max_cost_fen: quote.maximum_cost_fen,
    });
    editing.value = false;
    await load(true);
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') error.value = errorMessage(cause);
  } finally { regenerating.value = false; }
}

function onKeydown(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === 'Enter' && !event.shiftKey) { 
    event.preventDefault(); 
    send(); 
  }
}

onMounted(() => {
  load();
  refreshTimer = window.setInterval(() => { if (!document.hidden && isRunning.value) load(true); }, 5000);
});
onUnmounted(() => { 
  window.clearInterval(refreshTimer); 
  store.stopActiveTaskPolling(); 
  store.disconnect(); 
});
</script>

<template>
  <div class="video-workspace-page">
    <!-- Top Workspace Navigation Bar -->
    <header class="workspace-header">
      <div class="header-left">
        <button type="button" class="btn-back" @click="router.push('/videos')">
          <el-icon><ArrowLeft /></el-icon>
          <span>视频中心</span>
        </button>
        <div v-if="summary" class="project-info-group">
          <h1 class="project-title">{{ summary.course.title }}</h1>
          <div class="project-meta-pills">
            <span class="meta-pill">{{ summary.course.subject }}</span>
            <span class="meta-pill">{{ summary.course.grade_level }}</span>
            <span class="meta-pill"><el-icon><Clock /></el-icon> {{ summary.course.duration_minutes }} 分钟</span>
          </div>
        </div>
      </div>

      <div class="header-actions">
        <span class="badge-memory">
          <el-icon><CollectionTag /></el-icon>
          <span>项目记忆 V{{ summary?.memory_revision || 0 }}</span>
        </span>
        <span class="badge-sync">
          <span class="sync-dot"></span>
          <span>实时同步</span>
        </span>
        <el-button v-if="artifact" size="small" class="btn-tool" @click="loadVersions">
          版本历史
        </el-button>
        <el-button 
          v-if="artifact && !artifact.is_locked" 
          size="small" 
          class="btn-tool" 
          :icon="Lock" 
          @click="lockArtifact"
        >
          锁定视频
        </el-button>
        <el-button 
          v-if="artifact && task?.status === 'review'" 
          size="small" 
          type="primary" 
          class="btn-confirm" 
          @click="approve"
        >
          确认交付
        </el-button>
      </div>
    </header>

    <!-- Loading / Error States -->
    <div v-if="loading && !task" class="workspace-state-box">
      <el-skeleton :rows="10" animated />
    </div>
    <div v-else-if="error && !task" class="workspace-state-box">
      <el-alert type="error" :title="error" show-icon :closable="false">
        <template #default>
          <el-button size="small" @click="load()">重新加载</el-button>
        </template>
      </el-alert>
    </div>

    <!-- Main Workspace Split Grid -->
    <template v-else>
      <div class="mobile-tabs-bar">
        <button :class="{ active: mobilePane === 'agent' }" @click="mobilePane = 'agent'">
          <el-icon><VideoCamera /></el-icon> 视频 Agent
        </button>
        <button :class="{ active: mobilePane === 'video' }" @click="mobilePane = 'video'">
          <el-icon><Film /></el-icon> 视频预览
        </button>
      </div>

      <main class="workspace-main-grid">
        <!-- Left Column: Video Agent Co-Pilot -->
        <section class="agent-pane" :class="{ 'mobile-hidden': mobilePane !== 'agent' }">
          <!-- Agent Header -->
          <header class="agent-header">
            <div class="agent-avatar">
              <el-icon><VideoCamera /></el-icon>
            </div>
            <div class="agent-title-info">
              <h2>视频生成 Agent</h2>
              <p>使用最新项目记忆 V{{ task?.last_context_revision || summary?.memory_revision || 0 }}</p>
            </div>
            <div class="agent-status-badge">
              <span class="live-dot"></span>
              <span>在线</span>
            </div>
          </header>

          <!-- Source Knowledge Strip -->
          <div class="source-strip">
            <span class="source-title">已读取知识</span>
            <div class="source-pills">
              <span v-for="label in sourceLabels" :key="label" class="source-pill">
                {{ label }}
              </span>
              <span v-if="!sourceLabels.length" class="source-pill">
                项目蓝图与视频脚本
              </span>
            </div>
          </div>

          <!-- Chat Stream -->
          <div ref="chatViewport" class="chat-viewport">
            <div v-if="!messages.length" class="agent-welcome-card">
              <div class="welcome-icon">
                <el-icon><MagicStick /></el-icon>
              </div>
              <h3>告诉我你想怎样生成或调整视频</h3>
              <p>视频 Agent 会结合教学设计、逐字稿与分镜脚本进行全流程视频生成。涉及生成费用时会在执行前向您请求确认。</p>
            </div>

            <!-- Messages Stream -->
            <article 
              v-for="message in messages" 
              :key="message.id" 
              class="chat-bubble-wrap" 
              :class="message.role"
            >
              <div class="bubble-sender-meta">
                <span class="sender-name">{{ message.role === 'user' ? '你' : '视频 Agent' }}</span>
              </div>
              <div class="bubble-content">
                <p>{{ message.content }}</p>
              </div>
            </article>

            <!-- Pending Action Confirmation Card -->
            <article v-if="pendingAction" class="action-confirm-card">
              <div class="confirm-header">
                <div class="confirm-badge">
                  <el-icon><Money /></el-icon>
                  <span>生成费用与规格确认</span>
                </div>
                <h3>{{ pendingAction.intent === 'recompose' ? '重新合成现有片段' : `准备生成 ${pendingAction.quote?.scene_count || 0} 个视频片段` }}</h3>
              </div>

              <div v-if="pendingAction.quote" class="quote-details-grid">
                <div class="quote-cell">
                  <span class="cell-label">视频模型</span>
                  <span class="cell-val">{{ pendingAction.quote.model_name }}</span>
                </div>
                <div class="quote-cell">
                  <span class="cell-label">画质规格</span>
                  <span class="cell-val">{{ pendingAction.quote.resolution }}</span>
                </div>
                <div class="quote-cell cost">
                  <span class="cell-label">预计费用</span>
                  <span class="cell-val price">¥{{ (pendingAction.quote.maximum_cost_fen / 100).toFixed(2) }}</span>
                </div>
              </div>

              <div class="confirm-actions">
                <el-button :disabled="resolving" @click="resolvePending('cancel')">取消</el-button>
                <el-button type="primary" :loading="resolving" @click="resolvePending('confirm')">确认并执行生成</el-button>
              </div>
            </article>
          </div>

          <!-- Inline Error -->
          <div v-if="error" class="inline-error-banner">
            <el-icon><Warning /></el-icon>
            <span>{{ error }}</span>
          </div>

          <!-- Quick Action Prompts -->
          <div class="quick-prompts-bar">
            <button class="btn-prompt-chip" @click="send('帮我说明当前视频生成状态和下一步建议')">
              💡 说明当前状态
            </button>
            <button class="btn-prompt-chip primary" @click="send('帮我生成视频')">
              🚀 生成整片
            </button>
            <button v-if="content" class="btn-prompt-chip" @click="send('请检查现有片段的连续性并给出调整建议')">
              🔍 检查连续性
            </button>
          </div>

          <!-- Composer Form -->
          <div class="composer-area">
            <div class="composer-box">
              <textarea 
                v-model="input" 
                :disabled="sending" 
                placeholder="描述要生成或调整的视频内容… (Enter 发送, Shift+Enter 换行)" 
                rows="2"
                @keydown="onKeydown" 
              />
              <div class="composer-actions">
                <span class="composer-hint">Enter 发送</span>
                <button 
                  type="button" 
                  class="btn-send" 
                  :disabled="!input.trim() || sending" 
                  @click="send()"
                >
                  <el-icon><Promotion /></el-icon>
                </button>
              </div>
            </div>
          </div>
        </section>

        <!-- Right Column: Video Preview Stage -->
        <section class="video-pane" :class="{ 'mobile-hidden': mobilePane !== 'video' }">
          <!-- File Stage Toolbar -->
          <header class="stage-toolbar">
            <div class="stage-version-chip">
              <span class="label">当前视频</span>
              <span class="val">{{ artifact ? `V${artifact.version}` : '尚未生成' }}</span>
            </div>

            <div class="model-selector-wrap">
              <ModelSelector 
                :model-value="task?.video_model_config_id" 
                capability="video_generation" 
                label="视频模型" 
                wide 
                :disabled="isRunning" 
                @change="setVideoModel" 
              />
            </div>

            <el-button 
              v-if="isRunning" 
              type="danger" 
              plain 
              size="small" 
              :icon="VideoPause" 
              @click="cancelRun"
            >
              停止生成
            </el-button>
          </header>

          <!-- Stage Body -->
          <div class="stage-viewport">
            <VideoGenerationEditor 
              v-if="editing && content" 
              :content="content" 
              :selected-scene-id="selectedSceneId" 
              :busy="regenerating" 
              @close="editing = false" 
              @regenerate="regenerateScene" 
            />

            <VideoGenerationPreview 
              v-else-if="content && artifact" 
              :content="content" 
              :version="artifact.version" 
              :disabled="isRunning || artifact.is_locked" 
              @edit="editScene" 
              @recompose="send('请重新合成现有视频片段')" 
            />

            <!-- Empty / Ready to Generate State -->
            <div v-else class="stage-ready-card">
              <div class="ready-icon-halo">
                <el-icon><VideoCamera /></el-icon>
              </div>
              <h2>{{ summary?.status === 'not_ready' ? '视频脚本尚未就绪' : isRunning ? '视频正在生成中' : '准备开始生成微课视频' }}</h2>
              <p v-if="summary?.status === 'not_ready'">
                微课视频需要基于结构化的分镜脚本生成。请先前往视频脚本工作台完成脚本设计。
              </p>
              <p v-else-if="isRunning">
                Agent 正在并发渲染视频分镜并同步原生音轨，已完成 {{ task?.progress || 0 }}%，请稍候。
              </p>
              <p v-else>
                系统将使用分镜脚本 V{{ summary?.script?.version || '—' }} 与项目记忆 V{{ summary?.memory_revision || 0 }} 进行高保真视频合成。
              </p>

              <div class="ready-cta-group">
                <el-button 
                  v-if="summary?.status === 'not_ready'" 
                  type="primary" 
                  @click="router.push(`/courses/${courseId}/tasks/video_script`)"
                >
                  前往视频脚本
                </el-button>
                <el-button 
                  v-else-if="!isRunning" 
                  type="primary" 
                  :icon="VideoCamera" 
                  @click="send('帮我生成视频'); mobilePane = 'agent'"
                >
                  让 Agent 准备生成
                </el-button>
              </div>
            </div>
          </div>
        </section>
      </main>
    </template>

    <!-- Version Selector Drawer / Modal -->
    <VersionSelector 
      v-if="showVersions" 
      :versions="versions" 
      :current-version="artifact?.version" 
      allow-restore 
      @close="showVersions = false" 
      @restore="restoreVersion" 
    />
  </div>
</template>

<style scoped>
.video-workspace-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: var(--bg-page, #f5f7fa);
  color: var(--text-primary, #0f172a);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

/* 1. Header Toolbar */
.workspace-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 20px;
  background: var(--surface-primary, #ffffff);
  border-bottom: 1px solid var(--border-default, #e2e8f0);
  flex-shrink: 0;
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.btn-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-pill, 999px);
  color: var(--text-secondary, #475569);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-back:hover {
  background: var(--primary-50, #eef2ff);
  color: var(--primary-600, #4f46e5);
  border-color: var(--color-primary-border, #c7d2fe);
}

.project-info-group {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding-left: 12px;
  border-left: 1px solid #e2e8f0;
}

.project-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 380px;
}

.project-meta-pills {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meta-pill {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted, #64748b);
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.badge-memory {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--primary-600, #4f46e5);
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--color-primary-border, #c7d2fe);
  padding: 3px 10px;
  border-radius: var(--radius-pill, 999px);
}

.badge-sync {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 3px 10px;
  border-radius: var(--radius-pill, 999px);
}

.sync-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #059669;
  animation: pulse-sync 2s infinite ease-in-out;
}

@keyframes pulse-sync {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.3); }
}

.btn-tool {
  border-radius: var(--radius-pill, 999px) !important;
}

.btn-confirm {
  border-radius: var(--radius-pill, 999px) !important;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%) !important;
  border: none !important;
}

/* 2. Main Grid Split */
.workspace-main-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(360px, 34%) minmax(0, 1fr);
  background: var(--surface-primary, #ffffff);
}

/* Left Pane: Agent */
.agent-pane {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-default, #e2e8f0);
  background: #ffffff;
  min-height: 0;
}

.agent-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid #f1f5f9;
}

.agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  display: grid;
  place-items: center;
  font-size: 18px;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.25);
}

.agent-title-info h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.agent-title-info p {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--text-muted, #64748b);
}

.agent-status-badge {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 700;
  color: #059669;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #059669;
}

.source-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  overflow-x: auto;
}

.source-title {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  white-space: nowrap;
}

.source-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
}

.source-pill {
  font-size: 10.5px;
  font-weight: 700;
  color: #334155;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.chat-viewport {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.agent-welcome-card {
  background: #f8faff;
  border: 1.5px dashed var(--color-primary-border, #c7d2fe);
  border-radius: var(--radius-card, 16px);
  padding: 24px 20px;
  text-align: center;
}

.welcome-icon {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--primary-50, #eef2ff);
  color: var(--primary-600, #4f46e5);
  font-size: 22px;
  display: grid;
  place-items: center;
  margin: 0 auto 12px;
}

.agent-welcome-card h3 {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.agent-welcome-card p {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary, #475569);
  line-height: 1.6;
}

.chat-bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 88%;
}

.chat-bubble-wrap.user {
  align-self: flex-end;
}

.chat-bubble-wrap.assistant,
.chat-bubble-wrap.agent {
  align-self: flex-start;
}

.bubble-sender-meta {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  padding: 0 4px;
}

.chat-bubble-wrap.user .bubble-sender-meta {
  text-align: right;
  color: var(--primary-600, #4f46e5);
}

.bubble-content {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.chat-bubble-wrap.user .bubble-content {
  background: var(--primary-50, #eef2ff);
  color: var(--primary-700, #4338ca);
  border: 1px solid var(--color-primary-border, #c7d2fe);
  border-top-right-radius: 4px;
}

.chat-bubble-wrap.assistant .bubble-content,
.chat-bubble-wrap.agent .bubble-content {
  background: #f8fafc;
  color: var(--text-primary, #0f172a);
  border: 1px solid #e2e8f0;
  border-top-left-radius: 4px;
}

.bubble-content p {
  margin: 0;
}

/* Pending Confirmation Card */
.action-confirm-card {
  background: #ffffff;
  border: 1.5px solid var(--primary-500, #6366f1);
  border-radius: var(--radius-card, 16px);
  padding: 16px 18px;
  box-shadow: 0 6px 20px rgba(79, 70, 229, 0.12);
}

.confirm-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 800;
  color: var(--primary-600, #4f46e5);
  background: var(--primary-50, #eef2ff);
  padding: 2px 8px;
  border-radius: 6px;
  margin-bottom: 6px;
}

.action-confirm-card h3 {
  margin: 0 0 12px;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.quote-details-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px;
  margin-bottom: 14px;
}

.quote-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cell-label {
  font-size: 10.5px;
  font-weight: 700;
  color: #64748b;
}

.cell-val {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.cell-val.price {
  color: #d97706;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.confirm-actions :deep(.el-button) {
  border-radius: var(--radius-pill, 999px) !important;
}

.inline-error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 18px 8px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #dc2626;
  font-size: 12px;
  font-weight: 600;
}

.quick-prompts-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-top: 1px solid #f1f5f9;
  overflow-x: auto;
}

.btn-prompt-chip {
  padding: 5px 10px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: var(--radius-pill, 999px);
  color: var(--text-secondary, #475569);
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.btn-prompt-chip:hover {
  background: var(--primary-50, #eef2ff);
  border-color: var(--color-primary-border, #c7d2fe);
  color: var(--primary-600, #4f46e5);
}

.btn-prompt-chip.primary {
  background: var(--primary-50, #eef2ff);
  border-color: var(--color-primary-border, #c7d2fe);
  color: var(--primary-600, #4f46e5);
}

.composer-area {
  padding: 10px 18px 16px;
  background: #ffffff;
}

.composer-box {
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #ffffff;
  transition: all 0.15s ease;
}

.composer-box:focus-within {
  border-color: var(--primary-500, #6366f1);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.composer-box textarea {
  width: 100%;
  border: 0;
  outline: none;
  font: inherit;
  font-size: 13px;
  color: var(--text-primary, #0f172a);
  resize: none;
  background: transparent;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.composer-hint {
  font-size: 11px;
  color: var(--text-muted, #94a3b8);
}

.btn-send {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 0;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
  color: #ffffff;
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(79, 70, 229, 0.3);
}

.btn-send:disabled {
  background: #e2e8f0;
  color: #94a3b8;
  cursor: not-allowed;
}

/* Right Pane: Video Stage */
.video-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #f8fafc;
}

.stage-toolbar {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  background: #ffffff;
  border-bottom: 1px solid var(--border-default, #e2e8f0);
}

.stage-version-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
}

.stage-version-chip .label {
  color: #64748b;
}

.stage-version-chip .val {
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.model-selector-wrap {
  margin-left: auto;
}

.stage-viewport {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.stage-ready-card {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
  text-align: center;
  box-sizing: border-box;
}

.ready-icon-halo {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: var(--primary-50, #eef2ff);
  color: var(--primary-600, #4f46e5);
  font-size: 36px;
  display: grid;
  place-items: center;
  margin-bottom: 18px;
  box-shadow: 0 4px 20px rgba(79, 70, 229, 0.15);
}

.stage-ready-card h2 {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.stage-ready-card p {
  max-width: 480px;
  margin: 0 0 24px;
  font-size: 13.5px;
  color: var(--text-secondary, #475569);
  line-height: 1.6;
}

.ready-cta-group :deep(.el-button) {
  border-radius: var(--radius-pill, 999px) !important;
  padding: 10px 24px !important;
}

.mobile-tabs-bar {
  display: none;
}

.workspace-state-box {
  padding: 32px;
}

/* Responsive adjustments */
@media (max-width: 900px) {
  .workspace-header {
    height: auto;
    padding: 12px 16px;
    flex-wrap: wrap;
  }
  .project-info-group {
    border-left: 0;
    padding-left: 0;
  }
  .header-actions {
    width: 100%;
    justify-content: flex-start;
    overflow-x: auto;
  }
  .mobile-tabs-bar {
    display: grid;
    grid-template-columns: 1fr 1fr;
    border-bottom: 1px solid #e2e8f0;
    background: #ffffff;
  }
  .mobile-tabs-bar button {
    border: 0;
    padding: 12px;
    font-size: 13px;
    font-weight: 800;
    background: transparent;
    color: #64748b;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    cursor: pointer;
  }
  .mobile-tabs-bar button.active {
    color: var(--primary-600, #4f46e5);
    border-bottom: 2px solid var(--primary-600, #4f46e5);
  }
  .workspace-main-grid {
    display: block;
  }
  .agent-pane,
  .video-pane {
    height: calc(100% - 45px);
    border-right: 0;
  }
  .mobile-hidden {
    display: none;
  }
}
</style>

