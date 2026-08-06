import { api } from './client';
import type { PipelineDetail } from '../types/agentPipeline';

export const pipelineApi = {
  async get(courseId: string, taskType: string): Promise<PipelineDetail> {
    const { data } = await api.get<PipelineDetail>(`/courses/${courseId}/tasks/${taskType}/pipeline`);
    return data;
  },
  async pause(courseId: string, taskType: string): Promise<{ status: string }> {
    const { data } = await api.post(`/courses/${courseId}/tasks/${taskType}/pause`);
    return data;
  },
  async resume(courseId: string, taskType: string): Promise<{ status: string }> {
    const { data } = await api.post(`/courses/${courseId}/tasks/${taskType}/resume`);
    return data;
  },
};
