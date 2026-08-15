# 学习任务单动态目录 + 教师逐字稿 Agent 重构收尾报告

> 日期：2026-08-14 · 分支：main（含大量未提交的 PPT/任务单在制品，本报告只覆盖本次交付）

## 一、本次交付与验收对照

| 用户需求 | 状态 | 说明 |
|---|---|---|
| 1. 学习任务单大目录动态化 | ✅ 已实现（默认开关关闭） | task_sheet Agent V3 动态目录迁移完成，测试全绿；`task_sheet_agent_runtime_enabled` 保持默认 `False`，经 `TASK_SHEET_AGENT_RUNTIME_ENABLED=true` 启用 |
| 2. 教师逐字稿改为多轮工具调用 Agent | ✅ 已实现（默认开启） | 全新 `VerbatimContentV2` + 7 角色流水线：意图识别 → 上下文调研 → 逐段口播 → 时序 → QA → 返修 → 发布 |
| 3. 流式输出 + 工具调用可视化 | ✅ 已实现 | 复用通用事件发射器与 `AgentExecutionTimeline`；新增 `VerbatimWorkbench` 左侧流式展示意图/工具卡/QA/返修，右侧逐段口播预览 |

验收重点：
- 逐字稿每段对齐视频脚本 `scene_id`，数值时间轴为权威值，展示字符串程序派生。
- 改写口播不得丢失源场景必需术语/数字/结论（QA critical 门禁），口播字数/语速 + 停顿不得超过段落时长。
- `word_count` / `estimated_duration_seconds` 由后端确定性计算，不接受模型伪造。
- 一轮对话至少经历「意图识别 → 读取上下文 → 工具修改 → QA → 返修 → 发布」多次模型调用。
- 前端右侧实时显示候选稿，正式版本仅在运行成功后替换。

## 二、教师逐字稿 Agent V2（新建）

### 数据契约 `backend/app/schemas/verbatim_v2.py`
- `VerbatimContentV2`：`schema_version: "2.0"`、默认语速 `speaking_rate_cps`、`source_versions`、`course_info`。
- `VerbatimSectionV2`：稳定 `id`、关联 `scene_id`、可选 `slide_ids`、数值 `start_seconds/end_seconds`、`pedagogical_action`、`delivery_tone`、`required_text`、`optional_text`、`key_emphasis`、`interaction`、`pause_seconds`。
- 文档校验器按 `required_text 字数 / 语速 + 停顿` 确定性重算 `word_count` 与 `estimated_duration_seconds`；时间轴连续、总时长守恒、scene 一对一。
- `upgrade_verbatim_v2()`：V1 → V2 运行期适配（首次修改生成 V2 候选，旧 Artifact 不改写）。
- `verbatim_sections_for()`：V1/V2 统一章节投影（预览/导出/质量校验复用）。

### Agent（`backend/app/agent/agents/verbatim/`）
7 角色：`intent_planner / context_researcher / verbatim_director / timing_engine / verbatim_qa / repair_router / finalizer`。
- 意图：GENERATE / SECTION_EDIT / STRUCTURE_EDIT / SCRIPT_EDIT / TONE_EDIT / TIMING_ADJUST / STYLE_EDIT / INTERACTION_EDIT / SYNC_CONTEXT / QA_ONLY / ANSWER_ONLY / CLARIFICATION_REQUIRED。
- 工具（`vb_*`，15 个）：读取（context/source/scenes/sections/locks）、编辑（initialize / update_section / batch_style / rebalance_timing / add / delete / move section）、检查（validate / diff / render）。删除章节等高风险操作需人工确认令牌。
- 运行时：意图 → 计划 → 工具循环（每角色 ≤8 轮）→ QA → 返修（≤2 轮，指纹防空转）→ 发布；`result_status ∈ {applied, no_change, rejected, needs_confirmation}`；支持暂停/恢复与运行中指令合并重规划。

### 服务与接线
- `backend/app/services/verbatim_pipeline_service.py`：initial / message / sync_context 三条路径，`skip_publish` 语义对齐。
- `course_task_service.execute_task_run`：新增 `use_verbatim_pipeline` 分支、校验/标记/`complete_verbatim_pipeline_after_publish`、`TASK_SCHEMAS["verbatim"]=VerbatimContentV2`、`_generate_initial/_generate_revision/_generate_context_sync` 的 V2 mock 路径、`_ensure_current_task_profile` 支持 verbatim 升级。
- `agent_prompt_service.py`：`VERBATIM_SYSTEM_TEMPLATE_V2` 并激活。
- `api/v1/verbatim_agent.py`：`/courses/{id}/tasks/verbatim/runs|messages`（携带 `selected_section_ids` / `mode`）；`main.py` 注册。
- 兼容：`generators.to_markdown` 与 `quality_service.validate_resources` 支持 V2。

## 三、学习任务单动态目录（task_sheet，外部在制品收口）
- 确认 task_sheet Agent V3 已具备动态目录能力：`intents.py`（STRUCTURE_EDIT/TASK_EDIT/… 新枚举 + `target_task_ids/target_phases`）、`agents.py`（`task_architect/task_designer` 分工）、`runtime.py`（`confirmation_tokens`、人工确认、运行中指令合并）。
- 验证 `test_task_sheet_agentic.py` 全绿（迁移后不再有 `target_section_ids` AttributeError）。
- **开关**：`task_sheet_agent_runtime_enabled` 默认 `False`（保持可配置），`TASK_SHEET_AGENT_RUNTIME_ENABLED=true` 即启用动态目录；`video_script_agent_runtime_enabled` 同理。

## 四、测试
- `backend/tests/test_verbatim_agent.py`（新增，24 项）：schema、builder CRUD/时间轴、QA 事实/时长/scene 门禁、意图识别、Mock 全链 runtime（initial applied / timing applied / no_change / answer-only / destructive 需确认）。
- 核心回归：`test_verbatim_agent + test_task_sheet_agentic + test_task_sheet_v3_schema + test_lesson_plan_runtime + test_video_script_agentic + test_video_script_v4_schema` → **72 passed**。
- 前端：`vue-tsc --noEmit` 退出码 0；`npm run build` 成功。

## 五、已知问题 / 说明
1. `test_project_tasks.py::test_task_message_creates_version_and_marks_dependents_stale` 失败：根因是外部在制品的 PPT 几何门禁（`PPTAgentError: 只改文字的任务意外调整了页面几何`），与本次逐字稿/任务单改动无关，由 PPT 工作收口后解决。
2. `test_task_sheet_upgrade.py::test_knowledge_snapshot…` 失败：依赖教学设计 V1 字段 `content_analysis`，教学设计 V2 迁移后失效，属既有在制品问题。
3. 逐字稿运行时依赖**完整**视频脚本：知识投影超长会被 `_bounded` 截断，`run_verbatim_pipeline` 已从 DB 注入完整 `video_script` 规避。
4. 目录动态化（任务单/视频脚本）为独立开关，默认关闭以保持向后兼容。

## 六、前端
- 新增 `frontend/src/components/agent/verbatim/VerbatimPreviewWorkbench.vue`（右侧逐段渲染：时间轴/场景/教学动作/必讲/补充/语气/重音/互动/停顿/字数/口播时长，支持点选章节作为指令作用域）。
- 新增 `frontend/src/components/agent/pipeline/VerbatimWorkbench.vue`（左侧流式 Agent 时间线 + 输入框 + 暂停/继续 + 人工确认，右侧预览）。
- `TaskWorkspaceView.vue` 接入 `verbatim` 分支；`api/pipeline.ts`、`stores/project.ts` 新增 `createVerbatimRun`。
