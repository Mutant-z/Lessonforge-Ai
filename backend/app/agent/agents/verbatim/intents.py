"""教师逐字稿意图协议。

意图枚举：
GENERATE / SECTION_EDIT / STRUCTURE_EDIT / SCRIPT_EDIT / TONE_EDIT /
TIMING_ADJUST / STYLE_EDIT / INTERACTION_EDIT / SYNC_CONTEXT / QA_ONLY /
ANSWER_ONLY / CLARIFICATION_REQUIRED。

路由规则：
- 首次生成：调研 → 导演（逐段口播）→ 时序 → QA → 终稿。
- 结构调整（新增/移动/删除章节）：意图 → 调研 → 导演 → QA → 终稿。
- 正文/语气/风格/互动修改：意图 → 调研 → 导演 → QA → 终稿。
- 时序调整（语速/停顿/时间轴适配）：意图 → 调研 → 时序 → QA → 终稿。
- QA：QA → 必要返修 → 终稿。上下文同步：调研 → 导演 → QA → 终稿。

普通内容/语气/停顿修改不得选择 STRUCTURE_EDIT；只有明确要求增删/移动/重排
逐字稿章节时才选择。删除章节或解绑场景属于高风险操作，要求人工确认。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

VerbatimIntent = Literal[
    "GENERATE",
    "SECTION_EDIT",
    "STRUCTURE_EDIT",
    "SCRIPT_EDIT",
    "TONE_EDIT",
    "TIMING_ADJUST",
    "STYLE_EDIT",
    "INTERACTION_EDIT",
    "SYNC_CONTEXT",
    "QA_ONLY",
    "ANSWER_ONLY",
    "CLARIFICATION_REQUIRED",
]


class VerbatimIntentDecision(BaseModel):
    """intent_planner 的强类型产物。"""

    intent: VerbatimIntent = "SECTION_EDIT"
    mutates_document: bool = False
    target_section_ids: list[str] = Field(default_factory=list, description="受影响的逐字稿章节 ID（空 = 全局）")
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


# 修改文档内容的意图（会创建新版本）
MUTATING_INTENTS = {
    "GENERATE", "SECTION_EDIT", "STRUCTURE_EDIT", "SCRIPT_EDIT", "TONE_EDIT",
    "TIMING_ADJUST", "STYLE_EDIT", "INTERACTION_EDIT", "SYNC_CONTEXT",
}
# 结构调整型意图（增删/移动/重排章节）
STRUCTURAL_INTENTS = {"STRUCTURE_EDIT"}

# 意图 → 角色链（确定性兜底路由）
INTENT_AGENTS: dict[str, list[str]] = {
    "GENERATE": ["context_researcher", "verbatim_director", "timing_engine", "verbatim_qa", "finalizer"],
    "STRUCTURE_EDIT": ["intent_planner", "context_researcher", "verbatim_director", "verbatim_qa", "finalizer"],
    "SECTION_EDIT": ["intent_planner", "context_researcher", "verbatim_director", "verbatim_qa", "finalizer"],
    "SCRIPT_EDIT": ["intent_planner", "context_researcher", "verbatim_director", "verbatim_qa", "finalizer"],
    "TONE_EDIT": ["intent_planner", "context_researcher", "verbatim_director", "verbatim_qa", "finalizer"],
    "STYLE_EDIT": ["intent_planner", "context_researcher", "verbatim_director", "verbatim_qa", "finalizer"],
    "INTERACTION_EDIT": ["intent_planner", "context_researcher", "verbatim_director", "verbatim_qa", "finalizer"],
    "TIMING_ADJUST": ["intent_planner", "context_researcher", "timing_engine", "verbatim_qa", "finalizer"],
    "SYNC_CONTEXT": ["context_researcher", "verbatim_director", "verbatim_qa", "finalizer"],
    "QA_ONLY": ["verbatim_qa", "finalizer"],
    "ANSWER_ONLY": ["context_researcher", "finalizer"],
    "CLARIFICATION_REQUIRED": ["finalizer"],
}

INTENT_AGENT_ALIASES = {
    "qa": "verbatim_qa",
    "quality": "verbatim_qa",
    "director": "verbatim_director",
    "editor": "verbatim_director",
    "writer": "verbatim_director",
    "timing": "timing_engine",
    "timing_engine": "timing_engine",
    "researcher": "context_researcher",
    "planner": "intent_planner",
    "final": "finalizer",
    "finalizer": "finalizer",
    "repair": "repair_router",
}

# 关键字 → 意图（确定性兜底；问题式指令优先判定 QA_ONLY）
KEYWORD_INTENTS: list[tuple[tuple[str, ...], str]] = [
    (("是什么", "为什么", "怎么办", "解释一下", "说明一下", "两者的区别", "是什么意思", "怎么理解", "多少秒", "几个章节"), "QA_ONLY"),
    (("新增章节", "删除章节", "移动章节", "调整章节顺序", "重排", "重组", "章节顺序"), "STRUCTURE_EDIT"),
    (("语速", "停顿", "时间轴", "时长", "节奏", "太慢", "太快", "压缩", "延长", "重算"), "TIMING_ADJUST"),
    (("语气", "表达", "口吻", "措辞"), "TONE_EDIT"),
    (("整体", "统一", "风格", "批量"), "STYLE_EDIT"),
    (("互动", "提问", "思考提示", "检查"), "INTERACTION_EDIT"),
    (("口播", "台词", "正文", "必讲", "改写", "重写", "更口语", "说", "讲"), "SECTION_EDIT"),
    (("检查", "质量", "问题", "评审", "门禁", "QA", "是否通过"), "QA_ONLY"),
]

# 高风险操作标记 → 必须人工确认
DESTRUCTIVE_MARKERS = ("删除章节", "删除逐字稿", "解绑", "移除章节")


def _confirm_decision(intent: str, instruction: str, *, reason: str, confidence: float) -> VerbatimIntentDecision:
    return VerbatimIntentDecision(
        intent=intent,  # type: ignore[arg-type]
        destructive=any(marker in instruction for marker in DESTRUCTIVE_MARKERS),
        structural=intent in STRUCTURAL_INTENTS,
        mutates_document=intent in MUTATING_INTENTS,
        confidence=confidence,
        requires_confirmation=True,
        clarification_question="本次修改涉及章节删除或解绑，请确认执行范围后再继续。",
        assumptions=["需要教师确认后才能继续执行修改"],
        plan_steps=["等待教师确认", "确认后重新规划"],
        acceptance_criteria=["已获得教师确认"],
        summary=f"需要确认（{reason}）",
        rationale=f"deterministic-confirm:{reason}",
    )


def _fallback_intent(instruction: str, mode: str | None = None, selected: list[str] | None = None) -> VerbatimIntentDecision:
    """关键字/确定性兜底路由。"""
    if mode == "structure":
        return VerbatimIntentDecision(
            intent="STRUCTURE_EDIT", mutates_document=True, structural=True,
            confidence=0.8, target_section_ids=selected or [],
            plan_steps=["读取当前逐字稿", "调整章节与场景归属", "验证时间轴"],
            acceptance_criteria=["目录变化已应用", "QA 通过"], summary="重组逐字稿章节", rationale="deterministic-fallback",
        )
    if mode == "content":
        return VerbatimIntentDecision(
            intent="SECTION_EDIT", mutates_document=True, confidence=0.8,
            target_section_ids=selected or [],
            plan_steps=["读取当前逐字稿", "修改目标章节口播", "验证语义与时长"],
            acceptance_criteria=["内容已更新", "QA 通过"], summary="修改逐字稿口播", rationale="deterministic-fallback",
        )
    if mode == "timing":
        return VerbatimIntentDecision(
            intent="TIMING_ADJUST", mutates_document=True, confidence=0.8,
            target_section_ids=selected or [],
            plan_steps=["读取当前时间轴", "重算语速/停顿", "验证时长守恒"],
            acceptance_criteria=["时间轴已重算", "QA 通过"], summary="调整语速与停顿", rationale="deterministic-fallback",
        )
    if mode == "qa":
        return VerbatimIntentDecision(intent="QA_ONLY", mutates_document=False, confidence=1.0, summary="仅质量检查", rationale="deterministic-fallback")
    lowered = instruction
    destructive = any(marker in lowered for marker in DESTRUCTIVE_MARKERS)
    for markers, intent in KEYWORD_INTENTS:
        if any(marker in lowered for marker in markers):
            if destructive and intent != "STRUCTURE_EDIT":
                return _confirm_decision(intent, instruction, reason="destructive-keyword", confidence=0.6)
            return VerbatimIntentDecision(
                intent=intent,  # type: ignore[arg-type]
                mutates_document=intent in MUTATING_INTENTS,
                structural=intent in STRUCTURAL_INTENTS,
                destructive=destructive,
                confidence=0.8 if not destructive else 0.6,
                requires_confirmation=destructive,
                target_section_ids=selected or [],
                plan_steps=["读取当前逐字稿", "执行修改", "验证语义"] if intent in MUTATING_INTENTS else [],
                acceptance_criteria=["QA 通过"] if intent in MUTATING_INTENTS else [],
                summary=f"识别为 {intent}", rationale="deterministic-fallback",
            )
    if destructive:
        return _confirm_decision("SECTION_EDIT", instruction, reason="destructive-default", confidence=0.55)
    return VerbatimIntentDecision(
        intent="SECTION_EDIT", mutates_document=True, confidence=0.55, target_section_ids=selected or [],
        plan_steps=["读取当前逐字稿", "修改内容", "验证语义"],
        acceptance_criteria=["内容已更新", "QA 通过"], summary="修改逐字稿内容", rationale="deterministic-default",
    )


async def infer_verbatim_intent(
    provider,
    trigger_type: str,
    instruction: str,
    selected_section_ids: list[str] | None = None,
    mode: str | None = None,
) -> VerbatimIntentDecision:
    """识别意图：initial 确定性 GENERATE；message 走 LLM，失败回退确定性路由。"""
    if trigger_type != "message" or not instruction:
        return VerbatimIntentDecision(
            intent="GENERATE", mutates_document=True, confidence=1.0,
            plan_steps=["读取课程蓝图与视频脚本", "逐段设计必讲口播与互动", "校验语速与时间轴"],
            acceptance_criteria=["每段对齐 scene_id", "口播符合时长", "QA 通过"],
            summary="首次生成完整逐字稿", rationale="deterministic-initial",
        )
    if provider is None or provider.__class__.__name__ == "MockProvider":
        return _fallback_intent(instruction, mode, selected_section_ids)
    system = (
        "你是 LessonForge AI 教师逐字稿 Agent 的意图规划器。判断教师指令属于哪类意图：\n"
        "GENERATE（生成全新逐字稿）/ SECTION_EDIT（修改指定章节的口播正文）/\n"
        "STRUCTURE_EDIT（新增/删除/移动/重排逐字稿章节）/\n"
        "SCRIPT_EDIT（整体改写口播叙事）/ TONE_EDIT（只改表达语气与措辞）/\n"
        "TIMING_ADJUST（只调整语速/停顿/时间轴节奏）/ STYLE_EDIT（批量统一风格）/\n"
        "INTERACTION_EDIT（只调整互动/思考提示）/ SYNC_CONTEXT（同步最新项目上下文）/\n"
        "QA_ONLY（仅质量检查）/ ANSWER_ONLY（仅回答关于逐字稿的问题，不创建新版本）/\n"
        "CLARIFICATION_REQUIRED（关键歧义，必须追问才能继续）。\n"
        "只返回符合 Schema 的 JSON，不展示隐藏推理。口播/语气/停顿修改不要选择 STRUCTURE_EDIT；"
        "只有明确要求增删/移动/重排章节时才选择。删除章节或解绑场景 → destructive=true 且 requires_confirmation=true。"
    )
    prompt = (
        f"教师指令：\n{instruction}\n"
        f"用户选中的逐字稿章节：{selected_section_ids or '无'}\n"
        f"用户显式模式：{mode or 'auto'}\n"
        "输出 intent / mutates_document / target_section_ids / structural / destructive / "
        "confidence / summary / requires_confirmation / clarification_question / "
        "assumptions / plan_steps / acceptance_criteria / rationale。"
        "只有 QA_ONLY 和 ANSWER_ONLY 时 mutates_document=false。"
        "summary 是给教师看的一两句可见摘要，不要思维链。"
    )
    try:
        return await provider.structured(system, prompt, VerbatimIntentDecision)
    except Exception:  # noqa: BLE001  意图识别失败回退确定性路由
        return _fallback_intent(instruction, mode, selected_section_ids)


def agent_chain_for_intent(intent: str, trigger_type: str) -> list[str]:
    if trigger_type == "sync_context":
        return INTENT_AGENTS["SYNC_CONTEXT"]
    return INTENT_AGENTS.get(intent, INTENT_AGENTS["SECTION_EDIT"])
