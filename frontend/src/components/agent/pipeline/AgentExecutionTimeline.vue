<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Document } from '@element-plus/icons-vue';
import { buildAgentTurns } from '../../../composables/useAgentStream';
import type { AgentStreamNode } from '../../../composables/useAgentStream';
import type { PipelineTimelineItem } from '../../../stores/pipeline';
import type { CourseTask } from '../../../types';
import type { PipelineToolCall, PPTLayoutCandidateRanking, PPTPolishObjectiveResult, PPTPolishPageResult } from '../../../types/agentPipeline';
import MarkdownRenderer from '../../content-renderers/MarkdownRenderer.vue';
import AuthenticatedPreviewImage from './AuthenticatedPreviewImage.vue';

const props = defineProps<{
  items: PipelineTimelineItem[];
  task: CourseTask | null;
  toolCalls: PipelineToolCall[];
  isRunning?: boolean;
  agentThoughts?: Record<string, string>;
  agentStatusTexts?: Record<string, string>;
  humanResponsePending?: string;
}>();

const emit = defineEmits<{
  (e: 'select-slide', slideIndex: number): void;
  (e: 'human-response', requestId: string, choice: string, data?: Record<string, unknown>): void;
}>();

const scrollRef = ref<HTMLElement | null>(null);
const isUserScrolledUp = ref(false);
const unreadCount = ref(0);
const expandedTools = ref<Set<string>>(new Set());
const expandedEvents = ref<Set<string>>(new Set());
let lastUnreadMessageId = '';
let isProgrammaticScrolling = false;
let resizeObserver: ResizeObserver | null = null;

/** Codex 式 Turn：教师指令、执行轨迹、最终回复不会跨轮混排。 */
const turns = computed(() =>
  buildAgentTurns(
    props.items,
    props.agentThoughts || {},
    props.task?.messages || [],
    props.toolCalls,
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

const TOOL_ERROR_LABELS: Record<string, string> = {
  blueprint_missing: '缺少课程蓝图，无法执行质量检查',
  blueprint_invalid: '课程蓝图结构异常，无法执行质量检查',
  tool_not_allowed: '该角色无权调用此工具',
  tool_input_invalid: '工具参数不符合要求',
  source_view_forbidden: '该角色无权读取完整候选稿',
  section_scope_violation: '修改超出本轮选中的章节范围',
  locked_path_conflict: '修改位置已被锁定',
  artifact_locked: '教学设计已被整体锁定',
  candidate_invalid: '修改后的教学设计结构不合法',
  no_progress: '重复读取没有产生新信息，请继续下一步',
  confirmation_required: '本次修改涉及高风险变更，等待教师确认后继续',
};

function friendlyToolError(node: Extract<AgentStreamNode, { kind: 'tool' }>): string {
  return TOOL_ERROR_LABELS[String(node.errorCode || '')] || node.error || '工具执行失败';
}

/** QA / 修复类事件：可展开查看 severity/rule/message 明细 */
const ISSUE_EVENT_TYPES = new Set([
  'qa_issue_found', 'qa.issue', 'qa_completed', 'qa.completed',
  'validation.issue',
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

function eventPayload(node: Extract<AgentStreamNode, { kind: 'event' }>): Record<string, any> {
  const payload = node.data?.payload;
  return {
    ...(node.data || {}),
    ...(payload && typeof payload === 'object' ? payload : {}),
  };
}

interface HumanOption {
  id: string;
  label: string;
  candidate_id?: string;
  preview_url?: string;
  render_path?: string;
  quality_score?: number;
  quality_delta?: number;
  [key: string]: unknown;
}

interface CandidateView {
  candidateId: string;
  choiceId: string;
  label: string;
  layoutType: string;
  qualityScore: number | null;
  qualityDelta: number | null;
  previewUrl: string;
  style: Record<string, unknown>;
  objectives: PPTPolishObjectiveResult[];
  slideId: string;
  rank: number;
}

function humanOptions(node: Extract<AgentStreamNode, { kind: 'event' }>): HumanOption[] {
  const options = eventPayload(node).options;
  if (!Array.isArray(options)) return [];
  return options
    .filter((option): option is Record<string, any> => Boolean(option) && typeof option === 'object')
    .map(option => ({
      ...option,
      id: String(option.id || option.choice || ''),
      label: String(option.label || option.title || option.id || '确认'),
      candidate_id: option.candidate_id ? String(option.candidate_id) : undefined,
    }))
    .filter(option => Boolean(option.id));
}

function asCandidateRanking(value: unknown): PPTLayoutCandidateRanking | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, any>;
  const candidateId = String(item.candidate_id || item.id || '');
  if (!candidateId) return null;
  return {
    ...item,
    candidate_id: candidateId,
    objective_results: Array.isArray(item.objective_results) ? item.objective_results : [],
  };
}

function pageResults(node: Extract<AgentStreamNode, { kind: 'event' }>): PPTPolishPageResult[] {
  const values = eventPayload(node).page_results;
  return Array.isArray(values)
    ? values.filter(value => Boolean(value) && typeof value === 'object') as PPTPolishPageResult[]
    : [];
}

function candidateViews(node: Extract<AgentStreamNode, { kind: 'event' }>): CandidateView[] {
  const payload = eventPayload(node);
  const options = humanOptions(node);
  const sources: Array<{ candidate: PPTLayoutCandidateRanking; slideId: string }> = [];
  const addValues = (values: unknown, slideId = '') => {
    if (!Array.isArray(values)) return;
    for (const value of values) {
      const candidate = asCandidateRanking(value);
      if (candidate) sources.push({ candidate, slideId });
    }
  };
  addValues(payload.candidates, String(payload.slide_id || ''));
  addValues(payload.candidate_rankings, String(payload.slide_id || ''));
  for (const page of pageResults(node)) {
    if (page.requires_candidate_confirmation || node.type === 'polish.result') {
      addValues(page.candidate_rankings, String(page.slide_id || ''));
    }
  }
  // Some backends put the complete candidate directly into each human option.
  addValues(options.filter(option => option.candidate_id), String(payload.slide_id || ''));

  const previews = payload.preview_urls && typeof payload.preview_urls === 'object'
    ? payload.preview_urls as Record<string, string>
    : {};
  const seen = new Set<string>();
  const result: CandidateView[] = [];
  for (const { candidate, slideId } of sources) {
    if (seen.has(candidate.candidate_id)) continue;
    seen.add(candidate.candidate_id);
    const option = options.find(value => value.candidate_id === candidate.candidate_id || value.id === candidate.candidate_id);
    const raw = candidate as Record<string, any>;
    const preview = String(
      option?.preview_url || option?.render_path
      || raw.preview_url || raw.candidate_png || raw.render_path
      || previews[candidate.candidate_id] || '',
    );
    result.push({
      candidateId: candidate.candidate_id,
      choiceId: option?.id || candidate.candidate_id,
      label: option?.label || `方案 ${result.length + 1}`,
      layoutType: String(candidate.layout_type || raw.recipe || '候选布局'),
      qualityScore: typeof candidate.quality_score === 'number' ? candidate.quality_score : null,
      qualityDelta: typeof candidate.quality_delta === 'number' ? candidate.quality_delta : null,
      previewUrl: preview,
      style: candidate.style && typeof candidate.style === 'object' ? candidate.style : {},
      objectives: Array.isArray(candidate.objective_results) ? candidate.objective_results : [],
      slideId,
      rank: typeof candidate.rank === 'number' ? candidate.rank : result.length + 1,
    });
  }
  return result.sort((a, b) => a.rank - b.rank).slice(0, 2);
}

function shouldShowCandidateComparison(node: Extract<AgentStreamNode, { kind: 'event' }>): boolean {
  if (!candidateViews(node).length) return false;
  const payload = eventPayload(node);
  return node.type === 'human.required'
    || Boolean(payload.requires_candidate_confirmation)
    || pageResults(node).some(page => page.requires_candidate_confirmation);
}

function humanRequestId(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  return String(eventPayload(node).request_id || '');
}

function objectivePassed(objective: PPTPolishObjectiveResult): boolean | null {
  if (typeof objective.passed === 'boolean') return objective.passed;
  if (typeof objective.met === 'boolean') return objective.met;
  if (typeof objective.achieved === 'boolean') return objective.achieved;
  return null;
}

function objectiveStatusLabel(objective: PPTPolishObjectiveResult): string {
  const passed = objectivePassed(objective);
  return passed === true ? '达标' : passed === false ? '未达标' : '目标';
}

const OBJECTIVE_LABELS: Record<string, string> = {
  font_size: '字号', vertical_utilization: '纵向利用', horizontal_utilization: '横向利用',
  whitespace_balance: '留白平衡', spacing: '间距', alignment: '对齐', density: '密度',
  image_scale: '图片尺寸', contrast: '对比度', layout_quality: '综合质量',
};

function objectiveLabel(objective: PPTPolishObjectiveResult): string {
  const label = OBJECTIVE_LABELS[String(objective.metric || '')] || String(objective.metric || '目标');
  const final = typeof objective.final === 'number' ? ` ${formatCandidateNumber(objective.final)}` : '';
  return `${label}${final}`;
}

function formatCandidateNumber(value: number): string {
  if (Math.abs(value) <= 1) return `${Math.round(value * 100)}%`;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function candidateStyleLabel(candidate: CandidateView): string {
  const tier = String(candidate.style.font_tier || '');
  const scale = typeof candidate.style.font_scale === 'number' ? Number(candidate.style.font_scale) : null;
  const parts = [tier === 'spacious' ? '舒展字号' : tier === 'compact' ? '紧凑字号' : tier ? '标准字号' : ''];
  if (scale && scale !== 1) parts.push(`×${scale.toFixed(2)}`);
  return parts.filter(Boolean).join(' · ');
}

function isBrowserPreview(url: string): boolean {
  return /^(?:https?:|data:image\/|blob:|\/api\/|\/static\/|\/uploads\/)/.test(url);
}

function turnCandidateEventId(turn: { trace: AgentStreamNode[] }): string {
  const events = turn.trace.filter(
    (node): node is Extract<AgentStreamNode, { kind: 'event' }> => node.kind === 'event',
  );
  // Candidate rankings are also retained in compile diagnostics.  They are
  // not a selectable preview by themselves: after a teacher chooses one, the
  // continuation run used to render a second, URL-less comparison card from
  // those diagnostics.  Only show the comparison when this turn owns a real
  // confirmation request with candidate options.
  const hasCandidateRequest = events.some(event => (
    Boolean(humanRequestId(event))
    && humanOptions(event).some(option => Boolean(option.candidate_id))
  ));
  if (!hasCandidateRequest) return '';
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (shouldShowCandidateComparison(events[index])) return events[index].id;
  }
  return '';
}

function confirmationEventForTurn(
  turn: { trace: AgentStreamNode[] },
  node: Extract<AgentStreamNode, { kind: 'event' }>,
): Extract<AgentStreamNode, { kind: 'event' }> {
  if (humanRequestId(node)) return node;
  const slideId = String(eventPayload(node).slide_id || candidateViews(node)[0]?.slideId || '');
  const events = turn.trace.filter(
    (candidate): candidate is Extract<AgentStreamNode, { kind: 'event' }> => candidate.kind === 'event',
  );
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const candidate = events[index];
    if (candidate.type !== 'human.required' || !humanRequestId(candidate)) continue;
    const candidateSlideId = String(eventPayload(candidate).slide_id || candidateViews(candidate)[0]?.slideId || '');
    if (!slideId || !candidateSlideId || candidateSlideId === slideId) return candidate;
  }
  return node;
}

function mergedCandidateViews(
  turn: { trace: AgentStreamNode[] },
  node: Extract<AgentStreamNode, { kind: 'event' }>,
): CandidateView[] {
  const confirmation = confirmationEventForTurn(turn, node);
  const confirmedOptions = humanOptions(confirmation);
  const requestId = humanRequestId(confirmation);
  const byId = new Map(candidateViews(confirmation).map(candidate => [candidate.candidateId, candidate]));
  for (const candidate of candidateViews(node)) {
    const existing = byId.get(candidate.candidateId);
    const option = confirmedOptions.find(value => (
      value.candidate_id === candidate.candidateId || value.id === candidate.choiceId
    ));
    const fallback = requestId && option?.id
      ? `/api/v1/ppt-agent/runs/${node.runId}/candidate-previews/${requestId}/${option.id}`
      : '';
    byId.set(candidate.candidateId, {
      ...(existing || candidate),
      ...candidate,
      choiceId: option?.id || existing?.choiceId || candidate.choiceId,
      label: option?.label || existing?.label || candidate.label,
      previewUrl: option?.preview_url || existing?.previewUrl || candidate.previewUrl || fallback,
    });
  }
  return [...byId.values()].sort((a, b) => a.rank - b.rank).slice(0, 2);
}

function turnHumanRequestId(
  turn: { trace: AgentStreamNode[] },
  node: Extract<AgentStreamNode, { kind: 'event' }>,
): string {
  return humanRequestId(confirmationEventForTurn(turn, node));
}

function turnHumanOptions(
  turn: { trace: AgentStreamNode[] },
  node: Extract<AgentStreamNode, { kind: 'event' }>,
): HumanOption[] {
  return humanOptions(confirmationEventForTurn(turn, node));
}

function submitTurnCandidate(
  turn: { trace: AgentStreamNode[] },
  node: Extract<AgentStreamNode, { kind: 'event' }>,
  candidate: CandidateView,
) {
  submitCandidate(confirmationEventForTurn(turn, node), candidate);
}

function submitTurnHumanOption(
  turn: { trace: AgentStreamNode[] },
  node: Extract<AgentStreamNode, { kind: 'event' }>,
  option: HumanOption,
) {
  submitHumanOption(confirmationEventForTurn(turn, node), option);
}

function submitCandidate(node: Extract<AgentStreamNode, { kind: 'event' }>, candidate: CandidateView) {
  const requestId = humanRequestId(node);
  if (!requestId) return;
  emit('human-response', requestId, candidate.choiceId, { candidate_id: candidate.candidateId });
}

function submitHumanOption(node: Extract<AgentStreamNode, { kind: 'event' }>, option: HumanOption) {
  const requestId = humanRequestId(node);
  if (!requestId) return;
  emit(
    'human-response',
    requestId,
    option.id,
    option.candidate_id ? { candidate_id: option.candidate_id } : {},
  );
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
  // slide.page 由后端按 1-based 发出（render_tools: page = index + 1），
  // 而 slide_index 是 0-based；统一归一化为 0-based 页索引。
  if (typeof page === 'number') return Math.max(0, page - 1);
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
    case 'validation.completed': return 'OK';
    case 'validation.issue': return '!';
    case 'revision_started': case 'revision_completed': case 'repair.started': case 'repair.completed': return '🔄';
    case 'layout.compile.result': return '📐';
    case 'polish.result': return '✅';
    case 'intent.resolved': return '🎯';
    case 'edit.plan.created': return '📋';
    case 'slide.change.applied': return '✏️';
    case 'edit.corrected': return '🩹';
    case 'qa.warning': return '⚠️';
    case 'task.spec.created': return '📋';
    case 'context.snapshot.created': return '📌';
    case 'evidence.bundle.ready': return '🗂';
    case 'patch.operation.applied': return '✏️';
    case 'verification.completed': return '🧾';
    case 'result.applied': return '✅';
    case 'result.no_change': return '➖';
    case 'result.rejected': return '⛔';
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
      const level = d.qa_level || d.payload?.qa_level || 'geometry';
      const label = level === 'vision' ? '视觉 QA' : level === 'raster' ? '真实渲染 QA' : '几何 QA（降级）';
      const geometry = d.geometry_score ?? d.payload?.geometry_score ?? d.score ?? d.payload?.score ?? '-';
      return d.message || `${label} · 几何 ${geometry} · 严重${sev.critical || 0}/主要${sev.major || 0}/次要${sev.minor || 0}`;
    }
    case 'qa_issue_found': case 'qa.issue':
      return `发现 QA 问题：${d.issue?.message || d.payload?.issue?.message || ''}`;
    case 'validation.completed': {
      const count = Number(d.payload?.blocking_count ?? d.blocking_count ?? 0);
      return d.message || (count ? `发布前检查仍有 ${count} 个阻断问题` : '发布前约束已检查');
    }
    case 'validation.issue':
      return d.message || '发现需要定向修复的发布阻断问题';
    case 'plan.revised': return d.message || '已根据追加要求更新执行计划';
    case 'revision_started': case 'repair.started':
      return d.message || `自动修订（第 ${d.round ?? d.payload?.round ?? 1}/${d.max_rounds ?? d.payload?.max_rounds ?? '?'} 轮）${d.reason || ''}`;
    case 'revision_completed': case 'repair.completed':
      return d.message || `修订完成（第 ${d.round ?? d.payload?.round ?? ''} 轮）`;
    case 'layout.compile.result':
      return d.message || `${d.slide?.slide_id || d.payload?.slide_id || '页面'} 布局编译完成`;
    case 'polish.result': {
      const status = d.payload?.result_status;
      const applied = d.payload?.applied_slide_ids?.length || 0;
      const preserved = d.payload?.preserved_slide_ids?.length || 0;
      if (d.message) return d.message;
      if (status === 'partial' || status === 'applied_with_warnings') return `已更新 ${applied} 页，并保留非阻断警告`;
      if (status === 'no_change') return '当前页面已达到安全排版上限，原版本保持不变';
      if (status === 'needs_confirmation') {
        return d.payload?.request_id
          ? '安全候选等待选择，确认后再发布'
          : '修改范围或目标存在歧义，请确认后再执行';
      }
      return `已完成 ${applied} 页润色`;
    }
    case 'intent.resolved': {
      const intent = d.payload?.intent || d.intent || '';
      return d.message || `意图已识别：${intent}`;
    }
    case 'edit.plan.created':
      return d.message || '已生成元素级修改计划';
    case 'slide.change.applied':
      return d.message || `${d.slide?.slide_id || d.payload?.slide_id || '页面'} 已应用精确修改`;
    case 'edit.corrected':
      return d.message || '已自动恢复计划外变化';
    case 'qa.warning':
      return d.message || d.payload?.message || '存在不阻断发布的质量提示';
    case 'context.snapshot.created':
      return d.message || `执行前上下文快照已创建（v${d.payload?.source_version || '?'}）`;
    case 'task.spec.created':
      return d.message || '任务规格已生成';
    case 'evidence.bundle.ready':
      return d.message || '证据包已就绪';
    case 'patch.operation.applied':
      return d.message || '修改操作已应用';
    case 'verification.completed':
      return d.message || '确定性验证已完成';
    case 'result.applied':
      return d.message || '修改已应用，新版本已生成';
    case 'result.no_change':
      return d.message || '未发现需要修改的内容';
    case 'result.rejected':
      return d.message || '本轮修改被拒绝，原教学设计保持不变';
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

/** 教学设计保留契约详情；逐字稿等 LLM 协同流程不显示硬性契约卡片。 */
const CONTRACT_EVENT_TYPES = new Set(['intent.resolved', 'context.snapshot.created', 'result.rejected']);
const expandedContracts = ref<Set<string>>(new Set());

function isContractEvent(type: string): boolean {
  return CONTRACT_EVENT_TYPES.has(type);
}

function toggleContract(id: string) {
  const next = new Set(expandedContracts.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedContracts.value = next;
}

function contractTitle(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  if (node.type === 'intent.resolved') return '执行前契约：意图与修改范围';
  if (node.type === 'context.snapshot.created') return '执行前上下文快照';
  return '执行前契约';
}

function contractIntentLabel(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  const payload = node.data?.payload || {};
  const intent = payload.intent || node.data?.intent || '';
  const intentNames: Record<string, string> = {
    GENERATE: '首次生成完整教学设计',
    SECTION_EDIT: '修改指定章节内容',
    SECTION_FORMAT_EDIT: '修正章节格式（编号/层级）',
    RESTRUCTURE: '调整目录结构',
    CONTENT_ENRICH: '补充丰富内容',
    TIMING_ADJUST: '调整环节时长',
    QA_ONLY: '仅质量检查',
    ANSWER_ONLY: '仅回答问题',
    CLARIFICATION_REQUIRED: '需要澄清',
  };
  return intentNames[intent] || intent || '未识别';
}

function contractTargets(node: Extract<AgentStreamNode, { kind: 'event' }>): string[] {
  const payload = node.data?.payload || {};
  const targets = payload.affected_section_ids || payload.target_section_ids || [];
  return Array.isArray(targets) ? targets.map(String) : [];
}

function contractSourceVersion(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  return String((node.data?.payload || {})?.source_version || '—');
}

function contractPreserved(node: Extract<AgentStreamNode, { kind: 'event' }>): string[] {
  const preserved = (node.data?.payload || {})?.preserved_section_ids || [];
  return Array.isArray(preserved) ? preserved.map(String) : [];
}

function contractFactOwners(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  const owners = (node.data?.payload || {})?.fact_owners || {};
  if (!owners || typeof owners !== 'object') return '—';
  const entries = Object.entries(owners);
  return entries.length ? entries.map(([fact, section]) => `${fact}→${section}`).join('；') : '—';
}

function contractRejectedCode(node: Extract<AgentStreamNode, { kind: 'event' }>): string {
  return String((node.data?.payload || {})?.error_code || '');
}

function handleScroll() {
  if (!scrollRef.value || isProgrammaticScrolling) return;
  const { scrollTop, scrollHeight, clientHeight } = scrollRef.value;
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
  isUserScrolledUp.value = distanceFromBottom > 60;
  if (!isUserScrolledUp.value) {
    unreadCount.value = 0;
    lastUnreadMessageId = '';
  }
}

function scrollToBottom(smooth = true) {
  if (!scrollRef.value) return;
  isProgrammaticScrolling = true;
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
    requestAnimationFrame(() => {
      isProgrammaticScrolling = false;
    });
  });
}

function notifyVisibleMessage() {
  if (!isUserScrolledUp.value) {
    scrollToBottom(true);
  } else {
    const messageId = latestVisibleMessageId.value;
    if (messageId && messageId !== lastUnreadMessageId) {
      unreadCount.value += 1;
      lastUnreadMessageId = messageId;
    }
  }
}

// 监听消息与追踪流
watch(visibleMessageSignature, notifyVisibleMessage, { flush: 'post' });
watch(traceSignature, () => {
  if (!isUserScrolledUp.value) scrollToBottom(false);
}, { flush: 'post' });

// 切换任务/运行状态时重置向上滚动状态并触底
watch(() => props.task?.id, () => {
  isUserScrolledUp.value = false;
  unreadCount.value = 0;
  scrollToBottom(false);
});

watch(() => props.isRunning, (running) => {
  if (running) {
    isUserScrolledUp.value = false;
    unreadCount.value = 0;
    scrollToBottom(false);
  }
});

// 组件挂载与 Resize 动态自适应触底
onMounted(() => {
  isUserScrolledUp.value = false;
  scrollToBottom(false);

  // 多阶段校准：应对 Markdown 公式、<details> 展开和异步素材渲染导致的高度二次膨胀
  setTimeout(() => scrollToBottom(false), 80);
  setTimeout(() => scrollToBottom(false), 240);

  // 监听内容区域高度变动，只要未处于主动向上翻阅状态就自动贴底
  if (scrollRef.value) {
    const target = scrollRef.value.querySelector('.term-stream') || scrollRef.value;
    resizeObserver = new ResizeObserver(() => {
      if (!isUserScrolledUp.value) {
        scrollToBottom(false);
      }
    });
    resizeObserver.observe(target);
  }
});

onBeforeUnmount(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
});
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
              <div v-if="node.attachments.length" class="message-attachments">
                <span v-for="attachment in node.attachments" :key="attachment.id" class="message-attachment">
                  <el-icon><Document /></el-icon>
                  <span>{{ attachment.filename }}</span>
                </span>
              </div>
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
              <span v-else class="term-status fail">✗ {{ friendlyToolError(node) }}</span>
            </button>
            <pre v-if="expandedTools.has(node.id)" class="term-tool-json">{{
              JSON.stringify({ input: node.input, output: node.output, error_code: node.errorCode, technical_error: node.error }, null, 2)
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
            <span v-if="node.type === 'human.required' && !shouldShowCandidateComparison(node)" class="human-options">
              <button
                v-for="option in humanOptions(node)"
                :key="option.id"
                type="button"
                :disabled="humanResponsePending === humanRequestId(node)"
                @click.stop="submitHumanOption(node, option)"
              >
                {{ option.label }}
              </button>
            </span>
          </div>
          <section
            v-if="node.kind === 'event' && node.id === turnCandidateEventId(turn)"
            class="candidate-comparison"
            @click.stop
          >
            <div class="candidate-comparison-head">
              <div>
                <strong>{{ mergedCandidateViews(turn, node).length > 1 ? '两个方案评分接近' : '安全改善方案等待确认' }}</strong>
                <span>请选择更符合课堂表达的版式，或保留原版</span>
              </div>
              <span v-if="eventPayload(node).display_label || mergedCandidateViews(turn, node)[0]?.slideId" class="candidate-slide">
                {{ eventPayload(node).display_label || mergedCandidateViews(turn, node)[0].slideId }}
              </span>
            </div>
            <div class="candidate-grid">
              <article v-for="candidate in mergedCandidateViews(turn, node)" :key="candidate.candidateId" class="candidate-card">
                <div v-if="isBrowserPreview(candidate.previewUrl)" class="candidate-preview">
                  <AuthenticatedPreviewImage :src="candidate.previewUrl" :alt="`${candidate.label}预览`" />
                </div>
                <div v-else class="candidate-preview candidate-preview-empty">
                  <span>候选预览不可用</span>
                  <small>请重试本次润色；无真实预览时不会发布</small>
                </div>
                <div class="candidate-copy">
                  <div class="candidate-title">
                    <strong>{{ candidate.label }}</strong>
                    <span>#{{ candidate.rank }}</span>
                  </div>
                  <div class="candidate-recipe">{{ candidate.layoutType }}<span v-if="candidateStyleLabel(candidate)"> · {{ candidateStyleLabel(candidate) }}</span></div>
                  <div class="candidate-scores">
                    <span>质量 <b>{{ candidate.qualityScore == null ? '—' : candidate.qualityScore.toFixed(1) }}</b></span>
                    <span :class="(candidate.qualityDelta || 0) > 0 ? 'score-up' : 'score-flat'">
                      较原页 {{ candidate.qualityDelta == null ? '—' : `${candidate.qualityDelta > 0 ? '+' : ''}${candidate.qualityDelta.toFixed(1)}` }}
                    </span>
                  </div>
                  <div v-if="candidate.objectives.length" class="candidate-objectives">
                    <span
                      v-for="(objective, objectiveIndex) in candidate.objectives.slice(0, 3)"
                      :key="`${candidate.candidateId}-${objective.metric}-${objectiveIndex}`"
                      :class="{ pass: objectivePassed(objective) === true, fail: objectivePassed(objective) === false }"
                    >
                      {{ objectiveStatusLabel(objective) }} · {{ objectiveLabel(objective) }}
                    </span>
                  </div>
                  <button
                    v-if="turnHumanRequestId(turn, node)"
                    type="button"
                    class="candidate-select"
                    :disabled="humanResponsePending === turnHumanRequestId(turn, node)"
                    @click="submitTurnCandidate(turn, node, candidate)"
                  >
                    {{ humanResponsePending === turnHumanRequestId(turn, node) ? '提交中…' : `选择${candidate.label}` }}
                  </button>
                </div>
              </article>
            </div>
            <div v-if="!turnHumanRequestId(turn, node)" class="candidate-readonly-note">
              候选仅供比较；等待确认请求生成后即可选择。
            </div>
            <div v-else-if="turnHumanOptions(turn, node).some(option => !option.candidate_id)" class="candidate-secondary-actions">
              <button
                v-for="option in turnHumanOptions(turn, node).filter(option => !option.candidate_id)"
                :key="option.id"
                type="button"
                :disabled="humanResponsePending === turnHumanRequestId(turn, node)"
                @click="submitTurnHumanOption(turn, node, option)"
              >
                {{ option.label }}
              </button>
            </div>
          </section>
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

          <!-- 教学设计可展开查看契约；逐字稿等流程只保留普通轨迹和真实拒绝事件。 -->
          <section
            v-if="node.kind === 'event' && node.type !== 'result.rejected' && task?.task_type === 'lesson_plan' && (node.type === 'intent.resolved' || node.type === 'context.snapshot.created')"
            class="contract-card"
            @click.stop
          >
            <div class="contract-card-head" @click="toggleContract(node.id)">
              <strong>{{ contractTitle(node) }}</strong>
              <span class="expand-caret" aria-hidden="true">{{ expandedContracts.has(node.id) ? '▾' : '▸' }}</span>
            </div>
            <dl class="contract-grid">
              <template v-if="node.type === 'intent.resolved'">
                <div class="contract-row">
                  <dt>识别意图</dt>
                  <dd>{{ contractIntentLabel(node) }}</dd>
                </div>
                <div class="contract-row">
                  <dt>目标章节</dt>
                  <dd>{{ contractTargets(node).length ? contractTargets(node).join('、') : '全局' }}</dd>
                </div>
              </template>
              <template v-if="node.type === 'context.snapshot.created'">
                <div class="contract-row">
                  <dt>上下文版本</dt>
                  <dd>{{ contractSourceVersion(node) }}</dd>
                </div>
                <div class="contract-row">
                  <dt>保护章节</dt>
                  <dd>{{ contractPreserved(node).length ? contractPreserved(node).join('、') : '无' }}</dd>
                </div>
                <div class="contract-row">
                  <dt>事实归属</dt>
                  <dd>{{ contractFactOwners(node) }}</dd>
                </div>
              </template>
            </dl>
            <pre v-if="expandedContracts.has(node.id)" class="contract-json">{{
              JSON.stringify(node.data?.payload || node.data, null, 2)
            }}</pre>
          </section>
          <section
            v-if="node.kind === 'event' && node.type === 'result.rejected'"
            class="contract-card contract-card-rejected"
            @click.stop
          >
            <div class="contract-card-head">
              <strong>⛔ 本轮修改未执行</strong>
              <span v-if="contractRejectedCode(node)" class="rejected-code">{{ contractRejectedCode(node) }}</span>
            </div>
            <p class="contract-rejected-message">{{ eventLabel(node) }}</p>
          </section>

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

.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  width: 100%;
}

.message-attachment {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 220px;
  padding: 3px 6px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 11px;
}

.message-attachment span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.human-options {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-left: auto;
}

.human-options button,
.candidate-secondary-actions button {
  border: 1px solid #c4b5fd;
  border-radius: 7px;
  padding: 3px 8px;
  background: #ffffff;
  color: #5b21b6;
  font: inherit;
  font-weight: 750;
  cursor: pointer;
}

.human-options button:hover,
.candidate-secondary-actions button:hover {
  border-color: #7c3aed;
  background: #f5f3ff;
}

.human-options button:disabled,
.candidate-secondary-actions button:disabled,
.candidate-select:disabled {
  cursor: wait;
  opacity: 0.55;
}

.candidate-comparison {
  margin: 6px 0 8px 24px;
  padding: 10px;
  border: 1px solid #c4b5fd;
  border-radius: 11px;
  background: linear-gradient(180deg, #faf8ff, #ffffff);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.candidate-comparison-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.candidate-comparison-head > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.candidate-comparison-head strong {
  color: #312e81;
  font-size: 12px;
}

.candidate-comparison-head span {
  color: #7c3aed;
  font-size: 10px;
}

.candidate-slide {
  padding: 1px 6px;
  border-radius: 999px;
  background: #ede9fe;
  font-weight: 800;
  white-space: nowrap;
}

.candidate-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.candidate-card {
  min-width: 0;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #ffffff;
  box-shadow: 0 2px 5px rgba(15, 23, 42, 0.04);
}

.candidate-preview {
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: #eef2ff;
  border-bottom: 1px solid #e2e8f0;
}

.candidate-preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.candidate-preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: #64748b;
  background:
    linear-gradient(135deg, rgba(99, 102, 241, 0.07) 25%, transparent 25%) 0 0 / 12px 12px,
    #f8fafc;
}

.candidate-preview-empty span { font-size: 10px; font-weight: 800; }
.candidate-preview-empty small { font-size: 9px; color: #94a3b8; text-align: center; }

.candidate-copy {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px;
}

.candidate-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #1e293b;
}

.candidate-title strong { font-size: 11px; }
.candidate-title span { color: #94a3b8; font-size: 9px; font-weight: 800; }
.candidate-recipe { color: #64748b; font-size: 9px; overflow-wrap: anywhere; }

.candidate-scores {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  font-size: 9px;
  color: #475569;
}

.candidate-scores b { color: #312e81; font-size: 11px; }
.score-up { color: #15803d; font-weight: 800; }
.score-flat { color: #64748b; }

.candidate-objectives {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.candidate-objectives span {
  width: fit-content;
  padding: 1px 5px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 9px;
}

.candidate-objectives span.pass { color: #166534; background: #dcfce7; }
.candidate-objectives span.fail { color: #b91c1c; background: #fee2e2; }

.candidate-select {
  width: 100%;
  margin-top: 2px;
  border: 0;
  border-radius: 7px;
  padding: 6px 8px;
  background: #4f46e5;
  color: #ffffff;
  font-size: 10px;
  font-weight: 800;
  cursor: pointer;
  transition: background 140ms ease;
}

.candidate-select:hover { background: #4338ca; }

.candidate-readonly-note {
  margin-top: 7px;
  color: #7c3aed;
  font-size: 9px;
}

.candidate-secondary-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

@media (max-width: 560px) {
  .candidate-grid { grid-template-columns: 1fr; }
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

/* 执行前契约卡片（教学设计） */
.contract-card {
  margin: 4px 0 4px 26px;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #7c3aed;
  border-radius: 6px;
  font-size: 12px;
}

.contract-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: pointer;
  color: #334155;
}

.contract-card-head strong {
  font-size: 12px;
}

.contract-grid {
  margin: 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.contract-row {
  display: flex;
  gap: 8px;
  line-height: 1.5;
}

.contract-row dt {
  flex-shrink: 0;
  color: #64748b;
  min-width: 56px;
}

.contract-row dd {
  margin: 0;
  color: #1e293b;
  word-break: break-all;
}

.contract-json {
  margin: 6px 0 0;
  max-height: 220px;
  overflow: auto;
  font-size: 10px;
  color: #475569;
  background: #f1f5f9;
  border-radius: 4px;
  padding: 6px 8px;
}

.contract-card-rejected {
  border-left-color: #dc2626;
  background: #fef2f2;
}

.contract-card-rejected .contract-card-head {
  cursor: default;
}

.rejected-code {
  font-size: 10px;
  font-weight: 700;
  color: #b91c1c;
  background: #fee2e2;
  border-radius: 999px;
  padding: 1px 8px;
}

.contract-rejected-message {
  margin: 6px 0 0;
  color: #7f1d1d;
  line-height: 1.6;
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
