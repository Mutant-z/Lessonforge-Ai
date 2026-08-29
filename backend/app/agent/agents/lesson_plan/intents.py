"""教学设计意图识别与修改契约（工作区接地版）。

意图识别不再依赖业务特化硬编码规则（旧阶段 A：教学评价/教学反思/拆分等
预设关键词），改为：

1. 每次消息先读取**当前工作区内容**（当前教学设计大纲的章节 ID/标题/覆盖事实、
   项目材料摘要、兄弟产物、Profile），把教师指令接地到真实章节；
2. 真实 Provider 走 **LLM 结构化意图提取**，提示词注入工作区上下文，
   要求目标章节只能取自当前大纲的现有 SEC-* ID，不得编造；
3. Mock / Provider 缺失 / LLM 失败时，走**通用语言线索粗分类**（问答/质检/同步/
   时长/结构/格式/默认内容修改），目标范围同样由内容接地解析，不预设章节名。

修改契约（LessonPlanChangeContract）仍作为执行范围、工具权限与发布门禁的依据。
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.agents.lesson_plan.section_refs import (
    FACT_ALIASES,
    coverage_refs_for_sections,
    ground_instruction_sections,
    walk_all_sections,
)

LessonPlanIntent = Literal[
    "GENERATE",
    "SECTION_EDIT",
    "SECTION_FORMAT_EDIT",
    "RESTRUCTURE",
    "CONTENT_ENRICH",
    "TIMING_ADJUST",
    "SYNC_CONTEXT",
    "QA_ONLY",
    "ANSWER_ONLY",
    "CLARIFICATION_REQUIRED",
]

LessonPlanChangeKind = Literal[
    "outline_structure",
    "section_content",
    "core_content",
    "timing",
    "formatting",
    "qa_only",
    "answer_only",
]

#: 意图分类器版本；v4 起意图识别结合工作区内容做接地（删除业务特化硬编码规则）。
CLASSIFIER_VERSION = "v4"

VALID_FACT_KEYS = frozenset({
    "objectives",
    "stages",
    "key_points",
    "difficulty_points",
    "methods",
    "resources",
    "assessment_plan",
    "homework",
    "board_design",
    "reflection",
    "content_analysis",
    "learner_analysis",
})


class LessonPlanChangeContract(BaseModel):
    """教学设计结构化修改契约。"""

    intent: LessonPlanIntent = "SECTION_EDIT"
    confidence: float = 1.0
    requested_scope: list[str] = Field(default_factory=list, description="用户在前端选中的章节 ID（原始值）")
    resolved_scope: list[str] = Field(default_factory=list, description="依据语义和上下文解析出的目标章节 ID（规范化后）")
    target_section_ids: list[str] = Field(default_factory=list, description="目标章节 ID 列表（规范化后）")
    target_fact_keys: list[str] = Field(default_factory=list, description="涉及的稳定事实键")
    allowed_change_kinds: list[LessonPlanChangeKind] = Field(default_factory=list)
    required_change_kinds: list[LessonPlanChangeKind] = Field(default_factory=list)
    forbidden_change_kinds: list[LessonPlanChangeKind] = Field(default_factory=list)
    required_invariants: list[str] = Field(default_factory=list)
    ambiguity_reasons: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    structural: bool = False
    summary: str = ""
    rationale: str = ""
    affected_section_ids: list[str] = Field(default_factory=list, description="兼容旧版字段（等于 resolved_scope）")
    required_separate_facts: list[str] = Field(default_factory=list)
    must_be_distinct_top_level: bool = False
    strip_hardcoded_numbering: bool = Field(
        default=False,
        description="是否确定性去除目标章节正文中硬编码的旧序号标记（一、/二、/1. 等）",
    )
    #: 意图分类器版本（v4）；区分代码版本差异与模型误判。
    classifier_version: str = Field(default=CLASSIFIER_VERSION, description="意图分类器版本")
    #: 命中的粗分类规则名（如 coarse_format），未命中时为空。
    rule_match: str = Field(default="", description="命中的分类规则标识")
    #: 用户原始传入的章节 ID（未规范化，审计用）。
    raw_section_ids: list[str] = Field(default_factory=list, description="用户原始章节 ID")
    #: 执行前生成的不可变上下文快照标识（由 runtime 填充）。
    context_snapshot_id: str = Field(default="", description="上下文快照 ID")
    context_snapshot_hash: str = Field(default="", description="上下文快照内容哈希")


# 向后兼容别名
LessonPlanIntentDecision = LessonPlanChangeContract


class LessonPlanTaskSpec(BaseModel):
    """统一任务规格：每次运行在任何 Agent 启动前生成，后续 Agent 不得重新解释任务。

    对应 Coding Agent 的 TaskSpec：把意图契约、修改范围、允许/禁止变更与
    成功条件固化为不可变规格，用于工具层越权校验与发布门禁。
    """

    spec_id: str = ""
    instruction: str = ""
    intent: LessonPlanIntent = "SECTION_EDIT"
    expected_outcome: str = ""
    requested_section_ids: list[str] = Field(default_factory=list)
    target_section_ids: list[str] = Field(default_factory=list)
    target_fact_keys: list[str] = Field(default_factory=list)
    allowed_change_kinds: list[LessonPlanChangeKind] = Field(default_factory=list)
    forbidden_change_kinds: list[LessonPlanChangeKind] = Field(default_factory=list)
    required_invariants: list[str] = Field(default_factory=list)
    success_conditions: list[str] = Field(default_factory=list)
    requires_teaching_reasoning: bool = False
    requires_confirmation: bool = False
    context_snapshot_id: str = ""
    classifier_version: str = CLASSIFIER_VERSION
    rule_match: str = ""


#: 不需要教学推理（纯确定性/格式类）的意图：不检索课程材料、不调用内容生成模型。
#: 时长调整由 lesson_calculate_timeline 确定性收敛，不涉及教学内容推理。
_DETERMINISTIC_INTENTS = {
    "SECTION_FORMAT_EDIT", "QA_ONLY", "ANSWER_ONLY", "SYNC_CONTEXT",
    "TIMING_ADJUST", "CLARIFICATION_REQUIRED",
}


def _expected_outcome_for(decision: LessonPlanChangeContract, instruction: str) -> str:
    intent = decision.intent
    if intent == "SECTION_FORMAT_EDIT":
        return "移除目标章节正文中错误继承的硬编码序号，章节编号改由渲染器按章节树生成"
    if intent == "SECTION_EDIT":
        return "按教师指令修改目标章节正文，其他章节逐字不变"
    if intent == "RESTRUCTURE":
        return "按教师指令调整目录结构（新增/拆分/合并/移动/重命名），保持内容与教学内核不变"
    if intent == "CONTENT_ENRICH":
        return "在不改变目录结构的前提下丰富目标章节内容"
    if intent == "TIMING_ADJUST":
        return "调整教学环节时长并保持总时长守恒"
    if intent == "QA_ONLY":
        return "仅执行质量检查，不修改任何内容"
    if intent == "ANSWER_ONLY":
        return "仅回答教师问题，不生成新版本"
    if intent == "SYNC_CONTEXT":
        return "基于最新蓝图、材料与兄弟产物同步教学设计与教学内核"
    if intent == "CLARIFICATION_REQUIRED":
        return "请求教师澄清指令意图或修改范围"
    return "生成/完善完整教学设计"


def _success_conditions_for(decision: LessonPlanChangeContract) -> list[str]:
    conditions: list[str] = []
    intent = decision.intent
    targets = list(decision.target_section_ids or decision.resolved_scope or [])
    if intent == "SECTION_FORMAT_EDIT":
        conditions.extend([
            "目标章节正文不包含错误硬编码章节序号",
            "其他章节逐字不变",
            "pedagogical_core 不变",
            "预览编号由章节树生成",
        ])
    elif intent in {"SECTION_EDIT", "CONTENT_ENRICH"}:
        conditions.extend([
            "目标章节完成教师要求的修改",
            "其他章节逐字不变",
            "教学目标—活动—评价保持对齐",
        ])
    elif intent == "RESTRUCTURE":
        conditions.extend([
            "目录结构调整满足教师要求",
            "非目标章节正文逐字不变",
            "pedagogical_core 不被无关重写",
        ])
    elif intent == "TIMING_ADJUST":
        conditions.extend(["总时长守恒", "环节时间为正"])
    elif intent == "QA_ONLY":
        conditions.extend(["候选稿内容完全不变"])
    elif intent == "ANSWER_ONLY":
        conditions.extend(["候选稿内容完全不变"])
    elif intent == "CLARIFICATION_REQUIRED":
        conditions.extend(["教师确认意图或修改范围后继续执行"])
    elif intent == "SYNC_CONTEXT":
        conditions.extend([
            "依据最新蓝图/材料/兄弟产物同步教学设计与教学内核",
            "环节时长守恒",
        ])
    if targets:
        conditions.append("目标章节 " + "、".join(targets) + " 完成预期修改")
    for invariant in decision.required_invariants or []:
        if invariant not in conditions:
            conditions.append(invariant)
    return conditions


def build_lesson_plan_task_spec(
    decision: LessonPlanChangeContract,
    instruction: str,
    *,
    context_snapshot_id: str = "",
) -> LessonPlanTaskSpec:
    """从修改契约生成不可变任务规格（确定性，无 LLM）。"""
    intent = decision.intent
    # 结构调整（新增/拆分/合并/移动）通常涉及正文迁移或写入，需要教学推理；
    # 纯格式/问答/质检/时长/同步为确定性任务。
    requires_reasoning = intent not in _DETERMINISTIC_INTENTS
    return LessonPlanTaskSpec(
        spec_id=f"spec-{decision.classifier_version}-{hash(decision.summary or intent) % (10 ** 6):06d}",
        instruction=instruction,
        intent=intent,
        expected_outcome=_expected_outcome_for(decision, instruction),
        requested_section_ids=list(decision.requested_scope or []),
        target_section_ids=list(decision.target_section_ids or decision.resolved_scope or []),
        target_fact_keys=list(decision.target_fact_keys or []),
        allowed_change_kinds=list(decision.allowed_change_kinds or []),
        forbidden_change_kinds=list(decision.forbidden_change_kinds or []),
        required_invariants=list(decision.required_invariants or []),
        success_conditions=_success_conditions_for(decision),
        requires_teaching_reasoning=requires_reasoning,
        requires_confirmation=decision.requires_confirmation or bool(decision.ambiguity_reasons),
        context_snapshot_id=context_snapshot_id,
        classifier_version=decision.classifier_version,
        rule_match=decision.rule_match,
    )


STRUCTURAL_INTENTS = {"RESTRUCTURE"}
CONTENT_INTENTS = {"SECTION_EDIT", "CONTENT_ENRICH", "TIMING_ADJUST"}

# 意图 → Agent 链（确定性路由）
INTENT_AGENTS: dict[str, list[str]] = {
    "GENERATE": ["context_researcher", "outline_architect", "lesson_designer", "pedagogy_qa", "finalizer"],
    "SECTION_EDIT": ["intent_planner", "context_researcher", "lesson_designer", "pedagogy_qa", "finalizer"],
    "SECTION_FORMAT_EDIT": ["intent_planner", "context_researcher", "format_normalizer", "pedagogy_qa", "finalizer"],
    "RESTRUCTURE": ["intent_planner", "context_researcher", "outline_architect", "pedagogy_qa", "finalizer"],
    "CONTENT_ENRICH": ["intent_planner", "context_researcher", "lesson_designer", "pedagogy_qa", "finalizer"],
    "TIMING_ADJUST": ["intent_planner", "context_researcher", "lesson_designer", "pedagogy_qa", "finalizer"],
    "SYNC_CONTEXT": ["context_researcher", "lesson_designer", "finalizer"],
    "QA_ONLY": ["pedagogy_qa", "finalizer"],
    "ANSWER_ONLY": ["context_researcher", "answer_finalizer"],
    "CLARIFICATION_REQUIRED": ["intent_planner"],
}

INTENT_AGENT_ALIASES = {
    "qa": "pedagogy_qa",
    "quality": "pedagogy_qa",
    "designer": "lesson_designer",
    "editor": "lesson_designer",
    "outline": "outline_architect",
    "architect": "outline_architect",
    "researcher": "context_researcher",
    "planner": "intent_planner",
    "final": "finalizer",
    "finalizer": "finalizer",
    "repair": "repair_router",
}


# ---------------------------------------------------------------------------
# 工作区接地：意图识别前把当前文档 + 项目 RAG 资料 + 兄弟产物整理为上下文
# ---------------------------------------------------------------------------


def _project_section_projection(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "coverage_refs": list(item.get("coverage_refs") or []),
            "text_preview": str(item.get("summary") or "")[:60],
            "children": _project_section_projection(list(item.get("children") or [])),
        }
        for item in sections or []
    ]


def _workspace_grounding_text(
    content: dict[str, Any] | None,
    knowledge: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> str:
    """把当前教学设计大纲 + 项目材料 + 兄弟产物压缩为意图识别的接地上下文。"""
    content = content or {}
    outline = (content.get("outline") or {}).get("sections") or []
    core = content.get("pedagogical_core") or {}
    knowledge = knowledge or {}
    profile = profile or {}
    agent_profile = knowledge.get("agent_profile_summary") or {}
    materials = agent_profile.get("material_summaries") if isinstance(agent_profile, dict) else None
    if not materials:
        materials = profile.get("material_summaries") or knowledge.get("materials") or []
    siblings = {
        str(kind): int((value or {}).get("version") or 0)
        for kind, value in (knowledge.get("sibling_artifacts") or {}).items()
    }
    deps = {
        str(kind): int((value or {}).get("version") or 0)
        for kind, value in (knowledge.get("hard_dependencies") or {}).items()
    }
    payload = {
        "current_outline": _project_section_projection(outline),
        "core_summary": {
            "objective_count": len(core.get("objectives", [])),
            "stage_titles": [item.get("title") for item in core.get("stages", [])],
            "key_points": list(core.get("key_points") or [])[:6],
            "difficulty_points": list(core.get("difficulty_points") or [])[:6],
        },
        "project_materials": [str(item)[:200] for item in (materials or [])][:10],
        "sibling_artifact_versions": siblings,
        "hard_dependency_versions": deps,
        "fact_aliases": FACT_ALIASES,
    }
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)[:6000]
    except (TypeError, ValueError):
        return str(payload)[:6000]


# ---------------------------------------------------------------------------
# 通用语言线索粗分类（Mock / Provider 缺失 / LLM 失败时使用）。
# 只做意图大类分类，目标章节一律由 ground_instruction_sections 按当前大纲解析，
# 不再预设任何业务章节名（教学评价/教学反思等）。
# ---------------------------------------------------------------------------

_QUESTION_STARTERS = ("为什么", "怎么看", "解释一下", "你觉得", "介绍一下", "有哪些", "什么是", "如何理解")
_EDIT_SIGNALS = (
    "修改", "添加", "新增", "删除", "拆分", "合并", "重写", "改写", "扩写", "丰富",
    "调整", "优化", "有问题", "序号", "编号", "不对", "错了", "错误", "修正", "重新编号",
    "去掉", "去除", "改成", "换成", "补充", "同步", "作为新的点", "另起", "单独成章", "独立成章",
    "格式", "层级", "标题",
)
_QA_MARKERS = ("质量检查", "合规检查", "质检", "审查", "评估教学设计", "检查一下")
_SYNC_MARKERS = ("同步", "按最新", "依据最新")
_STRUCTURE_VERBS = (
    "调整目录", "重排目录", "拆分章节", "合并章节", "移动章节", "重命名章节", "调整结构",
    "单独成章", "独立成章",
)
_STRUCTURE_PATTERN = re.compile(
    r"(?:新增|添加|增加|插入|删除|移除|去掉|移动|重排|重命名|合并|拆分)"
    r"[^，。；]{0,12}(?:章节|小节|环节|目录|点|部分)"
)
_TIMING_MARKERS = ("调整时长", "修改用时", "时间分配", "环节时长", "分钟")
#: 强格式信号：命中即进入 SECTION_FORMAT_EDIT（确定性处理优先）。
_STRONG_FORMAT_MARKERS = ("序号", "编号", "重新编号", "层级", "格式", "排版", "为什么是", "标成", "写成了")

# 这两个事实经常以“教学重难点”合称出现。它们仍然是两个稳定事实键，
# 但“合称”不等于“必须拆成两个一级章节”；只有教师明确要求分开呈现时，
# 才启用 must_be_distinct_top_level 门禁。
_CORE_FACT_KEYS = ("key_points", "difficulty_points")
_FACT_SUPPLEMENT_MARKERS = (
    "缺少", "缺失", "没有", "未写", "未体现", "补充", "完善", "增加", "添加", "丰富", "补齐",
)
_DISTINCT_FACT_MARKERS = (
    "分别", "分开", "拆分", "拆成", "分成", "各自", "独立", "单独", "两个部分", "两个章节",
)


def _core_fact_keys_in_instruction(instruction: str) -> list[str]:
    """识别指令中明确提到的教学重点/难点事实键。"""
    compact = "".join((instruction or "").split())
    result: list[str] = []
    if "重难点" in compact or "重难" in compact:
        result.extend(_CORE_FACT_KEYS)
    else:
        if any(alias in compact for alias in FACT_ALIASES["key_points"]):
            result.append("key_points")
        if any(alias in compact for alias in FACT_ALIASES["difficulty_points"]):
            result.append("difficulty_points")
    return list(dict.fromkeys(result))


def _fact_supplement_requested(instruction: str) -> bool:
    compact = "".join((instruction or "").split())
    return any(marker in compact for marker in _FACT_SUPPLEMENT_MARKERS)


def _explicitly_separates_facts(instruction: str) -> bool:
    compact = "".join((instruction or "").split())
    return any(marker in compact for marker in _DISTINCT_FACT_MARKERS)


def _fallback_contract(
    intent: LessonPlanIntent,
    requested: list[str],
    targets: list[str],
    facts: list[str],
    allowed: list[str],
    required: list[str],
    forbidden: list[str],
    structural: bool,
    summary: str,
    rule_match: str,
    *,
    strip_numbering: bool = False,
    invariants: list[str] | None = None,
    requires_confirmation: bool = False,
    ambiguity: list[str] | None = None,
) -> LessonPlanChangeContract:
    targets = [sid for sid in targets if sid]
    resolved = list(targets) if targets else list(requested)
    return LessonPlanChangeContract(
        intent=intent,
        confidence=0.85,
        requested_scope=list(requested),
        resolved_scope=resolved,
        target_section_ids=list(targets),
        target_fact_keys=list(facts),
        allowed_change_kinds=list(allowed),
        required_change_kinds=list(required),
        forbidden_change_kinds=list(forbidden),
        required_invariants=list(invariants or []),
        ambiguity_reasons=list(ambiguity or []),
        requires_confirmation=requires_confirmation,
        structural=structural,
        summary=summary,
        rationale=rule_match,
        affected_section_ids=resolved,
        raw_section_ids=list(requested),
        rule_match=rule_match,
        strip_hardcoded_numbering=strip_numbering,
    )


def _coarse_intent_fallback(
    instruction: str,
    selected_section_ids: list[str] | None,
    mode: str | None,
    content: dict[str, Any] | None,
) -> LessonPlanChangeContract:
    """通用语言线索粗分类（无业务特化章节规则）。

    目标章节由 ground_instruction_sections 按当前大纲解析；指令中提到但大纲中
    不存在的部分会进入 ambiguity，绝不静默丢弃（避免“对用户要求无响应”）。
    """
    raw_text = (instruction or "").strip()
    compact = "".join(raw_text.split())
    requested = [str(sid) for sid in (selected_section_ids or []) if str(sid)]
    # 接地：优先按当前大纲解析，其次保留用户显式选中（别名已在入口/接地层规范化）。
    grounded = ground_instruction_sections(raw_text, content, requested)
    facts = coverage_refs_for_sections(content, grounded) if content else []
    all_kinds = ["outline_structure", "section_content", "core_content", "timing", "formatting"]
    unresolved_requested = [raw for raw in requested if raw and raw not in grounded]

    # 0. 显式模式硬约束（用户在前端选择的修改模式优先级最高）。
    if mode == "qa":
        return _fallback_contract("QA_ONLY", requested, [], [], ["qa_only"], ["qa_only"], all_kinds,
                                  False, "仅执行教学质量检查", "coarse-qa-mode")
    if mode == "timing":
        return _fallback_contract("TIMING_ADJUST", requested, grounded or requested, ["stages"],
                                  ["timing", "core_content"], ["timing"], ["outline_structure"],
                                  False, "调整教学环节时长", "coarse-timing-mode")
    if mode == "structure":
        return _fallback_contract("RESTRUCTURE", requested, [], [], ["outline_structure", "section_content"],
                                  ["outline_structure"], ["timing"], True, "调整教学设计目录结构", "coarse-structure-mode")

    # 1. 纯问答（无编辑信号）：例如“教学目标为什么要用行为动词描述？”
    is_question = any(q in compact for q in _QUESTION_STARTERS) and not any(v in compact for v in _EDIT_SIGNALS)
    if is_question:
        return _fallback_contract("ANSWER_ONLY", requested, [], [], ["answer_only"], ["answer_only"], all_kinds,
                                  False, "解答教师关于教学设计的问题", "coarse-question")

    # 2. 质量检查。
    if any(m in compact for m in _QA_MARKERS):
        return _fallback_contract("QA_ONLY", requested, [], [], ["qa_only"], ["qa_only"], all_kinds,
                                  False, "仅执行教学质量检查", "coarse-qa")

    # 3. 上下文同步。
    if any(m in compact for m in _SYNC_MARKERS):
        return _fallback_contract("SYNC_CONTEXT", requested, [], [], ["section_content", "core_content"],
                                  ["section_content"], ["outline_structure", "timing"],
                                  False, "基于最新项目上下文同步教学设计", "coarse-sync")

    # 4. 时长调整（确定性收敛）。
    if any(m in compact for m in _TIMING_MARKERS):
        return _fallback_contract("TIMING_ADJUST", requested, grounded or requested, ["stages"],
                                  ["timing", "core_content"], ["timing"], ["outline_structure"],
                                  False, "调整教学环节时长", "coarse-timing")

    is_format = any(m in compact for m in _STRONG_FORMAT_MARKERS) or (
        mode == "content" and any(w in compact for w in ("序号", "编号"))
    )

    # 重点/难点是稳定教学事实。若当前大纲没有可展示的对应章节，“补充”
    # 意味着需要新增一个展示章节，而不是把请求当成普通正文润色后空转。
    core_fact_keys = _core_fact_keys_in_instruction(raw_text)
    if (
        core_fact_keys
        and not is_format
        and (_fact_supplement_requested(raw_text) or _explicitly_separates_facts(raw_text))
    ):
        targets = grounded or requested
        if targets:
            return _fallback_contract(
                "CONTENT_ENRICH", requested, targets, core_fact_keys,
                ["section_content", "core_content"], ["section_content"],
                ["outline_structure", "timing"], False,
                "补充教学重点与难点内容", "coarse-core-fact-content",
            )
        return _fallback_contract(
            "RESTRUCTURE", requested, [], core_fact_keys,
            ["outline_structure", "section_content", "core_content"],
            ["outline_structure", "section_content"], ["timing"], True,
            "新增教学重点与难点展示章节", "coarse-core-fact-section",
        )

    # 5. 目录结构调整（新增/拆分/合并/移动/重命名等）。
    is_structure = any(v in compact for v in _STRUCTURE_VERBS) or bool(_STRUCTURE_PATTERN.search(compact))
    if is_structure:
        return _fallback_contract("RESTRUCTURE", requested, [], [], ["outline_structure", "section_content"],
                                  ["outline_structure"], ["timing"], True, "调整教学设计目录结构", "coarse-structure")

    # 6. 格式/序号缺陷修正（确定性处理优先，不重写正文语义）。
    if is_format:
        unresolved = [f"format_target_unmatched:{raw}" for raw in unresolved_requested]
        return _fallback_contract(
            "SECTION_FORMAT_EDIT", requested, grounded or requested, facts,
            ["formatting", "section_content"], ["formatting"],
            ["outline_structure", "core_content", "timing"],
            False, "修正章节内的序号/编号/层级格式问题", "coarse-format",
            strip_numbering=True,
            invariants=[
                "其他章节正文保持不变",
                "保留目标章节正文语义，仅去除硬编码旧序号标记（一、/二、/1. 等）",
                "章节显示编号由渲染器按章节树层级统一生成，模型不得写入正文",
                "不得修改 pedagogical_core",
            ],
            ambiguity=unresolved or None,
        )

    # 7. 指令过短且未选中章节：无法安全判断。
    if len(compact) <= 2 and not requested:
        return _fallback_contract("CLARIFICATION_REQUIRED", [], [], [], [], [], [],
                                  False, "指令意图不明确，需教师进一步澄清", "coarse-ambiguity",
                                  requires_confirmation=True,
                                  ambiguity=["指令过于简略且未指定修改章节或修改目标"])

    # 8. 默认内容修改：目标由内容接地解析。
    unresolved = [f"target_unmatched:{raw}" for raw in unresolved_requested]
    return _fallback_contract("SECTION_EDIT", requested, grounded or requested, facts,
                              ["section_content"], ["section_content"], ["outline_structure", "timing"],
                              False, "按教师指令修改目标章节内容", "coarse-content",
                              invariants=["其他章节正文保持不变", "目标章节内的硬编码旧序号标记必须去除"],
                              ambiguity=unresolved or None,
                              strip_numbering=True)


async def infer_lesson_plan_intent(
    provider,
    trigger_type: str,
    instruction: str,
    selected_section_ids: list[str] | None = None,
    mode: str | None = None,
    content: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> LessonPlanChangeContract:
    """识别意图：initial 确定性 GENERATE；message 结合工作区内容做意图提取。

    - 真实 Provider：LLM 结构化意图提取（提示词注入当前大纲/材料/兄弟产物），
      目标章节必须取自当前大纲；
    - Mock / Provider 缺失 / LLM 失败：通用语言线索粗分类 + 内容接地。
    """
    if trigger_type != "message" or not instruction:
        return LessonPlanChangeContract(
            intent="GENERATE",
            confidence=1.0,
            requested_scope=[],
            resolved_scope=[],
            target_section_ids=[],
            target_fact_keys=list(VALID_FACT_KEYS),
            allowed_change_kinds=["outline_structure", "section_content", "core_content", "timing"],
            required_change_kinds=["outline_structure", "section_content", "core_content"],
            forbidden_change_kinds=[],
            required_invariants=["蓝图目标完全覆盖", "环节时长守恒"],
            requires_confirmation=False,
            structural=True,
            summary="首次生成完整教学设计",
            rationale="deterministic-initial",
            affected_section_ids=[],
        )

    requested = list(selected_section_ids or [])
    fallback = _coarse_intent_fallback(instruction, requested, mode, content)

    if provider is None or provider.__class__.__name__ == "MockProvider":
        return _augment_requirements(fallback, instruction, mode, content=content)

    try:
        grounding = _workspace_grounding_text(content, knowledge, profile)
        system = (
            "你是 LessonForge AI 教学设计 Agent 的意图规划器。依据教师指令、下方「当前大纲与工作区上下文」"
            "与用户显式模式，输出结构化修改契约 LessonPlanChangeContract。\n"
            "意图类型：\n"
            "- GENERATE（首次生成）\n"
            "- SECTION_EDIT（修改指定章节内容）\n"
            "- SECTION_FORMAT_EDIT（修正章节格式：硬编码序号、标题层级、显示顺序；确定性处理优先，"
            "不重写正文语义）\n"
            "- RESTRUCTURE（新增、删除、拆分、合并、移动、重排章节）\n"
            "- CONTENT_ENRICH（补充或丰富内容但保持目录不变）\n"
            "- TIMING_ADJUST（调整教学环节时长）\n"
            "- SYNC_CONTEXT（同步蓝图或兄弟产物）\n"
            "- QA_ONLY（仅做质量检查）\n"
            "- ANSWER_ONLY（仅回答问题，不产生变更）\n"
            "- CLARIFICATION_REQUIRED（指令模糊或存在冲突，需教师确认）\n"
            "硬性规则：\n"
            "· target_section_ids / resolved_scope 必须使用「当前大纲」中已有的章节 ID（SEC-* 形式），"
            "不得编造大纲外的章节 ID；\n"
            "· 用户选中的章节（requested_scope）必须保留在 resolved_scope 中；\n"
            "· 指令提到的内容若在当前大纲中找不到对应章节，在 ambiguity_reasons 中说明，"
            "而不是随意选择近似章节；\n"
            "· 稳定事实键只能从 objectives, stages, key_points, difficulty_points, methods, "
            "resources, assessment_plan, homework, board_design, reflection, content_analysis, learner_analysis 中选择。\n"
            "只返回符合 Schema 的 JSON，不输出其他额外内容。"
        )
        prompt = (
            f"教师指令：\n{instruction}\n"
            f"用户选中的章节：{selected_section_ids or '无'}\n"
            f"用户显式模式：{mode or 'auto'}\n"
            f"当前大纲与工作区上下文（结合该内容定位需要修改的章节）：\n{grounding}\n\n"
            "请严格分析 intent, confidence, requested_scope, resolved_scope, target_section_ids, "
            "target_fact_keys, allowed_change_kinds, required_change_kinds, forbidden_change_kinds, "
            "required_invariants, ambiguity_reasons, requires_confirmation, structural, summary, rationale。"
        )
        decision = await provider.structured(system, prompt, LessonPlanChangeContract)
        return _validate_and_augment_contract(decision, instruction, mode, requested, content=content)
    except Exception:  # noqa: BLE001  LLM 失败回退粗分类
        return _augment_requirements(fallback, instruction, mode, content=content)


def _validate_and_augment_contract(
    contract: LessonPlanChangeContract,
    instruction: str,
    mode: str | None,
    selected_section_ids: list[str] | None,
    content: dict[str, Any] | None = None,
) -> LessonPlanChangeContract:
    """校验模型判定的契约，并应用硬约束与补齐（目标章节接地）。"""
    # 显式模式作为硬约束
    if mode == "structure" and contract.intent != "RESTRUCTURE":
        contract.intent = "RESTRUCTURE"
        contract.structural = True
    elif mode == "content" and contract.intent not in {"SECTION_EDIT", "CONTENT_ENRICH", "SECTION_FORMAT_EDIT"}:
        contract.intent = "SECTION_EDIT"
        contract.structural = False
    elif mode == "timing" and contract.intent != "TIMING_ADJUST":
        contract.intent = "TIMING_ADJUST"
    elif mode == "qa" and contract.intent != "QA_ONLY":
        contract.intent = "QA_ONLY"

    # 过滤非法事实键
    contract.target_fact_keys = [k for k in contract.target_fact_keys if k in VALID_FACT_KEYS]

    # 同步 scope 与 affected_section_ids；保留用户原始 ID 用于审计。
    contract.requested_scope = list(selected_section_ids or [])
    if not contract.raw_section_ids:
        contract.raw_section_ids = list(selected_section_ids or [])
    if not contract.resolved_scope and contract.target_section_ids:
        contract.resolved_scope = list(contract.target_section_ids)
    elif not contract.resolved_scope and contract.requested_scope:
        contract.resolved_scope = list(contract.requested_scope)
    contract.affected_section_ids = list(contract.resolved_scope)

    return _augment_requirements(contract, instruction, mode, content=content)


def _augment_requirements(
    decision: LessonPlanChangeContract,
    instruction: str,
    mode: str | None,
    content: dict[str, Any] | None = None,
) -> LessonPlanChangeContract:
    """补齐可确定验证的意图契约；不依赖模型自由文本作为发布证据。

    目标章节为空（或全部是自然语言、无法解析）时，用指令 + 当前大纲做内容接地；
    仍无法解析的引用记入 ambiguity_reasons，绝不静默丢弃。
    """
    kinds = list(dict.fromkeys(decision.required_change_kinds))
    if decision.intent == "SECTION_FORMAT_EDIT" or (
        mode == "content" and any(w in "".join((instruction or "").split()) for w in ("序号", "编号"))
    ):
        if "formatting" not in kinds:
            kinds.append("formatting")
        decision.strip_hardcoded_numbering = True
        if "core_content" not in (decision.forbidden_change_kinds or []):
            decision.forbidden_change_kinds = list(decision.forbidden_change_kinds or []) + ["core_content"]
    elif decision.intent == "RESTRUCTURE" or mode == "structure":
        if "outline_structure" not in kinds:
            kinds.append("outline_structure")
        decision.structural = True
    elif decision.intent == "TIMING_ADJUST" or mode == "timing":
        if "timing" not in kinds:
            kinds.append("timing")
    elif decision.intent == "QA_ONLY" or mode == "qa":
        kinds = ["qa_only"]
    elif decision.intent == "ANSWER_ONLY":
        kinds = ["answer_only"]

    # 目标章节接地：仅对「内容定位型」意图生效（要改哪个章节的正文）。
    # 目录结构调整（RESTRUCTURE）允许新建/移动章节，目标范围不应被接地结果锁死；
    # 问答/质检/同步/首次生成不涉及章节内容修改。
    content_targeted = decision.intent in {
        "SECTION_EDIT", "CONTENT_ENRICH", "SECTION_FORMAT_EDIT", "TIMING_ADJUST",
    }
    requested = list(decision.requested_scope or [])
    targets = list(decision.target_section_ids or [])
    natural_language_targets = [
        raw for raw in targets
        if not re.fullmatch(r"SEC-[A-Z0-9-]+", str(raw).strip())
    ]
    if content_targeted and (not targets or natural_language_targets):
        grounded = ground_instruction_sections(instruction, content, requested)
        if grounded:
            final_targets = [sid for sid in targets if re.fullmatch(r"SEC-[A-Z0-9-]+", str(sid).strip())]
            for sid in grounded:
                if sid not in final_targets:
                    final_targets.append(sid)
            decision.target_section_ids = final_targets
            if not decision.resolved_scope:
                decision.resolved_scope = list(final_targets)
            decision.affected_section_ids = list(decision.resolved_scope)
        elif natural_language_targets:
            decision.ambiguity_reasons = list(decision.ambiguity_reasons or []) + [
                f"unresolved_target:{raw}" for raw in natural_language_targets
            ]
            decision.target_section_ids = [
                sid for sid in targets if re.fullmatch(r"SEC-[A-Z0-9-]+", str(sid).strip())
            ]

    # 模型有时只返回“重难点”这一自然语言概念，未填稳定事实键；在执行前补齐，
    # 这样工具权限、上下文和发布门禁都能指向同一组事实。
    instruction_fact_keys = _core_fact_keys_in_instruction(instruction)
    if instruction_fact_keys:
        decision.target_fact_keys = list(dict.fromkeys(
            list(decision.target_fact_keys or []) + instruction_fact_keys
        ))
        if _fact_supplement_requested(instruction) and decision.intent in {
            "SECTION_EDIT", "CONTENT_ENRICH", "RESTRUCTURE",
        }:
            if "section_content" not in kinds:
                kinds.append("section_content")
            # 没有现有目标章节时，补充“重难点”只能通过新增展示章节落地。
            if not decision.target_section_ids and not requested and decision.intent in {
                "SECTION_EDIT", "CONTENT_ENRICH",
            }:
                decision.intent = "RESTRUCTURE"
                decision.structural = True
                if "outline_structure" not in kinds:
                    kinds.insert(0, "outline_structure")
                if "outline_structure" not in decision.allowed_change_kinds:
                    decision.allowed_change_kinds = list(decision.allowed_change_kinds or []) + ["outline_structure"]

    facts = list(dict.fromkeys(decision.required_separate_facts or decision.target_fact_keys))

    # “教学重难点”是一个常见的合并展示单元。只有教师明确说“分别/拆分/独立”等
    # 才要求两个事实各占一个一级章节，避免把一个合法的合并章节误判为未完成。
    if (
        decision.must_be_distinct_top_level
        and facts
        and set(facts).issubset(set(_CORE_FACT_KEYS))
        and not _explicitly_separates_facts(instruction)
    ):
        decision.must_be_distinct_top_level = False

    # 独立事实章节（拆分评价/反思等）：按当前大纲把事实归属章节确定性加入目标范围，
    # 不依赖意图识别来源（LLM / 脚本 / 粗分类）都能保持拆分语义。
    if decision.must_be_distinct_top_level and facts and content:
        outline = (content.get("outline") or {}).get("sections") or []
        owner_ids: list[str] = []
        for node, _parent, _order, _depth in walk_all_sections({"sections": outline}):
            refs = set(node.get("coverage_refs") or [])
            if refs.intersection(facts):
                owner_ids.append(str(node.get("id") or ""))
        targets = list(decision.target_section_ids or [])
        for sid in owner_ids:
            if sid and sid not in targets:
                targets.append(sid)
        if targets != list(decision.target_section_ids or []):
            decision.target_section_ids = targets
            decision.resolved_scope = list(targets)
            decision.affected_section_ids = list(targets)

    decision.required_change_kinds = kinds
    decision.required_separate_facts = facts
    if not decision.target_fact_keys and facts:
        decision.target_fact_keys = list(facts)
    return decision


def agent_chain_for_intent(
    intent: str,
    trigger_type: str,
    change_kinds: list[str] | None = None,
) -> list[str]:
    """按修改契约动态组装 Agent 执行链。"""
    if trigger_type == "message" and intent == "QA_ONLY":
        return INTENT_AGENTS["QA_ONLY"]
    if trigger_type == "message" and intent == "ANSWER_ONLY":
        return INTENT_AGENTS["ANSWER_ONLY"]
    if trigger_type == "sync_context":
        return INTENT_AGENTS["SYNC_CONTEXT"]
    if intent == "SECTION_FORMAT_EDIT":
        # 格式修正：确定性清理优先，不重写正文语义。
        return INTENT_AGENTS["SECTION_FORMAT_EDIT"]
    if intent == "RESTRUCTURE":
        kinds = set(change_kinds or [])
        # 若结构调整涉及正文迁移或写入（如拆分章节、内容搬移），则在 outline_architect 之后加入 lesson_designer
        if "section_content" in kinds or "core_content" in kinds:
            return ["intent_planner", "context_researcher", "outline_architect", "lesson_designer", "pedagogy_qa", "finalizer"]
        return INTENT_AGENTS["RESTRUCTURE"]
    return INTENT_AGENTS.get(intent, INTENT_AGENTS["SECTION_EDIT"])
