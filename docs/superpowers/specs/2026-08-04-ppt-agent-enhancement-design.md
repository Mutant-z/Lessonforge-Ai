# PPT Agent 强化设计（Agent 提示词/知识层）

- 日期：2026-08-04
- 范围：仅强化「Agent 提示词/知识层」维度；不改 Slide Schema、不改渲染器、本次不接入质量闭环
- 方案：方案 B —— v2 专属系统提示词 + 结构化 PPT 设计知识库（单一事实源，既注入提示又供规则检查读取）

## 1. 背景与差距诊断

PPT Agent 当前通过通用 v1 系统提示词 + 单薄的四组 profile 要求生成 PPT 页面方案，与 task_sheet / exercise / video_script 三个已升级 v2 的 Agent 相比存在五处差距：

1. **无 v2 专属提示词**：`TEMPLATE_SPECS` 中 `ppt_agent` 仍走通用 `SYSTEM_TEMPLATE`，无角色边界、叙事规则、自检清单
2. **Profile 要求单薄**：PPTProfile 仅 4 组一句话规则，未覆盖版式、字体、图示、视觉建议维度
3. **无设计知识库**：密度上限、版式库、图示指导等 PPT 设计知识散落或缺失，Agent 无法系统性遵循
4. **Mock 生成器不符合设计规则**：speaker_notes 固定模板句、visual_suggestion 模糊、正文可能超密度上限
5. **无 PPT 质检规则**：quality_service 只有视频脚本对 PPT 的交叉引用检查

## 2. 架构约束（决定注入通道）

- 系统提示词只允许 `{{agent_name}}` 与 `{{agent_context_json}}` 两个占位符（`agent_prompt_service.py` 的 `active_prompt_template` 强制校验）
- 因此 PPT 设计知识**只能经 `agent_context_json`（profile_context）通道注入**，在 `prepare_profile_prompts` 中合并
- 该注入点与 profile 来源无关：deterministic_bundle（Mock）与 LLM 生成的 AgentInitializationBundle 都自动获得知识库

## 3. 设计

### 3.1 PPT 设计知识库（单一事实源）

新建 `templates/ppt_design/knowledge.json`，结构：

| 区块 | 内容 |
|---|---|
| `version` | 知识库版本号（如 "1.0.0"） |
| `design_principles` | 顶层设计原则（每页一个核心信息层级、标题传达结论、视觉服务于教学目的等） |
| `page_type_guidance` | 11 种页面类型（cover/objectives/scenario/concept/process/exercise/summary/comparison/transition/diagram/case）各自的叙事目标、建议内容、典型版式 |
| `density_limits` | 密度上限：标题 ≤30 字；正文每页 ≤120 字；条目 ≤6 条；单条 ≤25 字；speaker_notes ≥30 字 |
| `layout_library` | 版式库（title/steps/process/split/comparison/bullet/question/exercise/summary/cover），每种版式的适用页面类型与结构 |
| `visual_suggestion_guidelines` | 视觉建议可执行性要求（指明图形类型、位置与信息关系） |
| `diagram_guidance` | 5 类图示指导（流程/对比/因果/层级/数据变化），指明抽象关系应配哪种图示 |
| `quality_checklist` | 输出前自检清单（叙事完整、密度达标、版式匹配、视觉可执行、时长合理） |

密度上限的取值依据渲染器实际容量（`pptx_renderer.py`：正文 21pt、文本框 3.85" 高、最多 6 条），非拍脑袋。

同一 JSON 同时服务两个消费方：

1. **注入 Agent 提示**：`prepare_profile_prompts` 将知识库 dict 合并进 profile_context 的 `ppt_design_knowledge` 区块，随 `{{agent_context_json}}` 注入
2. **规则检查读取**：评估工具与测试读取同一文件执行规则检查

### 3.2 v2 专属系统提示词

`agent_prompt_service.py` 新增 `PPT_SYSTEM_TEMPLATE_V2`，四段式结构（仿 VIDEO_SCRIPT_SYSTEM_TEMPLATE_V2）：

1. **角色与职责边界**：只负责 PPT 页面方案，不修改其他交付物；先读已批准蓝图与教学设计建立目标—环节—页面映射
2. **叙事与结构规则**：按导入→建构→应用→总结组织页面；每页一个核心信息层级；标题传达结论
3. **设计知识引用**：引用 `agent_context_json` 中 `ppt_design_knowledge` 区块（密度上限、版式库、图示指导）
4. **输出前自检清单**：对照知识库 quality_checklist 检查

接线改动（`ensure_prompt_templates`）：

- 第 99-104 行新增 `if agent_type == "ppt_agent": versions.append(("v2", PPT_SYSTEM_TEMPLATE_V2, "v2"))`
- 第 119 行 active_version 集合加入 `"ppt_agent"`
- v1 保留为回退版本，存量 profile 不受影响，新初始化自动走 v2

### 3.3 Profile 初始化强化 + 注入机制

**PPTProfile schema 扩充**（`backend/app/schemas/agent_profile.py`）：4 组 → 7 组 requirements：

| 字段 | 变化 | 内容 |
|---|---|---|
| `narrative_requirements` | 扩充 | 按导入→建构→应用→总结组织；页面与教学环节对齐 |
| `visual_hierarchy_requirements` | 扩充 | 每页一个核心信息层级；标题传达结论而非主题 |
| `information_density_requirements` | 扩充 | 遵守知识库密度上限；正文只留关键结论 |
| `animation_and_diagram_requirements` | 扩充 | 抽象关系必须指明图示方式，优先过程动画 |
| `layout_requirements` | 新增 | 每页 layout 必须从该页面类型的版式库中选择 |
| `typography_requirements` | 新增 | 标题/正文层级清晰，避免全页同字号 |
| `visual_suggestion_requirements` | 新增 | 视觉建议可执行，指明图形类型、位置与信息关系 |

同步更新：

- `agent_initialization_service.py` 的 `deterministic_bundle` ppt extras 扩充为有实质内容的规则
- LLM 初始化路径须填充新字段（`AgentInitializationBundle` 的 model_validator 强制所有 `*_requirements` 非空，缺一即报错）

**注入机制**：

```
templates/ppt_design/knowledge.json
        ↓ load_ppt_design_knowledge()（lru_cache，仿 ppt_template_service.load_ppt_template_catalog）
backend/app/services/ppt_knowledge_service.py（新模块）
        ↓ prepare_profile_prompts 中：agent_type == "ppt_agent" 时
        ↓ profile_context["ppt_design_knowledge"] = 知识库 dict
agent_prompt_service.py（注入点，agent_context_json 现有通道）
        ↓
PPT_SYSTEM_TEMPLATE_V2 引用该区块
```

### 3.4 Mock 生成器更新 + 评估工具

**`make_ppt` 更新**（`backend/app/agents/generators.py`）：使其输出成为「知识库规则的确定性范本」——Mock 生成的内容本身能通过全部规则检查：

| 规则 | 现况 | 改后 |
|---|---|---|
| 标题传达结论 | "学习目标""核心概念" | 结论式标题（如"本课学习目标：可观察、可检验"） |
| 每页正文 ≤120 字、≤6 条、单条 ≤25 字 | S04 可能超限 | 按条数/字数约束组织 |
| speaker_notes ≥30 字 | 固定模板句 | 实质性讲解建议（环节目的 + 提问/演示动作） |
| visual_suggestion 可执行 | 模糊描述 | 指明图形类型、位置与信息关系（如"左侧概念框图，右侧关系箭头图，底部留白"） |

**评估工具**（`backend/app/services/ppt_knowledge_service.py` 与 3.3 同一模块）导出：

```python
@dataclass
class RuleViolation:
    slide_id: str
    rule_id: str      # 如 "density.body_chars"、"title.conclusion"
    message: str

def check_ppt_against_knowledge(content) -> list[RuleViolation]
```

**测试**（新建 `backend/tests/test_ppt_knowledge.py`）：

1. 规则检查器单元测试：构造违规/合规样本各若干，验证检查器自身正确
2. Mock 全量断言：`make_ppt` 对任意 blueprint 的输出 0 违规（确定性，CI 常跑）
3. v1 vs v2 对比评测（env 门控）：设置 `PPT_EVAL_API_KEY` 时运行——同一批课程分别用 v1/v2 系统提示词调真实 provider，统计两版命中率与违规数对比；未设置时跳过，不阻塞 CI

## 4. 验收标准

1. **规则检查**：知识库规则可由 `check_ppt_against_knowledge` 逐项检查；Mock 输出 0 违规
2. **对比评测**：v1/v2 同批课程对比，v2 命中率 ≥ v1（以规则命中数衡量）
3. **回归**：现有后端测试全绿；v1 回退路径可用
4. **文档**：设计文档入库，知识库版本号可追溯

## 5. 明确不做（范围边界）

- 不改 Slide Schema（11 种 page_type 不变）
- 不改 PPTX 渲染器（不改版式/字号/容量）
- 本次不接入 quality_service 质检闭环（规则检查器预留位置，后续接入）
