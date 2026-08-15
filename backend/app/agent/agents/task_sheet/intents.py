"""学习任务单意图协议。

意图枚举（与方案文档一致）：
GENERATE / TASK_EDIT / STRUCTURE_EDIT / TIMING_ADJUST / ALIGNMENT_REPAIR /
SCAFFOLD_EDIT / RECORDING_EDIT / SYNC_CONTEXT / QA_ONLY。

路由规则（方案 §2.1）：
- 首次生成：调研 → 架构 → 设计 → 终稿。
- 结构调整：意图 → 调研 → 架构 → 设计 → 终稿。
- 内容/支架/记录表/时间/对齐修改：意图 → 调研 → 设计 → 终稿。
- 只读质询（QA_ONLY）：终稿渲染（发布门禁不创建新版本）。
- 上下文同步：调研 → 设计 → 终稿。

QA 门禁已移除：链中不再包含 task_sheet_qa 角色，修改完成后直接发布；
结构安全校验仍由发布门禁承担（TaskSheetContentV3 结构非法时保留原版）。

意图置信度低于 0.65、目标任务无法解析、指令互相冲突或包含删除操作时进入人工确认。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TaskSheetIntent = Literal[
    "GENERATE",
    "TASK_EDIT",
    "STRUCTURE_EDIT",
    "TIMING_ADJUST",
    "ALIGNMENT_REPAIR",
    "SCAFFOLD_EDIT",
    "RECORDING_EDIT",
    "SYNC_CONTEXT",
    "QA_ONLY",
]


class TaskSheetIntentDecision(BaseModel):
    """intent_planner 的强类型产物（方案 §2.2）。"""

    intent: TaskSheetIntent = "TASK_EDIT"
    target_task_ids: list[str] = Field(default_factory=list, description="受影响的任务（learning_task Block）ID")
    target_phases: list[str] = Field(default_factory=list, description="受影响的教学环节（stage_id）")
    affected_json_paths: list[str] = Field(default_factory=list)
    structural: bool = False
    destructive: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    summary: str = ""
    requires_confirmation: bool = False
    clarification_question: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    plan_steps: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    rationale: str = ""

    @property
    def mutates_document(self) -> bool:
        return self.intent in MUTATING_INTENTS


# 结构调整型意图
STRUCTURAL_INTENTS = {"STRUCTURE_EDIT"}
# 破坏性意图（删除任务/目标解绑等）
DESTRUCTIVE_INTENTS = {"STRUCTURE_EDIT"}
# 修改文档内容的意图（会创建新版本）
MUTATING_INTENTS = {
    "GENERATE", "TASK_EDIT", "STRUCTURE_EDIT", "TIMING_ADJUST",
    "ALIGNMENT_REPAIR", "SCAFFOLD_EDIT", "RECORDING_EDIT", "SYNC_CONTEXT",
}
# 低置信度阈值
CONFIDENCE_THRESHOLD = 0.65

# 意图 → 角色链（确定性兜底路由，方案 §2.1；QA 门禁已移除，链中不再有 task_sheet_qa）
INTENT_AGENTS: dict[str, list[str]] = {
    "GENERATE": ["context_researcher", "task_architect", "task_designer", "finalizer"],
    "STRUCTURE_EDIT": ["intent_planner", "context_researcher", "task_architect", "task_designer", "finalizer"],
    "TASK_EDIT": ["intent_planner", "context_researcher", "task_designer", "finalizer"],
    "TIMING_ADJUST": ["intent_planner", "context_researcher", "task_designer", "finalizer"],
    "ALIGNMENT_REPAIR": ["intent_planner", "context_researcher", "task_designer", "finalizer"],
    "SCAFFOLD_EDIT": ["intent_planner", "context_researcher", "task_designer", "finalizer"],
    "RECORDING_EDIT": ["intent_planner", "context_researcher", "task_designer", "finalizer"],
    "SYNC_CONTEXT": ["context_researcher", "task_designer", "finalizer"],
    "QA_ONLY": ["finalizer"],
}

INTENT_AGENT_ALIASES = {
    "qa": "task_sheet_qa",
    "quality": "task_sheet_qa",
    "designer": "task_designer",
    "editor": "task_designer",
    "architect": "task_architect",
    "outline": "task_architect",
    "structure": "task_architect",
    "researcher": "context_researcher",
    "planner": "intent_planner",
    "final": "finalizer",
    "finalizer": "finalizer",
    "repair": "repair_router",
}

# 关键字 → 意图（确定性兜底；问题式指令优先判定 QA_ONLY）
KEYWORD_INTENTS: list[tuple[tuple[str, ...], str]] = [
    (("是什么", "为什么", "怎么办", "解释一下", "说明一下", "两者的区别", "是什么意思", "怎么理解", "什么意思", "怎么样"), "QA_ONLY"),
    (("检查", "质量", "问题", "评审", "评价"), "QA_ONLY"),
    (("大纲", "目录", "章节顺序", "重组", "调整结构", "重排", "新增章节", "删除章节", "重命名章节", "调整目录"), "STRUCTURE_EDIT"),
    (("对齐", "覆盖", "环节", "目标映射", "一致性"), "ALIGNMENT_REPAIR"),
    (("支架", "提示卡", "脚手架", "思考支架"), "SCAFFOLD_EDIT"),
    (("记录表", "观察表", "记录单"), "RECORDING_EDIT"),
    (("用时", "时长", "时间"), "TIMING_ADJUST"),
    (("任务", "步骤", "完成标准", "产出"), "TASK_EDIT"),
]

# 删除/解绑等高风险操作标记 → 必须人工确认
DESTRUCTIVE_MARKERS = ("删除", "移除", "去掉", "解绑", "取消绑定", "合并章节", "删除任务")


def _confirm_decision(intent: str, instruction: str, *, reason: str, confidence: float) -> TaskSheetIntentDecision:
    return TaskSheetIntentDecision(
        intent=intent,  # type: ignore[arg-type]
        destructive=any(marker in instruction for marker in DESTRUCTIVE_MARKERS),
        structural=intent in STRUCTURAL_INTENTS,
        confidence=confidence,
        requires_confirmation=True,
        clarification_question="本次修改涉及结构变更或高风险操作，请确认执行范围后再继续。",
        assumptions=["需要教师确认后才能继续执行修改"],
        plan_steps=["等待教师确认", "确认后重新规划"],
        acceptance_criteria=["已获得教师确认"],
        summary=f"需要确认（{reason}）",
        rationale=f"deterministic-confirm:{reason}",
    )


def _fallback_intent(instruction: str, mode: str | None = None, selected: list[str] | None = None) -> TaskSheetIntentDecision:
    """关键字/确定性兜底路由。"""
    if mode == "structure":
        return TaskSheetIntentDecision(
            intent="STRUCTURE_EDIT", structural=True, destructive=True,
            confidence=0.8, target_phases=selected or [],
            plan_steps=["读取当前任务单", "重组目录", "验证语义"],
            acceptance_criteria=["目录变化已应用", "QA 通过"], summary="重组任务单目录", rationale="deterministic-fallback",
        )
    if mode == "content":
        return TaskSheetIntentDecision(
            intent="TASK_EDIT", confidence=0.8, target_phases=selected or [],
            plan_steps=["读取当前任务单", "修改任务内容", "验证语义"],
            acceptance_criteria=["内容已更新", "QA 通过"], summary="修改任务单内容", rationale="deterministic-fallback",
        )
    if mode == "timing":
        return TaskSheetIntentDecision(
            intent="TIMING_ADJUST", confidence=0.8, target_phases=selected or [],
            plan_steps=["读取当前任务单", "调整任务用时", "验证时长一致"],
            acceptance_criteria=["用时已调整", "QA 通过"], summary="调整任务用时", rationale="deterministic-fallback",
        )
    if mode == "qa":
        return TaskSheetIntentDecision(intent="QA_ONLY", confidence=1.0, summary="仅质量检查", rationale="deterministic-fallback")
    lowered = instruction
    destructive = any(marker in lowered for marker in DESTRUCTIVE_MARKERS)
    for markers, intent in KEYWORD_INTENTS:
        if any(marker in lowered for marker in markers):
            if destructive and intent != "STRUCTURE_EDIT":
                return _confirm_decision(intent, instruction, reason="destructive-keyword", confidence=0.6)
            return TaskSheetIntentDecision(
                intent=intent,  # type: ignore[arg-type]
                structural=intent in STRUCTURAL_INTENTS,
                destructive=destructive,
                confidence=0.8 if not destructive else 0.6,
                target_phases=selected or [],
                plan_steps=["读取当前任务单", "执行修改", "验证语义"],
                acceptance_criteria=["QA 通过"],
                summary=f"识别为 {intent}", rationale="deterministic-fallback",
            )
    if destructive:
        return _confirm_decision("TASK_EDIT", instruction, reason="destructive-default", confidence=0.55)
    return TaskSheetIntentDecision(
        intent="TASK_EDIT", confidence=0.55, target_phases=selected or [],
        plan_steps=["读取当前任务单", "修改内容", "验证语义"],
        acceptance_criteria=["内容已更新", "QA 通过"], summary="修改任务单内容", rationale="deterministic-default",
    )


async def infer_task_sheet_intent(
    provider,
    trigger_type: str,
    instruction: str,
    selected_section_ids: list[str] | None = None,
    mode: str | None = None,
) -> TaskSheetIntentDecision:
    """识别意图：initial 确定性 GENERATE；message 走 LLM，失败回退确定性路由。"""
    if trigger_type == "sync_context":
        return TaskSheetIntentDecision(
            intent="SYNC_CONTEXT", confidence=1.0,
            plan_steps=["读取最新项目上下文", "同步任务单内容", "验证语义"],
            acceptance_criteria=["上下文已同步", "QA 通过"],
            summary="同步最新项目上下文", rationale="deterministic-sync",
        )
    if trigger_type != "message" or not instruction:
        return TaskSheetIntentDecision(
            intent="GENERATE", structural=True, confidence=1.0,
            plan_steps=["读取课程蓝图与上下文", "生成动态目录与内容", "验证语义"],
            acceptance_criteria=["任务单含目标/任务/证据/评价", "QA 通过"],
            summary="首次生成完整任务单", rationale="deterministic-initial",
        )
    if provider is None or provider.__class__.__name__ == "MockProvider":
        return _fallback_intent(instruction, mode, selected_section_ids)
    system = (
        "你是 LessonForge AI 学习任务单 Agent 的意图规划器。判断教师指令属于哪类意图：\n"
        "GENERATE（生成全新任务单）/ STRUCTURE_EDIT（增删、重排、重命名、嵌套章节目录或阶段划分）/\n"
        "TASK_EDIT（调整学习任务：步骤/完成标准/产出/任务链）/\n"
        "TIMING_ADJUST（调整任务或环节用时）/ ALIGNMENT_REPAIR（目标/知识点/环节映射对齐）/\n"
        "SCAFFOLD_EDIT（修改思考支架/提示卡）/ RECORDING_EDIT（修改记录表）/\n"
        "SYNC_CONTEXT（同步最新项目上下文）/ QA_ONLY（仅质量检查或回答问题）。\n"
        "只返回符合 Schema 的 JSON，不展示隐藏推理。目录/阶段调整（STRUCTURE_EDIT）只应在指令明确要求"
        "增删/重排/重命名/嵌套章节或调整阶段时选择；普通内容或任务修改不选择它。\n"
        "规则：删除/解绑等破坏性操作 → destructive=true 且 requires_confirmation=true；"
        "置信度低于 0.65 或目标任务无法解析 → requires_confirmation=true。"
    )
    prompt = (
        f"教师指令：\n{instruction}\n"
        f"用户选中的章节：{selected_section_ids or '无'}\n"
        f"用户显式模式：{mode or 'auto'}\n"
        "输出 intent / target_task_ids / target_phases / affected_json_paths / "
        "structural / destructive / confidence / summary / requires_confirmation / "
        "clarification_question / assumptions / plan_steps / acceptance_criteria / rationale。"
        "只有 QA_ONLY 时意图不修改文档。"
    )
    try:
        return await provider.structured(system, prompt, TaskSheetIntentDecision)
    except Exception:  # noqa: BLE001  意图识别失败回退确定性路由
        return _fallback_intent(instruction, mode, selected_section_ids)


def agent_chain_for_intent(intent: str, trigger_type: str) -> list[str]:
    if trigger_type == "sync_context":
        return INTENT_AGENTS["SYNC_CONTEXT"]
    return INTENT_AGENTS.get(intent, INTENT_AGENTS["TASK_EDIT"])


# ---------------------------------------------------------------------------
# 兼容别名（旧版实现沿用旧枚举名；新方案统一使用新枚举）
# ---------------------------------------------------------------------------

#: 旧版类名 → 新版类名（测试与调用方逐步迁移）
TaskSheetIntentPlan = TaskSheetIntentDecision
