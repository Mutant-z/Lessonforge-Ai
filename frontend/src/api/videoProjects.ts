import { api } from './client';
import type { VideoAgentPendingAction, VideoProjectStatus, VideoProjectSummary, VideoWorkspaceSnapshot } from '../types';

export const videoProjectsApi = {
  async list(params: { search?: string; status?: VideoProjectStatus; limit?: number; offset?: number } = {}) {
    const { data } = await api.get<{ items: VideoProjectSummary[]; total: number; limit: number; offset: number }>('/video-projects', { params });
    return data;
  },
  async get(courseId: string) {
    const { data } = await api.get<VideoWorkspaceSnapshot>(`/video-projects/${courseId}`);
    return data;
  },
  async message(courseId: string, content: string, selectedSceneIds: string[] = []) {
    const { data } = await api.post<{
      message_id: string;
      assistant_message: Record<string, any>;
      run_id: string;
      outcome: string;
      pending_action: VideoAgentPendingAction | null;
      memory_revision: number;
    }>(`/video-projects/${courseId}/agent/messages`, {
      content,
      selected_scene_ids: selectedSceneIds,
      client_message_id: crypto.randomUUID(),
    });
    return data;
  },
  async resolveAction(courseId: string, requestId: string, choice: 'confirm' | 'cancel') {
    const { data } = await api.post(`/video-projects/${courseId}/agent/actions/${requestId}`, { choice });
    return data;
  },
};
