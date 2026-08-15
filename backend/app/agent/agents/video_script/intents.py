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
]


class VideoScriptIntentDecision(BaseModel):
    """intent_planner 的强类型产物。"""

    intent: VideoScriptIntent = "SECTION_EDIT"
    mutates_document: bool = False
    structural: bool = False
    target_section_ids: list[str] = Field(default_factory=list, description="受影响的章节 ID（空 = 全局）")
    target_scene_ids: list[str] = Field(default_factory=list, description="受影响的场景 ID（空 = 全局）")
    assumptions: list[str] = Field(default_factory=list)
    plan_steps: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    visible_summary: str = Field(default="", description="面向用户的可见执行摘要")
    rationale: str = ""


# 修改文档内容的意图（会创建新版本）
MUTATING_INTENTS = {
    "GENERATE", "RESTRUCTURE", "SECTION_EDIT", "SCENE_EDIT", "NARRATION_EDIT",
    "VISUAL_EDIT", "TIMING_ADJUST", "CONTINUITY_EDIT", "GLOBAL_STYLE", "SYNC_CONTEXT",
}
STRUCTURAL_INTENTS = {"RESTRUCTURE"}

# 意图 → 角色链（确定性兜底路由）
INTENT_AGENTS: dict[str, list[str]] = {
    "GENERATE": ["context_researcher", "outline_architect", "script_director", "production_qa", "finalizer"],
    "RESTRUCTURE": ["intent_planner", "context_researcher", "outline_architect", "script_director", "production_qa", "finalizer"],
    "SECTION_EDIT": ["intent_planner", "context_researcher", "outline_architect", "script_director", "production_qa", "finalizer"],
    "SCENE_EDIT": ["intent_planner", "context_researcher", "script_director", "production_qa", "finalizer"],
    "NARRATION_EDIT": ["intent_planner", "context_researcher", "script_director", "production_qa", "finalizer"],
    "VISUAL_EDIT": ["intent_planner", "context_researcher", "script_director", "production_qa", "finalizer"],
    "TIMING_ADJUST": ["intent_planner", "context_researcher", "script_director", "production_qa", "finalizer"],
    "CONTINUITY_EDIT": ["intent_planner", "context_researcher", "script_director", "production_qa", "finalizer"],
    "GLOBAL_STYLE": ["intent_planner", "context_researcher", "script_director", "production_qa", "finalizer"],
    "SYNC_CONTEXT": ["context_researcher", "script_director", "production_qa", "finalizer"],
    "ANSWER_ONLY": ["context_researcher", "finalizer"],
    "QA_ONLY": ["production_qa", "finalizer"],
    "CLARIFICATION_REQUIRED": ["finalizer"],
}

INTENT_AGENT_ALIASES = {
    "qa": "production_qa",
    "quality": "production_qa",
    "outline": "outline_architect",
    "architect": "outline_architect",
    "director": "script_director",
    "editor": "script_director",
    "researcher": "context_researcher",
    "planner": "intent_planner",
    "final": "finalizer",
    "finalizer": "finalizer",
    "repair": "repair_router",
}

# 关键字 → 意图（确定性兜底）
KEYWORD_INTENTS: list[tuple[tuple[str, ...], str]] = [
    (("大纲", "目录", "章节", "重组", "调整结构", "调整目录", "重排", "新增章节", "删除章节", "重命名章节", "合并章节", "分镜归属", "改成", "三章", "章节数"), "RESTRUCTURE"),
    (("口播", "旁白", "解说词", "念", "配音"), "NARRATION_EDIT"),
    (("风格", "整体风格", "视觉风格", "统一风格"), "GLOBAL_STYLE"),
    (("画面", "镜头", "视觉", "场景描述", "镜头节拍"), "VISUAL_EDIT"),
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


def _fallback_intent(instruction: str, mode: str | None = None, selected_sections: list[str] | None = None) -> VideoScriptIntentDecision:
    """关键字/确定性兜底路由。"""
    if mode == "structure":
        return VideoScriptIntentDecision(
            intent="RESTRUCTURE", mutates_document=True, structural=True,
            target_section_ids=selected_sections or [],
            plan_steps=["读取当前视频脚本", "重组章节与分镜归属", "验证结构与时间轴"],
            acceptance_criteria=["目录变化已应用", "QA 通过"],
            visible_summary="识别为章节重组：调整动态章节与分镜归属", rationale="deterministic-fallback",
        )
    if mode == "content":
        return VideoScriptIntentDecision(
            intent="SECTION_EDIT", mutates_document=True, structural=False,
            target_section_ids=selected_sections or [],
            plan_steps=["读取当前视频脚本", "修改目标章节内容", "验证语义与引用"],
            acceptance_criteria=["内容已更新", "QA 通过"],
            visible_summary="识别为章节内容修改", rationale="deterministic-fallback",
        )
    if mode == "timing":
        return VideoScriptIntentDecision(
            intent="TIMING_ADJUST", mutates_document=True, structural=False,
            target_scene_ids=[],
            plan_steps=["读取当前时间轴", "按指令重平衡片段时长", "验证时长守恒与 4–15 秒窗口"],
            acceptance_criteria=["时间轴已重算", "QA 通过"],
            visible_summary="识别为时间轴调整：重平衡片段时长", rationale="deterministic-fallback",
        )
    if mode == "qa":
        return VideoScriptIntentDecision(
            intent="QA_ONLY", mutates_document=False, structural=False,
            visible_summary="仅执行质量检查，不修改文件", rationale="deterministic-fallback",
        )
    lowered = instruction
    for markers, intent in KEYWORD_INTENTS:
        if any(marker in lowered for marker in markers):
            return VideoScriptIntentDecision(
                intent=intent, mutates_document=intent in MUTATING_INTENTS,
                structural=intent == "RESTRUCTURE",
                target_section_ids=selected_sections or [],
                plan_steps=["读取当前视频脚本", "执行修改", "验证语义"] if intent in MUTATING_INTENTS else [],
                acceptance_criteria=["QA 通过"] if intent in MUTATING_INTENTS else [],
                visible_summary=f"识别为 {intent}：{'修改视频脚本' if intent in MUTATING_INTENTS else '仅检查/回答'}",
                rationale="deterministic-fallback",
            )
    return VideoScriptIntentDecision(
        intent="SECTION_EDIT", mutates_document=True, structural=False,
        target_section_ids=selected_sections or [],
        plan_steps=["读取当前视频脚本", "修改目标内容", "验证语义与引用"],
        acceptance_criteria=["内容已更新", "QA 通过"],
        visible_summary="识别为章节内容修改", rationale="deterministic-default",
    )


async def infer_video_script_intent(
    provider,
    trigger_type: str,
    instruction: str,
    selected_section_ids: list[str] | None = None,
    selected_scene_ids: list[str] | None = None,
    mode: str | None = None,
) -> VideoScriptIntentDecision:
    """识别意图：initial 确定性 GENERATE；message 走 LLM，失败回退确定性路由。

    首次生成固定识别为 GENERATE，但目录内容由 AI 根据项目上下文动态规划，
    不要求固定"导入—建构—示范—检查—总结"目录。
    """
    if trigger_type != "message" or not instruction:
        return VideoScriptIntentDecision(
            intent="GENERATE", mutates_document=True, structural=False,
            plan_steps=["读取课程蓝图与教学设计", "动态规划章节与分镜结构", "验证时间轴与引用"],
            acceptance_criteria=["目录由 AI 动态规划", "每个分镜绑定章节", "QA 通过"],
            visible_summary="首次生成：按课程内容动态规划视频脚本章节", rationale="deterministic-initial",
        )
    if provider is None or provider.__class__.__name__ == "MockProvider":
        return _fallback_intent(instruction, mode, selected_section_ids)
    system = (
        "你是 LessonForge AI 视频脚本 Agent 的意图规划器。视频脚本目录是动态的："
        "章节数量、标题、顺序与分镜归属由 AI 根据课程内容和教师意图决定，没有固定目录。"
        "判断教师指令属于哪类意图：\n"
        "GENERATE（生成全新视频脚本）/ RESTRUCTURE（增删、重排、重命名、合并章节或调整分镜归属）/\n"
        "SECTION_EDIT（修改指定章节及其分镜内容）/ SCENE_EDIT（修改指定单个分镜）/\n"
        "NARRATION_EDIT（只改口播/旁白）/ VISUAL_EDIT（只改画面提示词与镜头）/\n"
        "TIMING_ADJUST（只调整片段时长/时间轴节奏）/ CONTINUITY_EDIT（只调整连续性分组）/\n"
        "GLOBAL_STYLE（整体视觉或声音风格）/ SYNC_CONTEXT（同步项目上下文）/\n"
        "QA_ONLY（仅质量检查，不修改文件）/ ANSWER_ONLY（仅回答关于脚本的问题，不创建新版本）/\n"
        "CLARIFICATION_REQUIRED（关键歧义，必须追问才能继续）。\n"
        "只返回符合 Schema 的 JSON，不展示隐藏推理。普通内容/口播/画面/时长修改不要选择 RESTRUCTURE；"
        "只有明确要求增删/重排/重命名/合并章节或调整分镜归属时才选择 RESTRUCTURE。"
    )
    prompt = (
        f"教师指令：\n{instruction}\n"
        f"用户选中的章节：{selected_section_ids or '无'}\n"
        f"用户选中的分镜：{selected_scene_ids or '无'}\n"
        f"用户显式模式：{mode or 'auto'}\n"
        "输出 intent / mutates_document / structural / target_section_ids / target_scene_ids / "
        "assumptions / plan_steps / acceptance_criteria / clarification_question / "
        "visible_summary / rationale。"
        "只有 ANSWER_ONLY 和 QA_ONLY 时 mutates_document=false。"
        "visible_summary 是一两句简短的中文可见摘要（给教师看，不要思维链）。"
    )
    try:
        return await provider.structured(system, prompt, VideoScriptIntentDecision)
    except Exception:  # noqa: BLE001  意图识别失败回退确定性路由
        return _fallback_intent(instruction, mode, selected_section_ids)


def agent_chain_for_intent(intent: str, trigger_type: str) -> list[str]:
    if trigger_type == "sync_context":
        return INTENT_AGENTS["SYNC_CONTEXT"]
    return INTENT_AGENTS.get(intent, INTENT_AGENTS["SECTION_EDIT"])
