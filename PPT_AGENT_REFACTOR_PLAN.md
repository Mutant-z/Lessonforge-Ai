# PPT Agent Agentic Runtime 重构计划

本次重构保留 FastAPI、CourseTask、LLM Provider、Artifact、SSE、PresentationBuilder、模板文件和 Vue Workspace，以 LangGraph `PPTAgentRuntime` 替换生产路径中的固定 Agent 清单。

实施顺序：Runtime → Skill/Tool → Multi-Agent → Template/Visual → Slide Artifact → Render/QA → Event/Control → Frontend → 兼容清理。每阶段必须通过相关单测、后端全量测试、前端测试、TypeScript 检查和构建。

兼容原则：旧课程任务 API 和 snake_case 事件在迁移期继续可用；新接口使用 `/ppt-agent/*` 与 dotted event；已有运行由旧数据恢复，新运行写入版本化 PPT/Slide 领域表。

