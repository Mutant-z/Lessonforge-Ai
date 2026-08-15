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

export type LessonPlanMode = 'auto' | 'content' | 'structure' | 'timing' | 'qa';

/** 视频脚本 V4 运行模式（最终意图仍由 Agent 识别）。 */
export type VideoScriptMode = 'auto' | 'content' | 'structure' | 'timing' | 'qa';

export interface LessonPlanRunResult {
  run_id: string;
  task_id: string;
  message_id: string;
  status: 'queued';
  selected_section_ids?: string[];
}

export interface AgentRunHumanResponseResult {
  status: string;
  resolution?: string;
  result_status?: string;
  continuation_run_id?: string | null;
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
  /** 通用 Agent 人工确认（教学设计 V2 等非 PPT 流水线）。 */
  async agentRunHumanResponse(
    runId: string,
    requestId: string,
    choice: string,
    responseData: PPTHumanResponseData = {},
  ): Promise<AgentRunHumanResponseResult> {
    const { data } = await api.post<AgentRunHumanResponseResult>(`/agent-runs/${runId}/human-response`, {
      request_id: requestId,
      choice,
      data: responseData,
    });
    return data;
  },
  /** 教学设计 V2 运行创建（携带章节作用域与显式模式）。 */
  async createLessonPlanRun(
    courseId: string,
    content: string,
    selectedSectionIds: string[] = [],
    mode: LessonPlanMode = 'auto',
    activeSectionId?: string,
  ): Promise<LessonPlanRunResult> {
    const { data } = await api.post<LessonPlanRunResult>(`/courses/${courseId}/tasks/lesson_plan/runs`, {
      content,
      selected_section_ids: selectedSectionIds,
      mode: mode ?? 'auto',
      ...(activeSectionId ? { active_section_id: activeSectionId } : {}),
    });
    return data;
  },
  /** 视频脚本 V4 运行创建（携带章节/分镜作用域与显式模式）。 */
  async createVideoScriptRun(
    courseId: string,
    content: string,
    selectedSectionIds: string[] = [],
    selectedSceneIds: string[] = [],
    mode: VideoScriptMode = 'auto',
    activeSectionId?: string,
  ): Promise<LessonPlanRunResult> {
    const { data } = await api.post<LessonPlanRunResult>(`/courses/${courseId}/tasks/video_script/runs`, {
      content,
      selected_section_ids: selectedSectionIds,
      selected_scene_ids: selectedSceneIds,
      mode: mode ?? 'auto',
      ...(activeSectionId ? { active_section_id: activeSectionId } : {}),
    });
    return data;
  },
  /** 学习任务单 V3 运行创建（方案 §3.3：空闲时创建新运行）。 */
  async createTaskSheetRun(
    courseId: string,
    content: string,
    selectedSectionIds: string[] = [],
    mode: LessonPlanMode = 'auto',
    activeSectionId?: string,
  ): Promise<LessonPlanRunResult> {
    const { data } = await api.post<LessonPlanRunResult>(`/courses/${courseId}/tasks/task_sheet/runs`, {
      content,
      selected_section_ids: selectedSectionIds,
      mode: mode ?? 'auto',
      ...(activeSectionId ? { active_section_id: activeSectionId } : {}),
    });
    return data;
  },
  /** 教师逐字稿 V2 运行创建（携带章节作用域与显式模式）。 */
  async createVerbatimRun(
    courseId: string,
    content: string,
    selectedSectionIds: string[] = [],
    mode: LessonPlanMode = 'auto',
    activeSectionId?: string,
  ): Promise<LessonPlanRunResult> {
    const { data } = await api.post<LessonPlanRunResult>(`/courses/${courseId}/tasks/verbatim/runs`, {
      content,
      selected_section_ids: selectedSectionIds,
      mode: mode ?? 'auto',
      ...(activeSectionId ? { active_section_id: activeSectionId } : {}),
    });
    return data;
  },
  /** 学习任务单运行中指令排队（方案 §3.2：合并到当前目标并重规划）。 */
  async enqueueTaskSheetInstruction(
    courseId: string,
    runId: string,
    content: string,
    selectedSectionIds: string[] = [],
    mode: LessonPlanMode = 'auto',
    resumeIfPaused = false,
    clientInstructionId = '',
  ): Promise<{
    instruction_id: string;
    message_id: string;
    message: { id: string; role: 'user'; content: string; run_id: string; status: 'completed' };
    status: string;
  }> {
    const { data } = await api.post(
      `/courses/${courseId}/tasks/task_sheet/runs/${runId}/instructions`,
      {
        content,
        selected_section_ids: selectedSectionIds,
        mode: mode ?? 'auto',
        resume_if_paused: resumeIfPaused,
        ...(clientInstructionId ? { client_instruction_id: clientInstructionId } : {}),
      },
    );
    return data;
  },
  /** 学习任务单人工确认（方案 §3.3：同一 GenerationRun 从 checkpoint 恢复）。 */
  async taskSheetHumanResponse(
    courseId: string,
    runId: string,
    requestId: string,
    choice: string,
    responseData: PPTHumanResponseData = {},
  ): Promise<AgentRunHumanResponseResult> {
    const { data } = await api.post<AgentRunHumanResponseResult>(
      `/courses/${courseId}/tasks/task_sheet/runs/${runId}/human-responses/${requestId}`,
      { choice, data: responseData },
    );
    return data;
  },
};
