export interface CanonicalPPTAgentEvent {
  eventId: number;
  sequence: number;
  runId: string;
  type: string;
  message: string;
  agent: Record<string, unknown>;
  progress: Record<string, unknown>;
  artifact: Record<string, unknown>;
  slide: Record<string, unknown>;
  payload: Record<string, unknown>;
  timestamp?: string;
}

const LEGACY_TYPES: Record<string, string> = {
  pipeline_started: 'run.started', pipeline_completed: 'run.completed', pipeline_failed: 'run.failed',
  agent_started: 'agent.started', agent_status_delta: 'agent.progress', agent_completed: 'agent.completed',
  tool_call_started: 'tool.started', tool_call_delta: 'tool.progress', tool_call_completed: 'tool.completed',
  artifact_started: 'artifact.created', artifact_patch: 'artifact.updated', artifact_created: 'artifact.created',
  qa_issue_found: 'qa.issue', qa_completed: 'qa.completed', revision_started: 'repair.started',
  revision_completed: 'repair.completed', task_paused: 'run.paused', task_resumed: 'run.resumed',
};

export function adaptPPTAgentEvent(type: string, data: Record<string, any>, eventId: number): CanonicalPPTAgentEvent {
  const canonicalType = LEGACY_TYPES[type] || type;
  const agentKey = String(data.agent_key || data.agent_type || '');
  return {
    eventId, sequence: eventId, runId: String(data.run_id || ''), type: canonicalType,
    message: String(data.message || data.summary || data.text || ''),
    agent: data.agent || (agentKey ? { id: agentKey, name: data.agent_label || agentKey } : {}),
    progress: typeof data.progress === 'object' ? data.progress : (data.progress == null ? {} : { current: data.progress }),
    artifact: data.artifact || (data.artifact_id ? { artifact_id: data.artifact_id, type: data.artifact_type } : {}),
    slide: data.slide || (data.slide_id ? { slide_id: data.slide_id, page: data.slide_index } : {}),
    payload: data.payload || data,
    timestamp: data.timestamp || data.created_at,
  };
}
