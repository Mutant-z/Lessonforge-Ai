import { defineStore } from 'pinia';
import { pipelineApi } from '../api/pipeline';
import type { PipelineDetail, PipelineStatus } from '../types/agentPipeline';
import { useProjectStore } from './project';

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
    /** agent_key → 累计思考文本（单调累加，不受 project.pipelineEvents 裁剪影响） */
    thoughts: {} as Record<string, string>,
  }),
  getters: {
    run: state => state.detail?.run ?? null,
    status: state => (state.detail?.run?.status || '') as PipelineStatus,
    artifacts: state => state.detail?.artifacts ?? [],
    toolCalls: state => state.detail?.tool_calls ?? [],
    plan: state => (state.detail?.plan as Array<Record<string, any>>) ?? [],
    timeline(state): PipelineTimelineItem[] {
      const project = useProjectStore();
      const live = project.pipelineEvents.map(event => ({
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
  },
  actions: {
    /** 从历史（detail.events）重建思考文本（刷新恢复） */
    restoreThoughtsFromHistory() {
      const apply = (type: string, data: Record<string, any>) => {
        if (type !== 'agent_thought_chunk' || !data.agent_key) return;
        const prev = this.thoughts[data.agent_key] || '';
        const text = String(data.text || '');
        if (!prev.includes(text)) this.thoughts[data.agent_key] = prev + text;
      };
      for (const item of this.detail?.events ?? []) apply(item.event_type, item.data);
    },
    /** 把 project store 收件箱的实时思考增量单调累加（幂等：已累加过的片段跳过） */
    syncThoughts() {
      const project = useProjectStore();
      for (const ev of project.pipelineEvents) {
        if (ev.type !== 'agent_thought_chunk' || !ev.data.agent_key) continue;
        const prev = this.thoughts[ev.data.agent_key] || '';
        const text = String(ev.data.text || '');
        if (!prev.includes(text)) this.thoughts[ev.data.agent_key] = prev + text;
      }
    },
    async load(courseId: string, taskType: string) {
      this.loading = true;
      this.error = '';
      try {
        this.detail = await pipelineApi.get(courseId, taskType);
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
        if (this.detail?.run) this.detail.run.status = 'paused';
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
    },
  },
});
