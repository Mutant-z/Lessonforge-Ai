import { ref, onBeforeUnmount } from 'vue';
import { api } from '../api/client';
import { normalizeAgentEvent } from '../services/agentEventAdapter';
import { StreamBuffer } from '../services/streamBuffer';
import type { AgentStreamEvent } from '../types';

export type StreamConnectionStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'failed' | 'closed';

export function useAgentStream(runId: string) {
  const events = ref<AgentStreamEvent[]>([]);
  const connectionStatus = ref<StreamConnectionStatus>('idle');
  const error = ref<string>('');
  const retryCount = ref(0);
  const maxRetries = 5;

  let eventSource: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const buffer = new StreamBuffer((batch) => {
    events.value = [...events.value, ...batch];
  });

  async function connect() {
    if (!runId) return;
    connectionStatus.value = retryCount.value > 0 ? 'reconnecting' : 'connecting';
    error.value = '';

    try {
      const { data } = await api.post(`/generations/${runId}/stream-token`);
      const token = data.token;

      if (eventSource) {
        eventSource.close();
      }

      eventSource = new EventSource(`/api/v1/generations/${runId}/events?token=${encodeURIComponent(token)}`);

      eventSource.onopen = () => {
        connectionStatus.value = 'connected';
        retryCount.value = 0;
      };

      const handleEvent = (e: MessageEvent) => {
        try {
          const raw = JSON.parse(e.data);
          const normalized = normalizeAgentEvent({ type: e.type, ...raw }, runId);
          buffer.push(normalized);
        } catch (err) {
          console.warn('Failed to parse SSE payload:', err, e.data);
        }
      };

      const eventTypes = [
        'run_started',
        'node_started',
        'node_progress',
        'content_delta',
        'content_block_started',
        'content_block_delta',
        'content_block_completed',
        'node_completed',
        'node_failed',
        'quality_issue_found',
        'human_input_required',
        'artifact_saved',
        'run_cancelled',
        'run_completed'
      ];

      eventTypes.forEach(type => {
        eventSource?.addEventListener(type, handleEvent);
      });

      eventSource.addEventListener('stream_closed', (e: MessageEvent) => {
        connectionStatus.value = 'closed';
        eventSource?.close();
      });

      eventSource.onerror = (err) => {
        console.warn('SSE Error encountered', err);
        eventSource?.close();
        if (connectionStatus.value !== 'closed' && retryCount.value < maxRetries) {
          retryCount.value++;
          connectionStatus.value = 'reconnecting';
          retryTimer = setTimeout(() => {
            connect();
          }, Math.min(1000 * Math.pow(2, retryCount.value), 10000));
        } else {
          connectionStatus.value = 'failed';
          error.value = '与 Agent 服务端的网络连接中断，请重新尝试。';
        }
      };

    } catch (e: any) {
      connectionStatus.value = 'failed';
      error.value = e.message || '获取 SSE Stream Token 失败';
    }
  }

  function disconnect() {
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    buffer.clear();
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    connectionStatus.value = 'closed';
  }

  onBeforeUnmount(() => {
    disconnect();
  });

  return {
    events,
    connectionStatus,
    error,
    connect,
    disconnect
  };
}
