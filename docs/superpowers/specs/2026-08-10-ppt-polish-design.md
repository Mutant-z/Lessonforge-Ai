# PPT 润色改进设计：确定性布局引擎 + LLM 有限选择 + 视觉自检

> 状态：已获用户批准（2026-08-10）
> 关联系统：LessonForge AI PPT Agent（`backend/app/agent/` + `frontend/`）
> 本文档是后续实施计划（writing-plans）的输入。

## 1. 概述与背景

教师通过推演工作台对 PPT 某一页或若干页发起润色指令（如「润色一下现在PPT的页面分布」）时，结果经常不合格，典型失败有：

1. **布局挤成一团 / 大面积空白**——只让润色页面分布，结果正文被压成窄条竖排或堆在一角，其余空白；
2. **文字溢出 / 被截断**——文本框过矮，正文显示不下；
3. **元素重叠 / 错位**——图片盖住文字、标题压正文；
4. **内容被改写 / 丢失**——只让改布局，措辞却被换掉；
5. **布局单调 / 无实际变化**——润色后页面几乎没变。

本设计把「让 LLM 自由输出坐标」改为「**确定性布局引擎 + LLM 有限选择 + 视觉蓝图自检**」，从源头杜绝前四类几何失败，并用视觉自检兜住审美层（平衡、留白、单调）。

## 2. 问题诊断（根因）

已通过源码与测试证据核实（2026-08-10 探索结论）：

### 2.1 「挤成一团」为什么拦不住
- **LLM 出自由坐标**：`SlideLayoutArtifact` 的 `LayoutElementSpec` 中 `x/y` 是无界 float（`backend/app/agent/schemas.py:51-67`），系统提示里的硬约束只是散文（`backend/app/agent/agents/layout.py:182-191`），模型经常不遵守。
- **确定性规范化只修一种形态**：`canonicalize_spatial_layout`（`layout.py:30-91`）仅在「纵向没铺满 45% **且** 横向没展开 60%」同时成立时重排。**窄条竖排占满高度、右侧大片空白**恰好纵向铺满 → 垂直检查通过 → 原样放行。
- **QA 门禁也有洞**：`layout.cluster_cramming` 要求文字元素 ≥3 个（`backend/app/agent/tools/qa_tools.py:85`）；LLM 把正文合成单聚合框时只剩 2 个文字元素，整块空间检查被跳过。`layout.blank_region` 用包围盒算覆盖率，横贯页面的标题会撑大包围盒、掩盖「正文挤在角落」。
- **修复环不收敛**：QA 命中后把**同一个 LLM 用同一套提示词重跑**（`runtime.py:479-503`），大概率复现同样的坏布局，3 轮耗尽后走 human 确认「保留当前版本」——教师看到的正是它。

### 2.2 其它放大因素
- **知识注入截断**：`ContextBlock.serialize()` 单块上限 6000 字符（`backend/app/agent/context.py:13,45`），17.5KB 的 `templates/ppt_design/knowledge.json` 中 `typography`（字号表）与 `ppt_skills`（设计模式库）**整体丢失**，布局 agent 拿不到字号规范。
- **模板无语义区域**：标题轨/正文列/视觉槽只存在于 `layout.py` 硬编码常量（`MARGIN_X/MARGIN_Y/SAFE_CONTENT_BOTTOM/_content_start_x`，`layout.py:15-22`），且仅 `smart_ai`/`academic` 两套模板有导轨特例；新模板需改代码。
- **`spatial_rules` 无执行方**：`knowledge.json` 的 `min_padding=0.5` / `min_element_gap=0.3` / `text_overflow_slack_ratio=0.1` 全库无一处读取执行，与 `layout.py:18`、`qa_tools.py:57,75` 的硬编码阈值漂移。
- **LibreOffice 像素 QA 未接入**：`PPTVisualQARenderer` 在 `run_qa` 里只探活不执行（`qa_tools.py:295-303`），`text_overflow` 纯靠字符宽度估算。
- **意图识别靠关键词**：`infer_intent` 用 30 个标记猜 11 种 intent（`runtime.py:31-146`），无结构化目标维度（distribution/spacing/alignment…），`visual_suggestion` 字段无人消费。
- **前端范围通道不一致**：单页「修改本页」路径（`frontend/src/components/agent/pipeline/AgentPipelineWorkbench.vue:224-227`）不进入 `selectedSlideIndexes`，`selected_slide_ids` 为空，仅靠文本前缀；教师气泡里的 `[针对第 N 页]` 前缀不被剥离（`frontend/src/composables/useAgentStream.ts:200` 只处理 `[目标页面:]`）。

### 2.3 已存在的防线（保留，不推翻）
- `_ensure_executable_layout`（`backend/app/agent/pipeline.py:381-546`）：schema 校验、`normalize_visual_region` 钳位、`bind_content_refs` 绑定权威文字、`render_coverage` 缺失即回退确定性编译。
- `_expand_aggregate_body_into_items`（`pipeline.py:337-378`）：把聚合 `body` 拆成逐条独立框。
- preserve/restore 内容锁定门禁（`runtime.py:627-660`、`qa_tools.py:205-215`）。
- 几何 QA 已有 7 条规则 + 4 条渲染层规则（`qa_tools.py:37-119`）。

## 3. 设计决策（用户拍板）

1. **技术路线**：确定性布局引擎 + LLM 做选择。
2. **LLM 能力**：生产为 Anthropic/OpenAI，支持视觉 → 启用「渲染后看图自检」。
3. **需一并解决的失败**：文字溢出/被截断、元素重叠/错位、内容被改写/丢失、布局单调/无实际变化（四类全要）。
4. **验收**：人工抽查真实指令 + 自动化测试（两者都要）。
5. **版式库边界**：固定预设库（约 10 个），LLM 只能从中选。
6. **视觉自检渲染路径**：几何蓝图图（PIL 画元素矩形+文字，不依赖 LibreOffice；LibreOffice 可用时可升级真实截图，作为可选增强）。
7. **前端改造**：加「只改布局/只改文字/只改图片」范围选择 + 持久化展示 QA/修复原因。

## 4. 架构总览

```
当前：  指令 → infer_intent(关键词标记) → LLM 自由坐标 → 后置规范化(只修一种形态) → QA(有洞) → 修复环(重跑同一 LLM)
目标：  指令 → 结构化意图提取 → LLM 选版式+参数(LayoutDirective) → 确定性引擎算坐标 → 编辑层
        → 几何 QA + 视觉蓝图自检 → 收敛性修复（几何类确定性收敛 / 审美类 LLM 换版式）
```

新增组件（均在 `backend/app/agent/` 下）：
- `layouts/zones.py` — 语义布局区域模型 `LayoutZones`
- `layouts/presets.py` — 固定预设版式库 + `compile()` 纯函数
- `layouts/engine.py` — 编译入口（`LayoutDirective` → `PageLayoutSpec.elements`）
- `intents.py` — 结构化意图提取 `extract_polish_intent`
- 布局 agent 提示词改输出 `LayoutDirective`（不输出坐标）
- 视觉自检：新工具 `render_geometry_preview` + 视觉审查能力（折叠进 layout/QA 修复环）
- 前端：Composer 范围选择 + 胶片修复/QA 徽标与详情

## 5. 结构化意图提取（`intents.py` + `runtime.py`）

run 启动时（非 mock、非 queued 增量）调一次 LLM 结构化输出：

```python
class PolishIntent(BaseModel):
    action: Literal["layout_only","text_polish","image_only",
                    "template_switch","full_regenerate","restore","visual_qa","export"]
    target_dimension: Literal["distribution","spacing","alignment",
                              "balance","size","color","overall","none"]
    preserve_text: bool
    scope_slide_ids: list[str]      # 与 selected_slide_ids 合并取并集
    summary: str
```

- 「润色一下现在PPT的页面分布」→ `{layout_only, distribution, preserve_text:True}` → 引擎选「铺得更开」的版式。
- 「润色这段文字，改得更精炼」→ `{text_polish, overall, preserve_text:False}`。
- 结果写入 `PipelineRuntime.polish_intent`，作为额外上下文块注入布局/内容 agent；`target_dimension` 直接映射引擎参数。
- **降级**：LLM 不可用或结构化失败时回退现有关键词 `infer_intent`（`runtime.py:125-146` 保留）。
- **前端 `modality` 字段**（见 §13）：前端范围选择显式传 `layout|text|image`，后端优先采信，消除文本猜测歧义。
- 修 bug：单页「修改本页」路径补 `selected_slide_ids`。

## 6. 语义布局区域模型（`layouts/zones.py`）

替换 `layout.py:15-22` 的硬编码常量：

```python
@dataclass
class LayoutZones:
    content_x: float          # 模板安全导轨左侧（替代 _content_start_x 特例）
    title_rail: Rect          # 标题轨（y≈0.55..1.35）
    body_column: Rect         # 正文列（y 1.7..6.8，右缘取决于有无视觉槽）
    visual_slot: Rect | None  # 右侧视觉槽（normalize_visual_region 钳位结果）
    canvas: Rect              # 13.333 × 7.5

zones_for(template_id, page_type, has_visual) -> LayoutZones
```

- 由 `template_id + page_type` 派生；非对称模板导轨偏移改为**模板配置驱动**（`templates/PPT_template` 下每套模板可声明，替代 `_content_start_x` 两套特例）。
- 唯一事实来源：**引擎算坐标 / QA 越界 / 修复重排 / 前端调试叠加层** 四处消费。
- `knowledge.json` 的 `spatial_rules`（0.5in 边距 / 0.3in 间距）在此落地为确定性执行方。

## 7. 布局引擎与固定预设库（`layouts/presets.py` + `engine.py`）

9 个预设（可扩展），每个是 `compile(zones, content, params) -> list[LayoutElementSpec]` 纯函数：

| preset | 适用 page_type | 结构 |
|---|---|---|
| `cover_left` / `cover_center` | cover | 标题+副标题+purpose；可选右视觉 |
| `bullet_flow` | 默认/正文 | 标题轨 + 正文逐条独立框、纵向均匀铺满 |
| `split_two_column` | concept/objectives | 条目均分左右两列 |
| `left_text_right_visual` | 有视觉槽 | 左文右图 |
| `steps_horizontal` | process/case | `blocks.steps` → 横向编号卡片（≤4 列） |
| `compare_columns` | comparison | `blocks.compare` → 左右双栏 |
| `quote_center` | scenario/question | 居中引用 |
| `agenda_list` | summary/objectives | 编号条目列表 |

**引擎构造性保证**（不是事后校验，是算不出错误几何）：
- 所有坐标落在 `LayoutZones` 内；
- 列内元素垂直排布、无两两重叠；
- 文本框高度 = 内容 + 字号估算（复用并集中 `_estimate_height`，`layout.py:153-159`，作为共享文本度量）→ 不溢出；
- 正文列纵向铺满 ≥45% 且宽度铺满列宽 → 窄条竖排、挤一角、右侧空白在源头不可能出现；
- 条间距由「总内容高度 vs 列高」摊匀（泛化 `canonicalize_spatial_layout` 的 gap 均摊逻辑，`layout.py:74-76`）。

**预设库边界**：`layout_type` 必须是预设库 key；非法值 → 静默回退 `bullet_flow`，不重调 LLM、不产生坏几何。预设库为可扩展目录，每模板可注册专属 preset。

## 8. LLM 输出：`LayoutDirective`

```python
class LayoutDirectiveSlide(BaseModel):
    slide_id: str
    layout_type: str                      # 必须是预设库 key，否则回退默认
    content_allocation: dict[str, list[str]] = {}   # 区域 → content_refs（split/compare/steps）
    style: dict[str, Any] = {}            # font_tier: default|compact|spacious; gap_scale: 0.8..1.5; highlight: bool
    visual_region: VisualPlacement | None = None
    rationale: str = ""
```

- `_ensure_executable_layout`（`pipeline.py:381`）改为：**校验 directive → 引擎编译 → `PageLayoutSpec`**。
- LLM 不携带文字：引擎编译的 textbox 文字**永远来自 `semantic_text_refs`**（`backend/app/agent/slide_rendering.py:90-108`），`bind_content_refs` 的权威覆盖继续保留。
- `layout_slide_batch`、`render_coverage` 门禁原样保留。

## 9. 视觉自检（几何蓝图图）

**目的**：弥补「审美层无任何规则能判断」（留白是否平衡、是否单调），并给修复环带来定向反馈。

1. 新工具 `render_geometry_preview(slide_id)`：用 PIL 把该页 `LayoutZones` + 元素（文本框矩形+文字、视觉槽、区域边界）按 13.333:7.5 比例画成 PNG——**蓝图图**。不依赖 LibreOffice。
2. 视觉模型看图 + `LayoutDirective` + 内容快照 → 结构化 `ReviewVerdict`：

```python
class ReviewVerdict(BaseModel):
    pass: bool
    issues: list[ReviewIssue]
    # ReviewIssue: {kind, severity, description, suggested_preset, suggested_param}
    # kind ∈ {overflow,overlap,cramped,wasted_space,misaligned,content_changed,monotonous}
```

3. 失败时：几何类 → 引擎换参重编译（§11）；审美类 → 把「上一版失败原因 + 一个正确示例」回给 LLM 换版式。
4. **降级**：模型无视觉能力（ModelConfig 无 vision）或渲染失败 → 跳过视觉层，退回确定性规则 QA。
5. **可选增强**：LibreOffice 可用时用 `convert_pptx_to_images` 生成真实截图代替蓝图图（两级降级，不影响主设计）。

## 10. QA 规则补齐（`qa_tools.py`）

补齐 `run_geometry_qa` 的洞，全部以 `LayoutZones` 为参照：

- `geometry.title_in_rail` — 标题框必须落在标题轨
- `geometry.min_margin` / `geometry.min_gap` — 执行 `spatial_rules` 的 0.5in 边距、0.3in 间距（现只查重叠不查间隙）
- `layout.column_balance` — 正文列右半留白指标，专抓「占满高度但右侧空」
- `layout.monotony` — 新布局几何哈希 == 旧布局 → 判「无实际变化」
- 去掉 `len(text_items) >= 3` 才查空间分布的空洞（`qa_tools.py:85`）：任何含正文的页面都查
- LibreOffice 可用时把 `convert_pptx_to_images` 真正接入 `run_qa`（像素级裁剪/溢出），不可用则保持 `degraded` 降级标记

## 11. 收敛性修复（`runtime.py` 修订环）

按失败类别分派：

- **几何类**（`geometry.overlap / out_of_bounds / text_overflow / vertical_underuse / cluster_cramming / column_balance / min_margin / min_gap`）→ **确定性路径**：引擎按规则换参重编译（缩字号档、加大间距、换版式），必然收敛，不烧 LLM 调用。
- **审美类**（视觉自检不达标 / 用户明确不满意）→ **LLM 路径**：回传失败原因 + 正确示例，换预设重选，限 1-2 次。
- 轮数上限维持 3，但几何类在引擎下收敛，不再依赖模型「运气」。

## 12. 内容保护与知识注入

### 内容保护
现有 `content_policy=preserve` + `render_coverage` + `semantic_content_changed` 门禁已把「内容被改」挡在发布前（`runtime.py:627-660`）。本设计保留并强化：
- `bind_content_refs` 继续用权威文字覆盖 LLM 措辞；
- 引擎编译的 textbox 文字永远来自 `semantic_text_refs`，`LayoutDirective` 不携带文字；
- 新增端到端测试证明 LAYOUT_ONLY 下逐字不变。

### 知识注入修复
- 布局 agent 系统提示**内嵌紧凑版版式库 + LayoutZones 定义**（独立块，不走 6000 字符截断路径）。
- 修复 `knowledge.json` 注入：提升 knowledge 块预算，或拆成多个独立块，保证 `typography` / `ppt_skills` 可达。
- `get_knowledge_base` 工具结果单独提上限，允许 layout agent 按需拉全文。

## 13. 前端（范围选择 + 修复原因展示）

- **修 bug**：单页「修改本页」路径补 `selected_slide_ids`（`AgentPipelineWorkbench.vue:224-227`）。
- **范围选择 UI**：Composer 顶部加三段选择「只改布局 / 只改文字 / 只改图片」，随请求发 `modality` 字段（`CreateRunRequest` 扩展，`backend/app/api/v1/ppt_agent.py`），后端用它覆盖/引导意图推断。
- **修复原因展示**：后端把每页 repair/QA 详情（`repair.started` 的 issues、`qa.issue`）**持久化到 slide 修订记录**；胶片上加「本页被修复 / QA 拦截」徽标，点击展开严重级/规则/建议面板。
- 教师气泡里 `[针对第 N 页]` 前缀统一剥离（`useAgentStream.ts:200`）。

## 14. 测试与验收

### 新增端到端测试（`backend/tests/test_ppt_polish.py`）
1. `test_layout_only_distributes_body_and_preserves_text` — 「润色页面分布」→ LAYOUT_ONLY → 正文纵向铺满、条距≥0.3、逐字保留
2. `test_engine_never_overlaps_or_overflows` — 每个 preset × 每类 page_type 的黄金几何不变量（边界内、无重叠、无溢出）
3. `test_preserve_run_cannot_change_text` — LLM 试图改词的润色被权威文字覆盖
4. `test_polish_produces_meaningful_change` — 几何哈希变化断言（单调性）
5. `test_vision_review_catches_cramped_layout` — 蓝图图自检发现「窄条竖排」并驱动收敛
6. 回归：现有 154 测试保持绿

### 人工抽查工具（`scripts/polish_eval.py`）
跑一组真实润色指令（含「页面分布」、溢出、重叠、单调），渲染每页 before/after 蓝图图 + 截图，输出 Markdown 报告（每页：指令 / 意图 / 版式 / QA / 自检 / 结论），供逐页判定合格率。

## 15. 实施阶段

| 阶段 | 内容 | 关键文件 |
|---|---|---|
| 1 | LayoutZones + 预设库 + 引擎（纯函数 TDD） | `layouts/zones.py` `presets.py` `engine.py` + 测试 |
| 2 | LayoutDirective + `_ensure_executable_layout` 编译 + LLM 提示词改造 | `schemas.py` `pipeline.py` `layout.py` |
| 3 | 结构化意图提取 + 降级 + 前端 bug 修复 | `intents.py` `runtime.py` `ppt_agent.py` Composer |
| 4 | QA 补规则 + 蓝图图工具 | `qa_tools.py` `render_geometry_preview` |
| 5 | 视觉自检 + 收敛修复 | `runtime.py` 修订环、layout agent |
| 6 | 知识注入修复 | `context.py` `layout.py` 系统提示 |
| 7 | 端到端测试 + 抽查工具 | `test_ppt_polish.py` `scripts/polish_eval.py` |
| 8 | 前端范围选择 + 修复原因展示 | `ppt_agent.py` Composer/胶片/API |

每阶段通过相关单测、后端全量测试、前端测试、TypeScript 检查与构建。

## 16. 风险与权衡

| 风险 | 缓解 |
|---|---|
| 固定预设库限制创意 | 预设库为可扩展目录；每模板可注册专属 preset；后续可加「受限自定义」 |
| 视觉自检依赖模型视觉能力 + 图片质量 | 蓝图图几何自检无环境依赖；无 vision 时自动降级到规则 QA |
| 意图提取新增 1 次 LLM 调用/run | 与润色质量收益相比可接受；失败自动降级关键词 |
| 改动面大（backend + frontend） | 分 8 阶段，每阶段独立可测；阶段 1-2 落地后「挤成一团」即从源头消失 |
| 旧路径（`_compile_layout_from_analysis` 等）并存 | 阶段 2 让新旧路径共用引擎编译，逐步收敛到单一路径 |

## 17. 非目标（本次不做）

- 不引入新的数据库迁移（slide 修订记录的扩展尽量复用现有字段或轻量追加）。
- 不做像素级 LibreOffice QA 的强制依赖（保持两级降级）。
- 不重构模板文件本身；`LayoutZones` 通过模板配置驱动，但不重写 `templates/PPT_template/*.pptx`。
