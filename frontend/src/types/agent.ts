export type AgentNodeType = 
  | 'supervisor'
  | 'blueprint_agent'
  | 'lesson_plan_agent'
  | 'ppt_agent'
  | 'task_sheet_agent'
  | 'exercise_agent'
  | 'video_script_agent'
  | 'verbatim_agent'
  | 'quality_assurance_agent'
  | 'final_review';

export type AgentNodeStatus =
  | 'idle'
  | 'queued'
  | 'connecting'
  | 'preparing'
  | 'retrieving'
  | 'reasoning'
  | 'generating'
  | 'validating'
  | 'saving'
  | 'completed'
  | 'paused'
  | 'waiting_human'
  | 'retrying'
  | 'failed'
  | 'cancelled';

export type AgentEventType =
  | 'run_started'
  | 'connection_ready'
  | 'node_queued'
  | 'node_started'
  | 'node_progress'
  | 'content_delta'
  | 'content_block_started'
  | 'content_block_delta'
  | 'content_block_completed'
  | 'node_completed'
  | 'node_failed'
  | 'quality_issue_found'
  | 'rework_started'
  | 'human_input_required'
  | 'artifact_saved'
  | 'run_paused'
  | 'run_resumed'
  | 'run_completed'
  | 'run_cancelled'
  | 'heartbeat'
  | 'stream_closed';

export interface AgentStreamEvent {
  id?: number | string;
  runId: string;
  nodeId?: AgentNodeType | string;
  agentType?: string;
  type: AgentEventType;
  sequence?: number;
  timestamp: string;
  progress?: number;
  message?: string;
  artifactType?: string;
  blockId?: string;
  blockType?: string;
  delta?: string;
  payload?: any;
}

export const NODE_LABEL_MAP: Record<string, string> = {
  supervisor: '核心调度 Agent',
  blueprint_agent: '课程蓝图 Agent',
  lesson_plan_agent: '教学设计 Agent',
  ppt_agent: 'PPT 课件 Agent',
  task_sheet_agent: '学习任务单 Agent',
  exercise_agent: '课后练习 Agent',
  video_script_agent: '微课视频脚本 Agent',
  verbatim_agent: '教师逐字稿 Agent',
  quality_assurance_agent: '质量检查 Agent',
  final_review: '终审节点'
};

export const NODE_DUTY_MAP: Record<string, string> = {
  supervisor: '负责全流程多 Agent 任务编排与协调',
  blueprint_agent: '分析教学大纲与要求，构建统一蓝图',
  lesson_plan_agent: '生成学情分析、教学目标与分时教学过程',
  ppt_agent: '规划 16:9 幻灯片结构、视觉重点与演讲提示',
  task_sheet_agent: '设计项目化/问题导向的探究学习任务单',
  exercise_agent: '编排梯度课后练习、参考答案与解析',
  video_script_agent: '撰写含分镜画面、旁白与字幕的微课脚本',
  verbatim_agent: '生成逐字口述稿，支持提词器与全屏朗读模式',
  quality_assurance_agent: '核查 Schema 规范、引用准确度与目标对齐度',
  final_review: '等待教师人工确认与打包导出'
};
