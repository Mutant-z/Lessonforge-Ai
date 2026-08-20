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

  it('applies monotonic video-script patches to the live candidate', () => {
    const pipeline = usePipelineStore();
    const project = useProjectStore();
    project.currentTask = {
      id: 'task-video', course_id: 'course-1', task_type: 'video_script',
      current_artifact: { content_json: {} },
    } as any;
    const videoDetail = detail('running');
    videoDetail.run!.generation_run_id = 'run-video';
    videoDetail.run!.pipeline_type = 'video_script_agent_pipeline';
    pipeline.detail = videoDetail;
    const baseline = {
      schema_version: '4.0', outline: { sections: [{ id: 'SEC-01', sequence: 1, title: '原章节' }] },
      scenes: [{ id: 'VS-01', section_id: 'SEC-01', sequence: 1, title: '原分镜', spoken_text: '原口播' }],
    };
    pipeline.applyStreamEvent('artifact_patch', {
      run_id: 'run-video', artifact_type: 'video_script', snapshot: true,
      base_revision: 0, draft_revision: 0, patch: [{ op: 'replace', path: '', value: baseline }],
    });
    pipeline.applyStreamEvent('artifact_patch', {
      run_id: 'run-video', artifact_type: 'video_script', base_revision: 0, draft_revision: 1,
      affected_scene_ids: ['VS-01'],
      patch: [{ op: 'replace', path: '/scenes/VS-01/spoken_text', value: '新口播' }],
    });

    expect(pipeline.draftArtifact?.scenes[0].spoken_text).toBe('新口播');
    expect(pipeline.draftRevision).toBe(1);
    expect(pipeline.lastAffectedSceneIds).toEqual(['VS-01']);
  });

  it('ignores duplicate video patches and requests a snapshot on a revision gap', () => {
    const pipeline = usePipelineStore();
    const project = useProjectStore();
    project.currentTask = { id: 'task-video', course_id: 'course-1', task_type: 'video_script' } as any;
    const videoDetail = detail('running');
    videoDetail.run!.generation_run_id = 'run-video';
    videoDetail.run!.pipeline_type = 'video_script_agent_pipeline';
    pipeline.detail = videoDetail;
    pipeline.applyStreamEvent('artifact_patch', {
      run_id: 'run-video', artifact_type: 'video_script', snapshot: true,
      base_revision: 0, draft_revision: 0,
      patch: [{ op: 'replace', path: '', value: { outline: { sections: [] }, scenes: [] } }],
    });
    pipeline.applyStreamEvent('artifact_patch', {
      run_id: 'run-video', artifact_type: 'video_script', base_revision: 1, draft_revision: 2,
      patch: [{ op: 'add', path: '/outline/sections/SEC-02', value: { id: 'SEC-02', sequence: 2, title: '跳号章节' } }],
    });

    expect(pipeline.draftNeedsRefresh).toBe(true);
    expect(pipeline.draftArtifact?.outline.sections).toHaveLength(0);
    expect(pipeline.draftRevision).toBe(0);
  });
});
