export * from './agent';
export * from './content-block';
export * from './artifact';
export * from './intake';
export * from './settings';
export * from './project';

export interface Course {
  id: string;
  title: string;
  subject: string;
  grade_level: string;
  audience: string;
  duration_minutes: number;
  scenario: string;
  language: string;
  status: string;
  current_blueprint_version: number;
  created_at: string;
  updated_at: string;
}

export const statusLabel: Record<string, string> = {
  draft: '草稿',
  requirement_review: '需求待确认',
  blueprint_generating: '蓝图生成中',
  blueprint_review: '蓝图待确认',
  resource_generating: '资源生成中',
  quality_checking: '质量检查中',
  teacher_review: '待教师审核',
  completed: '已完成',
  failed: '生成失败',
  needs_attention: '部分任务需处理',
  archived: '已归档'
};

export const statusTagType: Record<string, 'info' | 'warning' | 'primary' | 'success' | 'danger'> = {
  draft: 'info',
  requirement_review: 'warning',
  blueprint_generating: 'primary',
  blueprint_review: 'warning',
  resource_generating: 'primary',
  quality_checking: 'warning',
  teacher_review: 'warning',
  completed: 'success',
  failed: 'danger',
  needs_attention: 'danger',
  archived: 'info'
};
