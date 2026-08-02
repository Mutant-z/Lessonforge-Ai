<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, errorMessage } from '../api/client';
import { useCourseStore } from '../stores/courses';
import type { Artifact } from '../types';
import PageHeader from '../components/layout/PageHeader.vue';
import StatusBadge from '../components/feedback/StatusBadge.vue';
import EmptyState from '../components/feedback/EmptyState.vue';
import VersionSelector from '../components/domain/VersionSelector.vue';
import SlidePreview from '../components/domain/SlidePreview.vue';
import SlideThumbnail from '../components/domain/SlideThumbnail.vue';
import TeachingTimeline from '../components/domain/TeachingTimeline.vue';
import ObjectiveCard from '../components/domain/ObjectiveCard.vue';
import ExerciseCard from '../components/domain/ExerciseCard.vue';
import TaskSheetCard from '../components/domain/TaskSheetCard.vue';
import StoryboardItem from '../components/domain/StoryboardItem.vue';
import VerbatimSegment from '../components/domain/VerbatimSegment.vue';
import QualityIssueCard from '../components/domain/QualityIssueCard.vue';
import CitationCard from '../components/content-renderers/CitationCard.vue';
import MarkdownRenderer from '../components/content-renderers/MarkdownRenderer.vue';
import ModelSelector from '../components/agent/ModelSelector.vue';
import { 
  Download, 
  Edit, 
  CircleCheck, 
  Lock, 
  Clock, 
  Promotion, 
  ChatDotSquare 
} from '@element-plus/icons-vue';

const route = useRoute();
const router = useRouter();
const store = useCourseStore();

const courseId = route.params.id as string;

const items = ref<Artifact[]>([]);
const activeTab = ref('lesson_plan');
const isEditing = ref(false);
const draftMarkdown = ref('');
const error = ref('');
const versions = ref<Artifact[]>([]);
const showVersionsDrawer = ref(false);
const chatMessages = ref<any[]>([]);
const chatInput = ref('');
const selectedModelConfigId = ref<string | null>(null);
const chatSending = ref(false);
const modelSwitching = ref(false);
const isTeleprompterMode = ref(false);
const selectedSlideIndex = ref(0);

const tabs = [
  ['lesson_plan', '教学设计'],
  ['ppt', 'PPT 课件'],
  ['task_sheet', '学习任务单'],
  ['exercise', '课后练习'],
  ['video_script', '视频脚本'],
  ['verbatim', '教师逐字稿'],
  ['quality_report', '质量报告'],
  ['citation_report', '引用来源']
];

const currentArtifact = computed(() => items.value.find(x => x.artifact_type === activeTab.value));

async function loadArtifacts() {
  try {
    await store.open(courseId);
    const { data } = await api.get(`/courses/${courseId}/artifacts`);
    items.value = data || [];
    if (!data || !data.length) {
      error.value = '资源仍在生成中或尚未启动。';
    }
    await loadChatHistory();
  } catch (e) {
    error.value = errorMessage(e);
  }
}

function startEdit() {
  draftMarkdown.value = currentArtifact.value?.content_markdown || '';
  isEditing.value = true;
}

async function saveEdit() {
  if (!currentArtifact.value) return;
  try {
    const { data } = await api.patch(`/artifacts/${currentArtifact.value.id}`, {
      content_json: currentArtifact.value.content_json,
      content_markdown: draftMarkdown.value,
      change_summary: '教师在线微调编辑'
    });
    items.value = items.value.map(x => x.artifact_type === activeTab.value ? data : x);
    isEditing.value = false;
  } catch (e) {
    error.value = errorMessage(e);
  }
}

async function approveCurrent() {
  if (!currentArtifact.value) return;
  try {
    const { data } = await api.post(`/artifacts/${currentArtifact.value.id}/approve`);
    Object.assign(currentArtifact.value, data);
  } catch (e) {
    error.value = errorMessage(e);
  }
}

async function lockCurrent() {
  if (!currentArtifact.value) return;
  try {
    await api.post(`/artifacts/${currentArtifact.value.id}/lock`, { json_path: '$' });
    currentArtifact.value.is_locked = true;
  } catch (e) {
    error.value = errorMessage(e);
  }
}

async function loadVersionHistory() {
  if (!currentArtifact.value) return;
  try {
    const { data } = await api.get(`/artifacts/${currentArtifact.value.id}/versions`);
    versions.value = data;
    showVersionsDrawer.value = true;
  } catch (e) {
    error.value = errorMessage(e);
  }
}

function selectVersion(ver: Artifact) {
  items.value = items.value.map(x => x.artifact_type === activeTab.value ? ver : x);
  showVersionsDrawer.value = false;
}

async function loadChatHistory(moduleType = activeTab.value) {
  try {
    const { data } = await api.get(`/courses/${courseId}/modules/${moduleType}/chat/history`);
    if (moduleType !== activeTab.value) return;
    if (Array.isArray(data)) {
      chatMessages.value = data;
    } else {
      chatMessages.value = data.messages || [];
      selectedModelConfigId.value = data.model_config_id || null;
    }
  } catch (e) {
    console.warn('Load chat history error', e);
  }
}

async function sendChatInstruction() {
  if (!chatInput.value.trim() || chatSending.value) return;
  const text = chatInput.value;
  chatSending.value = true;
  try {
    const { data } = await api.post(`/courses/${courseId}/modules/${activeTab.value}/chat/send`, {
      path: '',
      instruction: text,
      preserve_locked_content: true
    });
    chatInput.value = '';
    chatMessages.value.push({ role: 'user', content: text });
    chatMessages.value.push(data.message);
    if (data.artifact) {
      items.value = items.value.map(x => x.artifact_type === activeTab.value ? data.artifact : x);
    }
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    chatSending.value = false;
  }
}

async function changeChatModel(modelConfigId: string) {
  const previous = selectedModelConfigId.value;
  selectedModelConfigId.value = modelConfigId;
  error.value = '';
  modelSwitching.value = true;
  try {
    const { data } = await api.patch(`/courses/${courseId}/modules/${activeTab.value}/chat/model`, {
      model_config_id: modelConfigId,
    });
    selectedModelConfigId.value = data.model_config_id;
  } catch (cause) {
    selectedModelConfigId.value = previous;
    error.value = errorMessage(cause);
  } finally {
    modelSwitching.value = false;
  }
}

function handleTabSwitch(tabKey: string) {
  if (chatSending.value || modelSwitching.value) return;
  activeTab.value = tabKey;
  isEditing.value = false;
  selectedSlideIndex.value = 0;
  selectedModelConfigId.value = null;
  loadChatHistory();
}

onMounted(loadArtifacts);
</script>

<template>
  <div class="workspace-full-container animate-fade-in">
    <!-- Top Workspace Header -->
    <div class="workspace-top-bar bg-glass">
      <div class="header-titles">
        <span class="eyebrow-text">04 / 课程资源工作台</span>
        <h2>{{ store.current?.title || '资源编辑器' }}</h2>
      </div>

      <div class="header-actions">
        <el-button type="primary" size="large" :icon="Download" @click="router.push(`/courses/${courseId}/export`)">
          前往导出中心打包
        </el-button>
      </div>
    </div>

    <!-- Secondary Tabs Bar with Larger Clearer Fonts -->
    <div class="tabs-nav-bar bg-glass">
      <button
        v-for="([key, label], idx) in tabs"
        :key="key"
        class="tab-btn"
        :class="{ active: activeTab === key }"
        :disabled="chatSending || modelSwitching"
        @click="handleTabSwitch(key)"
      >
        <span class="tab-index">0{{ idx + 1 }}</span>
        <span class="tab-name">{{ label }}</span>
        <span v-if="items.some(x => x.artifact_type === key)" class="tab-dot"></span>
      </button>
    </div>

    <!-- Main Workspace Split -->
    <div class="workspace-split-layout">
      <!-- Left Sidebar: Module Agent Chat & Metadata -->
      <aside class="module-agent-sidebar lf-card">
        <div class="agent-side-header">
          <div class="agent-title">
            <el-icon class="agent-icon"><ChatDotSquare /></el-icon>
            <h4>{{ tabs.find(x => x[0] === activeTab)?.[1] }} Agent</h4>
          </div>
          <span class="sub-text">模块专属助手</span>
        </div>

        <!-- Chat Conversation Area -->
        <div class="chat-viewport">
          <div v-for="(msg, mIdx) in chatMessages" :key="mIdx" class="chat-bubble" :class="[msg.role]">
            <span class="bubble-role">{{ msg.role === 'user' ? '教师' : 'Agent' }}</span>
            <p class="bubble-text">{{ msg.content }}</p>
          </div>
        </div>

        <!-- Chat Input Form -->
        <form class="chat-input-form" @submit.prevent="sendChatInstruction">
          <ModelSelector
            v-model="selectedModelConfigId"
            :disabled="chatSending || modelSwitching"
            compact
            label=""
            @change="changeChatModel"
          />
          <el-input 
            v-model="chatInput" 
            type="textarea" 
            :rows="3" 
            placeholder="输入针对本模块的局部修改要求..." 
            :disabled="chatSending"
          />
          <el-button native-type="submit" type="primary" size="default" class="send-btn" :icon="Promotion" :loading="chatSending">
            发送修改指令
          </el-button>
        </form>

        <!-- Artifact Version Meta Box -->
        <div v-if="currentArtifact" class="meta-version-box">
          <div class="meta-row">
            <span>当前版本:</span>
            <strong>V{{ currentArtifact.version }}</strong>
          </div>
          <div class="meta-row">
            <span>蓝图依据:</span>
            <strong>V{{ currentArtifact.blueprint_version }}</strong>
          </div>
          <div class="meta-row">
            <span>锁定状态:</span>
            <StatusBadge :status="currentArtifact.is_locked ? 'completed' : 'draft'" size="small" />
          </div>
        </div>
      </aside>

      <!-- Center Main Content Viewer / Specialized Renderer -->
      <main class="artifact-content-main lf-card">
        <div class="artifact-toolbar">
          <div class="toolbar-left">
            <h3 class="artifact-title">{{ tabs.find(x => x[0] === activeTab)?.[1] }} 交付产物</h3>
            <span v-if="currentArtifact" class="version-tag">Version {{ currentArtifact.version }}</span>
          </div>

          <div v-if="currentArtifact" class="toolbar-right">
            <el-button size="default" :icon="Clock" @click="loadVersionHistory">历史版本</el-button>
            <el-button size="default" :icon="Lock" @click="lockCurrent">
              {{ currentArtifact.is_locked ? '已锁定' : '锁定内容' }}
            </el-button>
            <el-button size="default" :icon="Edit" @click="startEdit">全局编辑</el-button>
            <el-button size="default" type="success" :icon="CircleCheck" @click="approveCurrent">
              审核通过
            </el-button>
          </div>
        </div>

        <!-- Full Editing Mode -->
        <div v-if="isEditing" class="editing-mode-wrapper">
          <textarea v-model="draftMarkdown" class="markdown-raw-editor" spellcheck="false"></textarea>
          <div class="edit-footer-actions">
            <el-button size="default" @click="isEditing = false">取消</el-button>
            <el-button size="default" type="primary" @click="saveEdit">保存为新版本</el-button>
          </div>
        </div>

        <!-- Domain Specialized Renderers -->
        <div v-else-if="currentArtifact" class="domain-renderer-viewport">
          <!-- 1. PPT Specialized Renderer -->
          <template v-if="activeTab === 'ppt' && currentArtifact.content_json?.slides">
            <div class="ppt-editor-grid">
              <div class="ppt-thumbnails-sidebar">
                <SlideThumbnail
                  v-for="(slide, sIdx) in currentArtifact.content_json.slides"
                  :key="sIdx"
                  :slide="slide"
                  :index="sIdx"
                  :is-active="selectedSlideIndex === sIdx"
                  @select="selectedSlideIndex = $event"
                />
              </div>
              <div class="ppt-main-preview">
                <SlidePreview
                  v-if="currentArtifact.content_json.slides[selectedSlideIndex]"
                  :slide="currentArtifact.content_json.slides[selectedSlideIndex]"
                  :slide-index="selectedSlideIndex"
                  :total-slides="currentArtifact.content_json.slides.length"
                />
              </div>
            </div>
          </template>

          <!-- 2. Lesson Plan Specialized Renderer -->
          <template v-else-if="activeTab === 'lesson_plan' && currentArtifact.content_json?.activities">
            <div class="lesson-plan-view">
              <h3>🎯 观察化教学目标</h3>
              <ObjectiveCard
                v-for="(obj, oIdx) in currentArtifact.content_json.objectives"
                :key="oIdx"
                :objective="obj"
                :index="oIdx"
              />

              <h3 style="margin-top: 28px;">⏱️ 分时教学过程设计</h3>
              <TeachingTimeline :activities="currentArtifact.content_json.activities" />
            </div>
          </template>

          <!-- 3. Exercises Specialized Renderer -->
          <template v-else-if="activeTab === 'exercise' && currentArtifact.content_json?.exercises">
            <div class="exercises-view">
              <ExerciseCard
                v-for="(ex, eIdx) in currentArtifact.content_json.exercises"
                :key="ex.id || eIdx"
                :exercise="ex"
                :index="eIdx"
              />
            </div>
          </template>

          <!-- 4. Task Sheet Specialized Renderer -->
          <template v-else-if="activeTab === 'task_sheet' && currentArtifact.content_json?.tasks">
            <div class="task-sheets-view">
              <TaskSheetCard
                v-for="(tk, tIdx) in currentArtifact.content_json.tasks"
                :key="tk.task_id || tIdx"
                :task="tk"
                :index="tIdx"
              />
            </div>
          </template>

          <!-- 5. Video Script Specialized Renderer -->
          <template v-else-if="activeTab === 'video_script' && currentArtifact.content_json?.scenes">
            <div class="video-script-view">
              <StoryboardItem
                v-for="(sc, scIdx) in currentArtifact.content_json.scenes"
                :key="scIdx"
                :scene="sc"
              />
            </div>
          </template>

          <!-- 6. Verbatim Teleprompter Mode Renderer -->
          <template v-else-if="activeTab === 'verbatim' && currentArtifact.content_json?.segments">
            <div class="verbatim-view">
              <div class="verbatim-toolbar">
                <el-switch v-model="isTeleprompterMode" active-text="提词器黑夜模式" />
              </div>
              <VerbatimSegment
                v-for="(seg, sgIdx) in currentArtifact.content_json.segments"
                :key="sgIdx"
                :segment="seg"
                :index="sgIdx"
                :is-teleprompter="isTeleprompterMode"
              />
            </div>
          </template>

          <!-- 7. Quality Report Renderer -->
          <template v-else-if="activeTab === 'quality_report' && currentArtifact.content_json?.issues">
            <div class="quality-report-view">
              <div class="score-banner">
                <div class="score-number">{{ currentArtifact.content_json.score }}</div>
                <div class="score-info">
                  <h4>综合质量规则检测得分</h4>
                  <p>{{ currentArtifact.content_json.summary }}</p>
                </div>
              </div>

              <h3>发现的合规性与缺陷问题</h3>
              <QualityIssueCard
                v-for="(iss, iIdx) in currentArtifact.content_json.issues"
                :key="iIdx"
                :issue="iss"
              />
            </div>
          </template>

          <!-- 8. Citation Report Renderer -->
          <template v-else-if="activeTab === 'citation_report' && currentArtifact.content_json?.source_refs">
            <div class="citations-view">
              <CitationCard
                v-for="(cRef, cIdx) in currentArtifact.content_json.source_refs"
                :key="cIdx"
                :source-name="cRef"
                :is-uploaded-material="true"
              />
            </div>
          </template>

          <!-- Default Markdown Fallback -->
          <template v-else>
            <MarkdownRenderer :content="currentArtifact.content_markdown" />
          </template>
        </div>

        <EmptyState v-else title="当前模块尚无生成产物" description="生成任务可能仍在处理中..." />
      </main>
    </div>

    <!-- Version Selector Drawer -->
    <VersionSelector
      v-if="showVersionsDrawer"
      :versions="versions"
      :current-version="currentArtifact?.version"
      @select="selectVersion"
      @close="showVersionsDrawer = false"
    />
  </div>
</template>

<style scoped>
.workspace-full-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--header-height));
  overflow: hidden;
}

.workspace-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 32px;
  border-bottom: 1px solid var(--border-default);
}

.eyebrow-text {
  font-size: 13px;
  font-weight: 800;
  color: var(--color-primary);
}

.header-titles h2 {
  margin: 4px 0 0;
  font-size: 24px;
  font-weight: 900;
  color: var(--text-primary);
}

.tabs-nav-bar {
  display: flex;
  padding: 0 24px;
  border-bottom: 1px solid var(--border-default);
  overflow-x: auto;
  background: var(--surface-primary);
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 22px;
  border: 0;
  background: transparent;
  cursor: pointer;
  position: relative;
  color: var(--text-secondary);
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
  transition: all var(--motion-fast);
}

.tab-btn.active {
  color: var(--color-primary);
  font-weight: 800;
  border-bottom: 3px solid var(--color-primary);
}

.tab-index {
  font-size: 12.5px;
  font-weight: 900;
  color: var(--color-primary);
}

.tab-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
}

.workspace-split-layout {
  display: grid;
  grid-template-columns: 340px 1fr;
  flex: 1;
  min-height: 0;
}

@media (max-width: 1024px) {
  .workspace-split-layout {
    grid-template-columns: 1fr;
  }
}

.module-agent-sidebar {
  border-radius: 0;
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  padding: 24px;
  background: var(--bg-page);
}

.agent-side-header {
  margin-bottom: 18px;
}

.agent-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.agent-title h4 {
  margin: 0;
  font-size: 17px;
  font-weight: 800;
}

.agent-icon {
  color: var(--color-primary);
  font-size: 20px;
}

.sub-text {
  font-size: 13px;
  color: var(--text-muted);
}

.chat-viewport {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-bubble {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  font-size: 14.5px;
}

.chat-bubble.user {
  border-left: 3.5px solid var(--color-primary);
}

.bubble-role {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--color-primary);
  display: block;
  margin-bottom: 4px;
}

.bubble-text {
  margin: 0;
  line-height: 1.6;
  color: var(--text-primary);
}

.send-btn {
  width: 100%;
  margin-top: 10px;
  font-weight: 700 !important;
}

.meta-version-box {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13.5px;
  color: var(--text-muted);
}

.artifact-content-main {
  border-radius: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 28px 36px;
}

.artifact-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 22px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.artifact-title {
  margin: 0;
  font-size: 22px;
  font-weight: 900;
}

.version-tag {
  font-size: 13.5px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 4px 12px;
  border-radius: var(--radius-xs);
  font-weight: 800;
}

.toolbar-right {
  display: flex;
  gap: 10px;
}

.domain-renderer-viewport {
  flex: 1;
  overflow-y: auto;
  font-size: 15.5px;
  line-height: 1.7;
}

.ppt-editor-grid {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 24px;
  height: 100%;
}

.ppt-thumbnails-sidebar {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-right: 8px;
}

.markdown-raw-editor {
  width: 100%;
  height: 520px;
  padding: 22px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-family: SFMono-Regular, Consolas, monospace;
  font-size: 15px;
  line-height: 1.75;
  outline: none;
}

.edit-footer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
}

.verbatim-toolbar {
  margin-bottom: 18px;
}

.score-banner {
  display: flex;
  align-items: center;
  gap: 28px;
  padding: 28px;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #fff;
  border-radius: var(--radius-xl);
  margin-bottom: 28px;
}

.score-number {
  font-size: 56px;
  font-weight: 900;
}

.score-info h4 {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 800;
}

.score-info p {
  margin: 0;
  font-size: 15px;
  opacity: 0.95;
  line-height: 1.6;
}
</style>
