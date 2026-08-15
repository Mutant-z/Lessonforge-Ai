import { api } from './client';
import type { ContextManifest, MemoryItem, ProjectMemorySummary } from '../types';

export interface ProjectMemoryDetail {
  revision: number;
  item_count: number;
  items: Record<string, MemoryItem[]>;
}

export interface ProjectMemoryContext extends ContextManifest {
  task_type: string;
  optional_reference_types?: string[];
  last_context_revision?: number;
  current_artifact_version?: number | null;
}

export const memoryApi = {
  /** 项目记忆总览：当前版本 + 按来源分组的条目。 */
  async get(courseId: string): Promise<ProjectMemoryDetail> {
    const { data } = await api.get<ProjectMemoryDetail>(`/courses/${courseId}/memory`);
    return data;
  },
  async getItem(courseId: string, itemId: string): Promise<MemoryItem> {
    const { data } = await api.get<MemoryItem>(`/courses/${courseId}/memory/items/${itemId}`);
    return data;
  },
  async search(courseId: string, query: string): Promise<{ query: string; items: MemoryItem[] }> {
    const { data } = await api.get<{ query: string; items: MemoryItem[] }>(
      `/courses/${courseId}/memory/search`,
      { params: { q: query } },
    );
    return data;
  },
  /** 某个 Agent 的上下文清单：记忆版本 + 可读取参考产物 + 缺失可选来源。 */
  async context(courseId: string, taskType?: string): Promise<ProjectMemoryContext> {
    const { data } = await api.get<ProjectMemoryContext>(
      `/courses/${courseId}/memory/context`,
      { params: taskType ? { task_type: taskType } : {} },
    );
    return data;
  },
};
