# PPT Agent Architecture

当前入口为 CourseTask API → `run_ppt_pipeline` → PipelineRun。新内核为：

```text
load_context → orchestrator → skill discovery/load → agent executor
             ↑                                  ↓
             └──── observe artifact/tool result ┘
→ builder → render → visual/content QA → repair/human → finalize
```

`PPTAgentRuntime` 管理 Graph、预算、Checkpoint 和 Agent Handoff；业务数据由 Artifact/Revision 表管理；事件由 `PipelineEventEmitter` 持久化并通过 SSE 传输。模板是 `TemplateDesignProfile`，不是内容占位容器。

