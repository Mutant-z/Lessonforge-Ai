"""教学设计内部角色。

前端统一显示为「教学设计 Agent」；内部按角色分工：
intent_planner / context_researcher / outline_architect / lesson_designer /
pedagogy_qa / repair_router / finalizer。

Mock 路径：每个 Agent 的 decide 确定性产出 schema 合法产物（走 completed）；
LLM 路径：通过 stream_decision 返回 AgentDecision，工具调用结果回喂继续决策。
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.agents.lesson_plan.tools import register_lesson_plan_tools
from app.agent.core.agent import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision
from app.providers.llm.mock import MockProvider

# 读取类工具（共享项目记忆工具供工作中按需读取其他 Agent 产物）
READ_TOOLS = [
    "lesson_get_blueprint", "lesson_get_source", "lesson_get_profile",
    "lesson_search_materials", "lesson_get_siblings", "lesson_get_locks",
    "list_project_memory", "search_project_memory", "read_project_memory_item",
    "read_artifact_version", "get_latest_project_artifact",
]
# 大纲结构工具
OUTLINE_TOOLS = [
    "lesson_get_source", "lesson_add_section",
    "lesson_move_section", "lesson_rename_section", "lesson_merge_sections",
    "lesson_delete_section", "lesson_validate_outline_coverage",
]
# 内容编辑工具
CONTENT_TOOLS = [
    "lesson_get_source", "lesson_get_blueprint", "lesson_write_section",
    "lesson_update_core", "lesson_apply_patch", "lesson_calculate_timeline",
]
# 检查工具
QA_TOOLS = [
    "lesson_get_source", "lesson_get_blueprint", "lesson_validate_alignment",
    "lesson_validate_outline_coverage", "lesson_validate_references",
    "lesson_validate_scope", "lesson_validate_numbering",
    "lesson_calculate_timeline", "lesson_render_preview",
]


def _blueprint(tc: ToolContext) -> dict[str, Any]:
    blueprint = tc.ctx.blueprint if tc.ctx is not None else None
    return blueprint.model_dump() if hasattr(blueprint, "model_dump") else (blueprint or {})


def _builder(tc: ToolContext):
    builder = tc.extra.get("builder")
    if builder is None:
        raise ValueError("候选稿 Builder 未初始化")
    return builder


def _short_summary(value: Any, limit: int = 800) -> Any:
    """Keep research artifacts useful without copying full sibling documents."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, list):
        return [_short_summary(item, limit=300) for item in value[:8]]
    if isinstance(value, dict):
        preferred = {
            key: value[key]
            for key in ("id", "type", "artifact_type", "title", "name", "summary", "version")
            if key in value
        }
        if preferred:
            return {
                key: (
                    child if not isinstance(child, str) or len(child) <= 300
                    else child[:299] + "…"
                )
                for key, child in preferred.items()
            }
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class IntentPlannerAgent(Agent):
    key = "intent_planner"
    name = "意图规划"
    role = "识别教师指令意图、范围与结构变化，生成执行计划"
    produced_artifacts = ["lesson_intent"]
    allowed_tools = []

    async def decide(self, tc: ToolContext) -> AgentDecision:
        resolved = getattr(tc.runtime, "resolved_intent", None)
        intent = getattr(resolved, "intent", None) or getattr(tc.runtime, "active_intent", "SECTION_EDIT")
        affected = list(getattr(resolved, "affected_section_ids", None) or getattr(tc.runtime, "selected_section_ids", None) or [])
        output = resolved.model_dump() if hasattr(resolved, "model_dump") else {
            "intent": intent,
            "affected_section_ids": affected,
            "structural": intent in {"RESTRUCTURE", "SECTION_EDIT"},
        }
        return AgentDecision(
            completed=True,
            output=output,
            summary=f"意图识别为 {intent}",
            message=f"已识别教师意图：{intent}",
        )


class ContextResearcherAgent(Agent):
    key = "context_researcher"
    name = "上下文调研"
    role = "深度调研蓝图、Profile、项目材料与兄弟产物，为教学设计建立事实基础"
    produced_artifacts = ["lesson_research"]
    #: 真实 Provider 下由 LLM 深度分析（可读取蓝图/源/材料/兄弟产物/锁）；
    #: Mock / LLM 失败时由 decide() 确定性兜底产出调研摘要。
    allowed_tools = READ_TOOLS

    async def decide(self, tc: ToolContext) -> AgentDecision:
        bp = _blueprint(tc)
        runtime = tc.runtime
        objectives = [
            {"id": item.get("id"), "statement": _short_summary(item.get("behavior", ""), limit=500)}
            for item in bp.get("objectives", [])
        ]
        knowledge_points = [
            {"id": item.get("id"), "name": _short_summary(item.get("name", ""), limit=300)}
            for item in bp.get("knowledge_points", [])
        ]
        stages = [
            {
                "id": item.get("segment_id"), "title": item.get("name"),
                "start_minute": item.get("start_minute"), "end_minute": item.get("end_minute"),
            }
            for item in bp.get("timeline", [])
        ]
        profile_object = getattr(runtime, "profile", None)
        profile = (
            profile_object
            if isinstance(profile_object, dict)
            else getattr(profile_object, "context_json", None)
        ) or {}
        profile_summary = {
            key: _short_summary(profile.get(key), limit=800)
            for key in (
                "mission", "responsibility_boundary", "project_background", "learner_profile",
                "teaching_scenario", "task_goals", "knowledge_focus", "constraints",
            )
            if profile.get(key) not in (None, "", [])
        }
        locks = [
            getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
            for lock in (getattr(runtime, "locks", None) or [])
        ]
        knowledge = getattr(runtime, "knowledge_context", None) or {}
        material_summary = _short_summary(knowledge.get("materials") or [])
        sibling_summary = _short_summary(
            knowledge.get("sibling_artifacts") or knowledge.get("upstream") or {}
        )
        source = getattr(runtime, "source_artifact", None)
        source_content = getattr(source, "content_json", None) or {}
        sections = (source_content.get("outline") or {}).get("sections") or []
        return AgentDecision(
            completed=True, output={
                "blueprint_summary": {
                    "course_identity": bp.get("course_identity") or {},
                    "objectives": objectives,
                    "knowledge_points": knowledge_points,
                    "key_points": bp.get("key_points", []),
                    "difficulty_points": bp.get("difficulty_points", []),
                    "timeline": stages,
                },
                "profile_summary": profile_summary,
                "locked_paths": [path for path in locks if path],
                "materials_summary": material_summary,
                "sibling_artifacts_summary": sibling_summary,
                "source_summary": {
                    "version": getattr(source, "version", None),
                    "section_ids": [str(item.get("id")) for item in sections if item.get("id")],
                    "outline": [
                        {"id": item.get("id"), "title": item.get("title"), "coverage_refs": item.get("coverage_refs", [])}
                        for item in sections
                    ],
                },
            },
            summary="已读取课程蓝图与项目配置",
            message="已梳理蓝图目标与教学环节，作为教学设计事实基础。",
        )


class OutlineArchitectAgent(Agent):
    key = "outline_architect"
    name = "目录设计"
    role = "生成或调整动态展示目录，保持章节 ID 稳定与事实覆盖"
    produced_artifacts = ["lesson_outline"]
    allowed_tools = OUTLINE_TOOLS

    async def decide(self, tc: ToolContext) -> AgentDecision:
        builder = _builder(tc)
        sections = builder.outline
        if not sections:
            # 首次生成：用蓝图驱动的确定性默认目录。
            from app.schemas.lesson_plan import make_lesson_plan_v2

            bp = _blueprint(tc)
            from app.schemas.blueprint import CourseBlueprintSchema

            try:
                v2 = make_lesson_plan_v2(CourseBlueprintSchema.model_validate(bp))
                sections = v2.model_dump()["outline"]["sections"]
                builder.set_outline(sections)
            except Exception:  # noqa: BLE001
                sections = []
        return AgentDecision(
            completed=True,
            output={"outline": sections, "section_count": builder.count_sections()},
            summary="目录结构就绪",
            message="已完成目录结构设计，章节 ID 保持稳定。",
        )


class LessonDesignerAgent(Agent):
    key = "lesson_designer"
    name = "教学设计"
    role = "编写教学内核与章节内容（目标、环节、活动、评价、板书、作业）"
    produced_artifacts = ["lesson_content"]
    allowed_tools = CONTENT_TOOLS

    async def decide(self, tc: ToolContext) -> AgentDecision:
        builder = _builder(tc)
        core = builder.core
        if not core.get("objectives") or not core.get("stages"):
            # 首次生成：用蓝图驱动的确定性内核。
            from app.schemas.blueprint import CourseBlueprintSchema
            from app.schemas.lesson_plan import make_lesson_plan_v2

            bp = _blueprint(tc)
            try:
                v2 = make_lesson_plan_v2(CourseBlueprintSchema.model_validate(bp))
                builder.update_core(v2.pedagogical_core.model_dump())
                core = builder.core
            except Exception:  # noqa: BLE001
                pass
        return AgentDecision(
            completed=True,
            output={"core": core},
            summary="教学内核与章节内容已编写",
            message="已编写教学内核（目标、环节、活动与评价）。",
        )


class FormatNormalizerAgent(Agent):
    key = "format_normalizer"
    name = "格式规范化"
    role = "确定性清理目标章节正文中的硬编码旧序号，不改写正文语义与教学内核"
    produced_artifacts = ["lesson_format"]
    allowed_tools = ["lesson_get_source"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        from app.agent.agents.lesson_plan.formatting import strip_hardcoded_ordinals

        builder = _builder(tc)
        decision = getattr(tc.runtime, "resolved_intent", None)
        targets = list(getattr(decision, "target_section_ids", None) or []) if decision else []
        content = builder.to_content()
        fixed = strip_hardcoded_ordinals(content, targets)
        changed = fixed != content
        if changed:
            builder.replace_content(fixed)
        return AgentDecision(
            completed=True,
            output={
                "changed": changed,
                "target_section_ids": targets,
                "normalized": "strip_hardcoded_numbering",
            },
            summary="格式规范化完成" if changed else "目标章节正文未包含硬编码序号",
            message=(
                "已确定性去除目标章节正文中的硬编码旧序号，章节编号由渲染器统一生成。"
                if changed
                else "目标章节正文未发现需要清理的硬编码序号。"
            ),
        )


class AnswerFinalizerAgent(Agent):
    key = "answer_finalizer"
    name = "问答答复"
    role = "仅回答教师关于教学设计的问题，不生成新版本、不修改任何章节"
    produced_artifacts = ["lesson_answer"]
    #: 确定性节点：不调用模型、不读取源数据、不进入工具循环（max_steps=1）。
    allowed_tools = []

    async def decide(self, tc: ToolContext) -> AgentDecision:
        instruction = tc.ctx.user_instruction if tc.ctx is not None else ""
        return AgentDecision(
            completed=True,
            output={
                "answer": (
                    f"已收到你的问题：「{instruction[:200] if instruction else ''}」。"
                    "当前为纯问答模式，未修改任何教学设计内容。"
                ),
                "mode": "answer_only",
            },
            summary="已回答问题（未修改教学设计）",
            message="已回答教师问题，未修改教学设计。",
        )


class PedagogyQAAgent(Agent):
    key = "pedagogy_qa"
    name = "教学质询"
    role = "独立检查可教性、目标对齐、时长守恒与意图完成度"
    produced_artifacts = ["lesson_qa"]
    allowed_tools = QA_TOOLS

    async def decide(self, tc: ToolContext) -> AgentDecision:
        from app.agent.agents.lesson_plan.qa import (
            build_lesson_plan_verification_report,
            fingerprint,
        )

        builder = _builder(tc)
        bp = _blueprint(tc)
        runtime = getattr(tc, "runtime", None)
        locks = getattr(runtime, "locks", None) if runtime else None
        locked_paths = [
            getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None)
            for lock in (locks or [])
        ]
        baseline = None
        if runtime is not None:
            baseline = getattr(runtime, "baseline_content", None)
            if not baseline and getattr(runtime, "source_artifact", None) is not None:
                baseline = dict(getattr(runtime.source_artifact, "content_json", None) or {})
        decision = getattr(runtime, "resolved_intent", None) if runtime else None
        target_ids = list(getattr(decision, "target_section_ids", None) or []) if decision else []
        numbering_blocking = bool(decision and getattr(decision, "intent", None) == "SECTION_FORMAT_EDIT")
        try:
            from app.schemas.blueprint import CourseBlueprintSchema

            report = build_lesson_plan_verification_report(
                CourseBlueprintSchema.model_validate(bp),
                baseline,
                builder.to_content(),
                locked_paths=locked_paths,
                target_section_ids=target_ids,
                numbering_blocking=numbering_blocking,
            )
        except Exception as exc:  # noqa: BLE001
            report = {
                "passed": False,
                "blocking_issues": [],
                "target_checks": [],
                "scope_checks": [],
                "pedagogical_checks": [],
                "baseline_warnings": [],
                "diff_summary": {},
                "error": str(exc)[:300],
            }
        blocking = list(report.get("blocking_issues") or [])
        return AgentDecision(
            completed=True,
            output={
                "issues": report.get("pedagogical_checks") or [],
                "blocking": blocking,
                "passed": bool(report.get("passed")),
                "fingerprint": fingerprint(blocking),
                "score": max(0, 100 - len(blocking) * 15),
                "verification_report": report,
                "baseline_warnings": report.get("baseline_warnings") or [],
                "target_section_ids": target_ids,
            },
            summary=f"教学质询{'通过' if not blocking else f'发现 {len(blocking)} 个阻断问题'}",
            message=f"教学质询完成：{'全部通过' if not blocking else '存在需要返修的问题。'}",
        )


class RepairRouterAgent(Agent):
    key = "repair_router"
    name = "返修路由"
    role = "依据 QA 问题决定需要重跑的角色与章节"
    produced_artifacts = ["lesson_repair_plan"]
    allowed_tools = ["lesson_get_source", "lesson_get_blueprint", "lesson_validate_alignment"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        issues = getattr(tc.runtime, "blocking_issues", None) or []
        dimensions = {item.get("dimension") for item in issues}
        agents = ["pedagogy_qa"]
        if dimensions & {"structure", "coverage"}:
            agents.insert(0, "outline_architect")
        if dimensions & {"alignment", "timing", "integrity", "lock", "visibility", "content_regression"}:
            agents.insert(0, "lesson_designer")
        return AgentDecision(
            completed=True,
            output={"plan": agents, "issue_count": len(issues), "dimensions": sorted(dimensions)},
            summary=f"返修计划：{', '.join(agents)}",
            message="已规划返修范围。",
        )


class FinalizerAgent(Agent):
    key = "finalizer"
    name = "终稿整合"
    role = "确定性组装最终候选稿：接收验证报告、候选稿与 diff，生成 lesson_plan_draft"
    produced_artifacts = ["lesson_plan_draft"]
    #: 确定性节点：不调用模型、不读取源数据、不执行校验工具（max_steps=1）。
    #: 最终发布门禁只保留在 runtime._finalize，不由模型决定是否发布。
    allowed_tools = []

    async def decide(self, tc: ToolContext) -> AgentDecision:
        builder = _builder(tc)
        content = builder.to_content()
        runtime = getattr(tc, "runtime", None)
        verification = getattr(runtime, "verification_report", None) if runtime else None
        return AgentDecision(
            completed=True,
            output={
                "content": content,
                "schema_version": "2.0",
                "verification_report": verification if verification is not None else {},
            },
            summary="终稿整合完成",
            message="教学设计候选稿已确定性整合（未调用模型与校验工具）。",
        )


INTENT_PLANNER = IntentPlannerAgent()
CONTEXT_RESEARCHER = ContextResearcherAgent()
OUTLINE_ARCHITECT = OutlineArchitectAgent()
LESSON_DESIGNER = LessonDesignerAgent()
FORMAT_NORMALIZER = FormatNormalizerAgent()
ANSWER_FINALIZER = AnswerFinalizerAgent()
PEDAGOGY_QA = PedagogyQAAgent()
REPAIR_ROUTER = RepairRouterAgent()
FINALIZER = FinalizerAgent()

AGENT_BY_KEY: dict[str, Agent] = {
    agent.key: agent
    for agent in (
        INTENT_PLANNER, CONTEXT_RESEARCHER, OUTLINE_ARCHITECT,
        LESSON_DESIGNER, FORMAT_NORMALIZER, ANSWER_FINALIZER,
        PEDAGOGY_QA, REPAIR_ROUTER, FINALIZER,
    )
}

PRODUCED_BY_KEY = {
    key: list(agent.produced_artifacts)
    for key, agent in AGENT_BY_KEY.items()
}


def ensure_lesson_plan_agents() -> None:
    """确保角色与工具注册就绪（幂等）。"""
    register_lesson_plan_tools()


def lesson_plan_spec(key: str) -> dict[str, Any]:
    agent = AGENT_BY_KEY[key]
    max_steps = {
        # 无工具节点：1 步完成（确定性组装/答复/意图展示）。
        "intent_planner": 1,
        "answer_finalizer": 1,
        "finalizer": 1,
        # 真实 Provider 下 LLM 深度分析可能请求只读工具：需要足够轮次完成
        # 「工具调用 → 基于结果完成」，否则 max_steps=1 会在工具执行后直接耗尽。
        "context_researcher": 4,   # 深度调研（可读蓝图/源/材料/兄弟产物/锁）
        "pedagogy_qa": 3,          # LLM 分析 + 只读校验工具
        "repair_router": 3,        # LLM 分析 + 只读路由工具
        "format_normalizer": 3,    # LLM 分析 + 只读源
        "outline_architect": 6,
        "lesson_designer": 6,
    }.get(key, 4)
    return {
        "key": agent.key, "role": agent.role, "description": agent.description,
        "max_steps": max_steps,
    }


def is_mock_provider(provider) -> bool:
    return isinstance(provider, MockProvider)
