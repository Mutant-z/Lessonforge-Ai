import type { AgentStreamEvent } from '../types';

export class StreamBuffer {
  private queue: AgentStreamEvent[] = [];
  private seenIds = new Set<string | number>();
  private animFrameId: number | null = null;
  private onBatchFlush: (events: AgentStreamEvent[]) => void;

  constructor(onBatchFlush: (events: AgentStreamEvent[]) => void) {
    this.onBatchFlush = onBatchFlush;
  }

  public push(event: AgentStreamEvent) {
    if (event.id && this.seenIds.has(event.id)) {
      return;
    }
    if (event.id) {
      this.seenIds.add(event.id);
    }
    this.queue.push(event);

    if (!this.animFrameId) {
      this.animFrameId = requestAnimationFrame(() => this.flush());
    }
  }

  private flush() {
    this.animFrameId = null;
    if (this.queue.length === 0) return;
    const batch = [...this.queue];
    this.queue = [];
    this.onBatchFlush(batch);
  }

  public clear() {
    this.queue = [];
    this.seenIds.clear();
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
  }
}
