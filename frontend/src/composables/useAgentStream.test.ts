import { describe, expect, it } from 'vitest';
import { buildAgentTurns, buildStreamNodes } from './useAgentStream';
import type { PipelineTimelineItem } from '../stores/pipeline';
import type { ProjectAgentMessage } from '../types';

function item(id: number, type: string, data: Record<string, any> = {}): PipelineTimelineItem {
  return { id, type, data };
}

const fullRunItems: PipelineTimelineItem[] = [
  item(1, 'pipeline_started', { run_id: 'run-1' }),
  item(2, 'agent_started', { run_id: 'run-1', agent_key: 'narrative', agent_label: '演示叙事' }),
  item(3, 'agent_status_delta', { run_id: 'run-1', agent_key: 'narrative', text: '正在分析章节。' }),
  item(4, 'tool_call_started', { run_id: 'run-1', agent_key: 'narrative', tool_call_id: 't1', tool_name: 'get_blueprint', input_json: { blueprint_id: 'b1' } }),
  item(5, 'tool_call_completed', { run_id: 'run-1', agent_key: 'narrative', tool_call_id: 't1', tool_name: 'get_blueprint', ok: true, duration_ms: 120, output_json: { ok: true } }),
  item(6, 'artifact_created', { run_id: 'run-1', producer_agent: 'narrative', artifact_type: 'presentation_narrative' }),
  item(7, 'qa_completed', { run_id: 'run-1', score: 92, round: 1 }),
  item(8, 'agent_completed', { run_id: 'run-1', agent_key: 'narrative', summary: '叙事完成' }),
  item(9, 'pipeline_completed', { run_id: 'run-1' }),
];

describe('buildStreamNodes', () => {
  it('flattens a full run into session/thought/tool/event nodes without reply', () => {
    const thoughts = { 'run-1:narrative': '用户希望设计一节勾股定理课…' };
    const nodes = buildStreamNodes(fullRunItems, thoughts, []);

    expect(nodes[0]).toMatchObject({ kind: 'session', runId: 'run-1' });
    expect(nodes[1]).toMatchObject({ kind: 'thought', thoughtKey: 'run-1:narrative', active: false });
    expect(nodes[2]).toMatchObject({ kind: 'tool', toolName: 'get_blueprint', running: false, ok: true, durationMs: 120 });
    expect(nodes[3]).toMatchObject({ kind: 'event', type: 'artifact_created' });
    expect(nodes[4]).toMatchObject({ kind: 'event', type: 'qa_completed' });
    expect(nodes.some(n => n.kind === 'reply')).toBe(false);
  });

  it('keeps a thought active until agent_completed and pairs tool calls', () => {
    const items = [
      item(1, 'agent_started', { run_id: 'run-1', agent_key: 'ppt_editor' }),
      item(2, 'tool_call_started', { run_id: 'run-1', agent_key: 'ppt_editor', tool_call_id: 't1', tool_name: 'write_slide_batch', input_json: {} }),
    ];
    const nodes = buildStreamNodes(items, {}, []);
    const thought = nodes.find(n => n.kind === 'thought')!;
    const tool = nodes.find(n => n.kind === 'tool')!;
    expect(thought).toMatchObject({ kind: 'thought', active: true });
    expect(tool).toMatchObject({ kind: 'tool', running: true, ok: true });
  });

  it('keeps streamed status text inside the thought node when the external store is late', () => {
    const nodes = buildStreamNodes([
      item(1, 'agent_started', { run_id: 'run-live', agent_key: 'slide_content' }),
      item(2, 'agent_status_delta', { run_id: 'run-live', agent_key: 'slide_content', text: '正在读取完整的 PPT' }),
      item(3, 'agent_status_delta', { run_id: 'run-live', agent_key: 'slide_content', text: '，准备润色首页。' }),
    ], {}, []);

    expect(nodes.find(node => node.kind === 'thought')).toMatchObject({
      kind: 'thought',
      content: '正在读取完整的 PPT，准备润色首页。',
      active: true,
    });
  });

  it('shows pause and resume events instead of making a stopped run look inert', () => {
    const nodes = buildStreamNodes([
      item(1, 'agent_status_delta', { run_id: 'run-paused', agent_key: 'orchestrator', text: '正在理解修改范围。' }),
      item(2, 'task_paused', { run_id: 'run-paused', message: '用户暂停' }),
      item(3, 'task_resumed', { run_id: 'run-paused' }),
    ], {}, []);

    expect(nodes.filter(node => node.kind === 'event')).toEqual([
      expect.objectContaining({ kind: 'event', type: 'task_paused' }),
      expect.objectContaining({ kind: 'event', type: 'task_resumed' }),
    ]);
  });

  it('keeps V2 layout candidate and polish result events for result and confirmation UI', () => {
    const nodes = buildStreamNodes([
      item(1, 'layout.compile.result', {
        run_id: 'run-v2',
        payload: { slide_id: 'slide_03', requires_candidate_confirmation: true },
      }),
      item(2, 'polish.result', {
        run_id: 'run-v2',
        payload: { result_status: 'partial', page_results: [{ slide_id: 'slide_03' }] },
      }),
    ], {}, []);

    expect(nodes.filter(node => node.kind === 'event').map(node => node.type)).toEqual([
      'layout.compile.result',
      'polish.result',
    ]);
  });

  it('puts user instruction before the session head and reply at the tail for message runs', () => {
    const nodes = buildStreamNodes(fullRunItems, { 'run-1:narrative': '…' }, [
      { id: 'u1', role: 'user', content: '请把第3页改成对比版式', run_id: 'run-1', status: 'completed' },
      { id: 'r1', role: 'assistant', content: '已根据你的要求创建PPT V2…', run_id: 'run-1', status: 'completed' },
    ]);

    expect(nodes[0]).toMatchObject({ kind: 'user', content: '请把第3页改成对比版式' });
    expect(nodes[1]).toMatchObject({ kind: 'session', runId: 'run-1' });
    expect(nodes[nodes.length - 1]).toMatchObject({ kind: 'reply', content: '已根据你的要求创建PPT V2…', streaming: false });
  });

  it('renders the final reply for a full pipeline as its own response section', () => {
    const nodes = buildStreamNodes(fullRunItems, {}, [
      { id: 'a1', role: 'assistant', content: 'PPT 已生成完成，共 15 页。', run_id: 'run-1', status: 'completed' },
    ]);
    expect(nodes[nodes.length - 1]).toMatchObject({
      kind: 'reply', content: 'PPT 已生成完成，共 15 页。', streaming: false,
    });
  });

  it('falls back to a thought node when agent_started is missing but status exists', () => {
    const items = [
      item(1, 'agent_status_delta', { run_id: 'run-1', agent_key: 'narrative', text: '正在分析章节。' }),
    ];
    const nodes = buildStreamNodes(items, {}, []);
    const thoughts = nodes.filter(n => n.kind === 'thought');
    expect(thoughts).toHaveLength(1);
    expect(thoughts[0]).toMatchObject({ kind: 'thought', thoughtKey: 'run-1:narrative', active: true });
  });

  it('separates multiple runs with their own session heads', () => {
    const items = [
      item(1, 'agent_started', { run_id: 'run-1', agent_key: 'narrative' }),
      item(2, 'agent_completed', { run_id: 'run-1', agent_key: 'narrative', summary: 's' }),
      item(3, 'agent_started', { run_id: 'run-2', agent_key: 'ppt_editor' }),
      item(4, 'agent_completed', { run_id: 'run-2', agent_key: 'ppt_editor', summary: 's' }),
    ];
    const nodes = buildStreamNodes(items, {}, []);
    const sessions = nodes.filter(n => n.kind === 'session');
    expect(sessions.map(s => s.runId)).toEqual(['run-1', 'run-2']);
  });

  it('keeps each instruction, execution trace and reply inside its own turn', () => {
    const items = [
      item(1, 'agent_started', { run_id: 'run-1', agent_key: 'layout' }),
      item(2, 'agent_completed', { run_id: 'run-1', agent_key: 'layout' }),
      item(3, 'agent_started', { run_id: 'run-2', agent_key: 'visual_qa' }),
      item(4, 'agent_completed', { run_id: 'run-2', agent_key: 'visual_qa' }),
    ];
    const turns = buildAgentTurns(items, {}, [
      { id: 'u1', role: 'user', content: '修改第一页', run_id: 'run-1', status: 'completed' },
      { id: 'a1', role: 'assistant', content: '第一页已修改', run_id: 'run-1', status: 'completed' },
      { id: 'u2', role: 'user', content: '再检查第二页', run_id: 'run-2', status: 'completed' },
      { id: 'a2', role: 'assistant', content: '第二页检查完成', run_id: 'run-2', status: 'completed' },
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[0]).toMatchObject({ runId: 'run-1' });
    expect(turns[0].users.map(node => node.content)).toEqual(['修改第一页']);
    expect(turns[0].replies.map(node => node.content)).toEqual(['第一页已修改']);
    expect(turns[1].users.map(node => node.content)).toEqual(['再检查第二页']);
    expect(turns[1].replies.map(node => node.content)).toEqual(['第二页检查完成']);
  });

  it('pairs legacy messages without run ids into chronological turns', () => {
    const turns = buildAgentTurns([], {}, [
      { id: 'u1', role: 'user', content: '第一轮', status: 'completed' },
      { id: 'a1', role: 'assistant', content: '第一轮回复', status: 'completed' },
      { id: 'u2', role: 'user', content: '第二轮', status: 'completed' },
      { id: 'a2', role: 'assistant', content: '第二轮回复', status: 'completed' },
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[0].replies[0].content).toBe('第一轮回复');
    expect(turns[1].replies[0].content).toBe('第二轮回复');
  });

  it('keeps the latest run after historical messages when detail events only contain that run', () => {
    const turns = buildAgentTurns([
      {
        id: 90,
        type: 'agent_started',
        data: { run_id: 'run-new', agent_key: 'layout' },
        created_at: '2026-08-08T11:57:57Z',
      },
    ], {}, [
      {
        id: 'u-old', role: 'user', content: '优化 PPT 页面排版视觉', run_id: 'run-old',
        status: 'completed', created_at: '2026-08-06T04:08:31Z',
      },
      {
        id: 'a-old', role: 'assistant', content: '旧版优化已完成', run_id: 'run-old',
        status: 'completed', created_at: '2026-08-06T04:09:00Z',
      },
      {
        id: 'u-new', role: 'user', content: '润色一下首页', run_id: 'run-new',
        status: 'completed', created_at: '2026-08-08T11:57:56Z',
      },
    ]);

    expect(turns.map(turn => turn.runId)).toEqual(['run-old', 'run-new']);
    expect(turns.at(-1)?.users.at(-1)?.content).toBe('润色一下首页');
  });

  it('places a new optimistic instruction without a server timestamp after historical turns', () => {
    const turns = buildAgentTurns([], {}, [
      {
        id: 'u-old', role: 'user', content: '旧指令', run_id: 'run-old',
        status: 'completed', created_at: '2026-08-06T04:08:31Z',
      },
      { id: 'local-new', role: 'user', content: '刚发送的指令', run_id: 'run-new', status: 'pending' },
    ]);

    expect(turns.at(-1)?.users.at(-1)?.content).toBe('刚发送的指令');
  });

  it('preserves failed delivery status so an optimistic bubble is not shown as successful', () => {
    const nodes = buildStreamNodes([], {}, [
      { id: 'local-failed', role: 'user', content: '继续润色首页', status: 'failed' },
    ]);

    expect(nodes[0]).toMatchObject({ kind: 'user', content: '继续润色首页', status: 'failed' });
  });

  it('does not show a historical server processing status as a delivery spinner', () => {
    const nodes = buildStreamNodes([], {}, [
      { id: 'server-message', role: 'user', content: '润色首页', status: 'pending', run_id: 'run-complete' },
    ]);

    expect(nodes[0]).toMatchObject({ kind: 'user', content: '润色首页' });
    expect(nodes[0]).not.toHaveProperty('status', 'pending');
  });

  it('strips the [针对第 N 页] scope prefix from the teacher bubble', () => {
    const nodes = buildStreamNodes([], {}, [
      { id: 'u-scoped', role: 'user', content: '[针对第 4 页] 请调整本页版式', run_id: 'run-1', status: 'completed' },
    ]);

    expect(nodes[0]).toMatchObject({ kind: 'user', content: '请调整本页版式' });
  });

  it('strips both [目标页面:...] and [针对第 N 页] prefixes', () => {
    const nodes = buildStreamNodes([], {}, [
      { id: 'u-target', role: 'user', content: '[目标页面: S02,S03] 改标题', status: 'completed' },
      { id: 'u-multi', role: 'user', content: '[针对第 1、3 页] 增加案例', status: 'completed' },
    ]);

    expect(nodes[0]).toMatchObject({ kind: 'user', content: '改标题' });
    expect(nodes[1]).toMatchObject({ kind: 'user', content: '增加案例' });
  });

  it('keeps teacher text intact when no scope prefix is present', () => {
    const nodes = buildStreamNodes([], {}, [
      { id: 'u-plain', role: 'user', content: '润色整份课件', status: 'completed' },
    ]);

    expect(nodes[0]).toMatchObject({ kind: 'user', content: '润色整份课件' });
  });
});
