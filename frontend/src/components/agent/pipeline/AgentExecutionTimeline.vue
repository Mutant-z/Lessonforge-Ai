<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { buildAgentTurns } from '../../../composables/useAgentStream';
import type { AgentStreamNode } from '../../../composables/useAgentStream';
import type { PipelineTimelineItem } from '../../../stores/pipeline';
import type { CourseTask } from '../../../types';
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';

const props = defineProps<{
  items: PipelineTimelineItem[];
  task: CourseTask | null;
  toolCalls: Array<{ id: string; input: Record<string, any>; output: Record<string, any>; status: string; duration_ms: number; error: any }>;
  isRunning?: boolean;
  agentThoughts?: Record<string, string>;
  agentStatusTexts?: Record<string, string>;
}>();

const emit = defineEmits<{
  (e: 'select-slide', slideIndex: number): void;
  (e: 'human-response', requestId: string, choice: string): void;
}>();

const scrollRef = ref<HTMLElement | null>(null);
const isUserScrolledUp = ref(false);
const unreadCount = ref(0);
const expandedTools = ref<Set<string>>(new Set());
const expandedEvents = ref<Set<string>>(new Set());
let lastUnreadMessageId = '';

/** Codex 式 Turn：教师指令、执行轨迹、最终回复不会跨轮混排。 */
const turns = computed(() =>
  buildAgentTurns(
    props.items,
    props.agentThoughts || {},
    props.task?.messages || [],
  ),
);

const agentName = computed(() => props.task?.agent_name || '教学 Agent');

/** 只有实际显示的 user/reply 正文变化，才属于“新消息”。 */
const visibleMessageSignature = computed(() => turns.value.flatMap(turn => [
  ...turn.users.map(node => `${node.id}:${node.content}`),
  ...turn.replies.map(node => `${node.id}:${node.streaming}:${node.content}`),
]).join('|'));

const latestVisibleMessageId = computed(() => {
  const nodes = turns.value.flatMap(turn => [...turn.users, ...turn.replies]);
  return nodes[nodes.length - 1]?.id || '';
});

/** Trace 更新可以跟随滚动，但不产生未读消息。 */
const traceSignature = computed(() => turns.value.map(turn => turn.trace.map(node => {
  if (node.kind === 'thought') return `${node.id}:${node.active}:${thoughtText(node)}`;
  if (node.kind === 'tool') return `${node.id}:${node.running}:${node.ok}`;
  return node.id;
}).join(',')).join('|'));

/** 执行摘要：优先 timeline 自带正文，低延迟 thought Store 与历史 status Store 兜底。 */
function thoughtText(node: Extract<AgentStreamNode, { kind: 'thought' }>): string {
  return node.content || props.agentThoughts?.[node.thoughtKey] || props.agentStatusTexts?.[node.agentKey] || '';
}

function summarize(value: any, limit: number): string {
  if (value == null) return '';
  let text = '';
  try {
    text = JSON.stringify(value);
  } catch {
    text = String(value);
  }
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}…`;
}

function toggleTool(id: string) {
  const next = new Set(expandedTools.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedTools.value = next;
}

/** QA / 修复类事件：可展开查看 severity/rule/message 明细 */
const ISSUE_EVENT_TYPES = new Set([
  'qa_issue_found', 'qa.issue', 'qa_completed', 'qa.completed',
  'repair.started', 'revision_started',
]);

const SEVERITY_LABELS: Record<string, string> = { critical: '严重', major: '主要', minor: '次要' };

function isIssueEvent(type: string): boolean {
  return ISSUE_EVENT_TYPES.has(type);
}

function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity] || severity || '问题';
}

interface IssueDetail { severity: string; rule_id: string; message: string; slide_id: string }

function eventIssues(node: Extract<AgentStreamNode, { kind: 'event' }>): IssueDetail[] {
  const d = node.data;
  const payload = d.payload && typeof d.payload === 'object' ? d.payload : {};
  const candidates: unknown[] = [];
  if (Array.isArray(payload.issues)) candidates.push(...payload.issues);
  if (payload.issue && typeof payload.issue === 'object') candidates.push(payload.issue);
  if (d.issue && typeof d.issue === 'object') candidates.push(d.issue);
  if (Array.isArray(d.issues)) candidates.push(...d.issues);
  return candidates
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map(item => ({
      severity: String(item.severity || ''),
      rule_id: String(item.rule_id || ''),
      message: String(item.message || ''),
      slide_id: String(item.slide_id || ''),
    }))
    .filter(detail => detail.message || detail.rule_id);
}

function toggleEvent(node: Extract<AgentStreamNode, { kind: 'event' }>) {
  const next = new Set(expandedEvents.value);
  if (next.has(node.id)) next.delete(node.id);
  else next.add(node.id);
  expandedEvents.value = next;
}

function slideIndexFor(node: Extract<AgentStreamNode, { kind: 'event' }>): number | null {
  const v = node.data.slide_index;
  if (typeof v === 'number') return v;
  const page = node.data.slide?.page;
  if (typeof page === 'number') return page;
  return null;
}

function handleEventClick(node: Extract<AgentStreamNode, { kind: 'event' }>) {
  if (isIssueEvent(node.type)) {
    toggleEvent(node);
    return;
  }
  const idx = slideIndexFor(node);
  if (idx !== null) emit('select-slide', idx);
}

function eventIcon(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  switch (node.type) {
    case 'artifact_created': case 'artifact_started': case 'artifact_patch': return '📄';
    case 'asset_generated': return '🖼';
    case 'qa_completed': case 'qa_issue_found': case 'qa.issue': case 'qa.completed': return '🧪';
    case 'revision_started': case 'revision_completed': case 'repair.started': case 'repair.completed': return '🔄';
    case 'skill.discovered': case 'skill.loaded': case 'skill.completed': return '🧩';
    case 'agent.handoff': return '↪';
    case 'human.required': return '🙋';
    case 'task_paused': case 'run.paused': return '⏸';
    case 'task_resumed': case 'run.resumed': return '▶';
    default: return '·';
  }
}

function eventLabel(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  const d = node.data;
  switch (node.type) {
    case 'artifact_created':
      return `产出 ${d.artifact_type || '产物'}${d.version ? ` v${d.version}` : ''}`;
    case 'artifact_started':
      return `开始生成 ${d.artifact_type || '草稿'}`;
    case 'artifact_patch':
      return `草稿已更新${d.summary ? `：${d.summary}` : ''}`;
    case 'asset_generated':
      return d.degraded
        ? `图片模型不可用，已生成替代图${d.degraded_reason ? `：${d.degraded_reason}` : ''}`
        : `已生成视觉素材 ${d.file_path || ''}`;
    case 'qa_completed': case 'qa.completed': {
      const sev = d.severity_counts || d.payload?.severity_counts || {};
      return d.message || `视觉 QA 评分 ${d.score ?? d.payload?.score ?? '-'} · 严重${sev.critical || 0}/主要${sev.major || 0}/次要${sev.minor || 0}`;
    }
    case 'qa_issue_found': case 'qa.issue':
      return `发现 QA 问题：${d.issue?.message || d.payload?.issue?.message || ''}`;
    case 'revision_started': case 'repair.started':
      return d.message || `自动修订（第 ${d.round ?? d.payload?.round ?? 1}/${d.max_rounds ?? d.payload?.max_rounds ?? '?'} 轮）${d.reason || ''}`;
    case 'revision_completed': case 'repair.completed':
      return d.message || `修订完成（第 ${d.round ?? d.payload?.round ?? ''} 轮）`;
    case 'plan.created': return d.message || '已创建动态执行计划';
    case 'skill.discovered': return `发现 Skill：${d.payload?.name || ''}`;
    case 'skill.loaded': return `已加载 Skill：${d.payload?.name || ''}`;
    case 'skill.completed': return d.message || `Skill ${d.payload?.name || ''} 已完成`;
    case 'agent.handoff': return d.message || `Agent 已交接给 ${d.payload?.to || '下一位 Agent'}`;
    case 'human.required': return d.message || '需要教师确认';
    case 'task_paused': case 'run.paused': return d.message || '运行已暂停，可点击顶部“继续”恢复';
    case 'task_resumed': case 'run.resumed': return d.message || '运行已继续';
    case 'run.failed': return `运行失败：${d.message || d.payload?.error?.message || '请重试'}`;
    case 'run.cancelled': return '运行已取消，未完成草稿已撤销';
    default:
      return node.type;
  }
}

function handleScroll() {
  if (!scrollRef.value) return;
  const { scrollTop, scrollHeight, clientHeight } = scrollRef.value;
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
  isUserScrolledUp.value = distanceFromBottom > 60;
  if (!isUserScrolledUp.value) {
    unreadCount.value = 0;
    lastUnreadMessageId = '';
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
      lastUnreadMessageId = '';
    }
  });
}

function notifyVisibleMessage() {
  if (!isUserScrolledUp.value) {
    scrollToBottom();
  } else {
    const messageId = latestVisibleMessageId.value;
    if (messageId && messageId !== lastUnreadMessageId) {
      unreadCount.value += 1;
      lastUnreadMessageId = messageId;
    }
  }
}

watch(visibleMessageSignature, notifyVisibleMessage, { flush: 'post' });
watch(traceSignature, () => {
  if (!isUserScrolledUp.value) scrollToBottom(false);
}, { flush: 'post' });
</script>

<template>
  <div class="term-container">
    <div ref="scrollRef" class="term-viewport" @scroll="handleScroll">
      <div v-if="turns.length" class="term-stream">
        <article v-for="(turn, turnIndex) in turns" :key="turn.id" class="term-turn">
          <div v-for="node in turn.users" :key="node.id" class="message-row user-row">
            <div class="message-identity user-identity">
              <span class="identity-name">教师</span>
              <span class="identity-avatar user-avatar">师</span>
            </div>
            <div class="message-bubble user-bubble">
              <span>{{ node.content }}</span>
              <span v-if="node.status === 'pending'" class="message-delivery">发送中…</span>
              <span v-else-if="node.status === 'failed'" class="message-delivery failed">发送失败，请重试</span>
            </div>
          </div>

          <div v-if="turn.trace.length || turn.replies.length" class="message-row assistant-row">
            <div class="message-identity assistant-identity">
              <span class="identity-avatar agent-avatar">✦</span>
              <span class="identity-name">{{ agentName }}</span>
            </div>
            <div class="assistant-content">
              <details
                v-if="turn.trace.length"
                class="term-execution"
                :open="turnIndex === turns.length - 1"
              >
              <summary class="term-session">
                <span class="term-session-chevron" aria-hidden="true">›</span>
                <span class="term-session-mark">◈</span>
                <span class="term-session-name">执行过程</span>
                <span class="term-session-count">{{ Math.max(0, turn.trace.length - 1) }} 项</span>
              </summary>
              <template v-for="node in turn.trace" :key="node.id">
          <!-- 思考流（默认展开，灰色等宽） -->
          <div v-if="node.kind === 'thought'" class="term-line term-thought">
            <span v-if="node.active" class="term-label">思考</span>
            <span class="term-thought-text">{{ thoughtText(node) }}</span>
            <i v-if="node.active && thoughtText(node)" class="term-caret" aria-hidden="true" />
          </div>

          <!-- 工具行 -->
          <div v-else-if="node.kind === 'tool'" class="term-line term-tool">
            <button type="button" class="term-tool-head" @click="toggleTool(node.id)">
              <span class="term-arrow">→</span>
              <span class="term-tool-name">{{ node.toolName }}</span>
              <span v-if="summarize(node.input, 120)" class="term-tool-arg">{{ summarize(node.input, 120) }}</span>
              <span v-if="node.running" class="term-status running">⏳ 执行中</span>
              <span v-else-if="node.ok" class="term-status ok">✓ {{ node.durationMs }}ms</span>
              <span v-else class="term-status fail">✗ {{ node.error || '失败' }}</span>
            </button>
            <pre v-if="expandedTools.has(node.id)" class="term-tool-json">{{
              JSON.stringify({ input: node.input, output: node.output }, null, 2)
            }}</pre>
          </div>

          <!-- 事件行 -->
          <div
            v-else-if="node.kind === 'event'"
            class="term-line term-event"
            :class="{
              clickable: slideIndexFor(node) !== null || isIssueEvent(node.type),
              expandable: isIssueEvent(node.type),
              expanded: expandedEvents.has(node.id),
            }"
            @click="handleEventClick(node)"
          >
            <span class="term-event-icon">{{ eventIcon(node) }}</span>
            <span class="term-event-text">{{ eventLabel(node) }}</span>
            <span v-if="isIssueEvent(node.type) && eventIssues(node).length" class="event-issue-badges">
              <span
                v-for="issue in eventIssues(node).slice(0, 3)"
                :key="`${issue.rule_id}-${issue.message}`"
                class="sev-badge"
                :class="issue.severity"
              >
                {{ severityLabel(issue.severity) }}
              </span>
              <span v-if="eventIssues(node).length > 3" class="sev-more">+{{ eventIssues(node).length - 3 }}</span>
            </span>
            <span v-if="slideIndexFor(node) !== null" class="term-jump">🎯 第 {{ slideIndexFor(node)! + 1 }} 页</span>
            <span v-if="isIssueEvent(node.type) && eventIssues(node).length" class="expand-caret" aria-hidden="true">
              {{ expandedEvents.has(node.id) ? '▾' : '▸' }}
            </span>
            <span v-if="node.type === 'human.required'" class="human-options">
              <button v-for="option in node.data.payload?.options || []" :key="option.id" type="button"
                      @click.stop="emit('human-response', node.data.payload?.request_id, option.id)">
                {{ option.label }}
              </button>
            </span>
          </div>
          <div
            v-if="node.kind === 'event' && isIssueEvent(node.type) && expandedEvents.has(node.id)"
            class="event-issue-detail"
          >
            <div v-for="(issue, issueIndex) in eventIssues(node)" :key="issueIndex" class="issue-row">
              <span class="sev-badge" :class="issue.severity">{{ severityLabel(issue.severity) }}</span>
              <code class="issue-rule">{{ issue.rule_id || '—' }}</code>
              <span class="issue-message">{{ issue.message }}</span>
              <span v-if="issue.slide_id" class="issue-slide">#{{ issue.slide_id }}</span>
            </div>
            <div v-if="!eventIssues(node).length" class="issue-row empty">该事件没有附带问题明细。</div>
          </div>

              </template>
              </details>

              <div v-for="node in turn.replies" v-show="Boolean(node.content)" :key="node.id" class="message-bubble assistant-bubble">
                <MarkdownRenderer :content="node.content" :is-streaming="node.streaming" />
                <i v-if="node.streaming" class="term-caret" aria-hidden="true" />
              </div>
            </div>
          </div>
        </article>
      </div>

      <!-- 空状态 -->
      <div v-else class="term-empty">
        <span class="term-empty-mark">_</span>
        <p>教学 Agent 推演就绪</p>
        <small>在下方输入修改指令，Agent 将在此以流式输出推演过程。</small>
      </div>
    </div>

    <!-- 悬浮回到最新 -->
    <button
      v-if="isUserScrolledUp"
      type="button"
      class="scroll-bottom-btn"
      @click="scrollToBottom(true)"
    >
      <span>{{ unreadCount > 0 ? '↓ 查看新回复' : '↓ 回到最新' }}</span>
      <span v-if="unreadCount > 0" class="unread-badge">{{ unreadCount }}</span>
    </button>
  </div>
</template>

<style scoped>
.term-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
  background: #f7f8fa;
}

.term-viewport {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
}

.term-stream {
  display: flex;
  flex-direction: column;
  gap: 24px;
  width: 100%;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
}

.term-turn {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}

.term-turn + .term-turn {
  padding-top: 8px;
}

.message-row {
  display: flex;
  flex-direction: column;
  max-width: 90%;
  min-width: 0;
}

.user-row {
  align-self: flex-end;
  align-items: flex-end;
}

.assistant-row {
  align-self: flex-start;
  align-items: flex-start;
}

.message-identity {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.identity-name {
  color: #64748b;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-size: 11px;
  font-weight: 750;
}

.identity-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #ffffff;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-size: 11px;
  font-weight: 800;
}

.user-avatar { background: linear-gradient(135deg, #3b82f6, #2563eb); }
.agent-avatar { background: linear-gradient(135deg, #6366f1, #4f46e5); }

.message-bubble {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 13px;
  line-height: 1.65;
  word-break: break-word;
}

.user-bubble {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  max-width: 100%;
  padding: 10px 14px;
  color: #ffffff;
  white-space: pre-wrap;
  background: linear-gradient(135deg, #4f46e5, #4338ca);
  border-radius: 16px 16px 4px 16px;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.18);
}

.message-delivery {
  color: rgba(255, 255, 255, 0.68);
  font-size: 10px;
  line-height: 1.2;
}

.message-delivery.failed {
  color: #fecaca;
  font-weight: 700;
}

.assistant-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.assistant-bubble {
  padding: 12px 15px;
  color: #1f2937;
  background: #ffffff;
  border: 1px solid #dbe3ed;
  border-radius: 4px 16px 16px 16px;
  box-shadow: 0 2px 7px rgba(15, 23, 42, 0.04);
}

.term-execution {
  padding: 4px 8px 4px 10px;
  border-left: 2px solid #e2e8f0;
}

.term-execution:not([open]) {
  border-left-color: transparent;
}

.term-line {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 2px 4px;
  border-radius: 4px;
  word-break: break-word;
}

/* —— 会话头 —— */
.term-session {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0 0 4px;
  padding: 3px 4px;
  color: #334155;
  font-weight: 800;
  font-size: 12px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.term-session::-webkit-details-marker { display: none; }

.term-session-mark {
  color: #4f46e5;
}

.term-session-chevron {
  display: inline-block;
  color: #64748b;
  font-size: 16px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 160ms ease;
}

.term-execution[open] .term-session-chevron {
  transform: rotate(90deg);
}

.term-session-name {
  letter-spacing: 0.2px;
}

.term-session-count {
  color: #94a3b8;
  font-weight: 600;
}

/* —— 思考流 —— */
.term-thought {
  color: #6b7280;
  margin: 2px 0 2px 10px;
  padding-left: 4px;
  white-space: pre-wrap;
}

.term-label {
  color: #9ca3af;
  font-weight: 700;
  flex-shrink: 0;
  margin-right: 2px;
}

.term-thought-text {
  color: #6b7280;
}

.term-caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: #4f46e5;
  animation: caret-blink 1s step-end infinite;
  flex-shrink: 0;
}

@keyframes caret-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* —— 工具行 —— */
.term-tool-head {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 0;
  background: transparent;
  padding: 2px 4px;
  font-family: inherit;
  font-size: inherit;
  color: inherit;
  cursor: pointer;
  text-align: left;
  width: 100%;
}

.term-arrow {
  color: #4f46e5;
  font-weight: 900;
}

.term-tool-name {
  font-weight: 700;
  color: #1e293b;
}

.term-tool-arg {
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
  flex-shrink: 1;
}

.term-status {
  margin-left: auto;
  font-weight: 700;
  flex-shrink: 0;
}

.term-status.running {
  color: #f59e0b;
}

.term-status.ok {
  color: #16a34a;
}

.term-status.fail {
  color: #dc2626;
}

.term-tool-json {
  margin: 2px 0 4px 24px;
  padding: 8px 10px;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre;
}

/* —— 事件行 —— */
.term-event {
  color: #475569;
  cursor: default;
}

.term-event.clickable {
  cursor: pointer;
}

.term-event.clickable:hover {
  background: #eef2ff;
}

.term-event.expandable.expanded {
  background: #f5f3ff;
}

.term-event-icon {
  flex-shrink: 0;
}

.term-event-text {
  color: #475569;
}

.term-jump {
  color: #4f46e5;
  font-weight: 700;
  margin-left: auto;
  flex-shrink: 0;
}

/* —— QA / 修复事件明细 —— */
.event-issue-badges {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  flex-shrink: 0;
}

.sev-badge {
  font-size: 10px;
  font-weight: 800;
  padding: 0 5px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.sev-badge.critical { color: #b91c1c; background: #fee2e2; }
.sev-badge.major { color: #b45309; background: #fef3c7; }
.sev-badge.minor { color: #1d4ed8; background: #dbeafe; }

.sev-more {
  font-size: 10px;
  font-weight: 800;
  color: #64748b;
}

.expand-caret {
  color: #7c3aed;
  flex-shrink: 0;
  font-size: 11px;
}

.event-issue-detail {
  margin: 2px 0 4px 26px;
  padding: 6px 10px;
  background: #faf5ff;
  border-left: 2px solid #ddd6fe;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.issue-row {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  line-height: 1.5;
}

.issue-row.empty {
  color: #94a3b8;
  font-style: italic;
}

.issue-rule {
  color: #6d28d9;
  background: #ede9fe;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 10px;
  flex-shrink: 0;
}

.issue-message {
  color: #475569;
  word-break: break-word;
}

.issue-slide {
  color: #94a3b8;
  font-size: 10px;
  margin-left: auto;
  flex-shrink: 0;
}

/* —— 空态 —— */
.term-empty {
  padding: 40px 16px;
  text-align: center;
  color: #94a3b8;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;
}

.term-empty-mark {
  font-size: 24px;
  color: #cbd5e1;
  animation: caret-blink 1s step-end infinite;
}

.term-empty p {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
}

.term-empty small {
  font-size: 11px;
  color: #94a3b8;
}

/* —— 回到最新 —— */
.scroll-bottom-btn {
  position: absolute;
  bottom: 14px;
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
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;
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
