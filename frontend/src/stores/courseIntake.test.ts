import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { api } from '../api/client';
import { useCourseIntakeStore } from './courseIntake';

vi.mock('../api/client', () => ({
  api: { post: vi.fn() },
}));

describe('course intake failure recovery', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(api.post).mockReset();
  });

  it('unlocks the session after failure and starts a retry without adding a message', async () => {
    const store = useCourseIntakeStore();
    store.session = {
      id: 'session-1',
      status: 'processing',
      current_revision: 0,
      draft: {},
      field_sources: {},
      missing_fields: ['title'],
      assumptions: [],
      conflicts: [],
      active_turn_id: 'turn-1',
    };
    store.messages = [{ id: 'message-1', turn_id: 'turn-1', role: 'user', content: '课程需求' }];
    store.failTurn({
      turn_id: 'turn-1',
      code: 'upstream_empty_response',
      message: '模型服务返回了空响应。',
      retryable: true,
      session_status: 'collecting',
    });

    expect(store.session.status).toBe('collecting');
    expect(store.session.active_turn_id).toBeNull();

    vi.mocked(api.post).mockResolvedValue({ data: { turn_id: 'turn-2', status: 'queued' } });
    const turnId = await store.retryFailedTurn();

    expect(turnId).toBe('turn-2');
    expect(store.session.status).toBe('processing');
    expect(store.session.active_turn_id).toBe('turn-2');
    expect(store.lastFailure).toBeNull();
    expect(store.messages).toHaveLength(1);
  });
});
