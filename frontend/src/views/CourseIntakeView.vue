<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ArrowLeft, Check, Cpu, DocumentChecked } from '@element-plus/icons-vue';
import { errorMessage } from '../api/client';
import { useIntakeStream } from '../composables/useIntakeStream';
import { useCourseIntakeStore } from '../stores/courseIntake';
import AgentComposer from '../components/intake/AgentComposer.vue';
import IntakeConversation from '../components/intake/IntakeConversation.vue';
import IntakeMaterialList from '../components/intake/IntakeMaterialList.vue';
import RequirementSummaryCard from '../components/intake/RequirementSummaryCard.vue';

const route = useRoute();
const router = useRouter();
const store = useCourseIntakeStore();
const error = ref('');
const savingField = ref(false);
const conversationScroll = ref<HTMLElement | null>(null);
const composerRef = ref<InstanceType<typeof AgentComposer> | null>(null);
const containerRef = ref<HTMLElement | null>(null);

const leftPercent = ref(71);
const isDragging = ref(false);

const isMobile = ref(false);
const summaryOpen = ref(false);
const selectedModelConfigId = ref<string | null>(null);
const modelSwitching = ref(false);
let mobileMedia: MediaQueryList | null = null;

const sessionId = computed(() => String(route.query.session || ''));
const canConfirm = computed(() =>
  store.session?.status === 'ready'
  && store.session.missing_fields.length === 0
  && !store.session.conflicts.some(item => item.severity === 'blocking')
);
const agentStatusLabel = computed(() => {
  if (store.session?.status === 'processing') return 'Agent 正在拆解意图...';
  if (store.lastFailure) return '本轮分析失败，可重试';
  return '需求 Copilot 已就绪';
});

const stream = useIntakeStream({
  onDraftUpdated: event => store.applyDraftUpdate(event),
  onCompleted: (turnId, content) => store.finishAssistant(turnId, content),
  onTurnFailed: failure => store.failTurn(failure),
});

async function scrollConversationToLatest() {
  await nextTick();
  if (conversationScroll.value) {
    conversationScroll.value.scrollTop = conversationScroll.value.scrollHeight;
  }
}

watch(
  [() => store.messages.length, () => stream.streamedText.value, () => stream.activityMessage.value],
  scrollConversationToLatest,
);

watch(
  () => store.session?.model_config_id,
  value => { selectedModelConfigId.value = value || null; },
  { immediate: true },
);

onMounted(async () => {
  mobileMedia = window.matchMedia('(max-width: 960px)');
  updateMobileBreakpoint();
  mobileMedia.addEventListener('change', updateMobileBreakpoint);
  try {
    let id = sessionId.value;
    if (!id) {
      const created = await store.create();
      id = created.id;
      await router.replace({ path: '/courses/new', query: { session: id } });
    }
    const session = await store.open(id);
    await scrollConversationToLatest();
    if (session.active_turn_id) await stream.connect(session.active_turn_id);
  } catch (cause) {
    error.value = errorMessage(cause);
  }
});

onBeforeUnmount(() => {
  mobileMedia?.removeEventListener('change', updateMobileBreakpoint);
  stopResize();
});

function updateMobileBreakpoint() {
  isMobile.value = Boolean(mobileMedia?.matches);
}

/* Dynamic Left/Right Window Resizing */
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
  if (newPercent >= 32 && newPercent <= 76) {
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
  leftPercent.value = 71;
}

function handleSelectTemplate(promptText: string) {
  if (composerRef.value) {
    composerRef.value.setText(promptText);
  }
}

function handlePromptField(fieldLabel: string) {
  if (composerRef.value) {
    composerRef.value.setText(`关于【${fieldLabel}】，我的具体要求是：`);
  }
}

async function send(content: string, files: File[]) {
  error.value = '';
  try {
    if (files.length) {
      const results = await Promise.allSettled(files.map(file => store.upload(file)));
      if (results.some(result => result.status === 'rejected')) {
        error.value = '部分材料上传或解析失败，已保留成功文件并继续分析文字需求。';
      }
    }
    const turnId = await store.send(content);
    await stream.connect(turnId);
  } catch (cause) {
    if ((cause as { response?: { status?: number } }).response?.status === 409) await store.refresh();
    error.value = errorMessage(cause);
  }
}

async function retryFailedTurn() {
  error.value = '';
  try {
    const turnId = await store.retryFailedTurn();
    await stream.connect(turnId);
  } catch (cause) {
    if ((cause as { response?: { status?: number } }).response?.status === 409) await store.refresh();
    error.value = errorMessage(cause);
  }
}

async function focusModelSelector() {
  await nextTick();
  const input = document.querySelector<HTMLElement>('.composer-dock .model-select input');
  input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  input?.focus();
  input?.click();
}

async function changeModel(modelConfigId: string) {
  const previous = store.session?.model_config_id || null;
  selectedModelConfigId.value = modelConfigId;
  error.value = '';
  modelSwitching.value = true;
  try {
    const session = await store.setModel(modelConfigId);
    selectedModelConfigId.value = session.model_config_id || null;
  } catch (cause) {
    selectedModelConfigId.value = previous;
    error.value = errorMessage(cause);
  } finally {
    modelSwitching.value = false;
  }
}

async function saveField(field: string, value: unknown) {
  savingField.value = true;
  error.value = '';
  try {
    await store.patchField(field, value);
  } catch (cause) {
    if ((cause as { response?: { status?: number } }).response?.status === 409) await store.refresh();
    error.value = errorMessage(cause);
  } finally {
    savingField.value = false;
  }
}

async function confirmAndGenerate() {
  error.value = '';
  try {
    const result = await store.confirm();
    await router.push(`/courses/${result.course_id}/project`);
  } catch (cause) {
    error.value = errorMessage(cause);
  }
}
</script>

<template>
  <div class="intake-page">
    <el-alert v-if="error" :title="error" type="error" show-icon closable @close="error = ''" />

    <div v-if="store.loading || !store.session" class="intake-loading">
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else ref="containerRef" class="intake-resizable-container">
      <!-- Left Panel: Chat Panel -->
      <section class="chat-panel" :style="{ width: isMobile ? '100%' : `${leftPercent}%` }">
        <div class="chat-top-bar">
          <button class="back-link" type="button" @click="router.push('/')">
            <el-icon><ArrowLeft /></el-icon>
            <span>返回工作台</span>
          </button>
          <div class="chat-top-status" :class="{ processing: store.session?.status === 'processing', failed: store.lastFailure }">
            <span class="status-pulse-dot animate-pulse"></span>
            <el-icon><Cpu /></el-icon>
            <span>{{ agentStatusLabel }}</span>
          </div>
        </div>

        <div ref="conversationScroll" class="conversation-scroll">
          <IntakeConversation
            :messages="store.messages"
            :streamed-text="stream.streamedText.value"
            :activity-message="stream.activityMessage.value"
            :failed-message="stream.connectionError.value"
            :task-failure-message="store.lastFailure?.message || ''"
            :task-retryable="store.lastFailure?.retryable"
            @select-template="handleSelectTemplate"
            @retry="retryFailedTurn"
            @switch-model="focusModelSelector"
          />
        </div>

        <div class="composer-dock">
          <IntakeMaterialList :materials="store.materials" />
          <AgentComposer
            ref="composerRef"
            :disabled="store.sending || store.session.status === 'processing' || store.session.status === 'completed'"
            v-model:model-config-id="selectedModelConfigId"
            :model-disabled="modelSwitching || store.session.status === 'processing' || store.session.status === 'completed'"
            :suggestions="['按上传材料组织内容', '用于复习巩固', '采用实验探究']"
            @model-change="changeModel"
            @send="send"
          />
        </div>
      </section>

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
        <div class="resizer-line"></div>
      </div>

      <!-- Right Panel: Requirement Summary Matrix -->
      <section 
        v-if="!isMobile" 
        class="summary-panel"
        :style="{ width: `${100 - leftPercent}%` }"
      >
        <RequirementSummaryCard 
          :session="store.session" 
          :saving="savingField" 
          @save="saveField"
          @prompt-field="handlePromptField"
        />
        <div class="confirm-dock">
          <div class="confirm-note">
            <el-icon><DocumentChecked /></el-icon>
            <span>确认的是 Agent 对教学意图的理解；内部规划不会展示 JSON。</span>
          </div>
          <el-button
            type="primary"
            size="large"
            :icon="Check"
            :disabled="!canConfirm"
            :loading="store.confirming"
            @click="confirmAndGenerate"
          >
            {{ store.session.status === 'completed' ? '项目已创建' : (canConfirm ? '确认教学意图并创建项目' : `需补充必填项 (缺 ${store.session.missing_fields.length} 项)`) }}
          </el-button>
        </div>
      </section>
    </div>

    <div v-if="store.session && isMobile" class="mobile-summary-bar">
      <div>
        <strong>需求摘要 V{{ store.session.current_revision }}</strong>
        <span>{{ store.session.status === 'completed' ? '已创建课程' : canConfirm ? '信息完整，可以确认' : `待补充 ${store.session.missing_fields.length} 项` }}</span>
      </div>
      <el-button type="primary" plain @click="summaryOpen = true">查看并确认</el-button>
    </div>

    <el-drawer
      v-if="store.session && isMobile"
      v-model="summaryOpen"
      direction="btt"
      size="88%"
      title="课程需求摘要"
      class="mobile-summary-drawer"
    >
      <RequirementSummaryCard 
        :session="store.session" 
        :saving="savingField" 
        @save="saveField"
        @prompt-field="handlePromptField"
      />
      <div class="confirm-dock mobile-confirm-dock">
        <div class="confirm-note">
          <el-icon><DocumentChecked /></el-icon>
          <span>确认教学意图后将创建六个专属 Agent 任务。</span>
        </div>
        <el-button
          type="primary"
          size="large"
          :icon="Check"
          :disabled="!canConfirm"
          :loading="store.confirming"
          @click="confirmAndGenerate"
        >
          {{ store.session.status === 'completed' ? '项目已创建' : '确认教学意图并创建项目' }}
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.intake-page {
  height: calc(100vh - var(--header-height));
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  background: #f7f7f8;
  box-sizing: border-box;
  overflow: hidden;
}

.intake-resizable-container {
  min-height: 0;
  flex: 1;
  display: flex;
  align-items: stretch;
  overflow: hidden;
}

.chat-panel,
.summary-panel {
  min-height: 0;
  background: var(--surface-primary);
  border: 1px solid #cfd2d9;
  border-radius: 0;
  box-shadow: none;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.chat-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #cfd2d9;
  background: #ffffff;
  flex-shrink: 0;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  border-radius: 0;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all var(--motion-fast) var(--ease-out-smooth);
}

.back-link:hover {
  background: #f2f5ff;
  color: #002fa7;
  border-color: #002fa7;
}

.chat-top-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #002fa7;
  background: #f2f5ff;
  border: 1px solid #c5d1f0;
  padding: 4px 12px;
  border-radius: 0;
  font-weight: 800;
  font-size: 12px;
}

.chat-top-status.processing {
  color: #002fa7;
  background: #f2f5ff;
  border-color: #c5d1f0;
}

.chat-top-status.failed {
  color: #b91c1c;
  background: #fff1f2;
  border-color: #fecdd3;
}

.chat-top-status.failed .status-pulse-dot {
  animation: none !important;
}

.status-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: none;
  animation: statusPulse 2s infinite ease-in-out;
}

/* Pane Resizer / Divider */
.pane-resizer {
  width: 10px;
  margin: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: col-resize;
  flex-shrink: 0;
  user-select: none;
  transition: background 150ms;
}

.pane-resizer:hover,
.pane-resizer.dragging {
  background: #f2f5ff;
  border-radius: 4px;
}

.resizer-line {
  width: 4px;
  height: 36px;
  border-radius: 4px;
  background: #cbd5e1;
  transition: background 150ms, height 150ms;
}

.pane-resizer:hover .resizer-line,
.pane-resizer.dragging .resizer-line {
  background: #002fa7;
  height: 48px;
}

.conversation-scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
}

.composer-dock {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border-top: 1px solid #f1f5f9;
  background: #f7f7f8;
  flex-shrink: 0;
}

.summary-panel :deep(.requirement-card) {
  flex: 1;
  min-height: 0;
  border: 0;
  box-shadow: none;
}

.confirm-dock {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  border-top: 1px solid #f1f5f9;
  background: #ffffff;
  flex-shrink: 0;
}

.confirm-dock .el-button {
  width: 100%;
  border-radius: 0;
  font-weight: 800;
  height: 44px;
  font-size: 15px;
}

.confirm-dock .el-button--primary:not(:disabled) {
  background: #002fa7 !important;
  border-color: #002fa7 !important;
  box-shadow: none !important;
}

.confirm-note {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}

.intake-loading {
  padding: 24px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
}

.mobile-summary-bar { display: none; }
.mobile-summary-drawer :deep(.el-drawer__body) { padding: 0; display: flex; flex-direction: column; min-height: 0; }
.mobile-summary-drawer :deep(.requirement-card) { flex: 1; min-height: 0; overflow-y: auto; border-left: 0; border-right: 0; }
.mobile-confirm-dock { flex: 0 0 auto; }

@media (max-width: 960px) {
  .intake-page { height: auto; min-height: calc(100vh - var(--header-height)); overflow-y: auto; padding-bottom: 96px; }
  .intake-resizable-container { flex-direction: column; }
  .chat-panel { width: 100% !important; min-height: 600px; }
  .summary-panel { width: 100% !important; max-height: none; }
  .pane-resizer { display: none; }
  .mobile-summary-bar {
    position: fixed;
    z-index: 18;
    left: calc(var(--sidebar-collapsed-width) + 16px);
    right: 16px;
    bottom: 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 14px;
    border: 1px solid var(--border-default);
    background: rgba(255, 255, 255, .96);
    box-shadow: var(--shadow-lg);
    border-radius: var(--radius-card);
  }
  .mobile-summary-bar div { display: flex; flex-direction: column; }
  .mobile-summary-bar strong { font-size: 13px; color: var(--text-primary); }
  .mobile-summary-bar span { color: var(--text-muted); font-size: 11px; }
}

@media (max-width: 640px) {
  .intake-page { padding: 12px 12px 96px; }
  .mobile-summary-bar { left: 12px; right: 12px; }
}
</style>
