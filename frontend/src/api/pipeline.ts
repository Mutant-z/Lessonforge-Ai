import { api } from './client';
import type { PipelineDetail } from '../types/agentPipeline';

export const pipelineApi = {
  async createRun(courseId: string, instruction: string, selectedSlideIds: string[] = []): Promise<{
    run_id: string;
    task_id: string;
    message_id: string;
    status: 'queued';
    selected_slide_ids: string[];
  }> {
    const { data } = await api.post('/ppt-agent/runs', {
      course_id: courseId,
      instruction,
      action: 'message',
      selected_slide_ids: selectedSlideIds,
    });
    return data;
  },
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
  async enqueue(runId: string, content: string, selectedSlideIds: string[] = []): Promise<{
    instruction_id: string;
    message_id: string;
    message: { id: string; role: 'user'; content: string; run_id: string; status: 'completed' };
    status: string;
  }> {
    const { data } = await api.post(`/ppt-agent/runs/${runId}/instructions`, {
      content,
      selected_slide_ids: selectedSlideIds,
    });
    return data;
  },
  async cancelRun(runId: string): Promise<{ status: string }> {
    const { data } = await api.post(`/ppt-agent/runs/${runId}/cancel`);
    return data;
  },
  async slides(artifactId: string) {
    const { data } = await api.get(`/ppt-agent/artifacts/${artifactId}/slides`);
    return data;
  },
  async switchTemplate(artifactId: string, templateId: string, selectedSlideIds: string[] = []) {
    const { data } = await api.post(`/ppt-agent/artifacts/${artifactId}/template-switch`, {
      template_id: templateId,
      selected_slide_ids: selectedSlideIds,
    });
    return data;
  },
  async humanResponse(runId: string, requestId: string, choice: string) {
    const { data } = await api.post(`/ppt-agent/runs/${runId}/human-response`, {
      request_id: requestId,
      choice,
      data: {},
    });
    return data;
  },
};
