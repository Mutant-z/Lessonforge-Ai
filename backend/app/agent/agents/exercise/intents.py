"""课后练习意图协议。

意图枚举：
GENERATE / STRUCTURE_EDIT / QUESTION_EDIT / SCORING_ADJUST / TIMING_ADJUST /
ALIGNMENT_REPAIR / VISUAL_EDIT / SYNC_CONTEXT / QA_ONLY。

路由规则：
- 首次生成：调研 → 架构 → 设计 → 评分 → 视觉 → 质询 → 终稿。
- 结构调整（增删分区/题组）：意图 → 调研 → 架构 → 设计 → 评分 → 终稿。
- 内容/评分/用时/对齐/视觉修改：意图 → 调研 → 对应角色 → 评分 → 终稿。
- 只读质询（QA_ONLY）：质询 → 终稿（发布门禁不创建新版本）。
- 上下文同步：调研 → 设计 → 评分 → 终稿。

意图置信度低于 0.65、目标无法解析、指令冲突或包含删除操作时进入人工确认。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

ExerciseIntent = Literal[
    "GENERATE",
    "STRUCTURE_EDIT",
    "QUESTION_EDIT",
    "SCORING_ADJUST",
    "TIMING_ADJUST",
    "ALIGNMENT_REPAIR",
    "VISUAL_EDIT",
    "SYNC_CONTEXT",
    "QA_ONLY",
]


class ExerciseIntentDecision(BaseModel):
    """intent_planner 的强类型产物。"""

    intent: ExerciseIntent = "QUESTION_EDIT"
    target_question_ids: list[str] = Field(default_factory=list, description="受影响的题目（question/sub_question）ID")
    target_section_ids: list[str] = Field(default_factory=list, description="受影响的练习分区 ID（三区固定）")
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
    operation: Literal["edit_questions", "ensure_question_type_count", "move_question"] = "edit_questions"
    destination_section_id: str | None = None
    question_type: str | None = None
    target_count: int | None = Field(default=None, ge=0)
    count_mode: Literal["exact"] | None = None
    mutation_mode: Literal["add_only", "delete_excess"] | None = None
    preserve_section_scores: bool = True
    allowed_section_ids: list[str] = Field(default_factory=list)
    current_count: int | None = Field(default=None, ge=0)
    requested_delta: int | None = None
    delete_position: Literal["last"] | None = None
    delete_question_ids: list[str] = Field(default_factory=list)

    @property
    def mutates_document(self) -> bool:
        return self.intent in MUTATING_INTENTS


# 结构调整型意图
STRUCTURAL_INTENTS = {"STRUCTURE_EDIT"}
# 破坏性意图（删除分区/题目/题组等）
DESTRUCTIVE_INTENTS = {"STRUCTURE_EDIT", "QUESTION_EDIT"}
# 修改文档内容的意图（会创建新版本）
MUTATING_INTENTS = {
    "GENERATE", "STRUCTURE_EDIT", "QUESTION_EDIT", "SCORING_ADJUST",
    "TIMING_ADJUST", "ALIGNMENT_REPAIR", "VISUAL_EDIT", "SYNC_CONTEXT",
}
# 低置信度阈值
CONFIDENCE_THRESHOLD = 0.65

# 意图 → 角色链
# scoring_guard 只出现在明确的分值/用时调整意图中；其他所有内容修改意图
# 直接由 question_designer 完成并由 finalizer 做确定性校验兜底，避免
# scoring_guard 在批量编辑场景（新增题目/补充多选题等）陷入空转循环。
INTENT_AGENTS: dict[str, list[str]] = {
    "GENERATE": [
        "context_researcher", "exercise_architect", "question_designer",
        "visual_specifier", "exercise_qa", "finalizer",
    ],
    "STRUCTURE_EDIT": [
        "intent_planner", "context_researcher", "exercise_architect",
        "question_designer", "finalizer",
    ],
    "QUESTION_EDIT": [
        "intent_planner", "context_researcher", "question_designer",
        "finalizer",
    ],
    "SCORING_ADJUST": [
        "intent_planner", "context_researcher", "scoring_guard", "finalizer",
    ],
    "TIMING_ADJUST": [
        "intent_planner", "context_researcher", "scoring_guard", "finalizer",
    ],
    "ALIGNMENT_REPAIR": [
        "intent_planner", "context_researcher", "question_designer", "finalizer",
    ],
    "VISUAL_EDIT": [
        "intent_planner", "context_researcher", "visual_specifier", "finalizer",
    ],
    "SYNC_CONTEXT": ["context_researcher", "question_designer", "finalizer"],
    "QA_ONLY": ["exercise_qa", "finalizer"],
}

INTENT_AGENT_ALIASES = {
    "qa": "exercise_qa",
    "quality": "exercise_qa",
    "designer": "question_designer",
    "editor": "question_designer",
    "architect": "exercise_architect",
    "structure": "exercise_architect",
    "scoring": "scoring_guard",
    "score": "scoring_guard",
    "visual": "visual_specifier",
    "image": "visual_specifier",
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
    (("分区", "题组结构", "重组", "调整结构", "新增分区", "删除分区", "新增题组", "删除题组"), "STRUCTURE_EDIT"),
    (("对齐", "覆盖", "目标映射", "知识点", "环节", "一致性"), "ALIGNMENT_REPAIR"),
    (("分值", "分数", "评分点", "评分标准", "总分"), "SCORING_ADJUST"),
    (("用时", "时长", "时间", "答题时间"), "TIMING_ADJUST"),
    (("图片", "配图", "图示", "图表", "视觉"), "VISUAL_EDIT"),
    (("题目", "题干", "选项", "答案", "解析", "难度", "题型", "删除", "删掉"), "QUESTION_EDIT"),
]

# 删除/解绑等高风险操作标记 → 必须人工确认
DESTRUCTIVE_MARKERS = ("删除", "移除", "去掉", "删掉", "解绑", "取消绑定", "合并分区")

_CHINESE_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_QUESTION_TYPE_MARKERS = {
    "多选题": "multiple_choice",
    "多项选择题": "multiple_choice",
    "单选题": "single_choice",
    "单项选择题": "single_choice",
    "判断题": "true_false",
    "填空题": "fill_blank",
    "多选": "multiple_choice",
    "单选": "single_choice",
}

_COUNT_ADD_MARKERS = ("补充", "增加", "添加", "扩充")
_COUNT_REDUCE_MARKERS = ("缩减", "减少", "删减", "减到", "缩到", "只保留", "保留到")

_SECTION_ALIASES = {
    "基础巩固区": "basic_consolidation",
    "基础巩固": "basic_consolidation",
    "理解应用区": "understanding_application",
    "理解应用": "understanding_application",
    "迁移挑战区": "transfer_challenge",
    "迁移挑战": "transfer_challenge",
}


def _parse_move_question_intent(
    instruction: str,
    available_question_ids: list[str] | None,
) -> ExerciseIntentDecision | None:
    """Resolve a displayed question ordinal to its real stable ID.

    The preview numbers questions from their current document order.  After a
    structure edit, the tenth displayed question is not necessarily ``ex_10``;
    ``available_question_ids`` is deliberately supplied in preview order so the
    ordinal must index that sequence instead of being guessed from an ID suffix.
    """
    if not any(marker in instruction for marker in ("放到", "移到", "移动到", "归入", "归属", "放入")):
        return None
    destination = next(
        (section_id for label, section_id in _SECTION_ALIASES.items() if label in instruction),
        None,
    )
    if destination is None:
        return None
    match = re.search(r"第\s*([0-9]+|[一二两三四五六七八九十])\s*(?:道|个)?题", instruction)
    if match is None:
        return None
    raw = match.group(1)
    number = int(raw) if raw.isdigit() else _CHINESE_NUMBERS.get(raw)
    if number is None:
        return None
    ordered_ids = available_question_ids or []
    if number < 1 or number > len(ordered_ids):
        return None
    question_id = str(ordered_ids[number - 1])
    return ExerciseIntentDecision(
        intent="STRUCTURE_EDIT",
        target_question_ids=[str(question_id)],
        target_section_ids=[destination],
        structural=True,
        destructive=False,
        confidence=1.0,
        operation="move_question",
        destination_section_id=destination,
        preserve_section_scores=False,
        summary=f"将 {question_id} 移入 {destination}",
        plan_steps=["读取既有题目", "原子移动题目并重算分区分值", "验证目标分区与总分"],
        acceptance_criteria=[
            f"{question_id} 位于 {destination}",
            "题目内容、答案和题目分值不变",
            "分区分值与题目之和一致且总分仍为 100",
        ],
        rationale="deterministic-displayed-ordinal-question-move",
    )


def _parse_target_count(instruction: str) -> tuple[str, int, str] | None:
    """Parse explicit exact question-type cardinality requests deterministically."""
    question_type = next(
        (value for marker, value in _QUESTION_TYPE_MARKERS.items() if marker in instruction),
        None,
    )
    if question_type is None:
        return None
    add_requested = any(marker in instruction for marker in _COUNT_ADD_MARKERS)
    reduce_requested = any(marker in instruction for marker in _COUNT_REDUCE_MARKERS)
    exact_requested = any(marker in instruction for marker in ("只要", "我要有", "需要有", "保持", "目标", "最终", "一共", "共", "总共"))
    if not (add_requested or reduce_requested or exact_requested):
        return None
    number = r"([0-9]+|[一二两三四五六七八九十])"
    # Target-language beats observed-current-language.  For example, in
    # “现在有六道多选，但是我只要五道” the target is five, not six.
    match = re.search(
        rf"(?:只要|目标(?:是|为)?|最终(?:要|保留|保持)?|缩减到|缩到|减少到|减到|删减到|保留到|保持为)\s*{number}\s*(?:道|个)?题?",
        instruction,
    )
    if match is None:
        match = re.search(
            rf"(?:我要有|需要有|应有|共|总共|一共|到|至)\s*{number}\s*(?:道|个)?题?",
            instruction,
        )
    if match is None:
        marker_pattern = "|".join(sorted(map(re.escape, _QUESTION_TYPE_MARKERS), key=len, reverse=True))
        match = re.search(
            rf"([0-9]+|[一二两三四五六七八九十])\s*(?:道|个)?\s*(?:{marker_pattern})",
            instruction,
        )
    if match is None:
        return None
    raw = match.group(1)
    count = int(raw) if raw.isdigit() else _CHINESE_NUMBERS.get(raw)
    if count is None:
        return None
    mode = "delete_excess" if reduce_requested else "add_only"
    return question_type, count, mode


def normalize_count_intent(
    decision: ExerciseIntentDecision,
    instruction: str,
    *,
    current_type_counts: dict[str, int] | None = None,
) -> ExerciseIntentDecision:
    """Make an explicit type-cardinality request authoritative over LLM routing."""
    parsed = _parse_target_count(instruction)
    if parsed is None:
        return decision
    question_type, target_count, requested_mode = parsed
    current_count = int((current_type_counts or {}).get(question_type, 0))
    positional_delete = bool(
        any(marker in instruction for marker in ("删除", "删掉", "去掉", "移除"))
        and re.search(r"最后\s*(?:一|1)?\s*(?:道|题)", instruction)
    )
    decision.intent = "QUESTION_EDIT"
    decision.structural = False
    explicit_reduction = positional_delete or (requested_mode == "delete_excess" and current_count > target_count)
    if positional_delete:
        # An explicit object-level command outranks the aggregate count phrase.
        # Runtime resolves the last matching stable ID from the authoritative Builder.
        target_count = max(0, current_count - 1)
    decision.destructive = explicit_reduction
    decision.requires_confirmation = current_count > target_count and not explicit_reduction
    decision.clarification_question = (
        f"当前已有 {current_count} 道该题型，超过目标 {target_count} 道；补充指令不会自动删除题目，请明确是否需要删减。"
        if decision.requires_confirmation else None
    )
    decision.operation = "ensure_question_type_count"
    decision.question_type = question_type
    decision.target_count = target_count
    decision.count_mode = "exact"
    decision.mutation_mode = "delete_excess" if explicit_reduction else "add_only"
    decision.preserve_section_scores = True
    decision.current_count = current_count
    decision.requested_delta = target_count - current_count
    decision.delete_position = "last" if positional_delete else None
    decision.delete_question_ids = []
    decision.target_question_ids = []
    action = (
        "删除最后一道目标题型并原子重平衡所在分区分值"
        if positional_delete else
        f"只删除 {-decision.requested_delta} 道多余题目"
        if decision.requested_delta < 0 else f"只新增 {decision.requested_delta} 道目标题型"
    )
    decision.summary = f"将 {question_type} 精确调整到 {target_count} 道"
    decision.plan_steps = ["读取当前候选稿题型统计", action, "验证精确数量与分值守恒"]
    decision.acceptance_criteria = [
        f"{question_type} 最终恰好 {target_count} 道",
        "不转换已有题型，且只在明确缩减时删除多余目标题型",
        "保留原分区分值并保持总分 100",
    ]
    decision.rationale = "deterministic-question-type-count"
    return decision


def _confirm_decision(intent: str, instruction: str, *, reason: str, confidence: float) -> ExerciseIntentDecision:
    return ExerciseIntentDecision(
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


def _fallback_intent(instruction: str, mode: str | None = None, selected: list[str] | None = None) -> ExerciseIntentDecision:
    """关键字/确定性兜底路由。"""
    if mode == "structure":
        return ExerciseIntentDecision(
            intent="STRUCTURE_EDIT", structural=True, destructive=True,
            confidence=0.8, target_section_ids=selected or [],
            plan_steps=["读取当前练习", "调整分区或题组结构", "验证分值守恒"],
            acceptance_criteria=["结构变化已应用", "总分仍为 100"],
            summary="重组练习结构", rationale="deterministic-fallback",
        )
    if mode == "content":
        return ExerciseIntentDecision(
            intent="QUESTION_EDIT", confidence=0.8, target_section_ids=selected or [],
            plan_steps=["读取当前练习", "修改题目内容", "验证语义"],
            acceptance_criteria=["内容已更新", "QA 通过"], summary="修改练习内容", rationale="deterministic-fallback",
        )
    if mode == "scoring":
        return ExerciseIntentDecision(
            intent="SCORING_ADJUST", confidence=0.8, target_section_ids=selected or [],
            plan_steps=["读取当前练习", "调整分值", "验证分值守恒"],
            acceptance_criteria=["分值已调整", "总分仍为 100"], summary="调整练习分值", rationale="deterministic-fallback",
        )
    if mode == "timing":
        return ExerciseIntentDecision(
            intent="TIMING_ADJUST", confidence=0.8, target_section_ids=selected or [],
            plan_steps=["读取当前练习", "调整答题用时", "验证时长一致"],
            acceptance_criteria=["用时已调整", "QA 通过"], summary="调整答题用时", rationale="deterministic-fallback",
        )
    if mode == "visual":
        return ExerciseIntentDecision(
            intent="VISUAL_EDIT", confidence=0.8, target_section_ids=selected or [],
            plan_steps=["读取当前练习", "调整视觉材料", "验证等价替代"],
            acceptance_criteria=["视觉材料已更新", "QA 通过"], summary="调整视觉材料", rationale="deterministic-fallback",
        )
    if mode == "qa":
        return ExerciseIntentDecision(intent="QA_ONLY", confidence=1.0, summary="仅质量检查", rationale="deterministic-fallback")
    lowered = instruction
    destructive = any(marker in lowered for marker in DESTRUCTIVE_MARKERS)
    for markers, intent in KEYWORD_INTENTS:
        if any(marker in lowered for marker in markers):
            if destructive and intent != "STRUCTURE_EDIT":
                return _confirm_decision(intent, instruction, reason="destructive-keyword", confidence=0.6)
            return ExerciseIntentDecision(
                intent=intent,  # type: ignore[arg-type]
                structural=intent in STRUCTURAL_INTENTS,
                destructive=destructive,
                confidence=0.8 if not destructive else 0.6,
                target_section_ids=selected or [],
                plan_steps=["读取当前练习", "执行修改", "验证语义"],
                acceptance_criteria=["QA 通过"],
                summary=f"识别为 {intent}", rationale="deterministic-fallback",
            )
    if destructive:
        return _confirm_decision("QUESTION_EDIT", instruction, reason="destructive-default", confidence=0.55)
    return ExerciseIntentDecision(
        intent="QUESTION_EDIT", confidence=0.55, target_section_ids=selected or [],
        plan_steps=["读取当前练习", "修改内容", "验证语义"],
        acceptance_criteria=["内容已更新", "QA 通过"], summary="修改练习内容", rationale="deterministic-default",
    )


async def infer_exercise_intent(
    provider,
    trigger_type: str,
    instruction: str,
    selected_section_ids: list[str] | None = None,
    mode: str | None = None,
    available_question_ids: list[str] | None = None,
    current_type_counts: dict[str, int] | None = None,
) -> ExerciseIntentDecision:
    """识别意图：initial 确定性 GENERATE；message 走 LLM，失败回退确定性路由。

    available_question_ids 按当前卷面显示顺序提供真实题目 ID，既用于把“第 N 题”
    解析成稳定 ID，也用于过滤 LLM 编造的 target_question_ids。
    """
    if trigger_type == "sync_context":
        return ExerciseIntentDecision(
            intent="SYNC_CONTEXT", confidence=1.0,
            plan_steps=["读取最新项目上下文", "同步练习内容", "验证语义"],
            acceptance_criteria=["上下文已同步", "QA 通过"],
            summary="同步最新项目上下文", rationale="deterministic-sync",
        )
    if trigger_type != "message" or not instruction:
        return ExerciseIntentDecision(
            intent="GENERATE", structural=True, confidence=1.0,
            plan_steps=["读取课程蓝图与上下文", "生成三区练习", "验证语义"],
            acceptance_criteria=["练习含三区/计分题/评分点", "总分 100"],
            summary="首次生成完整课后练习", rationale="deterministic-initial",
        )
    move_decision = _parse_move_question_intent(instruction, available_question_ids)
    if move_decision is not None:
        return move_decision
    if provider is None or provider.__class__.__name__ == "MockProvider":
        return normalize_count_intent(
            _fallback_intent(instruction, mode, selected_section_ids),
            instruction,
            current_type_counts=current_type_counts,
        )
    system = (
        "你是 LessonForge AI 课后练习 Agent 的意图规划器。判断教师指令属于哪类意图：\n"
        "GENERATE（生成全新课后练习）/ STRUCTURE_EDIT（增删、重排、调整分区或题组结构）/\n"
        "QUESTION_EDIT（修改题目：题干/选项/答案/解析/评分点/难度/题型）/\n"
        "SCORING_ADJUST（调整题目或分区分值，保持总分 100）/\n"
        "TIMING_ADJUST（调整答题用时）/ ALIGNMENT_REPAIR（目标/知识点/环节映射对齐）/\n"
        "VISUAL_EDIT（修改视觉材料：图示/配图/降级替代）/ SYNC_CONTEXT（同步最新项目上下文）/\n"
        "QA_ONLY（仅质量检查或回答问题）。\n"
        "只返回符合 Schema 的 JSON，不展示隐藏推理。分区/题组调整（STRUCTURE_EDIT）只应在指令"
        "明确要求增删/重排/合并分区或题组时选择；普通题目修改不选择它。\n"
        "规则：删除等破坏性操作 → destructive=true 且 requires_confirmation=true；"
        "置信度低于 0.65 或目标题目无法解析 → requires_confirmation=true。"
    )
    prompt = (
        f"教师指令：\n{instruction}\n"
        f"用户选中的分区：{selected_section_ids or '无'}\n"
        f"用户显式模式：{mode or 'auto'}\n"
        f"当前练习按卷面显示顺序排列的题目 ID（target_question_ids 必须从中选择，不得编造新的 ID）："
        f"{available_question_ids or '无（尚未生成或不可用）'}\n"
        "输出 intent / target_question_ids / target_section_ids / affected_json_paths / "
        "structural / destructive / confidence / summary / requires_confirmation / "
        "clarification_question / assumptions / plan_steps / acceptance_criteria / rationale。"
        "只有 QA_ONLY 时意图不修改文档。"
    )
    try:
        decision = await provider.structured(system, prompt, ExerciseIntentDecision)
        if available_question_ids:
            allowed = set(available_question_ids)
            decision.target_question_ids = [
                item for item in decision.target_question_ids if item in allowed
            ]
        return normalize_count_intent(decision, instruction, current_type_counts=current_type_counts)
    except Exception:  # noqa: BLE001  意图识别失败回退确定性路由
        return normalize_count_intent(
            _fallback_intent(instruction, mode, selected_section_ids),
            instruction,
            current_type_counts=current_type_counts,
        )


def agent_chain_for_intent(intent: str, trigger_type: str) -> list[str]:
    if trigger_type == "sync_context":
        return INTENT_AGENTS["SYNC_CONTEXT"]
    return INTENT_AGENTS.get(intent, INTENT_AGENTS["QUESTION_EDIT"])
