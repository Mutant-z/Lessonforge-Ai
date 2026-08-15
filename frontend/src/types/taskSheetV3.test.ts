import { describe, expect, it } from 'vitest';
import { isTaskSheetV3, orderTaskSheetSections } from './artifact';
import type { TaskSheetContentV3 } from './artifact';

function sampleV3(): TaskSheetContentV3 {
  return {
    schema_version: '3.0',
    course_info: { course_title: '浮力', subject: '物理', grade_level: '八年级', audience: '初二', duration_minutes: 10 },
    objective_catalog: [
      { id: 'OBJ-01', statement: '解释浮力', success_criterion: '说明依据' },
      { id: 'OBJ-02', statement: '应用原理', success_criterion: '结果正确' },
    ],
    sections: [
      { id: 'SEC-A', parent_id: '', order: 0, title: '导入', purpose: '', objective_ids: ['OBJ-01'], blocks: [{ kind: 'text', id: 'B-1', text: '观察' }] },
      { id: 'SEC-B', parent_id: '', order: 1, title: '任务', purpose: '', objective_ids: ['OBJ-01'], blocks: [
        { kind: 'learning_task', id: 'T-1', title: '任务一', action: '观察', object: '情境', steps: ['a'], student_output: 'o', completion_criterion: 'c', estimated_minutes: 2, collaboration_mode: 'individual', objective_ids: ['OBJ-01'], knowledge_point_ids: [], stage_id: null, scaffolds: [], record_table: null },
      ] },
      { id: 'SEC-C', parent_id: 'SEC-B', order: 0, title: '子任务', purpose: '', objective_ids: [], blocks: [] },
    ],
  };
}

describe('isTaskSheetV3', () => {
  it('recognizes V3 schema_version', () => {
    expect(isTaskSheetV3(sampleV3())).toBe(true);
  });
  it('rejects V2 and non-objects', () => {
    expect(isTaskSheetV3({ schema_version: '2.0' })).toBe(false);
    expect(isTaskSheetV3(null)).toBe(false);
    expect(isTaskSheetV3('x')).toBe(false);
  });
});

describe('orderTaskSheetSections', () => {
  it('sorts by parent_id then order and annotates depth', () => {
    const ordered = orderTaskSheetSections(sampleV3().sections);
    expect(ordered.map(s => s.id)).toEqual(['SEC-A', 'SEC-B', 'SEC-C']);
    expect(ordered.find(s => s.id === 'SEC-C')?.depth).toBe(1);
    expect(ordered.find(s => s.id === 'SEC-A')?.depth).toBe(0);
  });
});
