<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Promotion, ArrowDownBold } from '@element-plus/icons-vue';
import AgentRunCard from './AgentRunCard.vue';
import ToolCallCard from './ToolCallCard.vue';
import ArtifactEventCard from './ArtifactEventCard.vue';
import type { PipelineTimelineItem } from '../../../stores/pipeline';
import type { CourseTask, ProjectAgentMessage } from '../../../types';
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';

const props = defineProps<{
  items: PipelineTimelineItem[];
  task: CourseTask | null;
  toolCalls: Array<{ id: string; input: Record<string, any>; output: Record<string, any>; status: string; duration_ms: number; error: any }>;
}>();

const emit = defineEmits<{ (e: 'send', content: string): void }>();
const input = ref('');

function isAgentRun(run: any) {
  return Boolean(run.agentKey);
}

function resolveToolCall(id: string) {
  return props.toolCalls.find(call => call.id === id);
}

/** 把时间线条目分组为「Agent 运行」：agent_started 起，agent_completed 止，中间挂工具调用/事件 */
const runs = computed(() => {
  const result: Array<{ agentKey: string; label: string; status: 'running' | 'completed' | 'failed'; summary: string; children: PipelineTimelineItem[] }> = [];
  let current: (typeof result)[number] | null = null;
  for (const item of props.items) {
    if (item.type === 'agent_started') {
      current = {
        agentKey: item.data.agent_key || '',
        label: item.data.agent_label || item.data.agent_key || '',
        status: 'running',
        summary: item.data.message || '',
        children: [],
      };
      result.push(current);
    } else if (item.type === 'agent_completed') {
      if (current) {
        current.status = 'completed';
        current.summary = item.data.summary || current.summary;
      }
    } else if (item.type === 'tool_call_started') {
      if (current) current.children.push(item);
    } else if (item.type === 'tool_call_completed') {
      if (current) current.children.push(item);
    } else if (current && ['artifact_created', 'asset_generated', 'qa_completed', 'revision_started', 'revision_completed'].includes(item.type)) {
      current.children.push(item);
    } else {
      result.push({
        agentKey: '', label: item.type,
        status: item.type === 'pipeline_failed' ? 'failed' : 'completed',
        summary: '', children: [item],
      });
    }
  }
  return result;
});

/** 配对被合并的 started/completed 工具调用 */
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

function send() {
  const content = input.value.trim();
  if (!content) return;
  emit('send', content);
  input.value = '';
}

const scrollRef = ref<HTMLElement | null>(null);
watch(() => props.items.length, () => {
  requestAnimationFrame(() => {
    if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight;
  });
});
</script>

<template>
  <div class="timeline">
    <div class="timeline-scroll" ref="scrollRef">
      <!-- 用户消息 -->
      <div v-for="message in (task?.messages || []).filter((m: ProjectAgentMessage) => m.role === 'user')" :key="message.id" class="user-message">
        <span class="user-badge">我</span>
        <div class="user-bubble">{{ message.content }}</div>
      </div>
      <template v-for="(run, index) in runs" :key="index">
        <AgentRunCard v-if="isAgentRun(run)"
                      :agent-key="run.agentKey" :status="run.status" :summary="run.summary">
          <template v-for="pair in pairedToolCalls(run.children)" :key="pair.started.id">
            <ToolCallCard v-if="pair.started"
                          :tool-name="pair.started.data.tool_name || ''"
                          :agent-key="pair.started.data.agent_key || ''"
                          :input="resolveToolCall(String(pair.started.data.tool_call_id))?.input || pair.started.data.input || {}"
                          :output="resolveToolCall(String(pair.started.data.tool_call_id))?.output || (pair.done ? pair.done.data : {}) || {}"
                          :ok="pair.done ? pair.done.data.ok !== false : true"
                          :error="pair.done?.data.error || undefined"
                          :duration-ms="resolveToolCall(String(pair.started.data.tool_call_id))?.duration_ms || pair.done?.data.duration_ms" />
          </template>
          <ArtifactEventCard v-for="item in run.children.filter(c => !c.type.startsWith('tool_call'))"
                             :key="item.id" :type="item.type" :data="item.data" />
        </AgentRunCard>
        <ArtifactEventCard v-else :type="run.label" :data="run.children[0]?.data || {}" />
      </template>
      <div v-if="!items.length" class="empty">
        <p>PPT 多 Agent 流水线尚未运行。</p>
        <p class="hint">任务启动后将在这里实时展示每个 Agent 的执行过程与工具调用。</p>
      </div>
    </div>
    <div class="composer">
      <el-input v-model="input" type="textarea" :rows="2" resize="none" placeholder="执行过程中可随时追加指令，如：第 3 页不要人物图片，改成架构图…" @keydown.enter.exact.prevent="send" />
      <el-button type="primary" :disabled="!input.trim()" @click="send">
        <el-icon><Promotion /></el-icon>&nbsp;发送指令
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.timeline { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.timeline-scroll { flex: 1; overflow-y: auto; padding: 16px; }
.user-message { display: flex; gap: 8px; margin: 8px 0; }
.user-badge {
  width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
  background: #4f46e5; color: #fff; font-size: 12px;
  display: inline-flex; align-items: center; justify-content: center;
}
.user-bubble {
  background: #eef2ff; border-radius: 10px; padding: 8px 12px;
  font-size: 13px; color: #1f2937; max-width: 70%;
}
.empty { text-align: center; color: #9ca3af; padding: 60px 20px; font-size: 13px; }
.empty .hint { margin-top: 6px; font-size: 12px; }
.composer { padding: 10px 14px; border-top: 1px solid var(--border, #eef0f3); display: flex; gap: 8px; align-items: flex-end; }
.composer .el-input { flex: 1; }
</style>
