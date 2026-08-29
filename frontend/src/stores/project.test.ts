import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { api } from '../api/client';
import { useProjectStore } from './project';
import type { CourseProjectWorkspace, CourseTask, ProjectTaskEvent } from '../types';

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

  it('never rolls the official PPT back when an older artifact event is replayed', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    const v26 = {
      id: 'artifact-26', course_id: 'course-1', artifact_type: 'ppt', version: 26,
      blueprint_version: 1, content_json: { slides: [{ title: 'V26' }] }, content_markdown: '# V26',
      status: 'draft', is_locked: false, created_at: '2026-08-08T00:00:00Z',
    };
    store.project.tasks[0].current_artifact = v26;
    store.currentTask = store.project.tasks[0];
    store.syncOfficialArtifact();

    store.applyEvent('artifact_version_created', {
      event_id: 99, course_id: 'course-1', task_id: 'task-ppt', task_type: 'ppt', status: 'review',
      artifact: { ...v26, id: 'artifact-22', version: 22, content_json: { slides: [{ title: 'V22' }] } },
    });

    expect(store.currentTask.current_artifact?.version).toBe(26);
    expect(store.officialArtifact?.content_json.slides[0].title).toBe('V26');
  });

  it('ignores events already represented by the authoritative snapshot cursor', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];
    store.lastEventId = 5467;

    store.applyEvent('artifact_version_created', {
      event_id: 3180, course_id: 'course-1', task_id: 'task-ppt', task_type: 'ppt', status: 'review',
      artifact: {
        id: 'artifact-22', course_id: 'course-1', artifact_type: 'ppt', version: 22,
        blueprint_version: 1, content_json: { slides: [{ title: 'V22' }] }, content_markdown: '# V22',
        status: 'draft', is_locked: false, created_at: '2026-08-08T00:00:00Z',
      },
    });

    expect(store.currentTask.current_artifact).toBeNull();
    expect(store.lastEventId).toBe(5467);
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

  it('shows a queued PPT instruction immediately and reconciles the server message', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];
    let resolveRequest!: (value: any) => void;
    vi.mocked(api.post).mockReturnValue(new Promise(resolve => { resolveRequest = resolve; }));

    const request = store.enqueuePPTInstruction('run-1', '调整当前页配色', ['S02']);
    expect(store.currentTask.messages).toEqual([
      expect.objectContaining({ role: 'user', content: '调整当前页配色', status: 'pending', run_id: 'run-1' }),
    ]);

    resolveRequest({ data: {
      instruction_id: 'instruction-1', message_id: 'message-1', status: 'queued',
      message: { id: 'message-1', role: 'user', content: '调整当前页配色', status: 'completed', run_id: 'run-1' },
    } });
    await request;

    expect(api.post).toHaveBeenCalledWith('/ppt-agent/runs/run-1/instructions', {
      content: '调整当前页配色', target_slide_ids: ['S02'], selected_slide_ids: ['S02'],
      resume_if_paused: false, modality: 'auto', polish_options: {},
    });
    expect(store.currentTask.messages).toEqual([
      expect.objectContaining({ id: 'message-1', content: '调整当前页配色', status: 'completed', run_id: 'run-1' }),
    ]);
  });

  it('atomically queues an instruction and resumes its paused PPT run', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = { ...store.project.tasks[0], status: 'paused', messages: [] };
    store.pipelineStatus = 'paused';
    vi.mocked(api.post).mockResolvedValue({ data: {
      instruction_id: 'instruction-resume', message_id: 'message-resume', status: 'resumed',
      message: {
        id: 'message-resume', role: 'user', content: '继续润色首页',
        status: 'completed', run_id: 'run-paused',
      },
    } });

    const result = await store.enqueuePPTInstruction('run-paused', '继续润色首页', ['slide_01'], true);

    expect(api.post).toHaveBeenCalledWith('/ppt-agent/runs/run-paused/instructions', {
      content: '继续润色首页', target_slide_ids: ['slide_01'], selected_slide_ids: ['slide_01'],
      resume_if_paused: true, modality: 'auto', polish_options: {},
    });
    expect(result.status).toBe('resumed');
    expect(store.pipelineStatus).toBe('queued');
    expect(store.currentTask.status).toBe('queued');
    expect(store.currentTask.messages).toEqual([
      expect.objectContaining({ id: 'message-resume', run_id: 'run-paused', status: 'completed' }),
    ]);
  });

  it('creates a new PPT run with selected slides and replaces the stale run status', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];
    store.pipelineStatus = 'completed';
    vi.spyOn(store, 'startActiveTaskPolling').mockImplementation(() => undefined);
    vi.mocked(api.post).mockResolvedValue({ data: {
      run_id: 'run-2', task_id: 'task-ppt', message_id: 'message-2',
      status: 'queued', selected_slide_ids: ['slide_01'],
    } });

    await store.createPPTRun('course-1', '润色一下首页', ['slide_01']);

    expect(api.post).toHaveBeenCalledWith('/ppt-agent/runs', {
      course_id: 'course-1', instruction: '润色一下首页', action: 'message',
      target_slide_ids: ['slide_01'], selected_slide_ids: ['slide_01'], modality: 'auto', polish_options: {},
    });
    expect(store.pipelineStatus).toBe('queued');
    expect(store.currentTask.active_run_id).toBe('run-2');
    expect(store.currentTask.messages?.at(-1)).toMatchObject({
      id: 'message-2', run_id: 'run-2', content: '润色一下首页', status: 'completed',
    });
  });

  it('preserves first-run SSE feedback that arrives before createRun resolves', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];
    store.pipelineEvents = [{ type: 'pipeline_completed', data: { run_id: 'run-old' }, event_id: 10 }];
    store.lastEventId = 10;
    vi.spyOn(store, 'startActiveTaskPolling').mockImplementation(() => undefined);

    let resolveRequest!: (value: any) => void;
    vi.mocked(api.post).mockReturnValue(new Promise(resolve => { resolveRequest = resolve; }));

    const request = store.createPPTRun('course-1', '润色一下首页', ['slide_01']);
    expect(store.pipelineEvents).toEqual([]);

    store.applyEvent('agent_status_delta', {
      event_id: 11,
      course_id: 'course-1',
      run_id: 'run-2',
      task_id: 'task-ppt',
      agent_key: 'orchestrator',
      text: '正在理解修改范围。',
      status: 'running',
    });

    resolveRequest({ data: {
      run_id: 'run-2', task_id: 'task-ppt', message_id: 'message-2',
      status: 'queued', selected_slide_ids: ['slide_01'],
    } });
    await request;

    expect(store.pipelineEvents).toEqual([
      expect.objectContaining({
        type: 'agent_status_delta',
        event_id: 11,
        data: expect.objectContaining({ run_id: 'run-2', text: '正在理解修改范围。' }),
      }),
    ]);
  });

  it('cancels a non-pipeline task through the generic task endpoint and clears its active run', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.project.tasks[0] = { ...store.project.tasks[0], id: 'task-video', task_type: 'video_generation' };
    store.currentTask = store.project.tasks[0];
    vi.spyOn(store, 'refreshCurrentTask').mockResolvedValue(undefined);
    vi.mocked(api.post).mockResolvedValue({ data: { task_id: 'task-video', status: 'cancelled' } });

    await store.cancelTask('course-1', 'video_generation');

    expect(api.post).toHaveBeenCalledWith('/courses/course-1/tasks/video_generation/cancel');
    expect(store.currentTask.status).toBe('cancelled');
    expect(store.currentTask.active_run_id).toBeNull();
    expect(store.refreshCurrentTask).toHaveBeenCalledOnce();
  });

  it('preserves the large PPT artifact identity during status polling', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', globalThis);
    try {
      const store = useProjectStore();
      store.project = structuredClone(project);
      const artifact = {
        id: 'artifact-1', course_id: 'course-1', artifact_type: 'ppt', version: 1,
        blueprint_version: 1, content_json: { slides: Array.from({ length: 15 }, (_, id) => ({ id })) },
        content_markdown: '# PPT', status: 'draft', is_locked: false, created_at: '2026-08-03T00:00:00Z',
      };
      store.currentTask = { ...store.project.tasks[0], current_artifact: artifact };
      const artifactBeforePolling = store.currentTask.current_artifact;
      vi.mocked(api.get).mockResolvedValue({ data: {
        ...store.currentTask,
        current_artifact: structuredClone(artifact),
      } });

      store.startActiveTaskPolling('course-1', 'ppt');
      await vi.advanceTimersByTimeAsync(1);

      expect(store.currentTask.current_artifact).toBe(artifactBeforePolling);
      store.stopActiveTaskPolling();
    } finally {
      vi.unstubAllGlobals();
      vi.useRealTimers();
    }
  });

  it('keeps the formal PPT artifact when a restart refresh briefly returns null', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    const artifact = {
      id: 'artifact-26', course_id: 'course-1', artifact_type: 'ppt', version: 26,
      blueprint_version: 1, content_json: { slides: [{ id: 'slide_01', title: '封面' }] },
      content_markdown: '# PPT', status: 'draft', is_locked: false, created_at: '2026-08-08T00:00:00Z',
    };
    store.currentTask = { ...store.project.tasks[0], current_artifact: artifact };
    vi.mocked(api.get).mockResolvedValue({ data: { ...store.currentTask, current_artifact: null } });

    await store.refreshCurrentTask();

    expect(store.currentTask.current_artifact?.id).toBe('artifact-26');
    expect(store.currentTask.current_artifact?.content_json.slides).toHaveLength(1);
  });

  it('reconciles a queued instruction event without duplicating its optimistic bubble', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = {
      ...store.project.tasks[0],
      messages: [{ id: 'local-1', role: 'user', content: '调整当前页配色', status: 'pending', run_id: 'run-1' }],
    };

    store.applyEvent('run.instruction.queued', {
      event_id: 52, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1',
      payload: { user_message: { id: 'message-1', role: 'user', content: '调整当前页配色', status: 'completed', run_id: 'run-1' } },
    });

    expect(store.currentTask.messages).toEqual([
      expect.objectContaining({ id: 'message-1', content: '调整当前页配色', status: 'completed' }),
    ]);
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

  it('keeps non-empty content from agent_message_started (resume scenario)', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];

    store.applyEvent('agent_message_started', {
      event_id: 40, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1',
      message: { id: 'reply-9', role: 'assistant', content: '已生成的进度正文', status: 'streaming', run_id: 'run-1' },
    });

    expect(store.currentTask.messages).toEqual([
      expect.objectContaining({ id: 'reply-9', content: '已生成的进度正文', status: 'streaming' }),
    ]);
  });

  it('applies video resolution setting events immediately without waiting for snapshot refresh', () => {
    const store = useProjectStore();
    const videoScriptTask = {
      ...structuredClone(task),
      id: 'task-video-script',
      task_type: 'video_script',
      display_name: '视频脚本',
      preferred_video_resolution: '854x480',
    } as CourseTask;
    const videoGenerationTask = {
      ...structuredClone(task),
      id: 'task-video-generation',
      task_type: 'video_generation',
      display_name: '视频生成',
      preferred_video_resolution: '854x480',
    } as CourseTask;
    store.project = { ...structuredClone(project), tasks: [videoScriptTask, videoGenerationTask] };
    store.currentTask = videoScriptTask;
    // 保持后台校验刷新挂起，证明可见状态不依赖网络往返。
    vi.mocked(api.get).mockReturnValue(new Promise(() => {}));

    store.applyEvent('video_generation.setting.updated', {
      event_id: 45,
      course_id: 'course-1',
      task_id: 'task-video-script',
      task_type: 'video_script',
      run_id: 'run-1',
      payload: { resolution: '1280x720' },
    });

    expect(store.currentTask.preferred_video_resolution).toBe('1280x720');
    expect(store.project.tasks.map(item => item.preferred_video_resolution)).toEqual([
      '1280x720', '1280x720',
    ]);
  });

  it('does not let an older task snapshot roll back a committed resolution event', async () => {
    const store = useProjectStore();
    const videoTask = {
      ...structuredClone(task),
      id: 'task-video-script',
      task_type: 'video_script',
      preferred_video_resolution: '854x480',
      event_cursor: 44,
    } as CourseTask;
    store.project = { ...structuredClone(project), tasks: [videoTask] };
    store.currentTask = videoTask;
    vi.mocked(api.get).mockResolvedValue({
      data: { ...structuredClone(videoTask), preferred_video_resolution: '854x480', event_cursor: 44 },
    });

    store.applyEvent('video_generation.setting.updated', {
      event_id: 45,
      course_id: 'course-1',
      task_id: 'task-video-script',
      task_type: 'video_script',
      run_id: 'run-1',
      payload: { resolution: '1280x720', previous_resolution: '854x480', changed: true },
    });

    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    await Promise.resolve();
    expect(store.videoResolutionEventId).toBe(45);
    expect(store.currentTask.preferred_video_resolution).toBe('1280x720');
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

  it('passes the chosen polish modality through createRun and enqueue', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];
    vi.spyOn(store, 'startActiveTaskPolling').mockImplementation(() => undefined);
    vi.mocked(api.post).mockResolvedValue({ data: {
      run_id: 'run-modality', task_id: 'task-ppt', message_id: 'message-modality',
      status: 'queued', selected_slide_ids: ['slide_01'],
    } });

    await store.createPPTRun('course-1', '只调整排版', ['slide_01'], 'layout');

    expect(api.post).toHaveBeenCalledWith('/ppt-agent/runs', {
      course_id: 'course-1', instruction: '只调整排版', action: 'message',
      target_slide_ids: ['slide_01'], selected_slide_ids: ['slide_01'], modality: 'layout', polish_options: {},
    });

    vi.mocked(api.post).mockResolvedValue({ data: {
      instruction_id: 'instruction-modality', message_id: 'message-enqueue', status: 'queued',
      message: { id: 'message-enqueue', role: 'user', content: '只改文字', status: 'completed', run_id: 'run-modality' },
    } });
    await store.enqueuePPTInstruction('run-modality', '只改文字', ['slide_01'], false, 'text');

    expect(api.post).toHaveBeenCalledWith('/ppt-agent/runs/run-modality/instructions', {
      content: '只改文字', target_slide_ids: ['slide_01'], selected_slide_ids: ['slide_01'],
      resume_if_paused: false, modality: 'text', polish_options: {},
    });
  });

  it('passes the active section id through createLessonPlanRun', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];
    vi.spyOn(store, 'startActiveTaskPolling').mockImplementation(() => undefined);
    vi.mocked(api.post).mockResolvedValue({ data: {
      run_id: 'run-lesson', task_id: 'task-lesson', message_id: 'message-lesson',
      status: 'queued', selected_section_ids: ['SEC-REFLECTION'],
    } });

    await store.createLessonPlanRun('course-1', '教学反思的序号有问题', ['SEC-REFLECTION'], 'content', 'SEC-REFLECTION');

    expect(api.post).toHaveBeenCalledWith('/courses/course-1/tasks/lesson_plan/runs', {
      content: '教学反思的序号有问题',
      selected_section_ids: ['SEC-REFLECTION'],
      mode: 'content',
      active_section_id: 'SEC-REFLECTION',
    });
  });

  it('resets per-slide repair notes when a new repair round starts, keeping only the current round', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];

    store.applyEvent('qa_issue_found', {
      event_id: 101, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1', status: 'running',
      issue: { severity: 'critical', slide_id: 'slide_03', rule_id: 'content.not_rendered', message: '页面语义文字没有进入最终渲染层', target_agent: 'layout' },
    });
    store.applyEvent('repair.started', {
      event_id: 102, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1', status: 'running',
      payload: {
        target_agents: ['layout'],
        issues: [
          { severity: 'major', slide_id: 'slide_03', rule_id: 'layout.blank_region', message: '页面内容只覆盖画布少部分，大面积空白', target_agent: 'layout' },
          { severity: 'minor', slide_id: 'slide_07', rule_id: 'content.missing_title', message: '页面缺少标题', target_agent: 'slide_content' },
        ],
      },
    });

    // 上一轮的 content.not_rendered 徽标不跨轮累计：新轮开始即重置，
    // 页面徽标只反映当前轮待修复的问题（否则徽标数会随轮数越滚越大）。
    expect(store.slideRepairNotes['slide_03']).toEqual([
      '主要：页面内容只覆盖画布少部分，大面积空白（layout.blank_region）',
    ]);
    expect(store.slideRepairNotes['slide_07']).toEqual([
      '次要：页面缺少标题（content.missing_title）',
    ]);
  });

  it('does not duplicate identical repair notes across rounds', () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];

    const repair = (eventId: number): ProjectTaskEvent => ({
      event_id: eventId, course_id: 'course-1', task_id: 'task-ppt', run_id: 'run-1', status: 'running',
      payload: { issues: [{ severity: 'major', slide_id: 'slide_03', rule_id: 'layout.blank_region', message: '大面积空白', target_agent: 'layout' }] },
    });
    store.applyEvent('repair.started', repair(201));
    store.applyEvent('repair.started', repair(202));

    expect(store.slideRepairNotes['slide_03']).toHaveLength(1);
  });

  it('clears repair notes when a fresh PPT run starts', async () => {
    const store = useProjectStore();
    store.project = structuredClone(project);
    store.currentTask = store.project.tasks[0];
    store.slideRepairNotes = { slide_03: ['严重：页面文字没有进入最终渲染层'] };
    vi.spyOn(store, 'startActiveTaskPolling').mockImplementation(() => undefined);
    vi.mocked(api.post).mockResolvedValue({ data: {
      run_id: 'run-fresh', task_id: 'task-ppt', message_id: 'message-fresh',
      status: 'queued', selected_slide_ids: [],
    } });

    await store.createPPTRun('course-1', '整体润色');

    expect(store.slideRepairNotes).toEqual({});
  });
});
