<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api/client';
import { useAgentStream } from '../composables/useAgentStream';
import { useAutoScroll } from '../composables/useAutoScroll';
import { parseContentToBlocks } from '../services/contentParser';
import { useTaskCenterStore } from '../stores/taskCenter';
import type { GenerationRun } from '../types';
import PageHeader from '../components/layout/PageHeader.vue';
import AgentActivityCard from '../components/agent/AgentActivityCard.vue';
import AgentThinkingIndicator from '../components/agent/AgentThinkingIndicator.vue';
import AgentStepTimeline from '../components/agent/AgentStepTimeline.vue';
import AgentEventLog from '../components/agent/AgentEventLog.vue';
import GenerationToolbar from '../components/agent/GenerationToolbar.vue';
import StreamingCursor from '../components/agent/StreamingCursor.vue';
import HumanReviewPanel from '../components/agent/HumanReviewPanel.vue';
import ContentBlockRenderer from '../components/content-renderers/ContentBlockRenderer.vue';
import ConnectionStatus from '../components/feedback/ConnectionStatus.vue';
import ErrorState from '../components/feedback/ErrorState.vue';
import { ArrowDown } from '@element-plus/icons-vue';

const route = useRoute();
const router = useRouter();
const taskCenter = useTaskCenterStore();

const runId = route.params.runId as string;
const courseId = route.params.id as string;

const run = ref<GenerationRun | null>(null);
const rawStreamContent = ref('');
const completedNodes = ref<string[]>([]);
const latestMessage = ref('Agent 工作组集群初始化中...');

const scrollContainerRef = ref<HTMLElement | null>(null);
const { isAutoScrollActive, unreadCount, notifyNewContent, scrollToBottom } = useAutoScroll(scrollContainerRef);
const { events: streamEvents, connectionStatus, error: streamError, connect, disconnect } = useAgentStream(runId);

const contentBlocks = computed(() => parseContentToBlocks(rawStreamContent.value));

async function loadRunDetails() {
  try {
    const { data } = await api.get(`/generations/${runId}`);
    run.value = data;

    taskCenter.updateTaskStatus(runId, {
      course_id: courseId,
      progress: data.progress || 0,
      status: data.status,
      current_node: data.current_node
    });

    connect();
  } catch (e) {
    console.error('Load run details error', e);
  }
}

watch(streamEvents, (list) => {
  if (!list.length) return;
  const latest = list[list.length - 1];

  if (latest.payload?.message) {
    latestMessage.value = latest.payload.message;
  }

  if (latest.nodeId && run.value) {
    if (run.value.current_node && !completedNodes.value.includes(run.value.current_node)) {
      completedNodes.value.push(run.value.current_node);
    }
    run.value.current_node = latest.nodeId;
  }

  if (latest.payload?.progress !== undefined && run.value) {
    run.value.progress = latest.payload.progress;
    taskCenter.updateTaskStatus(runId, { progress: latest.payload.progress });
  }

  if (latest.type === 'run_completed' && run.value) {
    run.value.status = 'completed';
    taskCenter.updateTaskStatus(runId, { status: 'completed', progress: 100 });
  }

  if (latest.type === 'human_input_required' && run.value) {
    run.value.status = 'waiting_human';
    taskCenter.updateTaskStatus(runId, { status: 'waiting_human' });
  }

  if (latest.payload?.delta) {
    rawStreamContent.value += latest.payload.delta;
    notifyNewContent();
  }
}, { deep: true });

async function pauseRun() {
  if (run.value) run.value.status = 'paused';
}

async function resumeRun() {
  if (run.value) run.value.status = 'running';
}

async function cancelRun() {
  try {
    await api.post(`/generations/${runId}/cancel`);
    if (run.value) run.value.status = 'cancelled';
    disconnect();
  } catch (e) {
    console.error(e);
  }
}

async function approveHumanReview() {
  try {
    if (run.value?.run_type === 'blueprint') {
      router.push(`/courses/${courseId}/blueprint`);
      return;
    }
    await api.post(`/generations/${runId}/continue`);
    router.push(`/courses/${courseId}/workspace`);
  } catch (e) {
    console.error(e);
  }
}

onMounted(loadRunDetails);
</script>

<template>
  <div class="generation-root-view">
    <div v-if="run" class="page-container animate-fade-in">
      <PageHeader 
        :eyebrow="run.run_type === 'blueprint' ? '02 / 课程蓝图生成' : '03 / 多 Agent 运行监视'" 
        :title="run.run_type === 'blueprint' ? '需求 Agent 正在构建课程蓝图' : '课程资源实时生成与协作'"
        :subtitle="run.run_type === 'blueprint' ? '系统正在把已确认需求和参考材料整理为统一课程蓝图' : '多 Agent 协作工作流正基于课程蓝图并发推理生成微课材料'"
      >
        <template #actions>
          <ConnectionStatus :status="connectionStatus" />
        </template>
      </PageHeader>

      <!-- Top Generation Toolbar -->
      <GenerationToolbar 
        :status="run.status" 
        :is-streaming="connectionStatus === 'connected'" 
        :has-content="Boolean(rawStreamContent)" 
        @pause="pauseRun"
        @resume="resumeRun"
        @cancel="cancelRun"
        @reconnect="connect"
        @background="router.push('/')"
      />

      <!-- Agent Activity Banner Card -->
      <AgentActivityCard 
        :current-node="run.current_node" 
        :progress="run.progress" 
        :status="run.status" 
        :message="latestMessage" 
        @cancel="cancelRun"
        @pause="pauseRun"
        @resume="resumeRun"
        @background="router.push('/')"
      />

      <!-- Workflow Step Timeline -->
      <AgentStepTimeline v-if="run.run_type !== 'blueprint'"
        :current-node="run.current_node" 
        :completed-nodes="completedNodes" 
      />

      <!-- Main Split: Stream Viewer vs Log & Status -->
      <div class="generation-split-grid">
        <!-- Stream Viewer Column -->
        <div class="stream-viewer-card lf-card">
          <div class="stream-viewer-header">
            <div class="stream-title">
              <h3>Agent 实时输出面板</h3>
              <StreamingCursor :active="connectionStatus === 'connected'" />
            </div>
            <span class="stream-hint">流式结构化输出 (Auto-buffered)</span>
          </div>

          <div ref="scrollContainerRef" class="stream-scroll-viewport">
            <ErrorState v-if="streamError" :error="streamError" show-retry @retry="connect" />

            <div v-if="!contentBlocks.length && connectionStatus === 'connected'">
              <AgentThinkingIndicator :agent-name="run.current_node" :text="latestMessage" />
            </div>

            <div v-for="block in contentBlocks" :key="block.block_id" class="content-block-item">
              <ContentBlockRenderer :block="block" :is-streaming="block.status === 'streaming'" />
            </div>
          </div>

          <!-- Sticky Floating Back-to-Bottom Button -->
          <button 
            v-if="!isAutoScrollActive" 
            class="back-to-bottom-btn animate-fade-in"
            @click="scrollToBottom(true)"
          >
            <el-icon><ArrowDown /></el-icon>
            <span>回到最新输出</span>
            <el-badge v-if="unreadCount > 0" :value="unreadCount" type="primary" />
          </button>
        </div>

        <!-- Log & Human Approval Column -->
        <div class="side-log-column">
          <AgentEventLog :events="streamEvents" />

          <HumanReviewPanel
            v-if="run.status === 'waiting_human'"
            :title="run.run_type === 'blueprint' ? '课程蓝图等待确认' : undefined"
            :message="run.run_type === 'blueprint' ? '课程蓝图已经生成，请进入蓝图页核对教学目标、知识点和时间分配。' : undefined"
            :primary-action-text="run.run_type === 'blueprint' ? '进入课程蓝图' : undefined"
            :show-secondary-actions="run.run_type !== 'blueprint'"
            @approve="approveHumanReview" 
            @edit="router.push(`/courses/${courseId}/workspace`)"
            @reject="cancelRun"
          />
        </div>
      </div>
    </div>

    <div v-else class="page-container animate-fade-in">
      <div class="loading-state">正在建立 Agent 通讯通道...</div>
    </div>
  </div>
</template>

<style scoped>
.generation-root-view {
  height: 100%;
  width: 100%;
  overflow-y: auto;
}

.generation-toolbar-box {
  margin-bottom: 20px;
}

.generation-split-grid {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 20px;
}

@media (max-width: 1120px) {
  .generation-split-grid {
    grid-template-columns: 1fr;
  }
}

.stream-viewer-card {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 640px;
}

.stream-viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}

.stream-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stream-title h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.stream-hint {
  font-size: 13px;
  color: var(--text-muted);
}

.stream-scroll-viewport {
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
}

.content-block-item {
  margin-bottom: 16px;
}

.back-to-bottom-btn {
  position: absolute;
  bottom: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 18px;
  background: var(--color-primary);
  color: #fff;
  border: 0;
  border-radius: var(--radius-full);
  box-shadow: var(--shadow-md);
  cursor: pointer;
  font-weight: 700;
  font-size: 13.5px;
  z-index: 10;
}

.side-log-column {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.loading-state {
  padding: 80px;
  text-align: center;
  font-size: 15.5px;
  color: var(--text-muted);
}
</style>

