# PPT Agent LangGraph

统一状态为 `PPTAgentState`，包含 run/course/artifact、intent、课程上下文、模板、计划、slides、assets、skills、tool results、QA、repair、当前 Agent 和状态。

Graph 每次只执行一个 Agent，完成后回到 Orchestrator。Orchestrator可以根据 intent、选中页面、工具结果、显式 handoff、QA 和新指令重排后续节点。SQLite Checkpointer 使用 `run_id` 作为 `thread_id`，领域数据不依赖 Graph Snapshot。

运行限制：递归上限 100、Agent 工具轮次 8、全局步骤 40、Repair 默认 3。Pause/Cancel 在 Agent 与 Tool 边界检查。

