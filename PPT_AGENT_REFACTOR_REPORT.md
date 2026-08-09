# PPT Agent Agentic Runtime 重构报告

## 完成内容

- 生产路径已接入持久化 LangGraph `PPTAgentRuntime`；真实模型负责首次动态规划和 Agent 边界重规划，Mock 保持确定性。
- 显式 Handoff、Skill Discovery/Lazy Loading、Tool 输出 Schema/超时/重试/取消检查、SQLite Checkpoint 与运行中 Instruction Queue 已接入。
- 新增 8 个 PPT 设计 Skill、真实 PPTX Template Profile 分析与 hash 缓存。
- 新增 PPT/Slide Revision、Instruction、Human Request、Template Profile 表及 Alembic `0008`。
- 新增 `/ppt-agent/*` run-centric API、标准 dotted Event 协议、`Last-Event-ID` SSE 续传和旧事件兼容映射。
- 页面生成会实时发出内容、布局、渲染和 QA 事件；Visual QA 与 Content QA 可路由有限 Repair Loop。
- Workspace 支持运行中追加指令、单页/Cmd/Ctrl 多页上下文、Skill/Handoff/HITL 事件、预览/内容/结构模式和长胶片延迟渲染。
- 模板切换不再由 Workspace 直接替换 theme，而是创建新 Agent Run 和新 Revision。
- `PPT_AGENT_RUNTIME_ENABLED=false` 可回滚到原固定 pipeline，便于灰度发布。

## 验证结果

- 后端：`154 passed, 1 skipped`。
- 前端：`53 passed`，TypeScript 无输出检查通过，Vite production build 通过。
- Alembic：空 SQLite 数据库从 `0001` 完整升级到 `0008_ppt_agentic_runtime (head)`。
- 模板：Academic 与 AI Future 的真实 PPTX hash、布局样本和视觉密度分析结果不同。
- 新增端到端覆盖：run-centric API、PPT/Slide 版本持久化、跨 PPT 版本 Slide Revision 历史。

## 运行与回滚

默认启用新 Runtime。部署前执行 `alembic upgrade head`。如需临时回滚执行路径，设置：

```text
PPT_AGENT_RUNTIME_ENABLED=false
```

数据库新表和历史版本无需回滚，可在重新启用后继续使用。

## 环境相关限制

- 当前环境未配置真实 LLM Key，因此真实模型的动态 Orchestrator 已通过接口和 Mock/结构测试验证，但未做在线模型质量评测。
- 当前环境没有 LibreOffice/Poppler 时，Visual QA 会明确标记 degraded，并使用几何、字宽和内容规则；安装渲染依赖后可启用像素级检查。
- `render_slide` 当前复用整套 deck render 并只使目标页缓存失效，后续可替换为原生单页渲染服务而不改变 Tool/API 契约。
