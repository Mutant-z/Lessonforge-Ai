# 多 Agent 智能 PPT 生成系统改造报告

- 日期：2026-08-06
- 范围：将 PPT 生成从「单次 LLM 调用 → 固定模板槽位填充」改造为「多 Agent 协作 + Agent Loop + 工具调用 + Artifact 图 + 渲染/QA/修订闭环」，前端 PPT 任务页改为 Codex 风格三栏工作台。
- 决策：深度集成现有课程流；三栏工作台替换 PPT 视图；端到端一次打通（每个 Agent 带确定性 mock，本地全流程可跑）。

---

## 一、原有项目架构分析

LessonForge AI 是面向教师的微课多 Agent 平台。技术栈：后端 Python 3.12 + FastAPI + LangGraph + SQLAlchemy + Alembic + Pydantic v2；前端 Vue 3 + TypeScript + Pinia + Element Plus + SSE。

核心链路：`需求对话(CourseIntakeSession) → 课程蓝图(CourseBlueprint) → Agent 初始化(6 份 CourseTaskAgentProfile) → 6 个并行任务(lesson_plan/ppt/task_sheet/exercise/video_script/verbatim) → 规则质量检查 → 导出 zip`。每个任务通过 `generation_runs / generation_steps / generation_events` 记录运行；`artifacts` 表按 `(course_id, artifact_type, version)` 存 JSON 内容。

LLM 层接口仅 `provider.structured(system, prompt, schema)` 与 `stream_text`，**无原生工具调用**；`MockProvider.structured()` 抛 NotImplementedError（内容来自 `generators.py` 确定性生成器）。SSE 事件通过 `GET /courses/{id}/task-events?token&after=N` 用 `generation_events.id` 做 `Last-Event-ID` 续传。

## 二、原有 Agent 数据流

```
需求对话 → 需求 Agent(逐轮 structured) → 确认创建课程
→ 蓝图 Graph(3 节点，单次 structured/节点)
→ 初始化(一次 structured 生成 6 份 Profile)
→ 每个任务 execute_task_run：
     generating 阶段 一次 provider.structured(输出该任务 JSON)（Mock 走 make_* 生成器）
     validating（schema + 规则校验 + PPT 主题归一化）
     saving（写 artifacts 新版本，标记下游 stale，规则质量评分）
→ 导出 render_deck 把 PPT JSON 填入 15 角色模板槽位
```

Agent 之间**不直接传结构化 Artifact**，而是各自读共享的 `artifacts` 表（`_latest_artifact`）+ 已批准蓝图；PPT 修订通过聊天消息触发 `_generate_ppt_revision`（最多 2 轮 + 确定性修复）。

## 三、原有 PPT 生成问题

1. **单次 LLM 调用**：一次 `structured()` 生成整套 15 页 `PPTContent` JSON，无「先理解再设计再修改」的多轮推理，无法根据工具结果调整。
2. **固定 15 页模板填充**：内容按 `deck_slots.json` 锚点**位置式**填入 6 套成品模板，`render_deck` 只填字、不建元素；`blocks/layout/visual_suggestion` 不参与几何。
3. **模板被当作固定容器**：模板只提供锚点，AI 不参与布局计算、信息层级、元素位置。
4. **无图片/图表/流程图生成**：`visual_suggestion` 仅文本提示；`visual` 块渲染成"图示占位"矩形。
5. **无渲染→QA→修订闭环**：`ppt_visual_qa` 依赖 LibreOffice（本机未安装），仅把 PPT 转 JPG 供人工看，无几何/溢出/重叠自动检查，发现问题不回路由给 Agent 修改。
6. **无实时过程**：前端只看到 phase 级进度（preparing/generating…），看不到 Agent 分工、工具调用、Artifact 创建。
7. **无暂停/恢复**：任务只能取消或失败后重试，无 checkpoint。

## 四、新 Agent 架构

新增 `backend/app/agent/` 包：Agent Loop 引擎 + 工具注册表 + 流水线编排。

```
编排(plan) → 叙事(narrative) → 模板分析(template_analysis)
→ 页面内容(slide_content) → 视觉规划(visual_plan) → 布局(layout)
→ 媒体(media: 图片/图表/流程图) → PPT 编辑(ppt_editor) → 视觉 QA(visual_qa)
→ [有 critical/major 问题] 修订(revision 路由) → 重跑受影响 Agent → 再 QA（≤3 轮）
```

9 个 Agent，各含：`key/name/role/required_artifacts/produced_artifacts/allowed_tools` + `decide()`（确定性 mock）+ `build_system_prompt()`（LLM 路径）：

| Agent | 职责 | 产出 Artifact |
|---|---|---|
| narrative | 决定章节/总页数/页面顺序与目标 | presentation_narrative |
| template_analysis | 解析模板为设计系统（配色/字体/装饰/边距） | design_system |
| slide_content | 压缩重组上游内容为页面级内容 | slide_content |
| visual_plan | 判断哪些页需要图片/图表/流程图 | visual_plan |
| layout | 动态计算每页元素几何（英寸坐标） | slide_layout |
| media | 按视觉规划生成图片/图表/流程图 | visual_asset |
| ppt_editor | 动态创建/编辑 PPT 页面元素 | presentation_file |
| visual_qa | 渲染 + 几何/字宽/知识检查 | visual_qa |
| revision | 分析 QA 问题并路由到对应 Agent | revision_note |

上游内容来源：流水线直接读取**已确认蓝图 + 教学设计**等既有 Agent 产物（`get_blueprint` / `get_upstream_artifacts` 工具），无需用户重复上传完整内容文档。

## 五、Agent Artifact 协议

新表 `pipeline_artifacts`：`(pipeline_run_id, artifact_type, name, version)` 唯一，同 (type,name) 新版本将旧版标 `superseded`（版本图不建额外表）；`dependencies_json` 记录上游 artifact id 边；`file_path` 指向工作目录。类型覆盖需求 §4 的 PresentationNarrative / DesignSystem / SlideContent / SlideLayout / VisualPlan / VisualAsset / VisualQA / PresentationFile 等。

每个 Agent 完成时，loop 将其 `output` 持久化为 Artifact（`PipelineArtifactManager.create`），并写入 `generation_steps`（`output_ref=artifact_id`）——满足"禁止 Agent 之间隐式字符串拼接传递重要数据"。

## 六、Agent Handoff 流程

流水线计划 `PipelinePlan.agents` 顺序执行：loop 在每个 Agent 边界发 `agent_started` / `agent_completed`，把 `ContextState`（蓝图/上游/设计系统/知识库/工具结果/用户指令/锁定路径）带到下一个 Agent；`completed.handoff` 字段预留显式切换。修订环由 `revision` Agent 输出 `target_agents`，流水线据此重排受影响 Agent 子计划后继续。

## 七、PPT 生成完整数据流

```
用户确认需求 → 蓝图批准 → Agent 初始化 ready → ppt 任务触发
→ 服务创建 PipelineRun + 工作目录 storage/generated/{course}/ppt_pipeline/{run}/
→ run_agent_loop：叙事→模板→内容→视觉规划→布局→媒体→编辑→QA
   （每个 Agent 内部小循环：decide() → 工具调用 → 结果回喂上下文 → 再 decide → 完成）
→ run_revision_loop：QA 有 critical/major → revision 路由 → 重跑 → 再 QA（≤3 轮）
→ finalize_content：builder.to_ppt_content() → 锁定路径还原 → _validate_and_repair_ppt
→ 渲染最终动态 PPTX 到 storage/generated/{course}/ppt/{version}.pptx
→ 返回 execute_task_run 下游：schema 校验 → 写 artifacts(ppt) 新版本 → 标记下游 stale → 质量刷新
→ 导出优先用流水线动态 PPTX，否则回退 render_deck
```

## 八、动态布局实现方式

新增 `backend/app/renderers/presentation_builder.py`：模板只作为**设计语言来源**（`catalog.json` 调色板/字体 + 从 `scripts/build_generic_decks.py` 提炼的每套模板装饰几何）。

- 布局 Agent 按内容量动态计算元素几何：封面居中标题、正文流（标题 + 正文文本框，高度按字宽估算）、左文右图（视觉规划命中时留 `visual_region`）。
- PPT 编辑 Agent 通过 31 个工具动态创建/移动/缩放/删除元素：`create_slide / add_textbox / add_shape / add_image / add_chart / move_element / resize_element / delete_element / set_element_style / set_background / add_notes / write_slide_batch / layout_slide_batch` 等。
- `render()` 按元素 z 序程序化生成真实 PPTX，并套用模板装饰 + 页脚/品牌条；`geometry_report()` 输出坐标供 QA 检查越界/重叠/溢出。**不依赖模板占位符**。

## 九、图片和图表生成方式

- `generate_image`：优先用课程选择的图片模型（复用 `exercise_visual_service.generate_image`）；无图片模型时用 `mock_asset.generate_placeholder_image`（PIL，按模板配色生成带标签占位图）。提示词注入页面标题、目标、主色、留白方向与"不生成文字/Logo/水印"。
- `generate_chart_png`：PIL 绘制 bar/line/pie（matplotlib 缺失，不引新依赖）。
- `render_diagram`：PIL 绘制流程/架构/时间线示意（节点 + 连线）。
- 编辑层 `add_chart` 优先 python-pptx 原生图表（`XL_CHART_TYPE`），异常降级为 PIL PNG。
- 媒体 Agent 只在视觉规划判定需要的页生成素材（不为所有页机械配图），生成后写 `visual_asset` Artifact 并落盘 `assets/`。

## 十、前端 Agent 工作台改造

- 新增 `stores/pipeline.ts`、`api/pipeline.ts`、`types/agentPipeline.ts`；`stores/project.ts` 的 `TASK_EVENTS` 增补 13 种流水线事件并路由到 `pipelineEvents` 收件箱；`types/agent.ts` 的 `AgentEventType` 同步扩展。
- 新增三栏组件 `components/agent/pipeline/`：`AgentPipelineWorkbench`（骨架）、`ExecutionPlanPanel`（左：状态/暂停恢复/执行计划）、`PipelineTimeline`（中：用户消息 + Agent 运行卡 + 工具调用卡 + Artifact/QA/修订事件卡 + 中途指令输入）、`PipelineArtifactPanel`（右：产物 Tab 用 `JsonTreeRenderer` 展开 + PPT 预览 Tab 复用 `SlidePreview/SlideThumbnail`）。
- `TaskWorkspaceView` 对 `taskType === 'ppt'` 渲染工作台（其余 5 个任务保持原聊天界面）。
- 复用现有孤儿组件（`JsonTreeRenderer`、`MarkdownRenderer`、`SlidePreview`）与设计系统 token。

## 十一、数据库变更

Alembic `0007_ppt_agent_pipeline`：新增 `pipeline_runs`（1:1 子表，状态机/计划/checkpoint/token 用量）、`pipeline_artifacts`（Artifact 图 + 版本）、`pipeline_tool_calls`（工具调用日志）、`pipeline_events`（明细事件，`sequence` 镜像 `generation_events.id`）。`generation_runs.status` 复用字符串值 `paused`（无列变更）。工作目录 `storage/generated/{course}/ppt_pipeline/{run}/` 含 `analysis/content/plans/assets/drafts/renders/qa/logs/output`。

## 十二、修改文件列表

- `backend/app/models/entities.py`（+4 模型）
- `backend/app/services/course_task_service.py`（ppt 优先分派、`except PipelinePaused`、`resume_incomplete_task_runs` 加 paused）
- `backend/app/services/export_service.py`（优先流水线动态 PPTX）
- `backend/app/main.py`（注册新路由）
- `backend/app/agents/generators.py`（`make_ppt` 角色化重写——会话开始前已存在的工作区改动，随本次一并生效）
- `backend/tests/test_project_tasks.py`（失败路径改 patch `run_ppt_pipeline`）
- `frontend/src/stores/project.ts`（TASK_EVENTS + pipeline 事件路由）
- `frontend/src/types/agent.ts`、`frontend/src/types/index.ts`（事件类型扩展）
- `frontend/src/views/TaskWorkspaceView.vue`（ppt 分支渲染工作台）
- `backend/tests/test_deck_renderer.py`、`backend/tests/test_task_sheet_upgrade.py`、`frontend/src/components/domain/SlidePreview.vue`（既有工作区改动，保持一致）

## 十三、新增文件列表

后端：
- `backend/alembic/versions/0007_ppt_agent_pipeline.py`
- `backend/app/agent/__init__.py`、`schemas.py`、`context.py`、`artifacts.py`、`events.py`、`registry.py`、`loop.py`、`definitions.py`、`pipeline.py`、`charting.py`、`mock_asset.py`
- `backend/app/agent/agents/`：`base.py`、`narrative.py`、`template_analysis.py`、`slide_content.py`、`visual_plan.py`、`layout.py`、`media.py`、`ppt_editor.py`、`visual_qa.py`、`revision.py`
- `backend/app/agent/tools/`：`artifact_tools.py`、`template_tools.py`、`editing_tools.py`、`render_tools.py`、`asset_tools.py`、`qa_tools.py`、`workspace_tools.py`
- `backend/app/renderers/presentation_builder.py`
- `backend/app/services/ppt_pipeline_service.py`
- `backend/app/api/v1/ppt_pipeline.py`
- `backend/tests/`：`agent_pipeline_helpers.py`、`test_agent_pipeline_schema.py`、`test_agent_loop.py`、`test_agent_tools.py`、`test_presentation_builder.py`、`test_ppt_pipeline_initial.py`、`test_ppt_pipeline_revision.py`、`test_ppt_pipeline_qa.py`、`test_ppt_pipeline_pause_resume.py`、`test_ppt_pipeline_events.py`、`test_ppt_pipeline_charts.py`

前端：
- `frontend/src/types/agentPipeline.ts`、`frontend/src/api/pipeline.ts`、`frontend/src/stores/pipeline.ts`
- `frontend/src/components/agent/pipeline/`：`AgentPipelineWorkbench.vue`、`ExecutionPlanPanel.vue`、`PipelineTimeline.vue`、`PipelineArtifactPanel.vue`、`ToolCallCard.vue`、`AgentRunCard.vue`、`ArtifactEventCard.vue`

## 十四、测试结果

- 后端：`cd backend && ../.venv/bin/python -m pytest -q` → **135 passed, 1 skipped**（skipped 为 env 门控的 v1/v2 对比评测）。新增 32 个流水线测试覆盖：决策协议 XOR、Loop 多次 LLM 调用 + 工具结果入上下文 + checkpoint、工具入参校验 + path-traversal 防护、builder 坐标/round-trip、初始流水线表行/事件、修订锁定还原、QA 越界 + 修订路由 + 修订环有界、暂停/恢复、事件 sequence 镜像、图表/示意图 PNG 与原生图表。
- 前端：`npx vue-tsc -b` 通过；`npm run build`（vite）成功；`npm test` → **44 passed**。
- 端到端（mock，真实服务）：建课 → 蓝图 → 初始化 → ppt 流水线 → **23 个 pipeline Artifact、97 次工具调用、260 条事件**，任务 `review`；导出 zip 201，`02_课件.pptx` 可被 python-pptx 打开；流水线动态 PPTX（15 页）在 `storage/generated/{course}/ppt/1.pptx`。

## 十五、未验证内容

- **真实 LLM 路径**：本机未配置 LLM Key，未实测叙事 Agent 可变页数、LLM 返回工具调用决策、真实模型下的 QA→修订闭环（代码路径存在，mock parity 已保证确定性）。
- **图像/视觉 QA 图像检查**：本机无 LibreOffice/soffice，图像级 QA 降级为几何/字宽/知识检查（`degraded=true` 已在事件中标记）；有 soffice 的环境会自动启用图像检查。
- **前端浏览器交互**：三栏工作台已通过类型检查与构建，但未在浏览器中人工点击验证（无浏览器驱动工具）。可 `./scripts/restart.sh` 后访问 `http://localhost:5173` 进入 PPT 任务页查看。
- **跨进程暂停恢复**：暂停/恢复在单进程内验证；多 worker/重启后恢复依赖 `resume_incomplete_task_runs`（已把 `paused` 纳入），未做跨进程实测。

## 十六、启动方式

```bash
./scripts/init_db.sh          # 首次初始化数据库（含迁移 0007）
./scripts/restart.sh          # 启动前后端（会自动跑 Alembic 迁移）
# 前端 http://localhost:5173，后端 http://localhost:8000/docs
```
LLM 模式：在「设置 → 模型」配置 OpenAI-compatible/Anthropic 模型后，流水线各 Agent 自动走 `provider.structured(AgentDecision)`；无配置时全部走确定性 mock（可完整跑通并被测试）。

## 十七、后续扩展建议

1. **Orchestrator LLM 化**：当前执行计划由确定性 `agent_specs_for_trigger` 生成；可改为 Orchestrator 读任务上下文后由 LLM 动态增删 Agent/调整计划（`plan_updated` 事件已在协议中预留）。
2. **图像级视觉 QA**：安装 LibreOffice + poppler 后自动启用 `PPTVisualQARenderer` 像素检查（文字溢出/裁剪/对比度），并接入真实视觉模型复核。
3. **上下文记忆与摘要**：对超长工具结果与历史消息做 LLM 摘要，控制 token 预算（`ContextState` 已留截断/估算位）。
4. **中途指令抢占**：运行中指令先落 `agent_messages`，在下一次 checkpoint 或本 run 结束后由修订 Agent 消费；后续可在 Agent 边界实现真正的抢占式插入。
5. **多页并行**：layout/media/ppt_editor 目前逐页顺序；对 30+ 页大型 PPT 可并行处理不相关的页。
6. **模板上传解析**：支持用户上传模板并实时提取设计系统（当前为内置 6 套 + 装饰几何静态映射）。
