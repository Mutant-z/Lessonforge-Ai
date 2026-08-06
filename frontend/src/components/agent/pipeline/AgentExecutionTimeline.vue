<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { ArrowDown, Check, CircleCheck, Cpu, Edit, Loading, Promotion, Warning } from '@element-plus/icons-vue';
import AgentRunCard from './AgentRunCard.vue';
import ToolCallCard from './ToolCallCard.vue';
import ArtifactEventCard from './ArtifactEventCard.vue';
import ThinkingBlock from './ThinkingBlock.vue';
import type { PipelineTimelineItem } from '../../../stores/pipeline';
import type { CourseTask, ProjectAgentMessage } from '../../../types';
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';

const props = defineProps<{
  items: PipelineTimelineItem[];
  task: CourseTask | null;
  toolCalls: Array<{ id: string; input: Record<string, any>; output: Record<string, any>; status: string; duration_ms: number; error: any }>;
  isRunning?: boolean;
  agentThoughts?: Record<string, string>;
}>();

const emit = defineEmits<{
  (e: 'select-slide', slideIndex: number): void;
}>();

const scrollRef = ref<HTMLElement | null>(null);
const isUserScrolledUp = ref(false);
const unreadCount = ref(0);

/** 合并连续重复的教师指令 */
interface GroupedUserInstruction {
  id: string;
  content: string;
  count: number;
  status: string;
  run_id?: string;
}

const groupedUserMessages = computed<GroupedUserInstruction[]>(() => {
  const rawMessages = (props.task?.messages || []).filter((m: ProjectAgentMessage) => m.role === 'user');
  const result: GroupedUserInstruction[] = [];

  for (const msg of rawMessages) {
    const text = msg.content.trim();
    if (!text) continue;
    const last = result[result.length - 1];
    if (last && last.content === text) {
      last.count += 1;
    } else {
      result.push({
        id: msg.id,
        content: text,
        count: 1,
        status: msg.status || 'completed',
        run_id: msg.run_id || undefined,
      });
    }
  }

  return result;
});

function resolveToolCall(id: string) {
  return props.toolCalls.find(call => call.id === id);
}

/** 把时间线条目分组为「Agent 运行链」，过滤纯底层 JSON */
const runs = computed(() => {
  const result: Array<{
    agentKey: string;
    label: string;
    status: 'running' | 'completed' | 'failed';
    summary: string;
    children: PipelineTimelineItem[];
  }> = [];

  let current: (typeof result)[number] | null = null;

  for (const item of props.items) {
    // 忽略底层纯 JSON 标记
    if (['pipeline_completed', 'task_paused', 'task_resumed'].includes(item.type)) {
      continue;
    }

    if (item.type === 'agent_started') {
      current = {
        agentKey: item.data.agent_key || '',
        label: item.data.agent_label || item.data.agent_key || '',
        status: 'running',
        summary: String(item.data.message || ''),
        children: [],
      };
      result.push(current);
    } else if (item.type === 'agent_completed') {
      if (current) {
        current.status = 'completed';
        current.summary = String(item.data.summary || current.summary || '');
      }
    } else if (item.type === 'tool_call_started' || item.type === 'tool_call_completed') {
      if (current) current.children.push(item);
    } else if (current && ['artifact_created', 'asset_generated', 'qa_completed', 'revision_started', 'revision_completed'].includes(item.type)) {
      current.children.push(item);
    } else if (['artifact_created', 'asset_generated', 'qa_completed', 'revision_started', 'revision_completed'].includes(item.type)) {
      result.push({
        agentKey: '',
        label: item.type,
        status: item.type === 'pipeline_failed' ? 'failed' : 'completed',
        summary: '',
        children: [item],
      });
    }
  }
  return result;
});

/** 配对 started 与 completed 工具调用 */
function pairedToolCalls(children: PipelineTimelineItem[]) {
  const started = new Map<string, PipelineTimelineItem>();
  const completed = new Map<string, PipelineTimelineItem>();
  for (const item of children) {
    const id = item.data.tool_call_id || String(item.id);
    if (item.type === 'tool_call_started') started.set(id, item);
    else if (item.type === 'tool_call_completed') completed.set(id, item);
  }
  return [...started.entries()].map(([id, s]) => ({ started: s, done: completed.get(id) }));
}

/** 提取文本中可能提到的页码，如“第 3 页” */
function extractSlideTarget(text: string): number | null {
  const match = text.match(/第\s*(\d+)\s*页/);
  if (match && match[1]) {
    const pageNum = parseInt(match[1], 10);
    return pageNum > 0 ? pageNum - 1 : null;
  }
  return null;
}

function handleSelectSlide(index: number) {
  emit('select-slide', index);
}

function handleScroll() {
  if (!scrollRef.value) return;
  const { scrollTop, scrollHeight, clientHeight } = scrollRef.value;
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
  isUserScrolledUp.value = distanceFromBottom > 60;
  if (!isUserScrolledUp.value) {
    unreadCount.value = 0;
  }
}

function scrollToBottom(smooth = true) {
  nextTick(() => {
    if (scrollRef.value) {
      scrollRef.value.scrollTo({
        top: scrollRef.value.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto',
      });
      isUserScrolledUp.value = false;
      unreadCount.value = 0;
    }
  });
}

watch(
  () => [props.items.length, props.task?.messages?.length],
  () => {
    if (!isUserScrolledUp.value) {
      scrollToBottom();
    } else {
      unreadCount.value += 1;
    }
  },
  { deep: true },
);

// 思考增量持续到达时自动滚动到底部
watch(
  () => props.agentThoughts,
  () => {
    if (!isUserScrolledUp.value) {
      scrollToBottom();
    } else {
      unreadCount.value += 1;
    }
  },
  { deep: true },
);

/** 统一对话时间线：交替合并教师指令 (右侧) 与 Agent 运行链 (左侧) */
interface ConversationUserStep {
  kind: 'user';
  id: string;
  content: string;
  count: number;
  status: string;
  slideTarget: number | null;
}

interface ConversationAgentStep {
  kind: 'agent';
  id: string;
  run: (typeof runs.value)[number];
}

type ConversationStep = ConversationUserStep | ConversationAgentStep;

const conversationThread = computed<ConversationStep[]>(() => {
  const steps: ConversationStep[] = [];
  const userMsgs = groupedUserMessages.value;
  const agentRuns = runs.value;

  const maxLen = Math.max(userMsgs.length, agentRuns.length);

  for (let i = 0; i < maxLen; i++) {
    if (i < userMsgs.length) {
      const msg = userMsgs[i];
      steps.push({
        kind: 'user',
        id: `user-${msg.id || i}`,
        content: msg.content,
        count: msg.count,
        status: msg.status,
        slideTarget: extractSlideTarget(msg.content),
      });
    }

    if (i < agentRuns.length) {
      const run = agentRuns[i];
      steps.push({
        kind: 'agent',
        id: `agent-${i}`,
        run,
      });
    }
  }

  return steps;
});
</script>

<template>
  <div class="execution-timeline-container">
    <div ref="scrollRef" class="timeline-viewport" @scroll="handleScroll">
      <!-- 统一的对话时间线 (左 Agent / 右 教师) -->
      <div v-if="conversationThread.length" class="chat-thread">
        <template v-for="step in conversationThread" :key="step.id">
          <!-- 右侧：教师修改指令 (User Message) -->
          <div v-if="step.kind === 'user'" class="chat-row user-row">
            <div class="user-bubble-wrapper">
              <div class="user-header">
                <span class="user-name">教师</span>
                <span class="user-avatar">师</span>
              </div>
              <div class="user-bubble">
                <div class="user-text">{{ step.content }}</div>
                <div v-if="step.count > 1 || step.slideTarget !== null" class="user-bubble-actions">
                  <span v-if="step.count > 1" class="repeat-chip" title="相同要求被重复提交">
                    重复提交 {{ step.count }} 次
                  </span>
                  <button
                    v-if="step.slideTarget !== null"
                    type="button"
                    class="slide-jump-chip"
                    @click="handleSelectSlide(step.slideTarget)"
                  >
                    🎯 定位至第 {{ step.slideTarget + 1 }} 页
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 左侧：Agent 多轮推演与工具链 (Agent Execution Run) -->
          <div v-else-if="step.kind === 'agent'" class="chat-row agent-row">
            <div class="agent-card-wrapper">
              <AgentRunCard
                v-if="step.run.agentKey"
                :agent-key="step.run.agentKey"
                :status="step.run.status"
                :summary="step.run.summary"
              >
                <ThinkingBlock
                  v-if="agentThoughts?.[step.run.agentKey]"
                  :text="agentThoughts[step.run.agentKey]"
                  :active="step.run.status === 'running'"
                />
                <template v-for="pair in pairedToolCalls(step.run.children)" :key="pair.started.id">
                  <ToolCallCard
                    v-if="pair.started"
                    :tool-name="pair.started.data.tool_name || ''"
                    :agent-key="pair.started.data.agent_key || ''"
                    :input="resolveToolCall(String(pair.started.data.tool_call_id))?.input || pair.started.data.input || {}"
                    :output="resolveToolCall(String(pair.started.data.tool_call_id))?.output || (pair.done ? pair.done.data : {}) || {}"
                    :ok="pair.done ? pair.done.data.ok !== false : true"
                    :error="pair.done?.data.error || undefined"
                    :duration-ms="resolveToolCall(String(pair.started.data.tool_call_id))?.duration_ms || pair.done?.data.duration_ms"
                  />
                </template>
                <ArtifactEventCard
                  v-for="item in step.run.children.filter(c => !c.type.startsWith('tool_call'))"
                  :key="item.id"
                  :type="item.type"
                  :data="item.data"
                  @click="item.data.slide_index !== undefined ? handleSelectSlide(item.data.slide_index) : null"
                />
              </AgentRunCard>

              <ArtifactEventCard
                v-else
                :type="step.run.label"
                :data="step.run.children[0]?.data || {}"
                @click="step.run.children[0]?.data?.slide_index !== undefined ? handleSelectSlide(step.run.children[0].data.slide_index) : null"
              />
            </div>
          </div>
        </template>
      </div>

      <!-- 空状态 -->
      <div v-else class="empty-runs-box">
        <el-icon class="empty-icon"><Cpu /></el-icon>
        <p>教学 Agent 多轮协作推演就绪</p>
        <small>请在下方输入修改指令，Agent 将在此推演生成与修改课件。</small>
      </div>
    </div>

    <!-- 悬浮回到最新回复按钮 -->
    <button
      v-if="isUserScrolledUp"
      type="button"
      class="scroll-bottom-btn"
      @click="scrollToBottom(true)"
    >
      <el-icon><ArrowDown /></el-icon>
      <span>回到最新推演</span>
      <span v-if="unreadCount > 0" class="unread-badge">{{ unreadCount }}</span>
    </button>
  </div>
</template>

<style scoped>
.execution-timeline-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
  background: #f8fafc;
}

.timeline-viewport {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-thread {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
}

.chat-row {
  display: flex;
  width: 100%;
}

/* 右侧：教师指令 */
.chat-row.user-row {
  justify-content: flex-end;
}

.user-bubble-wrapper {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  max-width: 88%;
  gap: 4px;
}

.user-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-name {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.user-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  color: #ffffff;
  font-size: 10.5px;
  font-weight: 900;
  display: grid;
  place-items: center;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.25);
}

.user-bubble {
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
  color: #ffffff;
  padding: 10px 14px;
  border-radius: 16px 16px 4px 16px;
  box-shadow: 0 3px 12px rgba(79, 70, 229, 0.2);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.user-text {
  font-size: 13.5px;
  line-height: 1.55;
  font-weight: 600;
  word-break: break-word;
  color: #ffffff;
}

.user-bubble-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.repeat-chip {
  font-size: 10.5px;
  font-weight: 700;
  color: #fef3c7;
  background: rgba(255, 255, 255, 0.2);
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.slide-jump-chip {
  font-size: 10.5px;
  font-weight: 700;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.35);
  padding: 2px 8px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 150ms ease;
}

.slide-jump-chip:hover {
  background: rgba(255, 255, 255, 0.4);
  transform: translateY(-1px);
}

/* 左侧：Agent 推演卡片 */
.chat-row.agent-row {
  justify-content: flex-start;
  width: 100%;
}

.agent-card-wrapper {
  width: 100%;
  max-width: 100%;
}

.empty-runs-box {
  background: #ffffff;
  border: 1.5px dashed #cbd5e1;
  border-radius: 14px;
  padding: 32px 16px;
  text-align: center;
  color: #64748b;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.empty-icon {
  font-size: 28px;
  color: #94a3b8;
}

.empty-runs-box p {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

.empty-runs-box small {
  font-size: 11px;
  color: #94a3b8;
  max-width: 260px;
  line-height: 1.4;
}

.scroll-bottom-btn {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: #0f172a;
  color: #ffffff;
  border: 0;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.25);
  transition: all 180ms ease;
  z-index: 10;
}

.scroll-bottom-btn:hover {
  background: #1e293b;
  transform: translateX(-50%) translateY(-2px);
}

.unread-badge {
  background: #ef4444;
  color: #ffffff;
  font-size: 10px;
  font-weight: 900;
  padding: 0 6px;
  border-radius: 999px;
}
</style>
