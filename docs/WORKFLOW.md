# Agent 工作流说明

`backend/app/workflows/course_graph.py` 使用 LangGraph `StateGraph` 生成课程蓝图。蓝图确认并完成专属 Agent 初始化后，独立任务调度器并行启动教学设计、PPT、任务单和练习；视频脚本依赖 PPT Schema，逐字稿依赖 PPT 与视频脚本，最后执行确定性 QA。

正式课程创建前由 `CourseIntakeSession` 承载需求对话。需求 Agent 先生成经过 Schema 校验的需求快照，再流式回复教师；每轮快照保存版本、字段来源、系统假设与冲突。只有教师确认后，系统才在单个事务中创建课程、保存 `CourseRequirement` V1、迁移材料并启动 `run_type=blueprint` 的后台任务。

CourseGraphState 保存课程、运行、蓝图、六类资源、质量、锁定路径、重试计数和已完成节点。运行结果同时落入 Artifact、GenerationStep 与 GenerationEvent，应用异常重启后已有产物不会丢失；未完成运行会明确保留运行状态，教师可重试。

蓝图批准后不会直接生成六类资源。系统先执行一次 `run_type=agent_initialization` 的项目级初始化：需求快照、蓝图、材料摘要/片段和用户偏好被提取成六份强类型 `CourseTaskAgentProfile`，再通过版本化 `PromptTemplate` 渲染项目专属 Prompt。六份 Profile 原子生效后任务调度器才会生成首稿；后续首稿、对话修订和上下文同步都记录实际使用的 `agent_profile_id`。

需求、蓝图或激活模板变化会生成 Profile 新版本。旧文件继续保留并标记为 `stale`，教师通过 `sync_context` 创建使用新 Profile 的 Artifact 版本。存量项目由前端在读取到 `not_initialized` 后调用幂等初始化接口，不在 GET 请求中产生副作用。

本地 Mock Provider 输出确定性、Schema 合法的教学示例；`LLM_PROVIDER` 切换后可通过 OpenAI-compatible Provider 调用真实模型。
