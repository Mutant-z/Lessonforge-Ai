# 视频脚本逐字稿 Agent (Script/Verbatim Agent) 升级与润色设计方案

## 1. 概述与背景 (Overview)

LessonForge AI 系统中的“教学设计 Agent (Pedagogy Agent)”具备完善的布鲁姆认知层级划分、教学目标拆解与互动检查点设计能力。相比之下，原有的“视频脚本逐字稿 Agent”侧重于硬编码模板填充与固定时长切片，缺乏教学意图与口播台词的深度结合，且对口语化语速、停顿 (Pause Cue)、字幕对齐的智能化把控不足。

本方案旨在参考教学设计 Agent 的结构化约束与教学目标映射能力，将逐字稿 Agent 升级为**“智能教学主播与多轨时序导演 Agent”**。

---

## 2. 总体架构与三大核心能力 (Architecture & Capabilities)

```
+-----------------------------------------------------------------------------------+
|                            Course Blueprint & PPT Artifact                        |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                        Verbatim Script Agent (逐字稿 Agent)                       |
|                                                                                   |
|  1. 教学动作话术引擎 (Pedagogical Verbal Engine)                                    |
|     - 自动关联 Blueprint 教学动作 (hook, metaphor, misconception, check_in...)     |
|     - 注入表达风格与语气指导 (delivery_tone, emphasis_terms)                     |
|                                                                                   |
|  2. 多轨精确时序对齐器 (Multi-track Timing Controller)                             |
|     - 基于真实口播字数 + 停顿时间动态算精秒级时间轴                                 |
|     - 画面、声音、字幕、互动 Pause Cue 秒级联动                                    |
|                                                                                   |
|  3. 教学合规校验与修复 (Pedagogical Compliance Validator)                           |
|     - 核心概念覆盖度审查                                                          |
|     - 语速与时间上限溢出预警                                                      |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|              Updated VideoScriptContent / VerbatimContent Artifact                |
+-----------------------------------------------------------------------------------+
```

### 2.1 教学动作话术引擎 (Pedagogical Verbal Engine)
将教学蓝图中的学习目标与知识点隐式转化为具体的口播教学动作标记（`PedagogicalActionType`）：
- **hook (导入)**: 用痛点、悬念或真实场景提问切入。
- **metaphor_explain (概念讲解)**: 遇到抽象概念，自动引入生活化隐喻。
- **misconception_alert (易错预警)**: 显式提示常见误区（“90%的学生在这里容易踩坑...”）。
- **check_in (互动检查)**: 抛出具体思考题，并自动插入 2-3 秒思考停顿 Cue。
- **summary_recap (总结)**: 口语化提炼本节精髓。

### 2.2 多轨精确时序对齐 (Multi-track Timing Control)
不再强行平均分配时长。Agent 根据生成的实际口播字数（基于 240 字/分钟标准语速）以及配置的停顿 Cue 时长，动态计算并填充场景的 `start_seconds` 与 `end_seconds`。

---

## 3. Schema 扩展设计 (Schema Enhancements)

在 `backend/app/schemas/artifact.py` 中更新数据结构：

```python
# 新增教学动作标记类别
PedagogicalActionType = Literal[
    "hook",               # 导入勾子 / 激发兴趣
    "objective_guide",    # 目标指引
    "scenario_connect",   # 情境关联
    "metaphor_explain",   # 隐喻/化繁为简讲解
    "misconception_alert",# 常见误区预警
    "step_demonstration", # 步骤示范
    "check_in",           # 启发式检查点
    "summary_recap"       # 总结归纳与升华
]

class VideoAudioTrack(BaseModel):
    narration_text: str = Field(description="完整口播旁白文本")
    pedagogical_action: PedagogicalActionType = Field(
        default="metaphor_explain", 
        description="本句旁白承担的核心教学动作"
    )
    delivery_tone: str = Field(description="朗读语气与节奏指导，如：启发、稳重、生动")
    speaking_rate_cps: float = Field(default=4.0, description="预期语速（字/秒，默认 4.0 对应 240字/分）")
    emphasis_terms: list[str] = Field(default_factory=list, description="需要重音强调的关键词")
    pause_cues: list[PauseCue] = Field(default_factory=list)
    sound_cues: list[SoundCue] = Field(default_factory=list)

class VerbatimSection(BaseModel):
    id: str
    scene_id: str = Field(description="关联的分镜场景 ID，如 VS-01")
    slide_ids: list[str]
    time_range: str = Field(description="时间段标记，如 00:00—00:30")
    pedagogical_action: PedagogicalActionType = Field(description="教学功能动作标记")
    required_text: str = Field(description="核心必须口播的逐字台词")
    optional_text: str = Field(description="针对不同背景学员的扩充/举例旁白")
    key_emphasis: list[str] = Field(default_factory=list, description="台词中的关键词高亮列表")
    word_count: int = Field(description="逐字稿字数")
    estimated_duration_seconds: float = Field(description="根据语速算出的预计口播秒数")
    interaction: str = Field(description="提问或学员互动提示")
```

---

## 4. Prompt 与生成生成链 (Prompt & Agent Execution)

在 `backend/app/prompts/script/v1.md` 放置系统 Prompt，要求 LLM 输出包含语气、重音及教学动作的台词：

- 采用第二人称“你”，增加问答感与互动感。
- 保证句子长度在 15-25 字以内，短句为主。
- 自动按 `narration_len / chars_per_second` 严格校验字数与时间轴契合度。

---

## 5. 前端交互与编辑能力增强 (Frontend UX Updates)

针对 `VideoScriptEditor.vue` 和 `VerbatimSegment.vue`：
1. **教学动作 Badge 交互**：在每个分镜上增加彩色教学动作 Tag，方便教师快速识别该段台词的教学目的。
2. **实时语速/字数计算器**：动态显示当前台词字数与预估秒数，在语速过快（>360字/分）或过慢（<150字/分）时呈黄色/红色预警。
3. **一键按台词对齐时间轴 (Auto-Sync)**：提供前端/后端同步按钮，点击后根据全套台词长度一键自动刷新整条视频的 `start_seconds` 与 `end_seconds`。

---

## 6. 测试与验证计划 (Verification Plan)

1. **单元测试 (`backend/tests/test_script_agent.py`)**：
   - 验证 `recalculate_scene_timelines` 算法能否精准修正重叠与空档。
   - 校验带 `pedagogical_action` 的生成对象符合 Pydantic 规范。
2. **端到端流程验证**：
   - 导入经典蓝图，生成全套逐字稿，确认前端编辑器无报错呈现，字数/时长标记无误。
