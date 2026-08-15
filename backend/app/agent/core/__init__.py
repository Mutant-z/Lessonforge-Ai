"""通用 Agent Core：领域无关的 Agent 循环、状态基类与错误类型。

设计目标：教学设计 Runtime 基于本包构建，PPT Agent 代码零改动。
- 复用 app.agent 中已领域无关的设施：schemas（AgentDecision/ToolCall/AgentSpec/PipelinePlan）、
  registry（Tool 注册/校验/超时/重试）、artifacts（PipelineArtifactManager）、
  context（ContextState）、events（PipelineEventEmitter）、event_protocol。
- core/loop.run_agent_loop 是通用顺序执行器：工具轮次上限、总步数/token 上限、
  暂停边界、handoff 归一、artifact 持久化、checkpoint 落库——领域差异通过
  call_agent / persist_artifact / agent_registry 参数注入。
"""
