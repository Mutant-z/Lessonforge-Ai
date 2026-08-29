<script setup lang="ts">
/**
 * 学习任务单 V3 执行时间线（Codex 式 Turn）：
 * 每个 Turn 顺序展示 教师指令 → 意图摘要 → 计划 → Agent 执行摘要（打字机）
 * → 工具调用卡片 → QA 问题 → 返修过程 → 最终回复。
 *
 * 复用领域无关的 buildAgentTurns（按 run_id 分 Turn），去掉 PPT 的 slide/候选对比耦合，
 * 加入任务单特有事件（意图识别 / 计划 / 澄清 / 差异）渲染。
 */
import { computed, nextTick, ref, watch } from 'vue';
import { Document } from '@element-plus/icons-vue';
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
  (e: 'clear-draft'): void;
}>();

const scrollRef = ref<HTMLElement | null>(null);
const isUserScrolledUp = ref(false);
const unreadCount = ref(0);
const expandedTools = ref<Set<string>>(new Set());
const expandedEvents = ref<Set<string>>(new Set());
let lastUnreadMessageId = '';

const turns = computed(() =>
  buildAgentTurns(
    props.items,
    props.agentThoughts || {},
    props.task?.messages || [],
  ),
);

const agentName = computed(() => props.task?.agent_name || '学习任务单 Agent');

const latestVisibleMessageId = computed(() => {
  const nodes = turns.value.flatMap(turn => [...turn.users, ...turn.replies]);
  return nodes[nodes.length - 1]?.id || '';
});

/** 工具中文名称映射（ts_* 工具） */
const TOOL_LABELS: Record<string, string> = {
  ts_get_context: '读取任务单上下文',
  ts_inspect_sheet: '查看任务单草稿',
  ts_inspect_outline: '查看目录结构',
  ts_initialize_draft: '初始化任务单草稿',
  ts_migrate_to_v3: '迁移为 V3 结构',
  ts_apply_outline_ops: '调整目录结构',
  ts_apply_block_ops: '编辑章节内容',
  ts_validate_draft: '运行质量门禁',
  ts_compute_diff: '计算版本差异',
  ts_render_preview: '渲染预览',
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name;
}

function summarize(value: unknown, limit = 120): string {
  if (value == null) return '';
  try {
    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 0);
    return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
  } catch {
    return String(value);
  }
}

function thoughtText(node: Extract<AgentStreamNode, { kind: 'thought' }>): string {
  return node.content || props.agentThoughts?.[node.thoughtKey] || props.agentStatusTexts?.[node.agentKey] || '';
}

interface IssueDetail { severity: string; dimension: string; message: string; location: string }

function eventPayload(node: Extract<AgentStreamNode, { kind: 'event' }>): Record<string, any> {
  return (node.data?.payload as Record<string, any>) || node.data || {};
}

function isIssueEvent(type: string): boolean {
  return type === 'qa_issue_found' || type === 'qa.issue';
}

function qaIssues(node: Extract<AgentStreamNode, { kind: 'event' }>): IssueDetail[] {
  const raw = node.data?.issue || eventPayload(node).issue || eventPayload(node);
  const issues: IssueDetail[] = [];
  if (Array.isArray(eventPayload(node).issues)) {
    for (const item of eventPayload(node).issues) {
      issues.push({
        severity: String(item.severity || 'major'),
        dimension: String(item.dimension || ''),
        message: String(item.description || item.message || ''),
        location: String(item.location || ''),
      });
    }
  }
  if (raw && typeof raw === 'object') {
    issues.push({
      severity: String((raw as any).severity || 'major'),
      dimension: String((raw as any).dimension || ''),
      message: String((raw as any).message || (raw as any).description || ''),
      location: String((raw as any).location || ''),
    });
  }
  return issues.filter(item => item.message);
}

function severityLabel(severity: string): string {
  return { critical: '阻断', major: '重要', minor: '提示' }[severity] || severity;
}

/** 任务单专属事件：意图识别 / 计划 / 澄清 / 差异 */
function eventIcon(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  switch (node.type) {
    case 'intent.recognized':
    case 'intent.resolved': return '🎯';
    case 'plan.created': return '🗂';
    case 'agent.clarification.required': return '❓';
    case 'artifact.diff': return '⇄';
    case 'qa_issue_found':
    case 'qa.issue': return '⚠';
    case 'qa.completed': return '✔';
    case 'repair.started': return '🔧';
    case 'repair.completed': return '✅';
    case 'artifact_patch': return '📝';
    case 'artifact_created': return '📄';
    case 'polish.result': return '✓';
    case 'task_paused':
    case 'run.paused': return '⏸';
    case 'task_resumed':
    case 'run.resumed': return '▶';
    default: return '•';
  }
}

function eventLabel(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  const payload = eventPayload(node);
  switch (node.type) {
    case 'intent.recognized':
    case 'intent.resolved':
      return `意图识别：${payload.intent || payload.message || '已完成'}`;
    case 'plan.created':
      return `执行计划：${Array.isArray(payload.steps) ? `${payload.steps.length} 个步骤` : payload.message || '已创建'}`;
    case 'agent.clarification.required':
      return payload.question || payload.message || '需要教师补充说明';
    case 'artifact.diff': {
      const diff = payload;
      const added = (diff.added_sections || []).length;
      const removed = (diff.removed_sections || []).length;
      const changed = (diff.changed_sections || []).length + (diff.changed_blocks || []).length;
      return `版本差异：+${added} −${removed} 改${changed}`;
    }
    case 'qa_issue_found':
    case 'qa.issue': {
      const issues = qaIssues(node);
      return `质量检查发现 ${issues.length} 个问题`;
    }
    case 'qa.completed':
      return payload.message || '质量检查完成';
    case 'repair.started':
      return `开始返修（第 ${payload.round || payload.revision || ''} 轮）`;
    case 'repair.completed':
      return '返修完成';
    case 'artifact_patch':
      return `草稿已更新 ${Array.isArray(payload.patch) ? payload.patch.length : 0} 处`;
    case 'artifact_created':
      return payload.message || `已生成 ${payload.artifact_type || '产物'}`;
    case 'polish.result':
      return payload.message || '执行完成';
    case 'task_paused':
    case 'run.paused': return '已暂停';
    case 'task_resumed':
    case 'run.resumed': return '已恢复';
    default:
      return payload.message || String(payload.summary || '') || node.type;
  }
}

function toggleTool(id: string) {
  const next = new Set(expandedTools.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expandedTools.value = next;
}

function toggleEvent(id: string) {
  if (!isIssueEvent(turns.value.flatMap(t => t.trace).find((n): n is Extract<AgentStreamNode, { kind: 'event' }> => n.kind === 'event' && n.id === id)?.type || '')) return;
  const next = new Set(expandedEvents.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expandedEvents.value = next;
}

function eventClickable(node: Extract<AgentStreamNode, { kind: 'event' }>): boolean {
  return isIssueEvent(node.type) || node.type === 'artifact.diff';
}

function eventClicked(node: Extract<AgentStreamNode, { kind: 'event' }>) {
  if (isIssueEvent(node.type)) toggleEvent(node.id);
  if (node.type === 'artifact.diff') toggleEvent(node.id);
}

function issueList(node: Extract<AgentStreamNode, { kind: 'event' }>): IssueDetail[] {
  return qaIssues(node);
}

function scrollToBottom(force = false) {
  if (!scrollRef.value) return;
  if (!force && isUserScrolledUp.value) return;
  nextTick(() => {
    if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight;
  });
}

function handleScroll() {
  if (!scrollRef.value) return;
  const { scrollTop, scrollHeight, clientHeight } = scrollRef.value;
  isUserScrolledUp.value = scrollTop < scrollHeight - clientHeight - 24;
}

watch(
  () => [turns.value.length, latestVisibleMessageId.value],
  () => {
    scrollToBottom();
    const latest = latestVisibleMessageId.value;
    if (latest && latest !== lastUnreadMessageId) {
      lastUnreadMessageId = latest;
    }
  },
  { flush: 'post' },
);

watch(() => props.items.length, () => scrollToBottom());
</script>

<template>
  <div class="ts-term-container">
    <div ref="scrollRef" class="ts-term-viewport" @scroll="handleScroll">
      <div v-if="turns.length" class="ts-term-stream">
        <article v-for="(turn, turnIndex) in turns" :key="turn.id" class="ts-term-turn">
          <div v-for="node in turn.users" :key="node.id" class="ts-message-row ts-user-row">
            <div class="ts-message-identity ts-user-identity">
              <span class="ts-identity-name">教师</span>
              <span class="ts-identity-avatar ts-user-avatar">师</span>
            </div>
            <div class="ts-message-bubble ts-user-bubble">
              <span>{{ node.content }}</span>
              <div v-if="node.attachments.length" class="ts-message-attachments">
                <span v-for="attachment in node.attachments" :key="attachment.id" class="ts-message-attachment">
                  <el-icon><Document /></el-icon>
                  <span>{{ attachment.filename }}</span>
                </span>
              </div>
              <span v-if="node.status === 'pending'" class="ts-message-delivery">发送中…</span>
              <span v-else-if="node.status === 'failed'" class="ts-message-delivery failed">发送失败，请重试</span>
            </div>
          </div>

          <div v-if="turn.trace.length || turn.replies.length" class="ts-message-row ts-assistant-row">
            <div class="ts-message-identity ts-assistant-identity">
              <span class="ts-identity-avatar ts-agent-avatar">✦</span>
              <span class="ts-identity-name">{{ agentName }}</span>
            </div>
            <div class="ts-assistant-content">
              <details
                v-if="turn.trace.length"
                class="ts-term-execution"
                :open="turnIndex === turns.length - 1"
              >
                <summary class="ts-term-session">
                  <span class="ts-term-session-chevron" aria-hidden="true">›</span>
                  <span class="ts-term-session-mark">◈</span>
                  <span class="ts-term-session-name">执行过程</span>
                  <span class="ts-term-session-count">{{ Math.max(0, turn.trace.length - 1) }} 项</span>
                </summary>
                <template v-for="node in turn.trace" :key="node.id">
                  <!-- 可见执行摘要 -->
                  <div v-if="node.kind === 'thought'" class="ts-term-line ts-term-thought">
                    <span v-if="node.active" class="ts-term-label">执行</span>
                    <span class="ts-term-thought-text">{{ thoughtText(node) }}</span>
                    <i v-if="node.active && thoughtText(node)" class="ts-term-caret" aria-hidden="true" />
                  </div>

                  <!-- 工具调用卡片 -->
                  <div v-else-if="node.kind === 'tool'" class="ts-term-line ts-term-tool">
                    <button type="button" class="ts-term-tool-head" @click="toggleTool(node.id)">
                      <span class="ts-term-arrow">→</span>
                      <span class="ts-term-tool-name">{{ toolLabel(node.toolName) }}</span>
                      <span v-if="summarize(node.input, 120)" class="ts-term-tool-arg">{{ summarize(node.input, 120) }}</span>
                      <span v-if="node.running" class="ts-term-status running">⏳ 执行中</span>
                      <span v-else-if="node.ok" class="ts-term-status ok">✓ {{ node.durationMs }}ms</span>
                      <span v-else class="ts-term-status fail">✗ {{ node.error || '失败' }}</span>
                    </button>
                    <pre v-if="expandedTools.has(node.id)" class="ts-term-tool-json">{{
                      JSON.stringify({ input: node.input, output: node.output }, null, 2)
                    }}</pre>
                  </div>

                  <!-- 事件行（意图 / 计划 / QA / 返修 / 差异） -->
                  <div
                    v-else-if="node.kind === 'event'"
                    class="ts-term-line ts-term-event"
                    :class="{
                      clickable: eventClickable(node),
                      expandable: isIssueEvent(node.type) || node.type === 'artifact.diff',
                      expanded: expandedEvents.has(node.id),
                    }"
                    @click="eventClicked(node)"
                  >
                    <span class="ts-term-event-icon">{{ eventIcon(node) }}</span>
                    <span class="ts-term-event-text">{{ eventLabel(node) }}</span>
                    <span v-if="isIssueEvent(node.type) && issueList(node).length" class="ts-event-issue-badges">
                      <span
                        v-for="issue in issueList(node).slice(0, 3)"
                        :key="`${issue.location}-${issue.message}`"
                        class="ts-sev-badge"
                        :class="issue.severity"
                      >
                        {{ severityLabel(issue.severity) }}
                      </span>
                      <span v-if="issueList(node).length > 3" class="ts-sev-more">+{{ issueList(node).length - 3 }}</span>
                    </span>
                    <span v-if="isIssueEvent(node.type) && issueList(node).length" class="ts-expand-caret" aria-hidden="true">
                      {{ expandedEvents.has(node.id) ? '▾' : '▸' }}
                    </span>
                  </div>

                  <!-- 事件展开详情（QA 问题明细 / 版本差异明细） -->
                  <div
                    v-if="node.kind === 'event' && expandedEvents.has(node.id) && isIssueEvent(node.type)"
                    class="ts-event-detail"
                    @click.stop
                  >
                    <div v-for="issue in issueList(node)" :key="`${issue.location}-${issue.message}`" class="ts-issue-row">
                      <span class="ts-issue-sev" :class="issue.severity">{{ severityLabel(issue.severity) }}</span>
                      <span class="ts-issue-dim" v-if="issue.dimension">{{ issue.dimension }}</span>
                      <span class="ts-issue-msg">{{ issue.message }}</span>
                    </div>
                  </div>
                  <div
                    v-if="node.kind === 'event' && expandedEvents.has(node.id) && node.type === 'artifact.diff'"
                    class="ts-event-detail"
                    @click.stop
                  >
                    <div class="ts-diff-line">
                      <span class="ts-diff-badge add">新增</span>
                      <span>{{ (eventPayload(node).added_sections || []).join('、') || '—' }}</span>
                    </div>
                    <div class="ts-diff-line">
                      <span class="ts-diff-badge remove">移除</span>
                      <span>{{ (eventPayload(node).removed_sections || []).join('、') || '—' }}</span>
                    </div>
                    <div class="ts-diff-line">
                      <span class="ts-diff-badge change">修改</span>
                      <span>{{ [...(eventPayload(node).changed_sections || []), ...(eventPayload(node).changed_blocks || [])].join('、') || '—' }}</span>
                    </div>
                  </div>
                </template>
              </details>

              <!-- 最终回复 -->
              <div v-for="node in turn.replies" :key="node.id" class="ts-reply">
                <span v-if="node.streaming && !node.content" class="ts-reply-placeholder">正在组织回复</span>
                <MarkdownRenderer v-else :content="node.content" :is-streaming="node.streaming" />
                <i v-if="node.streaming" class="ts-streaming-caret" aria-hidden="true" />
              </div>
            </div>
          </div>
        </article>
      </div>
      <div v-else class="ts-term-empty">
        <p>还没有执行记录。发送一条修改指令后，这里会实时展示意图识别、工具调用、质量检查与返修过程。</p>
      </div>
    </div>
    <button
      v-if="isUserScrolledUp"
      type="button"
      class="ts-back-to-latest"
      @click="scrollToBottom(true)"
    >
      ↓ 回到最新
    </button>
  </div>
</template>

<style scoped>
.ts-term-container {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.ts-term-viewport {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px 16px;
}
.ts-term-stream {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.ts-term-turn {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ts-message-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.ts-message-identity {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.ts-identity-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.ts-user-avatar { background: #eef2ff; color: #4f46e5; }
.ts-agent-avatar { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; }
.ts-identity-name { font-size: 12px; color: #6b7280; font-weight: 600; }
.ts-message-bubble {
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.6;
  max-width: 85%;
}
.ts-user-bubble { background: #eef2ff; color: #1f2937; }
.ts-message-delivery { font-size: 11px; color: #f59e0b; margin-left: 6px; }
.ts-message-delivery.failed { color: #ef4444; }
.ts-message-attachments { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.ts-message-attachment {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 220px;
  padding: 3px 6px;
  border: 1px solid #c7d2fe;
  border-radius: 7px;
  background: #e0e7ff;
  color: #3730a3;
  font-size: 11px;
}
.ts-message-attachment span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ts-assistant-content { flex: 1; min-width: 0; }
.ts-term-execution {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fafafa;
  margin-bottom: 10px;
}
.ts-term-session {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  cursor: pointer;
  list-style: none;
}
.ts-term-session::-webkit-details-marker { display: none; }
.ts-term-session-chevron { transition: transform 0.15s; color: #9ca3af; }
.ts-term-execution[open] .ts-term-session-chevron { transform: rotate(90deg); }
.ts-term-session-mark { color: #6366f1; }
.ts-term-session-name { font-size: 12px; font-weight: 600; color: #374151; }
.ts-term-session-count { font-size: 11px; color: #9ca3af; margin-left: auto; }
.ts-term-line {
  padding: 6px 10px 6px 30px;
  border-top: 1px solid #f0f0f0;
  font-size: 13px;
}
.ts-term-thought {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  color: #6b7280;
}
.ts-term-label { color: #9ca3af; font-size: 11px; flex-shrink: 0; margin-top: 2px; }
.ts-term-thought-text { white-space: pre-wrap; word-break: break-word; }
.ts-term-caret {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: #6366f1;
  margin-left: 2px;
  animation: ts-blink 1s steps(1) infinite;
}
@keyframes ts-blink { 50% { opacity: 0; } }
.ts-term-tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  padding: 2px 0;
  cursor: pointer;
  font-size: 13px;
  color: #1f2937;
}
.ts-term-arrow { color: #6366f1; }
.ts-term-tool-name { font-weight: 600; }
.ts-term-tool-arg { color: #9ca3af; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 45%; }
.ts-term-status { font-size: 11px; margin-left: auto; flex-shrink: 0; }
.ts-term-status.running { color: #6366f1; }
.ts-term-status.ok { color: #10b981; }
.ts-term-status.fail { color: #ef4444; }
.ts-term-tool-json {
  background: #111827;
  color: #d1d5db;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 11px;
  overflow-x: auto;
  margin-top: 6px;
  max-height: 220px;
  overflow-y: auto;
}
.ts-term-event {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #4b5563;
}
.ts-term-event.clickable { cursor: pointer; }
.ts-term-event-icon { flex-shrink: 0; }
.ts-term-event-text { flex: 1; }
.ts-event-issue-badges { display: flex; gap: 4px; flex-shrink: 0; }
.ts-sev-badge { font-size: 10px; padding: 1px 6px; border-radius: 8px; }
.ts-sev-badge.critical { background: #fee2e2; color: #dc2626; }
.ts-sev-badge.major { background: #fef3c7; color: #d97706; }
.ts-sev-badge.minor { background: #e0e7ff; color: #4f46e5; }
.ts-sev-more { font-size: 10px; color: #9ca3af; }
.ts-expand-caret { color: #9ca3af; flex-shrink: 0; }
.ts-event-detail {
  border-top: 1px solid #f0f0f0;
  padding: 8px 10px 8px 30px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ts-issue-row { display: flex; gap: 8px; align-items: baseline; font-size: 12px; }
.ts-issue-sev { flex-shrink: 0; font-size: 10px; padding: 1px 6px; border-radius: 8px; }
.ts-issue-sev.critical { background: #fee2e2; color: #dc2626; }
.ts-issue-sev.major { background: #fef3c7; color: #d97706; }
.ts-issue-sev.minor { background: #e0e7ff; color: #4f46e5; }
.ts-issue-dim { color: #6366f1; flex-shrink: 0; }
.ts-issue-msg { color: #374151; }
.ts-diff-line { display: flex; gap: 8px; align-items: center; font-size: 12px; }
.ts-diff-badge { font-size: 10px; padding: 1px 6px; border-radius: 8px; flex-shrink: 0; }
.ts-diff-badge.add { background: #d1fae5; color: #059669; }
.ts-diff-badge.remove { background: #fee2e2; color: #dc2626; }
.ts-diff-badge.change { background: #e0e7ff; color: #4f46e5; }
.ts-reply { padding: 8px 0 0; font-size: 14px; line-height: 1.7; }
.ts-reply-placeholder { color: #9ca3af; }
.ts-streaming-caret {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: #6366f1;
  margin-left: 2px;
  animation: ts-blink 1s steps(1) infinite;
}
.ts-term-empty { color: #9ca3af; font-size: 13px; padding: 40px 16px; text-align: center; }
.ts-back-to-latest {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 6px 14px;
  font-size: 12px;
  color: #4f46e5;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  cursor: pointer;
}
</style>
