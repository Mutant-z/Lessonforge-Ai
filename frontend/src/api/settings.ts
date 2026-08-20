import { api } from './client';
import type {
  FullSettingsResponse,
  ModelConfigItem,
  ModelConfigPayload,
  TestConnectionPayload,
  UserPreferencesPayload,
} from '../types/settings';

export const settingsApi = {
  // 获取完整设置（包含所有模型配置与偏好）
  getSettings: () => api.get<FullSettingsResponse>('/settings').then(r => r.data),

  // 创建新模型配置
  createModelConfig: (data: ModelConfigPayload) =>
    api.post<ModelConfigItem>('/settings/models', data).then(r => r.data),

  // 更新已有的模型配置
  updateModelConfig: (configId: string, data: Partial<ModelConfigPayload>) =>
    api.patch<ModelConfigItem>(`/settings/models/${configId}`, data).then(r => r.data),

  // 设为当前激活配置
  activateModelConfig: (configId: string) =>
    api.post<ModelConfigItem>(`/settings/models/${configId}/activate`).then(r => r.data),

  duplicateModelConfig: (configId: string, data: Pick<ModelConfigPayload, 'model_category' | 'model_purpose'> & { name?: string }) =>
    api.post<ModelConfigItem>(`/settings/models/${configId}/duplicate`, data).then(r => r.data),

  // 删除模型配置
  deleteModelConfig: (configId: string) =>
    api.delete<{ message: string }>(`/settings/models/${configId}`).then(r => r.data),

  // 测试 LLM 连通性
  testConnection: (data: TestConnectionPayload) =>
    api.post<{ success: boolean; message: string; provider: string; model_name: string }>(
      '/settings/test-connection',
      data
    ).then(r => r.data),

  // 保存个人偏好
  updatePreferences: (data: UserPreferencesPayload) =>
    api.patch<{ message: string; preferences: UserPreferencesPayload }>(
      '/settings/preferences',
      data
    ).then(r => r.data),
};
