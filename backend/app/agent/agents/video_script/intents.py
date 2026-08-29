"""视频脚本意图识别。

意图枚举（与方案文档一致）：
GENERATE / RESTRUCTURE / SECTION_EDIT / SCENE_EDIT / NARRATION_EDIT /
VISUAL_EDIT / TIMING_ADJUST / CONTINUITY_EDIT / GLOBAL_STYLE / SYNC_CONTEXT /
QA_ONLY / ANSWER_ONLY / CLARIFICATION_REQUIRED。

initial 走确定性 GENERATE（目录内容由 AI 根据项目上下文动态规划，不再固定）；
message 走 LLM 意图识别（结构化），失败回退关键字/确定性路由。修改型意图必须
返回 plan_steps 与接受标准；ANSWER_ONLY / QA_ONLY 不创建新版本；关键歧义返回
澄清问题不修改文件。``visible_summary`` 面向 UI 执行摘要展示。
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

VideoScriptIntent = Literal[
    "GENERATE",
    "RESTRUCTURE",
    "SECTION_EDIT",
    "SCENE_EDIT",
    "NARRATION_EDIT",
    "VISUAL_EDIT",
    "TIMING_ADJUST",
    "CONTINUITY_EDIT",
    "GLOBAL_STYLE",
    "SYNC_CONTEXT",
    "QA_ONLY",
    "ANSWER_ONLY",
    "CLARIFICATION_REQUIRED",
    "VIDEO_GENERATION_SETTINGS_UPDATE",
]

VideoScriptOperation = Literal[
    "generate", "restructure", "edit_section", "edit_scene", "edit_narration",
    "edit_visual", "edit_audio", "edit_continuity", "adjust_timing", "edit_global_style",
    "sync_context", "answer", "inspect", "update_video_generation_settings",
]


class VideoScriptIntentDecision(BaseModel):
    """intent_planner 的强类型产物。"""

    intent: VideoScriptIntent = "SECTION_EDIT"
    mutates_document: bool = False
    structural: bool = False
    destructive: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requires_confirmation: bool = False
    operation: VideoScriptOperation = "edit_section"
    target_section_ids: list[str] = Field(default_factory=list, description="受影响的章节 ID（空 = 全局）")
    target_scene_ids: list[str] = Field(default_factory=list, description="受影响的场景 ID（空 = 全局）")
    affected_json_paths: list[str] = Field(default_factory=list)
    preserve_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    plan_steps: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    visible_summary: str = Field(default="", description="面向用户的可见执行摘要")
    rationale: str = ""
    #: 视频生成设置类指令解析出的目标分辨率（如 854x480），视频脚本本身不修改。
    resolution_preference: str | None = None
    requested_resolution_text: str | None = None
    #: 是否明确提到了视频生成分辨率；与视频脚本主意图相互独立。
    resolution_requested: bool = False
    #: 指令是否只更新视频生成设置，不包含视频脚本文档修改。
    resolution_setting_only: bool = False
    #: 不支持或无法解析的分辨率说明；由设置工具生成最终结构化拒绝结果。
    resolution_error: str | None = None
    setting_domain: Literal["video_generation"] | None = None
    settings_operation: Literal["none", "set_video_resolution", "query_video_resolution"] = "none"
    capability_check_required: bool = False


# 修改文档内容的意图（会创建新版本）
MUTATING_INTENTS = {
    "GENERATE", "RESTRUCTURE", "SECTION_EDIT", "SCENE_EDIT", "NARRATION_EDIT",
    "VISUAL_EDIT", "TIMING_ADJUST", "CONTINUITY_EDIT", "GLOBAL_STYLE", "SYNC_CONTEXT",
}
STRUCTURAL_INTENTS = {"RESTRUCTURE"}

# 意图 → 最小角色链。视频脚本不再运行内容质量校验或定向返修：
# 结构合法性由发布时的 V4 Schema 强校验兜底，内容由 Agent 依据教师意图直接产出。
INTENT_AGENTS: dict[str, list[str]] = {
    "GENERATE": ["context_researcher", "outline_architect", "script_director", "timeline_editor", "finalizer"],
    "RESTRUCTURE": ["context_researcher", "outline_architect", "script_director", "timeline_editor", "finalizer"],
    "SECTION_EDIT": ["context_researcher", "outline_architect", "script_director", "timeline_editor", "finalizer"],
    "SCENE_EDIT": ["context_researcher", "script_director", "finalizer"],
    "NARRATION_EDIT": ["context_researcher", "script_director", "timeline_editor", "finalizer"],
    "VISUAL_EDIT": ["context_researcher", "script_director", "finalizer"],
    "TIMING_ADJUST": ["context_researcher", "timeline_editor", "finalizer"],
    "CONTINUITY_EDIT": ["context_researcher", "script_director", "finalizer"],
    "GLOBAL_STYLE": ["context_researcher", "script_director", "finalizer"],
    "SYNC_CONTEXT": ["context_researcher", "script_director", "timeline_editor", "finalizer"],
    "VIDEO_GENERATION_SETTINGS_UPDATE": ["project_settings"],
    "ANSWER_ONLY": ["context_researcher", "answer_finalizer"],
    "QA_ONLY": ["context_researcher", "answer_finalizer"],
    "CLARIFICATION_REQUIRED": ["finalizer"],
}

INTENT_AGENT_ALIASES = {
    "qa": "validation",
    "quality": "validation",
    "validation": "validation",
    "outline": "outline_architect",
    "architect": "outline_architect",
    "director": "script_director",
    "editor": "script_director",
    "researcher": "context_researcher",
    "planner": "intent_planner",
    "final": "finalizer",
    "finalizer": "finalizer",
    "timing": "timeline_editor",
}

INTENT_OPERATIONS: dict[str, VideoScriptOperation] = {
    "GENERATE": "generate", "RESTRUCTURE": "restructure", "SECTION_EDIT": "edit_section",
    "SCENE_EDIT": "edit_scene", "NARRATION_EDIT": "edit_narration", "VISUAL_EDIT": "edit_visual",
    "TIMING_ADJUST": "adjust_timing", "CONTINUITY_EDIT": "edit_continuity",
    "GLOBAL_STYLE": "edit_global_style", "SYNC_CONTEXT": "sync_context",
    "VIDEO_GENERATION_SETTINGS_UPDATE": "update_video_generation_settings",
    "ANSWER_ONLY": "answer", "QA_ONLY": "inspect", "CLARIFICATION_REQUIRED": "answer",
}

DESTRUCTIVE_MARKERS = ("删除", "移除", "合并", "清空", "全部重做", "推翻", "替换全部", "大幅重排")
_CN_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _ordinal_scene(instruction: str, available_scene_ids: list[str] | None) -> str | None:
    match = re.search(r"第\s*([0-9]+|[一二两三四五六七八九十])\s*(?:个|条|段)?分镜", instruction)
    if not match:
        return None
    raw = match.group(1)
    number = int(raw) if raw.isdigit() else _CN_NUMBERS.get(raw)
    ordered = available_scene_ids or []
    return str(ordered[number - 1]) if number and 0 < number <= len(ordered) else None


def normalize_video_script_intent(
    decision: VideoScriptIntentDecision,
    *, instruction: str,
    selected_section_ids: list[str] | None,
    selected_scene_ids: list[str] | None,
    available_section_ids: list[str] | None,
    available_scene_ids: list[str] | None,
) -> VideoScriptIntentDecision:
    """把模型输出收敛为可执行范围；显式 UI 选择永远优先且不得被扩大。"""
    valid_sections = set(available_section_ids or [])
    valid_scenes = set(available_scene_ids or [])
    section_scope_supplied = bool(selected_section_ids)
    scene_scope_supplied = bool(selected_scene_ids)
    explicit_sections = [item for item in (selected_section_ids or []) if item in valid_sections]
    explicit_scenes = [item for item in (selected_scene_ids or []) if item in valid_scenes]
    proposed_sections = [item for item in decision.target_section_ids if item in valid_sections]
    proposed_scenes = [item for item in decision.target_scene_ids if item in valid_scenes]
    ordinal = _ordinal_scene(instruction, available_scene_ids)
    if ordinal and not explicit_scenes:
        proposed_scenes = [ordinal]
    # 显式范围即使已经失效，也不能退化为模型建议的全局范围。
    decision.target_section_ids = explicit_sections if section_scope_supplied else proposed_sections
    decision.target_scene_ids = explicit_scenes if scene_scope_supplied else proposed_scenes
    decision.operation = INTENT_OPERATIONS.get(decision.intent, decision.operation)
    if decision.intent == "VISUAL_EDIT" and any(marker in instruction for marker in ("声音", "音效", "配乐", "语音")):
        decision.operation = "edit_audio"
    preservation_markers = {
        "preserve_visual": ("画面保持不变", "不要改画面", "画面不变", "保留画面"),
        "preserve_narration": ("口播保持不变", "不要改口播", "口播不变", "保留口播"),
        "preserve_timing": ("时长保持不变", "不要改时长", "时间轴不变", "保留时长"),
        "preserve_structure": ("章节保持不变", "不要改章节", "结构不变", "保留结构"),
    }
    for constraint, markers in preservation_markers.items():
        if any(marker in instruction for marker in markers) and constraint not in decision.preserve_constraints:
            decision.preserve_constraints.append(constraint)
    decision.destructive = decision.destructive or any(marker in instruction for marker in DESTRUCTIVE_MARKERS)
    decision.requires_confirmation = bool(
        decision.requires_confirmation or decision.destructive or decision.confidence < 0.65
    )
    if (section_scope_supplied and not explicit_sections) or (scene_scope_supplied and not explicit_scenes):
        decision.requires_confirmation = True
        decision.confidence = min(decision.confidence, 0.4)
        decision.clarification_question = "所选章节或分镜已不存在，请重新选择范围后继续。"
    decision.mutates_document = decision.intent in MUTATING_INTENTS
    if decision.intent in {"ANSWER_ONLY", "QA_ONLY", "CLARIFICATION_REQUIRED", "VIDEO_GENERATION_SETTINGS_UPDATE"}:
        decision.mutates_document = False
    if decision.requires_confirmation and not decision.clarification_question:
        decision.clarification_question = "本次修改涉及删除、合并或范围不够明确，请确认后继续。"
    if decision.target_scene_ids:
        decision.affected_json_paths = decision.affected_json_paths or [
            f"$.scenes[{scene_id}]" for scene_id in decision.target_scene_ids
        ]
    elif decision.target_section_ids:
        decision.affected_json_paths = decision.affected_json_paths or [
            f"$.outline.sections[{section_id}]" for section_id in decision.target_section_ids
        ]
    return decision

# 关键字 → 意图（确定性兜底）
KEYWORD_INTENTS: list[tuple[tuple[str, ...], str]] = [
    (("大纲", "目录", "章节", "重组", "调整结构", "调整目录", "重排", "新增章节", "删除章节", "重命名章节", "合并章节", "分镜归属", "改成", "三章", "章节数"), "RESTRUCTURE"),
    (("口播", "旁白", "解说词", "念", "配音", "精简口播", "缩短口播", "简化口播"), "NARRATION_EDIT"),
    (("风格", "整体风格", "视觉风格", "统一风格"), "GLOBAL_STYLE"),
    (("画面", "镜头", "视觉", "场景描述", "镜头节拍", "声音", "音效", "配乐"), "VISUAL_EDIT"),
    (("时长", "时间", "节奏", "太慢", "太快", "压缩", "延长", "重新分配时间"), "TIMING_ADJUST"),
    (("连续性", "连续", "同一人物", "同一环境"), "CONTINUITY_EDIT"),
    (("风格", "整体风格", "视觉风格", "统一"), "GLOBAL_STYLE"),
    (("检查", "质量", "评审", "门禁", "QA", "是否通过", "有哪些问题", "发现问题", "检查一下", "跑一遍门禁"), "QA_ONLY"),
    (("是什么", "为什么", "怎么办", "解释", "说明", "区别", "含义", "多少秒", "几个片段"), "ANSWER_ONLY"),
]

ANSWER_ONLY_MARKERS = (
    "是什么", "为什么", "怎么办", "解释一下", "说明一下", "两者的区别", "是什么意思",
    "怎么理解", "举例", "告诉我", "什么意思", "多少秒", "几个片段",
)
_SUPPORTED_RESOLUTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\d)1280\s*[x×＊*]\s*720(?!\d)", re.I), "1280x720"),
    (re.compile(r"(?<!\d)854\s*[x×＊*]\s*480(?!\d)", re.I), "854x480"),
    (re.compile(r"(?<!\d)720\s*p?(?!\d)", re.I), "1280x720"),
    (re.compile(r"(?<!\d)480\s*p?(?!\d)", re.I), "854x480"),
)
_UNSUPPORTED_RESOLUTION_PATTERN = re.compile(
    r"(?<!\d)(?:1080\s*p?|2\s*k|4\s*k|1920\s*[x×＊*]\s*1080)(?!\d)", re.I,
)
_RESOLUTION_ACTION_PATTERN = re.compile(
    r"(?:调(?:整)?|改|设(?:置)?|切换|选择|指定|输出|生成|使用|采用|用)(?:成|为|到)?",
    re.I,
)
_RESOLUTION_QUESTION_PATTERN = re.compile(
    r"(?:多少|是什么|有哪些|支持|可以吗|能否|可不可以|是不是|最高|\?|？)",
    re.I,
)
_RESOLUTION_SETTING_PHRASE = re.compile(
    r"(?:请\s*)?(?:把|将)?\s*(?:视频(?:生成)?(?:的)?)?\s*分辨率\s*"
    r"(?:调(?:整)?|改|设(?:置)?|切换|选择|指定|输出)?\s*(?:成|为|到)?\s*"
    r"(?:1280\s*[x×＊*]\s*720|854\s*[x×＊*]\s*480|720\s*p?|480\s*p?|"
    r"1080\s*p?|2\s*k|4\s*k|1920\s*[x×＊*]\s*1080)",
    re.I,
)
_RESOLUTION_VALUE_PATTERN = re.compile(
    r"(?:1280\s*[x×＊*]\s*720|854\s*[x×＊*]\s*480|720\s*p?|480\s*p?|"
    r"1080\s*p?|2\s*k|4\s*k|1920\s*[x×＊*]\s*1080)",
    re.I,
)


class _ResolutionInstruction(BaseModel):
    requested: bool = False
    setting_only: bool = False
    question_only: bool = False
    preference: str | None = None
    requested_value: str | None = None
    error: str | None = None
    residual_instruction: str = ""


def _parse_resolution(instruction: str) -> str | None:
    """解析系统支持的分辨率别名，并归一化为宽高字符串。"""
    for pattern, value in _SUPPORTED_RESOLUTION_PATTERNS:
        if pattern.search(instruction):
            return value
    return None


def _resolution_instruction(instruction: str) -> _ResolutionInstruction:
    """把视频生成设置从脚本主意图中剥离，避免分辨率关键词吞掉复合指令。"""
    has_resolution_word = "分辨率" in instruction
    has_supported_value = _parse_resolution(instruction) is not None
    unsupported_match = _UNSUPPORTED_RESOLUTION_PATTERN.search(instruction)
    has_value = has_supported_value or unsupported_match is not None
    action = bool(_RESOLUTION_ACTION_PATTERN.search(instruction))
    question = bool(_RESOLUTION_QUESTION_PATTERN.search(instruction))
    bare_value_only = bool(re.fullmatch(
        rf"\s*(?:{_RESOLUTION_VALUE_PATTERN.pattern})\s*(?:分辨率)?\s*[。.!！]?\s*",
        instruction,
        flags=re.I,
    ))
    numeric_other_unit = bool(re.search(r"(?<!\d)(?:480|720)\s*(?:字|词|秒|帧|页|人|个|条)", instruction, re.I))
    requested = bool(
        has_value and (has_resolution_word or bare_value_only or (action and not numeric_other_unit))
    )
    if not requested and not has_resolution_word:
        return _ResolutionInstruction(residual_instruction=instruction)

    # 先移除完整的“分辨率调成 …”短语，再清理残留规格。剩余实质文本交给主意图规划器。
    residual = _RESOLUTION_SETTING_PHRASE.sub(" ", instruction)
    residual = _RESOLUTION_VALUE_PATTERN.sub(" ", residual)
    residual = re.sub(r"(?:视频生成)?分辨率", " ", residual, flags=re.I)
    residual = re.sub(
        r"^\s*(?:请|把|将)?\s*(?:调(?:整)?|改|设(?:置)?|切换|选择|指定|输出|生成|使用|采用|用)"
        r"\s*(?:成|为|到)?\s*",
        "",
        residual,
        flags=re.I,
    )
    residual = re.sub(r"^[\s，,。；;、]*(?:并且|并|同时|另外|以及|再)?[\s，,。；;、]*", "", residual)
    residual = re.sub(r"[\s，,。；;、]*(?:并且|并|同时|另外|以及|再)?[\s，,。；;、]*$", "", residual)
    residual = residual.strip()
    if re.fullmatch(
        r"(?:只(?:修改|调整|改)?|(?:视频)?脚本(?:内容)?(?:保持)?不变|不要修改(?:视频)?脚本(?:内容)?)",
        residual,
    ):
        residual = ""
    setting_only = not residual and not question
    error = None
    preference = _parse_resolution(instruction)
    if unsupported_match is not None:
        error = (
            f"暂不支持分辨率 {unsupported_match.group(0).replace(' ', '')}；"
            "当前仅支持 1280x720（720p）和 854x480（480p）。"
        )
    elif has_resolution_word and not preference and action:
        error = "未识别到目标分辨率；当前仅支持 1280x720（720p）和 854x480（480p）。"
    return _ResolutionInstruction(
        requested=requested or has_resolution_word,
        setting_only=setting_only,
        question_only=question,
        preference=preference,
        requested_value=(unsupported_match.group(0).replace(" ", "") if unsupported_match else preference),
        error=error,
        residual_instruction=residual,
    )


def _attach_resolution(
    decision: VideoScriptIntentDecision,
    resolution: _ResolutionInstruction,
) -> VideoScriptIntentDecision:
    decision.resolution_requested = resolution.requested
    decision.resolution_setting_only = resolution.setting_only
    decision.resolution_preference = resolution.preference
    decision.requested_resolution_text = resolution.requested_value
    decision.resolution_error = resolution.error
    if resolution.requested:
        decision.setting_domain = "video_generation"
        decision.settings_operation = "set_video_resolution" if not resolution.question_only else "query_video_resolution"
        decision.capability_check_required = bool(resolution.preference or resolution.error)
    return decision


def _fallback_intent(
    instruction: str, mode: str | None = None,
    selected_sections: list[str] | None = None, selected_scenes: list[str] | None = None,
) -> VideoScriptIntentDecision:
    """关键字/确定性兜底路由。"""
    if mode == "structure":
        return VideoScriptIntentDecision(
            intent="RESTRUCTURE", mutates_document=True, structural=True,
            destructive=any(marker in instruction for marker in DESTRUCTIVE_MARKERS), confidence=0.8,
            operation="restructure",
            target_section_ids=selected_sections or [],
            plan_steps=["读取当前视频脚本", "重组章节与分镜归属", "验证结构与时间轴"],
            acceptance_criteria=["目录变化已应用", "发布前约束通过"],
            visible_summary="识别为章节重组：调整动态章节与分镜归属", rationale="deterministic-fallback",
        )
    if mode == "content":
        return VideoScriptIntentDecision(
            intent="SECTION_EDIT", mutates_document=True, structural=False,
            confidence=0.8, operation="edit_section",
            target_section_ids=selected_sections or [],
            plan_steps=["读取当前视频脚本", "修改目标章节内容", "验证语义与引用"],
            acceptance_criteria=["内容已更新", "发布前约束通过"],
            visible_summary="识别为章节内容修改", rationale="deterministic-fallback",
        )
    if mode in {"narration", "visual", "continuity"}:
        intent = {
            "narration": "NARRATION_EDIT", "visual": "VISUAL_EDIT", "continuity": "CONTINUITY_EDIT",
        }[mode]
        return VideoScriptIntentDecision(
            intent=intent, mutates_document=True, structural=False, confidence=0.9,
            operation=INTENT_OPERATIONS[intent], target_section_ids=selected_sections or [],
            target_scene_ids=selected_scenes or [],
            plan_steps=["读取目标分镜", "按字段边界执行修改", "运行发布前校验"],
            acceptance_criteria=["仅目标字段发生变化", "发布前约束通过"],
            visible_summary=f"按指定范围执行{ {'narration': '口播', 'visual': '画面与声音', 'continuity': '连续性'}[mode] }修改",
            rationale="explicit-video-mode",
        )
    if mode == "timing":
        return VideoScriptIntentDecision(
            intent="TIMING_ADJUST", mutates_document=True, structural=False,
            confidence=0.8, operation="adjust_timing", target_scene_ids=selected_scenes or [],
            plan_steps=["读取当前时间轴", "按指令重平衡片段时长", "验证时长守恒与 4–15 秒窗口"],
            acceptance_criteria=["时间轴已重算", "发布前约束通过"],
            visible_summary="识别为时间轴调整：重平衡片段时长", rationale="deterministic-fallback",
        )
    if mode == "qa":
        return VideoScriptIntentDecision(
            intent="QA_ONLY", mutates_document=False, structural=False,
            confidence=1.0, operation="inspect",
            visible_summary="仅执行发布前检查，不评分、不修改文件", rationale="deterministic-fallback",
        )
    lowered = instruction
    for markers, intent in KEYWORD_INTENTS:
        if any(marker in lowered for marker in markers):
            return VideoScriptIntentDecision(
                intent=intent, mutates_document=intent in MUTATING_INTENTS,
                structural=intent == "RESTRUCTURE",
                destructive=any(marker in instruction for marker in DESTRUCTIVE_MARKERS),
                confidence=0.8, operation=INTENT_OPERATIONS.get(intent, "edit_section"),
                target_section_ids=selected_sections or [],
                target_scene_ids=selected_scenes or [],
                plan_steps=["读取当前视频脚本", "执行修改", "验证语义"] if intent in MUTATING_INTENTS else [],
                acceptance_criteria=["发布前约束通过"] if intent in MUTATING_INTENTS else [],
                visible_summary=f"识别为 {intent}：{'修改视频脚本' if intent in MUTATING_INTENTS else '仅检查/回答'}",
                rationale="deterministic-fallback",
            )
    return VideoScriptIntentDecision(
        intent="SECTION_EDIT", mutates_document=True, structural=False,
        confidence=0.75, operation="edit_section",
        target_section_ids=selected_sections or [],
        target_scene_ids=selected_scenes or [],
        plan_steps=["读取当前视频脚本", "修改目标内容", "验证语义与引用"],
        acceptance_criteria=["内容已更新", "发布前约束通过"],
        visible_summary="识别为章节内容修改", rationale="deterministic-default",
    )


async def infer_video_script_intent(
    provider,
    trigger_type: str,
    instruction: str,
    selected_section_ids: list[str] | None = None,
    selected_scene_ids: list[str] | None = None,
    mode: str | None = None,
    available_section_ids: list[str] | None = None,
    available_scene_ids: list[str] | None = None,
) -> VideoScriptIntentDecision:
    """识别意图：initial 确定性 GENERATE；message 走 LLM，失败回退确定性路由。

    首次生成固定识别为 GENERATE，但目录内容由 AI 根据项目上下文动态规划，
    不要求固定"导入—建构—示范—检查—总结"目录。
    """
    if trigger_type != "message" or not instruction:
        return VideoScriptIntentDecision(
            intent="GENERATE", mutates_document=True, structural=False,
            confidence=1.0, operation="generate",
            plan_steps=["读取课程蓝图与教学设计", "动态规划章节与分镜结构", "验证时间轴与引用"],
            acceptance_criteria=["目录由 AI 动态规划", "每个分镜绑定章节", "发布前约束通过"],
            visible_summary="首次生成：按课程内容动态规划视频脚本章节", rationale="deterministic-initial",
        )
    resolution = _resolution_instruction(instruction)
    primary_instruction = resolution.residual_instruction or instruction
    if provider is None or provider.__class__.__name__ == "MockProvider":
        if resolution.setting_only or resolution.question_only or resolution.error:
            decision = VideoScriptIntentDecision(
                intent="VIDEO_GENERATION_SETTINGS_UPDATE",
                mutates_document=False,
                confidence=1.0,
                operation="update_video_generation_settings",
                visible_summary=(
                    "识别为视频生成分辨率设置修改"
                    if not resolution.error else "识别为视频生成设置请求，需要校验当前模型能力"
                ),
                rationale="deterministic-settings-fallback",
            )
        else:
            decision = _fallback_intent(primary_instruction, mode, selected_section_ids, selected_scene_ids)
        normalized = normalize_video_script_intent(
            decision,
            instruction=primary_instruction, selected_section_ids=selected_section_ids,
            selected_scene_ids=selected_scene_ids, available_section_ids=available_section_ids,
            available_scene_ids=available_scene_ids,
        )
        return _attach_resolution(normalized, resolution)
    system = (
        "你是 LessonForge AI 视频脚本 Agent 的意图规划器。视频脚本目录是动态的："
        "章节数量、标题、顺序与分镜归属由 AI 根据课程内容和教师意图决定，没有固定目录。"
        "判断教师指令属于哪类意图：\n"
        "GENERATE（生成全新视频脚本）/ RESTRUCTURE（增删、重排、重命名、合并章节或调整分镜归属）/\n"
        "SECTION_EDIT（修改指定章节及其分镜内容）/ SCENE_EDIT（修改指定单个分镜）/\n"
        "NARRATION_EDIT（只改口播/旁白）/ VISUAL_EDIT（只改画面提示词与镜头）/\n"
        "TIMING_ADJUST（只调整片段时长/时间轴节奏）/ CONTINUITY_EDIT（只调整连续性分组）/\n"
        "GLOBAL_STYLE（整体视觉或声音风格）/ SYNC_CONTEXT（同步项目上下文）/\n"
        "VIDEO_GENERATION_SETTINGS_UPDATE（修改下游视频生成设置，不修改视频脚本 Artifact）/\n"
        "QA_ONLY（仅质量检查，不修改文件）/ ANSWER_ONLY（仅回答关于脚本的问题，不创建新版本）/\n"
        "CLARIFICATION_REQUIRED（关键歧义，必须追问才能继续）。\n"
        "只返回符合 Schema 的 JSON，不展示隐藏推理。普通内容/口播/画面/时长修改不要选择 RESTRUCTURE；"
        "只有明确要求增删/重排/重命名/合并章节或调整分镜归属时才选择 RESTRUCTURE。"
        "如果指令包含'精简口播'、'缩短口播'、'简化口播'等明确的口播修改动词，即使带有'目标分镜'等词也应识别为 NARRATION_EDIT，无需追问具体分镜编号。"
    )
    prompt = (
        f"教师脚本修改指令：\n{primary_instruction}\n"
        f"已从用户原话提取的视频生成分辨率请求：{resolution.requested_value or '无'}；规范化候选值：{resolution.preference or '无'}；校验提示：{resolution.error or '无'}\n"
        f"用户选中的章节：{selected_section_ids or '无'}\n"
        f"用户选中的分镜：{selected_scene_ids or '无'}\n"
        f"用户显式模式：{mode or 'auto'}\n"
        f"当前可用章节 ID：{available_section_ids or '无'}\n"
        f"当前按时间顺序排列的分镜 ID：{available_scene_ids or '无'}\n"
        "输出 intent / operation / mutates_document / structural / destructive / confidence / "
        "requires_confirmation / target_section_ids / target_scene_ids / affected_json_paths / preserve_constraints / "
        "assumptions / plan_steps / acceptance_criteria / clarification_question / "
        "visible_summary / rationale / setting_domain / settings_operation / capability_check_required / requested_resolution_text。"
        "只有 ANSWER_ONLY、QA_ONLY 和 VIDEO_GENERATION_SETTINGS_UPDATE 时 mutates_document=false。"
        "如果教师指令是分辨率或下游视频生成参数修改，必须选择 VIDEO_GENERATION_SETTINGS_UPDATE；不要因为当前模型不支持该值而改选 ANSWER_ONLY。"
        "visible_summary 是一两句简短的中文可见摘要（给教师看，不要思维链）。"
    )
    try:
        decision = await provider.structured(system, prompt, VideoScriptIntentDecision)
    except Exception:  # noqa: BLE001  意图识别失败回退确定性路由
        decision = _fallback_intent(instruction, mode, selected_section_ids, selected_scene_ids)
    normalized = normalize_video_script_intent(
        decision, instruction=primary_instruction, selected_section_ids=selected_section_ids,
        selected_scene_ids=selected_scene_ids, available_section_ids=available_section_ids,
        available_scene_ids=available_scene_ids,
    )
    return _attach_resolution(normalized, resolution)


def agent_chain_for_intent(intent: str, trigger_type: str) -> list[str]:
    if trigger_type == "sync_context":
        return INTENT_AGENTS["SYNC_CONTEXT"]
    return INTENT_AGENTS.get(intent, INTENT_AGENTS["SECTION_EDIT"])
