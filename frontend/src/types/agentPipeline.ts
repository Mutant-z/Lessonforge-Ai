/** 多 Agent 流水线（PPT）类型：运行 / 产物图 / 工具调用 / 事件。 */

export type PipelineStatus =
  | 'queued' | 'running' | 'pausing' | 'paused' | 'completed' | 'failed' | 'cancelled';

export interface PipelineRunInfo {
  id: string;
  generation_run_id: string;
  status: PipelineStatus;
  pipeline_type: string;
  current_agent: string;
  current_step_index: number;
  revision_round: number;
  max_revision_rounds: number;
  plan: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  token_usage: Record<string, unknown>;
  error: { code?: string; message?: string } | null;
  created_at: string;
}

export interface PipelineArtifact {
  id: string;
  artifact_type: string;
  name: string;
  version: number;
  status: 'draft' | 'validated' | 'approved' | 'superseded';
  data: Record<string, unknown>;
  file_path: string;
  mime_type: string;
  producer_agent: string;
  producer_tool: string;
  dependencies: string[];
  created_at: string;
}

export interface PipelineToolCall {
  id: string;
  model_call_id?: string;
  agent_key: string;
  tool_name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  status: 'started' | 'completed' | 'failed';
  duration_ms: number;
  error: { message?: string } | null;
  created_at: string;
}

export interface PipelineEventItem {
  id: number;
  event_type: string;
  sequence: number;
  data: Record<string, unknown>;
  created_at: string;
}

export interface PipelineDetail {
  run: PipelineRunInfo | null;
  plan: unknown[];
  artifacts: PipelineArtifact[];
  tool_calls: PipelineToolCall[];
  events: PipelineEventItem[];
}

/** 页面级 QA 问题 */
export interface QaIssue {
  severity: 'critical' | 'major' | 'minor';
  slide_id: string;
  rule_id: string;
  message: string;
  target_agent: string;
}

/** 工具调用展示卡片 */
export interface ToolCallView {
  id: string;
  agent_key: string;
  tool_name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  ok: boolean;
  error: string | null;
  duration_ms: number;
  created_at: string;
  expanded?: boolean;
}

export const AGENT_PIPELINE_LABELS: Record<string, string> = {
  narrative: '演示叙事 Agent',
  template_analysis: '模板分析 Agent',
  slide_content: '页面内容 Agent',
  layout: '页面布局 Agent',
  visual_plan: '视觉规划 Agent',
  media: '图片与图表 Agent',
  ppt_editor: 'PPT 编辑 Agent',
  visual_qa: '视觉 QA Agent',
  revision: '修订 Agent',
};

export const PIPELINE_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  pausing: '暂停中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

export const ARTIFACT_TYPE_LABELS: Record<string, string> = {
  pipeline_plan: '执行计划',
  source_snapshot: '上游内容快照',
  presentation_narrative: '演示叙事',
  design_system: '设计系统',
  slide_content: '页面内容',
  slide_layout: '页面布局',
  visual_plan: '视觉规划',
  visual_asset: '视觉素材',
  presentation_file: 'PPT 文件',
  visual_qa: '视觉 QA',
  revision_note: '修订记录',
};
