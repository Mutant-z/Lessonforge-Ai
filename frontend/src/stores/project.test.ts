import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { api } from '../api/client';
import { useProjectStore } from './project';
import type { CourseProjectWorkspace, CourseTask } from '../types';

vi.mock('../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (cause: { message?: string }) => cause.message || '操作失败',
}));

const task: CourseTask = {
  id: 'task-ppt',
  course_id: 'course-1',
  task_type: 'ppt',
  display_name: 'PPT 课件',
  agent_name: 'PPT Agent',
  agent_type: 'ppt_agent',
  display_order: 2,
  status: 'running',
  progress: 35,
  dependency_types: [],
  stale_dependencies: [],
  current_artifact: null,
  active_run_id: 'run-1',
  error: null,
  updated_at: '2026-08-03T00:00:00Z',
  messages: [],
};

const project: CourseProjectWorkspace = {
  course: {
    id: 'course-1', title: '阿基米德原理', subject: '物理', grade_level: '八年级',
    audience: '八年级学生', duration_minutes: 10, scenario: '课堂讲解', language: '中文',
    status: 'resource_generating', current_blueprint_version: 1,
    created_at: '2026-08-03T00:00:00Z', updated_at: '2026-08-03T00:00:00Z',
  },
  intent: {
    headline: '为八年级学生设计阿基米德原理微课', title: '阿基米德原理', subject: '物理',
    grade_level: '八年级', audience: '八年级学生', duration_minutes: 10, scenario: '课堂讲解',
    course_task: '解释浮力来源', teaching_objectives: '', key_points: '', difficulty_points: '',
    teaching_method: '', style_requirements: '', assumptions: [], deliverables: [],
  },
  planning: { status: 'ready', progress: 100, error: null },
  tasks: [{ ...task }],
  quality: { score: null, summary: '', open_issues: 0, issues: [] },
};

describe('project task store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(api.get).mockReset().mockResolvedValue({ data: [{ ...task }] });
    vi.mocked(api.post).mockReset();
  });

  it('atomically applies a validated artifact event to only its task', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];

    store.applyEvent('artifact_version_created', {
      event_id: 9,
      course_id: 'course-1',
      task_id: 'task-ppt',
      task_type: 'ppt',
      run_id: 'run-1',
      status: 'review',
      progress: 100,
      artifact: {
        id: 'artifact-2', course_id: 'course-1', artifact_type: 'ppt', version: 2,
        blueprint_version: 1, content_json: { slides: [] }, content_markdown: '# PPT',
        status: 'draft', is_locked: false, created_at: '2026-08-03T00:01:00Z',
      },
    });

    expect(store.tasks[0].status).toBe('review');
    expect(store.tasks[0].active_run_id).toBeNull();
    expect(store.tasks[0].current_artifact?.version).toBe(2);
    expect(store.lastEventId).toBe(9);
  });

  it('keeps a failed optimistic teacher message and exposes it for retry', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = { ...store.project.tasks[0], current_artifact: {
      id: 'artifact-1', course_id: 'course-1', artifact_type: 'ppt', version: 1,
      blueprint_version: 1, content_json: {}, content_markdown: '# PPT', status: 'draft',
      is_locked: false, created_at: '2026-08-03T00:00:00Z',
    }, messages: [] };
    vi.mocked(api.post).mockRejectedValue(new Error('网络失败'));

    await expect(store.sendMessage('course-1', 'ppt', '压缩核心概念页')).rejects.toThrow('网络失败');

    expect(store.currentTask.messages).toHaveLength(1);
    expect(store.currentTask.messages?.[0].status).toBe('failed');
  });
});
