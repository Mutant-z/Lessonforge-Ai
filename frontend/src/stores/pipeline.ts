import { defineStore } from 'pinia';
import { pipelineApi } from '../api/pipeline';
import type { PipelineDetail, PipelineStatus } from '../types/agentPipeline';
import { useProjectStore } from './project';
import { adaptPPTAgentEvent } from '../services/pptAgentEventAdapter';

const RENDER_MODES = new Set(['semantic', 'hybrid', 'absolute']);

function isCompleteSlidePatch(value: unknown): value is Record<string, any> {
  if (!value || typeof value !== 'object') return false;
  const slide = value as Record<string, any>;
  return typeof slide.id === 'string'
    && typeof slide.title === 'string'
    && typeof slide.purpose === 'string'
    && Array.isArray(slide.body)
    && Array.isArray(slide.blocks)
    && typeof slide.speaker_notes === 'string'
    && Array.isArray(slide.elements)
    && RENDER_MODES.has(String(slide.render_mode || ''));
}

/** 流水线时间线条目（SSE 事件与历史事件统一） */
export interface PipelineTimelineItem {
  id: number;
  type: string;
  data: Record<string, any>;
  created_at?: string;
}

export const usePipelineStore = defineStore('pipeline', {
  state: () => ({
    detail: null as PipelineDetail | null,
    loading: false,
    error: '',
    pauseLoading: false,
    resumeLoading: false,
    /** legacy thought text, isolated by run/agent key for old history consumers */
    thoughts: {} as Record<string, string>,
    /** run/agent scoped visible execution summaries */
    statusTexts: {} as Record<string, string>,
    statusRunIds: {} as Record<string, string>,
    draftArtifact: null as Record<string, any> | null,
    draftRunId: '' as string,
    draftCourseId: '' as string,
    draftTaskId: '' as string,
    processedEventIds: new Set<number>(),
    canonicalEvents: [] as ReturnType<typeof adaptPPTAgentEvent>[],
    selectedSlideIds: [] as string[],
    requestEpoch: 0,
  }),
  getters: {
    run: state => state.detail?.run ?? null,
    status: state => (state.detail?.run?.status || '') as PipelineStatus,
    artifacts: state => state.detail?.artifacts ?? [],
    toolCalls: state => state.detail?.tool_calls ?? [],
    plan: state => (state.detail?.plan as Array<Record<string, any>>) ?? [],
    timeline(state): PipelineTimelineItem[] {
      const project = useProjectStore();
      const currentRunId = String(state.detail?.run?.generation_run_id || project.currentTask?.active_run_id || '');
      const currentTaskId = String(project.currentTask?.id || '');
      const live = project.pipelineEvents
        .filter(event => {
          const evRunId = String(event.data?.run_id || '');
          const evTaskId = String(event.data?.task_id || '');
          if (currentRunId && evRunId) return evRunId === currentRunId;
          if (currentTaskId && evTaskId) return evTaskId === currentTaskId;
          return !currentRunId && !evRunId && !evTaskId;
        })
        .map(event => ({
          id: event.event_id,
          type: event.type,
          data: event.data,
        }));
      const history = (state.detail?.events ?? []).map(event => ({
        id: event.id,
        type: event.event_type,
        data: { ...event.data, created_at: event.created_at },
        created_at: event.created_at,
      }));
      // 合并历史 + 实时，按 id 去重并升序；思考增量由 agentThoughts 单独消费，不进时间线
      const seen = new Set<number>();
      const merged: PipelineTimelineItem[] = [];
      for (const item of [...history, ...live]) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        if (item.type === 'agent_thought_chunk') continue;
        merged.push(item);
      }
      return merged.sort((a, b) => a.id - b.id);
    },
    /** agent_key → 累计思考文本（实时 + 历史），供打字机渲染 */
    agentThoughts(): Record<string, string> {
      return this.thoughts;
    },
    agentStatusTexts(): Record<string, string> {
      return this.statusTexts;
    },
  },
  actions: {
    /** 从历史（detail.events）重建思考文本（刷新恢复） */
    restoreThoughtsFromHistory() {
      const terminalRun = ['completed', 'failed', 'cancelled'].includes(this.status);
      const apply = (type: string, data: Record<string, any>) => {
        if (type !== 'agent_thought_chunk' || !data.agent_key) return;
        const key = `${data.run_id || 'legacy'}:${data.agent_key}`;
        const prev = this.thoughts[key] || '';
        const text = String(data.text || '');
        if (!prev.includes(text)) this.thoughts[key] = prev + text;
      };
      for (const item of this.detail?.events ?? []) {
        this.processedEventIds.add(item.id);
        apply(item.event_type, item.data);
        // Historical page patches belong to a draft that was already finalized.
        // Replaying them after refresh makes an old intermediate slide replace
        // the authoritative artifact for a few seconds.
        if (!(terminalRun && item.event_type === 'artifact_patch')) {
          this.applyStreamEvent(item.event_type, item.data);
        }
      }
      if (terminalRun) this.draftArtifact = null;
    },
    /** 把 project store 收件箱的实时思考增量单调累加（幂等：已累加过的片段跳过） */
    syncThoughts() {
      const project = useProjectStore();
      const activeRunId = String(this.run?.generation_run_id || '');
      // SSE reconnect replays course-wide history. Until Pipeline Detail tells
      // us which run owns this workspace, no historical event may mutate the
      // active draft or the user will briefly see an old presentation.
      if (!activeRunId) return;
      for (const ev of project.pipelineEvents) {
        if (this.processedEventIds.has(ev.event_id)) continue;
        const eventRunId = String(ev.data.run_id || '');
        if (eventRunId && eventRunId !== activeRunId) {
          this.processedEventIds.add(ev.event_id);
          continue;
        }
        this.processedEventIds.add(ev.event_id);
        if (ev.type === 'agent_thought_chunk' && ev.data.agent_key) {
          const key = `${ev.data.run_id || 'legacy'}:${ev.data.agent_key}`;
          const prev = this.thoughts[key] || '';
          const text = String(ev.data.text || '');
          if (!prev.includes(text)) this.thoughts[key] = prev + text;
        }
        if (ev.type !== 'agent_thought_chunk') this.applyStreamEvent(ev.type, ev.data);
        this.canonicalEvents.push(adaptPPTAgentEvent(ev.type, ev.data, ev.event_id));
        if (this.canonicalEvents.length > 800) this.canonicalEvents.splice(0, this.canonicalEvents.length - 800);
      }
    },
    applyStreamEvent(type: string, data: Record<string, any>) {
      const activeRunId = String(this.run?.generation_run_id || '');
      const eventRunId = String(data.run_id || '');
      if (activeRunId && eventRunId && eventRunId !== activeRunId) return;
      const runId = eventRunId || activeRunId;
      const agentKey = String(data.agent_key || '');
      if (this.detail?.run && ['task_paused', 'run.paused'].includes(type)) {
        this.detail.run.status = 'paused';
      } else if (this.detail?.run && ['task_resumed', 'run.resumed'].includes(type)) {
        this.detail.run.status = 'queued';
      } else if (this.detail?.run && ['pipeline_completed', 'run.completed'].includes(type)) {
        this.detail.run.status = 'completed';
      } else if (this.detail?.run && ['pipeline_failed', 'run.failed'].includes(type)) {
        this.detail.run.status = 'failed';
        this.clearDraft();
      } else if (this.detail?.run && type === 'run.cancelled') {
        this.detail.run.status = 'cancelled';
        this.clearDraft();
      }
      if (type === 'pipeline_started' && runId) {
        for (const key of Object.keys(this.statusTexts)) {
          if (this.statusRunIds[key] !== runId) delete this.statusTexts[key];
        }
        this.clearDraft();
      }
      if (agentKey && type === 'agent_status_delta') {
        this.statusTexts[agentKey] = `${this.statusRunIds[agentKey] === runId ? this.statusTexts[agentKey] || '' : ''}${String(data.text || '')}`;
        this.statusRunIds[agentKey] = runId;
      } else if (agentKey && type === 'agent_status_completed') {
        this.statusTexts[agentKey] = String(data.text || this.statusTexts[agentKey] || '');
        this.statusRunIds[agentKey] = runId;
      }
      if (type === 'artifact_patch' && data.patch) {
        if (['completed', 'failed', 'cancelled'].includes(this.status)) return;
        const project = useProjectStore();
        const currentTask = project.currentTask;
        if (!currentTask
          || String(data.course_id || currentTask.course_id) !== currentTask.course_id
          || String(data.task_id || currentTask.id) !== currentTask.id
          || runId !== String(this.run?.generation_run_id || '')) return;
        const existing = this.draftArtifact || {};
        const draft = { ...existing } as Record<string, any>;
        // 任务单 V3：sections 目录树 / Block 局部更新；初始化与迁移整文档替换。
        const isTaskSheetV3Draft = Array.isArray(draft.sections) || data.artifact_type === 'task_sheet';
        let applied = false;
        for (const operation of data.patch as Array<Record<string, any>>) {
          const path = String(operation.path || '');
          if (isTaskSheetV3Draft) {
            if (!Array.isArray(draft.sections)) draft.sections = [];
            if (operation.op === 'replace' && path === '') {
              // 整文档替换（初始化 / 迁移）
              Object.assign(draft, operation.value || {});
              applied = true;
              continue;
            }
            const addMatch = path.match(/^\/sections\/([^/]+)$/);
            if (addMatch && operation.op === 'add' && operation.value) {
              const sectionId = decodeURIComponent(addMatch[1]);
              const sections = draft.sections as any[];
              const exists = sections.some((item: any) => item.id === sectionId);
              if (!exists) sections.push(operation.value);
              applied = true;
              continue;
            }
            const removeMatch = path.match(/^\/sections\/([^/]+)$/);
            if (removeMatch && operation.op === 'remove') {
              draft.sections = (draft.sections as any[]).filter((item: any) => item.id !== decodeURIComponent(removeMatch[1]));
              applied = true;
              continue;
            }
            const fieldMatch = path.match(/^\/sections\/([^/]+)\/([^/]+)$/);
            if (fieldMatch && operation.op === 'replace') {
              const sectionId = decodeURIComponent(fieldMatch[1]);
              const field = fieldMatch[2];
              const section = (draft.sections as any[]).find((item: any) => item.id === sectionId);
              if (section) {
                section[field] = operation.value;
                applied = true;
              }
              continue;
            }
            const blockRemoveMatch = path.match(/^\/sections\/([^/]+)\/blocks\/([^/]+)$/);
            if (blockRemoveMatch && operation.op === 'remove') {
              const section = (draft.sections as any[]).find((item: any) => item.id === decodeURIComponent(blockRemoveMatch[1]));
              if (section && Array.isArray(section.blocks)) {
                section.blocks = section.blocks.filter((block: any) => block.id !== decodeURIComponent(blockRemoveMatch[2]));
                applied = true;
              }
              continue;
            }
            const blockMatch = path.match(/^\/sections\/([^/]+)\/blocks\/([^/]+)(?:\/(.+))?$/);
            if (blockMatch) {
              const section = (draft.sections as any[]).find((item: any) => item.id === decodeURIComponent(blockMatch[1]));
              if (section && Array.isArray(section.blocks)) {
                const blockId = decodeURIComponent(blockMatch[2]);
                const rest = blockMatch[3];
                if (operation.op === 'add' && operation.value && !rest) {
                  const exists = section.blocks.some((block: any) => block.id === blockId);
                  if (!exists) section.blocks.push(operation.value);
                  applied = true;
                } else if (rest && operation.op === 'replace') {
                  const block = section.blocks.find((item: any) => item.id === blockId);
                  if (block) {
                    block[decodeURIComponent(rest)] = operation.value;
                    applied = true;
                  }
                }
              }
              continue;
            }
            continue;
          }
          const match = path.match(/^\/slides\/(\d+)$/);
          if (match && ['add', 'replace'].includes(String(operation.op)) && isCompleteSlidePatch(operation.value)) {
            draft.slides = [...(existing.slides || [])] as any[];
            draft.slides[Number(match[1])] = operation.value;
            applied = true;
          }
        }
        if (!applied) return;
        draft.last_patch = data.patch;
        draft.artifact_id = data.artifact_id;
        draft.artifact_type = data.artifact_type;
        this.draftArtifact = draft;
        this.draftRunId = runId;
        this.draftCourseId = currentTask.course_id;
        this.draftTaskId = currentTask.id;
      }
    },
    async load(courseId: string, taskType: string) {
      const epoch = ++this.requestEpoch;
      this.loading = true;
      this.error = '';
      try {
        const detail = await pipelineApi.get(courseId, taskType);
        if (epoch !== this.requestEpoch) return null;
        const project = useProjectStore();
        const activeRunId = project.currentTask?.active_run_id;
        if (activeRunId && detail.run?.generation_run_id && detail.run.generation_run_id !== activeRunId) {
          this.error = '流水线快照尚未对齐当前任务，正在重新同步。';
          return null;
        }
        this.detail = detail;
        return this.detail;
      } catch (cause: any) {
        this.error = cause?.message || '流水线详情加载失败';
        return null;
      } finally {
        this.loading = false;
      }
    },
    async pause(courseId: string, taskType: string) {
      this.pauseLoading = true;
      try {
        const result = await pipelineApi.pause(courseId, taskType);
        if (this.detail?.run) this.detail.run.status = result.status === 'paused' ? 'paused' : 'pausing';
        return result;
      } finally {
        this.pauseLoading = false;
      }
    },
    async resume(courseId: string, taskType: string) {
      this.resumeLoading = true;
      try {
        const result = await pipelineApi.resume(courseId, taskType);
        if (this.detail?.run) this.detail.run.status = 'queued';
        return result;
      } finally {
        this.resumeLoading = false;
      }
    },
    reset() {
      this.detail = null;
      this.error = '';
      this.thoughts = {};
      this.statusTexts = {};
      this.statusRunIds = {};
      this.draftArtifact = null;
      this.draftRunId = '';
      this.draftCourseId = '';
      this.draftTaskId = '';
      this.processedEventIds = new Set<number>();
      this.canonicalEvents = [];
      this.selectedSlideIds = [];
    },
    beginRun() {
      this.detail = null;
      this.error = '';
      this.thoughts = {};
      this.statusTexts = {};
      this.statusRunIds = {};
      this.draftArtifact = null;
      this.draftRunId = '';
      this.draftCourseId = '';
      this.draftTaskId = '';
      this.processedEventIds = new Set<number>();
      this.canonicalEvents = [];
    },
    clearDraft() {
      this.draftArtifact = null;
      this.draftRunId = '';
      this.draftCourseId = '';
      this.draftTaskId = '';
    },
  },
});
