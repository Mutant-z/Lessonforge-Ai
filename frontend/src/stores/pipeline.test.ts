import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { usePipelineStore } from './pipeline';
import { useProjectStore } from './project';
import type { PipelineDetail, PipelineStatus } from '../types/agentPipeline';

function compiledSlide(title: string) {
  return {
    id: 'slide_01', title, purpose: '', body: ['正文'], blocks: [],
    speaker_notes: '备注', elements: [], render_mode: 'semantic',
  };
}

function detail(status: PipelineStatus): PipelineDetail {
  return {
    run: {
      id: 'pipeline-1', generation_run_id: 'run-1', status, pipeline_type: 'ppt',
      current_agent: '', current_step_index: 0, revision_round: 0, max_revision_rounds: 3,
      plan: {}, checkpoint: {}, token_usage: {}, error: null, created_at: '2026-08-08T00:00:00Z',
    },
    plan: [], artifacts: [], tool_calls: [],
    events: [{
      id: 10, sequence: 10, event_type: 'artifact_patch', created_at: '2026-08-08T00:00:01Z',
      data: { run_id: 'run-1', patch: [{ op: 'replace', path: '/slides/0', value: compiledSlide('中间草稿') }] },
    }],
  };
}

describe('pipeline store draft restoration', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('does not replay an intermediate slide patch for a completed run', () => {
    const store = usePipelineStore();
    store.detail = detail('completed');

    store.restoreThoughtsFromHistory();

    expect(store.draftArtifact).toBeNull();
  });

  it('restores a draft patch while the run is still active', () => {
    const store = usePipelineStore();
    const project = useProjectStore();
    project.currentTask = { id: 'task-ppt', course_id: 'course-1', task_type: 'ppt' } as any;
    store.detail = detail('running');

    store.restoreThoughtsFromHistory();

    expect(store.draftArtifact?.slides?.[0]).toMatchObject({ title: '中间草稿' });
  });

  it('does not apply course history before the active run is known', () => {
    const pipeline = usePipelineStore();
    const project = useProjectStore();
    project.pipelineEvents = [{
      event_id: 20, type: 'artifact_patch',
      data: { run_id: 'old-run', patch: [{ op: 'replace', path: '/slides/0', value: { title: 'V22 旧页面' } }] },
    }];

    pipeline.syncThoughts();

    expect(pipeline.draftArtifact).toBeNull();
  });

  it('filters replayed page patches from older runs', () => {
    const pipeline = usePipelineStore();
    const project = useProjectStore();
    project.currentTask = { id: 'task-ppt', course_id: 'course-1', task_type: 'ppt' } as any;
    pipeline.detail = detail('running');
    project.pipelineEvents = [
      {
        event_id: 20, type: 'artifact_patch',
        data: { run_id: 'old-run', patch: [{ op: 'replace', path: '/slides/0', value: { title: 'V22 旧页面' } }] },
      },
      {
        event_id: 21, type: 'artifact_patch',
        data: { run_id: 'run-1', patch: [{ op: 'replace', path: '/slides/0', value: compiledSlide('当前 Run 页面') }] },
      },
    ];

    pipeline.syncThoughts();

    expect(pipeline.draftArtifact?.slides?.[0]).toMatchObject({ title: '当前 Run 页面' });
    expect(pipeline.processedEventIds).toEqual(new Set([20, 21]));
  });

  it('rejects a media-only intermediate page patch', () => {
    const pipeline = usePipelineStore();
    const project = useProjectStore();
    project.currentTask = { id: 'task-ppt', course_id: 'course-1', task_type: 'ppt' } as any;
    pipeline.detail = detail('running');

    pipeline.applyStreamEvent('artifact_patch', {
      run_id: 'run-1', course_id: 'course-1', task_id: 'task-ppt',
      patch: [{ op: 'replace', path: '/slides/3', value: {
        id: 'slide_04', elements: [{ kind: 'image', asset_id: 'new-image' }], render_mode: 'hybrid',
      } }],
    });

    expect(pipeline.draftArtifact).toBeNull();
  });

  it('clears a compiled draft when the image run fails', () => {
    const pipeline = usePipelineStore();
    const project = useProjectStore();
    project.currentTask = { id: 'task-ppt', course_id: 'course-1', task_type: 'ppt' } as any;
    pipeline.detail = detail('running');
    pipeline.applyStreamEvent('artifact_patch', {
      run_id: 'run-1', course_id: 'course-1', task_id: 'task-ppt',
      patch: [{ op: 'replace', path: '/slides/3', value: {
        ...compiledSlide('完整图片页'), id: 'slide_04', render_mode: 'hybrid',
        elements: [{ kind: 'image', asset_id: 'new-image' }],
      } }],
    });
    expect(pipeline.draftArtifact).not.toBeNull();

    pipeline.applyStreamEvent('run.failed', { run_id: 'run-1' });

    expect(pipeline.draftArtifact).toBeNull();
  });

  it('filters live timeline events belonging to a different task or run', () => {
    const pipeline = usePipelineStore();
    const project = useProjectStore();
    project.currentTask = { id: 'task-sheet-1', course_id: 'course-1', task_type: 'task_sheet', active_run_id: 'run-ts-1' } as any;
    pipeline.detail = {
      run: {
        id: 'pipeline-ts-1', generation_run_id: 'run-ts-1', status: 'running', pipeline_type: 'task_sheet_agent_pipeline',
        current_agent: '', current_step_index: 0, revision_round: 0, max_revision_rounds: 3,
        plan: {}, checkpoint: {}, token_usage: {}, error: null, created_at: '2026-08-08T00:00:00Z',
      },
      plan: [], artifacts: [], tool_calls: [],
      events: [{
        id: 10, sequence: 10, event_type: 'tool_call_completed', created_at: '2026-08-08T00:00:01Z',
        data: { run_id: 'run-ts-1', tool_name: 'task_sheet_initialize_draft' },
      }],
    };

    project.pipelineEvents = [
      { event_id: 1, type: 'tool_call_completed', data: { run_id: 'run-lesson-plan-old', tool_name: 'lesson_validate_alignment' } },
      { event_id: 2, type: 'tool_call_completed', data: { run_id: 'run-ts-1', tool_name: 'task_sheet_add_section' } },
    ];

    const timeline = pipeline.timeline;
    expect(timeline).toHaveLength(2);
    expect(timeline.map(item => item.data.tool_name)).toEqual(['task_sheet_add_section', 'task_sheet_initialize_draft']);
  });
});
