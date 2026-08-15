import type { PipelineTimelineItem } from '../stores/pipeline';
import type { ProjectAgentMessage } from '../types';

/** Codex 式会话流：一个用户请求对应一个 Turn，执行轨迹和最终回复都归属于该 Turn。 */

export type AgentStreamNode =
  | { kind: 'user'; id: string; content: string; status?: ProjectAgentMessage['status'] } // > 教师指令
  | { kind: 'session'; id: string; runId: string }                                  // ◈ 教学 Agent 会话头
  | { kind: 'thought'; id: string; runId: string; agentKey: string; thoughtKey: string; content: string; active: boolean }  // 灰色可见执行摘要
  | { kind: 'tool'; id: string; runId: string; toolName: string; input: Record<string, any>; output: Record<string, any>; ok: boolean; running: boolean; error?: string | null; errorCode?: string | null; retryable?: boolean; durationMs?: number }
  | { kind: 'event'; id: string; runId: string; type: string; data: Record<string, any> }
  | { kind: 'reply'; id: string; runId: string; content: string; streaming: boolean };

export interface AgentStreamTurn {
  id: string;
  runId: string;
  users: Extract<AgentStreamNode, { kind: 'user' }>[];
  trace: Exclude<AgentStreamNode, { kind: 'user' | 'reply' }>[];
  replies: Extract<AgentStreamNode, { kind: 'reply' }>[];
}

/** 纯底层标记，终端流不展示 */
const IGNORED_TYPES = new Set(['pipeline_started', 'pipeline_completed']);

/** 作为紧凑事件行渲染的领域事件 */
const EVENT_TYPES = new Set([
  'artifact_started', 'artifact_patch', 'artifact_created', 'asset_generated',
  'qa_issue_found', 'qa_completed', 'revision_started', 'revision_completed',
  'plan.created', 'agent.handoff', 'skill.discovered', 'skill.loaded', 'skill.completed', 'skill.failed',
  'artifact.created', 'artifact.updated', 'slide.planned', 'slide.started', 'slide.content.updated',
  'slide.layout.updated', 'slide.asset.updated', 'slide.rendering', 'slide.rendered', 'slide.qa',
  'slide.completed', 'slide.failed', 'qa.started', 'qa.issue', 'repair.started', 'repair.completed',
  'human.required', 'run.instruction.queued', 'run.instruction.merged', 'run.failed', 'run.cancelled',
  'layout.compile.result', 'polish.result',
  'task_paused', 'task_resumed', 'run.paused', 'run.resumed',
  // 学习任务单 V3：意图识别 / 计划 / 澄清 / 差异
  'intent.recognized', 'intent.resolved', 'agent.clarification.required', 'artifact.diff',
  // 教学设计：执行前上下文快照 / 拒绝结果
  'context.snapshot.created', 'result.rejected',
]);

interface StreamSession {
  runId: string;
  nodes: AgentStreamNode[];
  fallbackOrder: number;
  sortAt: number | null;
}

function timestampOf(value: unknown): number | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function recordSessionTime(session: StreamSession, value: unknown) {
  const timestamp = timestampOf(value);
  if (timestamp === null) return;
  session.sortAt = session.sortAt === null ? timestamp : Math.min(session.sortAt, timestamp);
}

function thoughtKey(runId: string, agentKey: string): string {
  return `${runId}:${agentKey}`;
}

/**
 * 生成终端流节点列表。节点按时间顺序（timeline 已按 id 升序）；可见执行摘要
 * 直接累积到 thought 节点，同时保留 thoughtKey 供实时 Store 兜底。
 */
export function buildAgentTurns(
  items: PipelineTimelineItem[],
  _thoughts: Record<string, string>,
  messages: ProjectAgentMessage[],
  historicalToolCalls: Array<{
    id: string; tool_name: string; input: Record<string, any>; output: Record<string, any>;
    status: string; duration_ms: number; error: any; error_code?: string | null;
    error_message?: string | null; retryable?: boolean;
  }> = [],
): AgentStreamTurn[] {
  const sessions: StreamSession[] = [];
  const byRun = new Map<string, StreamSession>();
  let current: StreamSession | null = null;
  let currentAgentKey = '';
  const toolMap = new Map<string, Extract<AgentStreamNode, { kind: 'tool' }>>();
  const thoughtSeen = new Set<string>(); // `${runId}:${agentKey}`，避免兜底重复创建 thought
  const activeThoughts = new Map<string, Extract<AgentStreamNode, { kind: 'thought' }>>();

  for (const item of items) {
    if (IGNORED_TYPES.has(item.type)) continue;
    const runId = String(item.data?.run_id || 'legacy');
    const agentKey = String(item.data?.agent_key || '');

    if (!current || current.runId !== runId) {
      current = byRun.get(runId) || null;
    }
    if (!current) {
      current = {
        runId,
        fallbackOrder: sessions.length,
        sortAt: null,
        nodes: [{ kind: 'session', id: `session-${runId}`, runId }],
      };
      sessions.push(current);
      byRun.set(runId, current);
      currentAgentKey = '';
    }
    recordSessionTime(current, item.created_at || item.data?.created_at || item.data?.timestamp);

    if (item.type === 'agent_started' || item.type === 'agent.started') {
      currentAgentKey = agentKey;
      const key = thoughtKey(runId, agentKey);
      thoughtSeen.add(key);
      // 可见执行摘要节点：status delta 直接追加正文，thought Store 作为低延迟兜底。
      const thought: Extract<AgentStreamNode, { kind: 'thought' }> = {
        kind: 'thought', id: `thought-${runId}-${agentKey}-${item.id}`, runId,
        agentKey, thoughtKey: key, content: '', active: true,
      };
      current.nodes.push(thought);
      activeThoughts.set(key, thought);
      continue;
    }
    if (item.type === 'agent_completed' || item.type === 'agent.completed') {
      let idx = -1;
      for (let i = current.nodes.length - 1; i >= 0; i--) {
        const n = current.nodes[i];
        if (n.kind === 'thought' && n.runId === runId && n.agentKey === agentKey) { idx = i; break; }
      }
      if (idx >= 0) (current.nodes[idx] as Extract<AgentStreamNode, { kind: 'thought' }>).active = false;
      activeThoughts.delete(thoughtKey(runId, agentKey));
      currentAgentKey = '';
      continue;
    }
    if (item.type === 'agent_status_delta' || item.type === 'agent_status_completed') {
      // 状态正文直接保存在节点中。不能只依赖外部 Store：SSE 与详情轮询错序时，
      // Store 可能尚未累积文本，但 timeline 已经创建了节点，最终会显示成空白。
      const key = thoughtKey(runId, agentKey);
      let thought = activeThoughts.get(key);
      if (!thought && thoughtSeen.has(key)) {
        for (let index = current.nodes.length - 1; index >= 0; index -= 1) {
          const candidate = current.nodes[index];
          if (candidate.kind === 'thought' && candidate.thoughtKey === key) {
            thought = candidate;
            break;
          }
        }
      }
      if (!thoughtSeen.has(key)) {
        thoughtSeen.add(key);
        thought = {
          kind: 'thought', id: `thought-${runId}-${agentKey}-status`, runId,
          agentKey, thoughtKey: key, content: '', active: item.type === 'agent_status_delta',
        };
        current.nodes.push(thought);
        activeThoughts.set(key, thought);
      }
      if (thought) {
        const text = String(item.data?.text || item.data?.message || '');
        if (item.type === 'agent_status_completed') {
          if (text) thought.content = text;
          thought.active = false;
          activeThoughts.delete(key);
        } else {
          thought.content += text;
          thought.active = true;
        }
      }
      continue;
    }
    if (item.type === 'tool_call_started' || item.type === 'tool.started') {
      const node: Extract<AgentStreamNode, { kind: 'tool' }> = {
        kind: 'tool', id: `tool-${item.data?.tool_call_id || item.id}`, runId,
        toolName: String(item.data?.tool_name || ''),
        input: (item.data?.input_json as Record<string, any>) || {},
        output: {}, ok: true, running: true,
      };
      toolMap.set(String(item.data?.tool_call_id || item.id), node);
      current.nodes.push(node);
      continue;
    }
    if (item.type === 'tool_call_completed' || item.type === 'tool.completed' || item.type === 'tool.failed') {
      const node = toolMap.get(String(item.data?.tool_call_id || item.id));
      if (node) {
        node.running = false;
        node.ok = item.data?.ok !== false;
        node.output = (item.data?.output_json as Record<string, any>) || {};
        node.error = item.data?.error ?? null;
        node.errorCode = item.data?.error_code ?? null;
        node.durationMs = typeof item.data?.duration_ms === 'number' ? item.data.duration_ms : undefined;
      }
      continue;
    }
    if (EVENT_TYPES.has(item.type)) {
      current.nodes.push({ kind: 'event', id: `event-${item.id}`, runId, type: item.type, data: item.data });
    }
  }

  // 刷新后的详情接口以 tool_calls 为权威来源。它和 SSE 使用相同的扁平
  // 错误字段，既可补齐被裁剪的历史事件，也能覆盖旧事件里的嵌套 error。
  for (const call of historicalToolCalls) {
    const errorObject = call.error && typeof call.error === 'object' ? call.error : {};
    let node = toolMap.get(String(call.id));
    if (!node) {
      let session = sessions[sessions.length - 1];
      if (!session) {
        session = {
          runId: 'legacy', fallbackOrder: 0, sortAt: null,
          nodes: [{ kind: 'session', id: 'session-legacy', runId: 'legacy' }],
        };
        sessions.push(session);
        byRun.set(session.runId, session);
      }
      node = {
        kind: 'tool', id: `tool-${call.id}`, runId: session.runId,
        toolName: call.tool_name, input: call.input || {}, output: call.output || {},
        ok: call.status !== 'failed', running: call.status === 'started',
      };
      session.nodes.push(node);
      toolMap.set(String(call.id), node);
    }
    node.toolName = call.tool_name || node.toolName;
    node.input = call.input || node.input;
    node.output = call.output || node.output;
    node.running = call.status === 'started';
    node.ok = call.status !== 'failed';
    node.error = call.error_message
      || (typeof call.error === 'string' ? call.error : errorObject.message)
      || null;
    node.errorCode = call.error_code || errorObject.code || null;
    node.retryable = call.retryable ?? errorObject.retryable ?? false;
    node.durationMs = call.duration_ms ?? node.durationMs;
  }

  // 对话消息严格归入自己的 run。没有 run_id 的历史消息按相邻 user/assistant 配成独立 Turn。
  let unscoped: StreamSession | null = null;
  for (const msg of messages) {
    const scopedRunId = msg.run_id ? String(msg.run_id) : '';
    let target = scopedRunId ? byRun.get(scopedRunId) : undefined;
    if (scopedRunId && !target) {
      target = { runId: scopedRunId, fallbackOrder: sessions.length, sortAt: null, nodes: [] };
      sessions.push(target);
      byRun.set(scopedRunId, target);
    }
    if (target) recordSessionTime(target, msg.created_at);
    if (msg.role === 'user') {
      const text = (msg.content || '').trim();
      if (!text) continue;
      const userNode: AgentStreamNode = {
        kind: 'user', id: `user-${msg.id}`,
        // 后端 create_run 会加 [目标页面:...]，前端 Composer 单页/多页定位会加
        // [针对第 N 页]；两种范围前缀都不应出现在教师气泡正文里。
        content: msg.content.replace(/^\[(?:目标页面|针对第 [^\]]+页)[^\]]*\]\s*/, ''),
        // Delivery state belongs to the local optimistic envelope. Historical
        // server messages may retain `pending` as their processing status even
        // after the Run completed, which must not be rendered as “发送中”.
        status: msg.id.startsWith('local-') ? msg.status : undefined,
      };
      if (target) {
        const firstTrace = target.nodes.findIndex(node => node.kind !== 'user');
        target.nodes.splice(firstTrace < 0 ? target.nodes.length : firstTrace, 0, userNode);
      }
      else {
        unscoped = {
          runId: `chat-${msg.id}`,
          fallbackOrder: sessions.length,
          sortAt: timestampOf(msg.created_at),
          nodes: [userNode],
        };
        sessions.push(unscoped);
      }
    } else if (msg.role === 'assistant') {
      if ((msg.content || '').trim() || msg.status === 'streaming') {
        const runId = target?.runId || unscoped?.runId || `chat-${msg.id}`;
        const replyNode: AgentStreamNode = {
          kind: 'reply', id: `reply-${msg.id}`, runId,
          content: msg.content || '', streaming: msg.status === 'streaming',
        };
        if (target) target.nodes.push(replyNode);
        else if (unscoped) unscoped.nodes.push(replyNode);
        else sessions.push({
          runId,
          fallbackOrder: sessions.length,
          sortAt: timestampOf(msg.created_at),
          nodes: [replyNode],
        });
      }
    }
  }

  return sessions
    // detail.events 通常只属于当前 run，而 messages 包含全部历史。不能按“事件先、消息后”
    // 排列，否则历史消息会被追加到当前 run 后面，自动滚动就会显示一条旧指令。
    // 有服务端时间时严格按会话起始时间；没有时间的是刚到达的实时会话，放在历史之后。
    .sort((a, b) => {
      if (a.sortAt !== null && b.sortAt !== null && a.sortAt !== b.sortAt) return a.sortAt - b.sortAt;
      if (a.sortAt === null && b.sortAt !== null) return 1;
      if (a.sortAt !== null && b.sortAt === null) return -1;
      return a.fallbackOrder - b.fallbackOrder;
    })
    .map(session => ({
      id: `turn-${session.runId}`,
      runId: session.runId,
      users: session.nodes.filter((node): node is Extract<AgentStreamNode, { kind: 'user' }> => node.kind === 'user'),
      trace: session.nodes.filter((node): node is Exclude<AgentStreamNode, { kind: 'user' | 'reply' }> => node.kind !== 'user' && node.kind !== 'reply'),
      replies: session.nodes.filter((node): node is Extract<AgentStreamNode, { kind: 'reply' }> => node.kind === 'reply'),
    }))
    .filter(turn => turn.users.length || turn.trace.length || turn.replies.length);
}

/** 兼容旧调用者；新 UI 应使用 buildAgentTurns 保留 Turn 边界。 */
export function buildStreamNodes(
  items: PipelineTimelineItem[],
  thoughts: Record<string, string>,
  messages: ProjectAgentMessage[],
): AgentStreamNode[] {
  return buildAgentTurns(items, thoughts, messages)
    .flatMap(turn => [...turn.users, ...turn.trace, ...turn.replies]);
}
