"""多 Agent 流水线引擎包。

核心组件：
- schemas：AgentDecision / ToolCall / ToolResult 等结构化协议
- context：按 Agent 职责加载上下文的 ContextState
- artifacts：流水线 Artifact 图管理（版本化 + 依赖边）
- events：事件发射（generation_events SSE 传输 + pipeline_events 明细）
- registry：工具注册表 + 执行器
- loop：Agent Loop 执行器（多次 LLM 调用 + 工具结果回传 + checkpoint）
- definitions：Agent 定义注册表（职责 / 产物 / 工具）
"""
