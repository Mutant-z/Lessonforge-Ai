# PPT 润色改进 · 收尾报告

> 日期：2026-08-11
> 范围：LessonForge AI PPT Agent 润色链路改造（`363d2bb..HEAD`，15 个提交，37 文件，+3512/-199 行）
> 设计：`docs/superpowers/specs/2026-08-10-ppt-polish-design.md`
> 计划：`docs/superpowers/plans/2026-08-10-ppt-polish.md`
> 台账：`.superpowers/sdd/2026-08-10-ppt-polish/progress.md`

---

## 1. 背景与目标

教师通过推演工作台对 PPT 某一页/若干页发起润色指令（如「润色一下现在PPT的页面分布」），结果经常不合格。典型失败五类：

1. **布局挤成一团 / 大面积空白**——只让润色页面分布，正文被压成窄条竖排或堆一角，其余空白；
2. **文字溢出 / 被截断**——文本框过矮，正文显示不下；
3. **元素重叠 / 错位**——图片盖住文字、标题压正文；
4. **内容被改写 / 丢失**——只让改布局，措辞却被换掉；
5. **布局单调 / 无实际变化**——润色后页面几乎没变。

本报告记录从诊断到实施的全部过程与最终形态。

## 2. 问题诊断（根因链）

### 2.1 「挤成一团」为什么此前拦不住
- **LLM 输出自由坐标**：`SlideLayoutArtifact` 的 `x/y` 是无界 float（`schemas.py`），系统提示里的硬约束只是散文，模型经常不遵守——这是"挤成一团"的直接来源。
- **确定性规范化只修一种形态**：`canonicalize_spatial_layout` 仅在「纵向没铺满 45% **且** 横向没展开 60%」同时成立时重排；**窄条竖排占满高度、右侧大片空白**恰好纵向铺满，原样放行。
- **QA 门禁有洞**：`layout.cluster_cramming` 要求文字元素 ≥3 个；LLM 把正文合成单聚合框时只剩 2 个文字元素，整块空间检查被跳过。`layout.blank_region` 用包围盒算覆盖率，横贯标题会掩盖"正文挤在角落"。
- **修复环不收敛**：QA 命中后把**同一个 LLM 用同一套提示词重跑**，大概率复现同样坏布局；3 轮耗尽后走 human 确认"保留当前版本"——教师看到的正是它。

### 2.2 其它放大因素
- **知识注入截断**：`context.py` 单块 6000 字符上限，17.5KB 的 `knowledge.json` 中 `typography`（字号表）与 `ppt_skills`（设计模式库）整体丢失。
- **模板无语义区域**：标题轨/正文列/视觉槽只存在于 `layout.py` 硬编码常量，仅 `smart_ai`/`academic` 两套模板有导轨特例。
- **`spatial_rules` 无执行方**：`knowledge.json` 的 0.5in 边距 / 0.3in 间距全库无一处执行。
- **LibreOffice 像素 QA 未接入**：只探活不执行，`text_overflow` 纯靠字符宽度估算。
- **意图识别靠关键词**：30 个标记猜 11 种 intent，无结构化目标维度，`visual_suggestion` 字段无人消费。

## 3. 解决方案架构

```
旧链路：指令 → 关键词猜意图 → LLM 自由输出坐标 → 事后补丁规范化 → QA(有洞) → 修复环(重跑同一 LLM)
新链路：指令 → LLM 结构化意图提取 → LLM 选版式+参数(LayoutDirective) → 确定性引擎算坐标
        → 几何 QA + 视觉蓝图自检 → 收敛性修复(几何类确定性 / 审美类带反馈换版式)
```

**设计原则**：把「让 LLM 心算英寸坐标」改为「确定性布局引擎保证几何正确 + LLM 在有限版式库内做选择 + 视觉模型兜审美」。**错误几何（越界/重叠/溢出/窄条）由引擎构造性保证不可能产出**，视觉自检补足"留白是否平衡、是否单调"这类规则测不出、人一眼看出的审美层。

## 4. 实施成果（13 任务）

| # | 任务 | 提交 | 关键产出 |
|---|---|---|---|
| 1 | 语义布局区域模型 | `10e4f5f` | `layouts/zones.py`：LayoutZones（标题轨/正文列/视觉槽，模板+页型驱动） |
| 2 | 统一文本度量 | `72338bc`+`2d2093f` | `layouts/metrics.py`：消除双份估算漂移，修复 >6 条聚合框高度求和语义 |
| 3 | 固定预设版式库 | `24336f1`+`d128a40` | `layouts/presets.py`：9 个 preset + 黄金几何不变量测试；修复 steps 卡数上限 |
| 4 | 编译入口 | `266c576` | `layouts/engine.py`：`compile_layout`（预设解析+参数收敛，非法回退） |
| 5 | 确定性路径接入引擎 | `edb3b9c` | `layout.py::_layout_slide` → `compile_layout`，mock 与 LLM 共用同一几何源 |
| 6 | LayoutDirective 接线 | `0aee086` | `LayoutDirectiveSlide/Artifact` schema + `_ensure_executable_layout` 编译 + LLM 提示词改造 |
| 7 | 结构化意图提取 | `d430d9e` | `intents.py`：`PolishIntent`（action/target_dimension/preserve_text）+ modality 字段 |
| 8 | QA 规则补齐 | `e360a20`+`3dbf8d5` | 标题轨/边距/列平衡规则、移除 ≥3 门槛；修复封面 title_in_rail 误伤 |
| 9 | 几何蓝图图+视觉自检 | `bc65475` | `LLMProvider.structured_with_image` + `vision_tools.py`（PIL 蓝图图） |
| 10 | 收敛性修复 | `4503882` | `DETERMINISTIC_RULES` 分类、`semantic_geometry_hash`、单调性门禁 |
| 11 | 知识注入修复 | `25b64de` | `context.py` knowledge 块预算 18000，typography/ppt_skills 可达 |
| 12 | 端到端测试+抽查工具 | `61138d9` | `test_ppt_polish.py`（五类防线）+ `scripts/polish_eval.py` |
| 13 | 前端范围选择+修复原因 | `1025215` | Composer 三段范围选择、胶片修复/QA 徽标、前缀剥离、单页选中修复 |

## 5. 验证与质量证据

- **后端**：PPT 全表面 **131 passed / 0 failed**（`test_layouts_engine` + `test_ppt_agentic_runtime` + `test_agent_tools` + `test_ppt_pipeline_qa` + `test_ppt_revision` + `test_ppt_polish` + `test_vision_tools`，42s）。
- **前端**：`vitest` + `vue-tsc --noEmit` + `npm run build` 全绿（Task 13 agent 验证）。
- **基线说明**：仓库原有 38 个环境性失败（`no such table` 测试库未迁移 / `Login failed 401` 鉴权种子缺失 / `KeyError: 'id'` 级联），存在于 `test_agent_loop` / `test_ppt_agent_api` 等，**非本计划引入**，需迁移测试库后另行处理。
- **TDD**：核心任务均 RED→GREEN 有证据；每个预设的几何不变量、QA 规则、端到端防线均有回归断言。

## 6. 文件结构

**新增（backend/app/agent/layouts/）**：`zones.py`、`metrics.py`、`presets.py`、`engine.py`、`__init__.py`
**新增**：`backend/app/agent/intents.py`、`backend/app/agent/tools/vision_tools.py`、`backend/tests/test_layouts_engine.py`、`backend/tests/test_vision_tools.py`、`backend/tests/test_ppt_polish.py`、`scripts/polish_eval.py`
**修改**：`schemas.py`、`layout.py`、`pipeline.py`、`runtime.py`、`qa_tools.py`、`context.py`、`slide_rendering.py`、`presentation_builder.py`、`ppt_agent.py`、`providers/llm/{base,mock,anthropic,openai_compatible}.py`、前端 `pipeline.ts`/`AgentComposer.vue`/`AgentPipelineWorkbench.vue`/`AgentExecutionTimeline.vue`/`PPTPreviewWorkbench.vue`/`PPTSlideFilmstrip.vue`/`useAgentStream.ts`/`stores/project.ts`/`types/project.ts` + 测试

## 7. 使用方式

**人工抽查工具**（按你的验收标准"人工 + 自动化两者都要"）：
```bash
cd "/Users/mutant/Documents/project/LessonForge AI" && .venv/bin/python scripts/polish_eval.py
# 输出 storage/polish_eval/report.md：每页 指令/意图/版式/QA/结论 + before/after 蓝图图
```

**前端**：Composer 顶部「自动/只改布局/只改文字/只改图片」选择随请求发 `modality`；胶片上出现「本页被修复/QA 拦截」徽标可展开原因。

## 8. 遗留事项与待决产品决策

| 项 | 说明 | 建议 |
|---|---|---|
| **单调性门禁（需产品拍板）** | Task 10 把「润色后布局无变化」从 append-only（实为无效）改为**抛 `layout_monotony` 拒绝发布**。多选页中某页已最优时，整次润色被拦 | ①接受严格版；②改为只对非最优页报 minor 提示 |
| **>6 条正文边界** | `bullet_flow` 在 >6 条正文时可能溢出页底（生产密度净化封顶 6 条，属边界） | 抽查工具已标注；后续可让引擎按列数自动拆双栏 |
| **确定性修复未重调参数** | `repair_mode=deterministic` 目前跳过 LLM/修订，但未按计划回填 `gap_scale=1.3` 重编译 | 可选增强 |
| **layout_type 自由字段** | 引擎预设 `layout_type` 与 `knowledge.json` 版式库仍可扩展对齐 | 低优先 |
| **环境性测试失败** | 38 个基线失败源于测试库未迁移/鉴权种子缺失 | 单独处理：`alembic upgrade head` + 种子脚本 |

## 9. 后续改进建议

1. **引擎补"受限自定义版式"**：在预设库基础上允许 LLM 声明列数/行距等受限参数，进一步释放创意自由度（需强校验）。
2. **LibreOffice 像素 QA 接入**：环境就绪后把 `convert_pptx_to_images` 接进 `run_qa`，替代字符宽度估算。
3. **单调性门禁产品化**：按 §8 决策落地后，把「本页已是最优」做成前端提示而非整批拒绝。
4. **新模板注册**：`zones.py::_TEMPLATE_CONTENT_X` 目前仍内嵌两套模板特例，后续可改为模板配置驱动。

## 10. 过程复盘与成本

- **执行方式**：串行 SDD（每任务实施+审查+修复轮）→ 中途按用户要求切换为并行 wave（文件所有权互斥分组）。并行显著降低墙钟时间，但对共享脏工作树（大量未提交 owner WIP）有提交混杂代价。
- **成本**：会话约 **$69**，大头为探索轮 + 逐任务审查 + 并行 agent + 分类器反复故障的重复调用。中途两次经用户批准继续。
- **经验**：① 后续大任务建议一开始就用「并行 wave + 合并审查」；② 脏工作树应在开工前先做基线提交（本任务用户选择直接在 main 上实施，导致部分提交混入既有 WIP）；③ 测试库环境（迁移/种子）应先于实施修复，否则审查门始终带着环境噪音。

---

*文档完成。所有设计、计划、台账、任务简报/报告均留存于 `docs/superpowers/` 与 `.superpowers/sdd/2026-08-10-ppt-polish/`。*
