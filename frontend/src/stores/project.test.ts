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
  agent_profile_status: 'ready',
  agent_profile_version: 1,
  agent_profile_template_version: 'v1',
  agent_profile_summary: null,
  stale_agent_profile: false,
  agent_profile_error: null,
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
  agent_initialization: { status: 'ready', version: 1, progress: 100, error: null },
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

  it('applies project-wide Agent initialization events without requiring a task id', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);

    store.applyEvent('agent_initialization_progress', {
      event_id: 10,
      course_id: 'course-1',
      status: 'running',
      progress: 65,
    });
    expect(store.project.agent_initialization.status).toBe('running');
    expect(store.project.agent_initialization.progress).toBe(65);

    store.applyEvent('agent_initialization_completed', {
      event_id: 11,
      course_id: 'course-1',
      status: 'ready',
      progress: 100,
      version: 2,
    });
    expect(store.project.agent_initialization).toMatchObject({ status: 'ready', progress: 100, version: 2 });
  });

  it('builds a streamed assistant message and ignores duplicate deltas', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];

    store.applyEvent('agent_message_started', {
      event_id: 20, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1',
      message: { id: 'reply-1', role: 'assistant', content: '', status: 'streaming', run_id: 'run-1' },
    });
    store.applyEvent('agent_message_delta', {
      event_id: 21, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1',
      message_id: 'reply-1', delta: '正在更新',
    });
    store.applyEvent('agent_message_delta', {
      event_id: 21, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1',
      message_id: 'reply-1', delta: '正在更新',
    });
    store.applyEvent('agent_message_completed', {
      event_id: 22, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1',
      message: { id: 'reply-1', role: 'assistant', content: '正在更新完成。', status: 'completed', run_id: 'run-1' },
    });

    expect(store.currentTask.messages).toEqual([
      expect.objectContaining({ id: 'reply-1', content: '正在更新完成。', status: 'completed' }),
    ]);
  });

  it('tracks safe task activity by phase and resets it for a new run', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];

    store.applyEvent('task_activity_updated', {
      event_id: 30, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1',
      phase: 'generating', phase_label: '生成结构化新版本', detail: '正在生成。',
      phase_status: 'running', progress: 42, elapsed_ms: 4000,
    });
    store.applyEvent('task_activity_updated', {
      event_id: 31, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-2',
      phase: 'preparing', phase_label: '读取配置', detail: '正在加载。',
      phase_status: 'running', progress: 10,
    });

    expect(store.currentTask.activity_run_id).toBe('run-2');
    expect(store.currentTask.activities).toHaveLength(1);
    expect(store.currentTask.current_activity).toMatchObject({ phase: 'preparing', progress: 10 });
  });
});
