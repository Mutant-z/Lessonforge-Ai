# Agent 工作流说明

`backend/app/workflows/course_graph.py` 使用 LangGraph `StateGraph` 建立真实状态图。蓝图确认后，教学设计、PPT、任务单和练习节点进入并行分支；视频脚本依赖 PPT Schema，逐字稿依赖 PPT 与视频脚本，最后汇合到 QA。

正式课程创建前由 `CourseIntakeSession` 承载需求对话。需求 Agent 先生成经过 Schema 校验的需求快照，再流式回复教师；每轮快照保存版本、字段来源、系统假设与冲突。只有教师确认后，系统才在单个事务中创建课程、保存 `CourseRequirement` V1、迁移材料并启动 `run_type=blueprint` 的后台任务。

CourseGraphState 保存课程、运行、蓝图、六类资源、质量、锁定路径、重试计数和已完成节点。运行结果同时落入 Artifact、GenerationStep 与 GenerationEvent，应用异常重启后已有产物不会丢失；未完成运行会明确保留运行状态，教师可重试。

本地 Mock Provider 输出确定性、Schema 合法的教学示例；`LLM_PROVIDER` 切换后可通过 OpenAI-compatible Provider 调用真实模型。
