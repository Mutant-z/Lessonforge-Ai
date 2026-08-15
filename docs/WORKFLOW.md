# Agent 工作流说明

`backend/app/workflows/course_graph.py` 使用 LangGraph `StateGraph` 生成课程蓝图。蓝图确认并完成专属 Agent 初始化后，独立任务调度器并行启动教学设计、PPT、任务单和练习；PPT 以教学设计为硬依赖（`TASK_SPECS` 中 `ppt → ["lesson_plan"]`），视频脚本依赖教学设计，逐字稿依赖 PPT 与视频脚本，最后执行确定性 QA。

## 教学设计 Agent V2（动态工具化）

教学设计 Agent 从"固定目录 + 单次结构化调用"升级为"动态文档 + 多轮 Agent Loop + 工具调用 + QA 返修 + 流式执行时间线"：

- **双层结构**（`backend/app/schemas/lesson_plan.py`）：
  - `pedagogical_core`：稳定教学内核（目标/知识点/环节/活动/评价/板书/作业），是下游 PPT、任务单、练习和视频脚本的权威事实源；
  - `outline`：AI 动态维护的展示章节树（一级 2–15、总数 ≤30、深度 ≤3），章节标题、数量、顺序和组合均可动态调整，章节 ID（`SEC-*`）跨版本稳定。
  - 下游只通过统一投影 `lesson_plan_core()` 读取稳定内核，不判断 V1/V2 字段。
- **执行流**（`backend/app/agent/agents/lesson_plan/` + `backend/app/services/lesson_plan_pipeline_service.py`）：
  - 意图识别（GENERATE / SECTION_EDIT / RESTRUCTURE / CONTENT_ENRICH / TIMING_ADJUST / SYNC_CONTEXT / QA_ONLY）→ 计划 → `core/loop.run_agent_loop`（工具结果回喂、流式思考/tool 事件）→ pedagogy_qa 确定性门禁 + 独立语义审核 → repair_router 定向返修（≤3 轮、指纹防空转）→ finalizer 发布。
  - 工具集（`lesson_*` 前缀）：读取（蓝图/候选稿/Profile/材料/兄弟产物/锁定）、编辑（目录 CRUD/内容写入/内核更新/深层补丁）、检查（时长/对齐/大纲覆盖/引用/预览/Diff）；编辑工具只修改内存候选稿并检查锁定路径。
- **发布门禁**：`applied`（创建 V2 版本）/ `no_change`（保留原版）/ `rejected`（阻断问题未收敛，保留原版）。`validate_lesson_plan()` 在 Agent 发布、人工编辑、审批与全局 QA 四入口复用。
- **通用 Agent Core**（`backend/app/agent/core/`）：从 PPT pipeline 抽取领域无关的循环骨架、状态基类与错误类型；PPT 代码保持零改动（`PipelineEventEmitter.for_run` 的 `task_type` 参数化默认仍为 `"ppt"`）。
- **人工确认**：通用 `agent_human_requests` 表 + `POST /api/v1/agent-runs/{run_id}/human-response`（原子认领、continuation run + 确认凭证）。
- **开关**：`LESSON_PLAN_AGENT_RUNTIME_ENABLED`（默认 true），关闭时回退旧单次生成路径。
- **前端**：`LessonPlanWorkbench`（左侧执行时间线：意图/计划/工具/QA/返修流式显示 + 思考摘要；右侧动态大纲树与文档预览），指令可携带 `selected_section_ids / active_section_id / mode`（auto/content/structure/timing/qa）。

正式课程创建前由 `CourseIntakeSession` 承载需求对话。需求 Agent 先生成经过 Schema 校验的需求快照，再流式回复教师；每轮快照保存版本、字段来源、系统假设与冲突。只有教师确认后，系统才在单个事务中创建课程、保存 `CourseRequirement` V1、迁移材料并启动 `run_type=blueprint` 的后台任务。

CourseGraphState 保存课程、运行、蓝图、六类资源、质量、锁定路径、重试计数和已完成节点。运行结果同时落入 Artifact、GenerationStep 与 GenerationEvent，应用异常重启后已有产物不会丢失；未完成运行会明确保留运行状态，教师可重试。

蓝图批准后不会直接生成六类资源。系统先执行一次 `run_type=agent_initialization` 的项目级初始化：需求快照、蓝图、材料摘要/片段和用户偏好被提取成六份强类型 `CourseTaskAgentProfile`，再通过版本化 `PromptTemplate` 渲染项目专属 Prompt。六份 Profile 原子生效后任务调度器才会生成首稿；后续首稿、对话修订和上下文同步都记录实际使用的 `agent_profile_id`。

需求、蓝图或激活模板变化会生成 Profile 新版本。旧文件继续保留并标记为 `stale`，教师通过 `sync_context` 创建使用新 Profile 的 Artifact 版本。存量项目由前端在读取到 `not_initialized` 后调用幂等初始化接口，不在 GET 请求中产生副作用。

本地 Mock Provider 输出确定性、Schema 合法的教学示例；`LLM_PROVIDER` 切换后可通过 OpenAI-compatible Provider 调用真实模型。

