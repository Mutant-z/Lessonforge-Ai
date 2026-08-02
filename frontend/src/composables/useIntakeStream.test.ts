import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useIntakeStream } from './useIntakeStream';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: { post: vi.fn() },
}));

type Listener = (event: MessageEvent) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];
  listeners = new Map<string, Listener[]>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(name: string, listener: EventListenerOrEventListenerObject) {
    const handlers = this.listeners.get(name) || [];
    handlers.push(listener as Listener);
    this.listeners.set(name, handlers);
  }

  close() {
    this.closed = true;
  }

  emit(name: string, payload: unknown) {
    this.emitRaw(name, JSON.stringify(payload));
  }

  emitRaw(name: string, data: string) {
    const event = { data, lastEventId: '' } as MessageEvent;
    for (const listener of this.listeners.get(name) || []) listener(event);
  }
}

describe('useIntakeStream', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.post).mockReset().mockResolvedValue({ data: { token: 'token' } });
    MockEventSource.instances = [];
    vi.stubGlobal('EventSource', MockEventSource);
  });

  it('stops reconnecting and exposes a task failure on turn_failed', async () => {
    const onTurnFailed = vi.fn();
    const stream = useIntakeStream({
      onDraftUpdated: vi.fn(),
      onCompleted: vi.fn(),
      onTurnFailed,
    });
    await stream.connect('turn-1');
    const source = MockEventSource.instances[0];

    source.emit('turn_failed', {
      turn_id: 'turn-1',
      code: 'upstream_empty_response',
      message: '模型服务返回了空响应。',
      retryable: true,
      session_status: 'collecting',
    });
    source.onerror?.();
    await vi.runAllTimersAsync();

    expect(source.closed).toBe(true);
    expect(stream.connectionError.value).toBe('');
    expect(stream.turnFailure.value?.code).toBe('upstream_empty_response');
    expect(onTurnFailed).toHaveBeenCalledOnce();
    expect(api.post).toHaveBeenCalledOnce();
  });

  it('turns malformed SSE data into a safe protocol error', async () => {
    const stream = useIntakeStream({
      onDraftUpdated: vi.fn(),
      onCompleted: vi.fn(),
      onTurnFailed: vi.fn(),
    });
    await stream.connect('turn-2');

    MockEventSource.instances[0].emitRaw('draft_updated', 'not-json');

    expect(stream.connectionStatus.value).toBe('failed');
    expect(stream.connectionError.value).toContain('无法识别');
  });

  it('reconnects only for transport failures', async () => {
    const stream = useIntakeStream({
      onDraftUpdated: vi.fn(),
      onCompleted: vi.fn(),
      onTurnFailed: vi.fn(),
    });
    await stream.connect('turn-3');

    MockEventSource.instances[0].onerror?.();
    await vi.advanceTimersByTimeAsync(2100);

    expect(api.post).toHaveBeenCalledTimes(2);
    expect(MockEventSource.instances).toHaveLength(2);
  });
});
