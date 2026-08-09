import { describe, expect, it } from 'vitest';
import { adaptPPTAgentEvent } from './pptAgentEventAdapter';

describe('pptAgentEventAdapter', () => {
  it('normalizes legacy events into the dotted protocol', () => {
    const event = adaptPPTAgentEvent('artifact_patch', {
      run_id: 'run-1', artifact_id: 'artifact-1', slide_id: 'S03', summary: '页面已更新',
    }, 42);
    expect(event.type).toBe('artifact.updated');
    expect(event.sequence).toBe(42);
    expect(event.slide).toEqual({ slide_id: 'S03', page: undefined });
  });

  it('preserves canonical skill and handoff events', () => {
    const event = adaptPPTAgentEvent('agent.handoff', {
      run_id: 'run-2', agent: { id: 'planner' }, payload: { to: 'layout' },
    }, 43);
    expect(event.type).toBe('agent.handoff');
    expect(event.payload).toEqual({ to: 'layout' });
  });
});
