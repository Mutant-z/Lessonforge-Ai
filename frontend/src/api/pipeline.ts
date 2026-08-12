import { api } from './client';
import type { PipelineDetail } from '../types/agentPipeline';
import type { PPTPolishModality } from '../types/project';

export interface PPTPolishOptions {
  strength?: 'subtle' | 'moderate' | 'strong';
  content_policy?: 'preserve' | 'edit';
  image_policy?: 'preserve' | 'geometry' | 'replace';
  page_count_policy?: 'preserve' | 'allow_change';
  preserve_text?: boolean;
  preserve_images?: boolean;
  preserve_notes?: boolean;
  preserve_page_count?: boolean;
  confirmation_token?: string;
}

export interface PPTHumanResponseData {
  candidate_id?: string;
  [key: string]: unknown;
}

export interface PPTHumanResponseResult {
  request_id: string;
  status: string;
  resolution?: string;
  result_status?: 'queued' | 'no_change';
  run_id?: string;
  continuation_run_id?: string | null;
  confirmation_token?: string;
  selected_candidate_id?: string | null;
  target_slide_ids?: string[];
}

export const pipelineApi = {
  async createRun(
    courseId: string,
    instruction: string,
    selectedSlideIds: string[] = [],
    modality: PPTPolishModality = 'auto',
    activeSlideId?: string,
    polishOptions: PPTPolishOptions = {},
  ): Promise<{
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
      target_slide_ids: selectedSlideIds,
      selected_slide_ids: selectedSlideIds,
      modality: modality ?? 'auto',
      polish_options: polishOptions,
      ...(activeSlideId ? { active_slide_id: activeSlideId } : {}),
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
  async enqueue(
    runId: string,
    content: string,
    selectedSlideIds: string[] = [],
    resumeIfPaused = false,
    modality: PPTPolishModality = 'auto',
    activeSlideId?: string,
    polishOptions: PPTPolishOptions = {},
  ): Promise<{
    instruction_id: string;
    message_id: string;
    message: { id: string; role: 'user'; content: string; run_id: string; status: 'completed' };
    status: string;
  }> {
    const { data } = await api.post(`/ppt-agent/runs/${runId}/instructions`, {
      content,
      target_slide_ids: selectedSlideIds,
      selected_slide_ids: selectedSlideIds,
      resume_if_paused: resumeIfPaused,
      modality: modality ?? 'auto',
      polish_options: polishOptions,
      ...(activeSlideId ? { active_slide_id: activeSlideId } : {}),
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
  async humanResponse(
    runId: string,
    requestId: string,
    choice: string,
    responseData: PPTHumanResponseData = {},
  ): Promise<PPTHumanResponseResult> {
    const { data } = await api.post<PPTHumanResponseResult>(`/ppt-agent/runs/${runId}/human-response`, {
      request_id: requestId,
      choice,
      data: responseData,
    });
    return data;
  },
};
