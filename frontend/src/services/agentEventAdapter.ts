import type { AgentStreamEvent, AgentEventType } from '../types';

export function normalizeAgentEvent(rawEvent: any, defaultRunId: string): AgentStreamEvent {
  const eventType: AgentEventType = rawEvent.type || rawEvent.event_type || 'node_progress';
  
  return {
    id: rawEvent.id || rawEvent.sequence || Date.now(),
    runId: rawEvent.runId || rawEvent.run_id || defaultRunId,
    nodeId: rawEvent.node || rawEvent.nodeId || rawEvent.node_name,
    agentType: rawEvent.agentType || rawEvent.agent_type,
    type: eventType,
    sequence: rawEvent.sequence || rawEvent.id,
    timestamp: rawEvent.timestamp || new Date().toISOString(),
    progress: rawEvent.progress !== undefined ? rawEvent.progress : undefined,
    message: rawEvent.message || rawEvent.description || rawEvent.text,
    artifactType: rawEvent.artifactType || rawEvent.artifact_type,
    blockId: rawEvent.blockId || rawEvent.block_id,
    blockType: rawEvent.blockType || rawEvent.block_type,
    delta: rawEvent.delta || rawEvent.content,
    payload: rawEvent.payload || rawEvent
  };
}
