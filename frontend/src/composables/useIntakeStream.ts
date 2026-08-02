import { getCurrentInstance, onBeforeUnmount, ref } from 'vue';
import { api } from '../api/client';
import type { IntakeDraftUpdatedEvent, IntakeTurnFailure } from '../types';

type IntakeStreamHandlers = {
  onDraftUpdated: (event: IntakeDraftUpdatedEvent) => void;
  onCompleted: (turnId: string, content: string) => void;
  onTurnFailed: (failure: IntakeTurnFailure) => void;
};

export function useIntakeStream(handlers: IntakeStreamHandlers) {
  const connectionStatus = ref<'idle' | 'connecting' | 'connected' | 'failed' | 'closed'>('idle');
  const streamedText = ref('');
  const activityMessage = ref('');
  const turnFailure = ref<IntakeTurnFailure | null>(null);
  const connectionError = ref('');
  let source: EventSource | null = null;
  let currentTurnId = '';
  let lastEventId = 0;
  let retryCount = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let manuallyClosed = false;

  async function connect(turnId: string) {
    disconnect();
    manuallyClosed = false;
    currentTurnId = turnId;
    streamedText.value = '';
    activityMessage.value = '';
    turnFailure.value = null;
    connectionError.value = '';
    retryCount = 0;
    await openSource();
  }

  async function openSource() {
    connectionStatus.value = 'connecting';
    try {
      const { data } = await api.post(`/course-intakes/turns/${currentTurnId}/stream-token`);
      const query = new URLSearchParams({ token: data.token, after: String(lastEventId) });
      source = new EventSource(`/api/v1/course-intakes/turns/${currentTurnId}/events?${query}`);
      source.onopen = () => {
        connectionStatus.value = 'connected';
        connectionError.value = '';
        retryCount = 0;
      };
      const parse = <T>(event: MessageEvent): T => {
        if (event.lastEventId) lastEventId = Number(event.lastEventId);
        return JSON.parse(event.data) as T;
      };
      const protocolFailure = () => {
        manuallyClosed = true;
        source?.close();
        source = null;
        activityMessage.value = '';
        connectionStatus.value = 'failed';
        connectionError.value = '需求 Agent 返回了无法识别的流式数据，请刷新页面后重试。';
      };
      const listen = <T>(name: string, handler: (payload: T) => void) => {
        source?.addEventListener(name, (event) => {
          try {
            handler(parse<T>(event as MessageEvent));
          } catch {
            protocolFailure();
          }
        });
      };
      listen<{ message?: string }>('requirement_analyzing', (payload) => {
        activityMessage.value = payload.message || '正在分析课程需求';
      });
      listen<IntakeDraftUpdatedEvent>('draft_updated', (payload) => {
        handlers.onDraftUpdated(payload);
        activityMessage.value = '需求摘要已更新';
      });
      listen<{ delta?: string }>('assistant_delta', (payload) => {
        streamedText.value += payload.delta || '';
        activityMessage.value = '';
      });
      listen<{ content?: string }>('assistant_completed', (payload) => {
        handlers.onCompleted(currentTurnId, payload.content || streamedText.value);
        streamedText.value = '';
        activityMessage.value = '';
      });
      listen<IntakeTurnFailure>('turn_failed', (payload) => {
        const failure: IntakeTurnFailure = {
          turn_id: payload.turn_id || currentTurnId,
          code: payload.code || 'intake_internal_error',
          message: payload.message || '需求分析暂时失败，请重试或切换模型。',
          retryable: payload.retryable !== false,
          session_status: payload.session_status || 'collecting',
        };
        manuallyClosed = true;
        if (retryTimer) clearTimeout(retryTimer);
        retryTimer = null;
        source?.close();
        source = null;
        streamedText.value = '';
        activityMessage.value = '';
        turnFailure.value = failure;
        connectionStatus.value = 'closed';
        handlers.onTurnFailed(failure);
      });
      source.addEventListener('stream_closed', () => {
        connectionStatus.value = 'closed';
        manuallyClosed = true;
        source?.close();
      });
      source.onerror = () => {
        source?.close();
        if (!manuallyClosed && retryCount < 5) {
          retryCount += 1;
          retryTimer = setTimeout(openSource, Math.min(1000 * 2 ** retryCount, 10000));
        } else if (!manuallyClosed) {
          connectionStatus.value = 'failed';
          connectionError.value = '与需求 Agent 的连接中断，请刷新页面重试。';
        }
      };
    } catch {
      connectionStatus.value = 'failed';
      connectionError.value = '无法连接需求 Agent，请检查网络后重试。';
    }
  }

  function disconnect() {
    manuallyClosed = true;
    if (retryTimer) clearTimeout(retryTimer);
    retryTimer = null;
    source?.close();
    source = null;
    lastEventId = 0;
    if (connectionStatus.value !== 'idle') connectionStatus.value = 'closed';
  }

  if (getCurrentInstance()) onBeforeUnmount(disconnect);
  return { connectionStatus, streamedText, activityMessage, turnFailure, connectionError, connect, disconnect };
}
