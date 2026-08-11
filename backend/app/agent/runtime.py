"""LangGraph-backed PPT Agentic Runtime.

The graph chooses one agent at a time, observes its persisted artifacts/tool results,
honours explicit handoffs, and returns to the orchestrator before the next action.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agent.definitions import AGENT_BY_KEY
from app.agent.pipeline import PipelinePaused, PipelineRuntime, run_agent_loop
from app.agent.schemas import AgentSpec, PipelinePlan, PPTAgentError
from app.agent.schemas import OrchestratorActionDecision, OrchestratorPlanDecision
from app.agent.skills import SkillRegistry, get_skill_registry
from app.agent.state import PPTAgentState, PPTIntent
from app.agent.slide_rendering import (
    render_coverage,
    runtime_baseline_slides,
    semantic_content_changed,
    semantic_content_hash,
    semantic_geometry_hash,
)
from app.providers.llm.mock import MockProvider


INTENT_AGENTS: dict[str, list[str]] = {
    "GENERATE": ["narrative", "template_analysis", "slide_content", "visual_plan", "layout", "media", "ppt_editor", "visual_qa"],
    "MODIFY": ["slide_content", "layout", "media", "ppt_editor", "visual_qa"],
    "LOCAL_REGENERATE": ["slide_content", "layout", "media", "ppt_editor", "visual_qa"],
    "LAYOUT_ONLY": ["layout", "ppt_editor", "visual_qa"],
    "GLOBAL_OPTIMIZE": ["template_analysis", "visual_plan", "layout", "media", "ppt_editor", "visual_qa"],
    "STYLE_CHANGE": ["template_analysis", "layout", "ppt_editor", "visual_qa"],
    "TEMPLATE_SWITCH": ["template_analysis", "layout", "ppt_editor", "visual_qa"],
    "CONTENT_UPDATE": ["slide_content", "layout", "ppt_editor", "visual_qa"],
    "IMAGE_UPDATE": ["visual_plan", "layout", "media", "ppt_editor", "visual_qa"],
    "VISUAL_QA": ["visual_qa"],
    "EXPORT": ["ppt_editor", "visual_qa"],
}

INTENT_CAPABILITIES: dict[str, list[str]] = {
    "GENERATE": ["storytelling", "template-analysis", "layout-design", "teaching-diagram", "visual-qa", "content-qa"],
    "MODIFY": ["layout-design", "slide-repair", "visual-qa", "content-qa"],
    "LOCAL_REGENERATE": ["layout-design", "slide-repair"],
    "LAYOUT_ONLY": ["layout-design", "visual-qa"],
    "GLOBAL_OPTIMIZE": ["layout-design", "visual-qa"],
    "STYLE_CHANGE": ["template-analysis", "template-relayout"],
    "TEMPLATE_SWITCH": ["template-analysis", "template-relayout", "visual-qa"],
    "CONTENT_UPDATE": ["storytelling", "content-qa"],
    "IMAGE_UPDATE": ["teaching-diagram"],
    "VISUAL_QA": ["visual-qa", "content-qa"],
    "EXPORT": ["visual-qa"],
}

MUTATION_INTENTS = {
    "MODIFY", "LOCAL_REGENERATE", "LAYOUT_ONLY", "GLOBAL_OPTIMIZE", "STYLE_CHANGE",
    "TEMPLATE_SWITCH", "CONTENT_UPDATE", "IMAGE_UPDATE",
}
CONTENT_REPAIR_INTENTS = {"GENERATE", "MODIFY", "LOCAL_REGENERATE", "CONTENT_UPDATE"}
RESTORE_MARKERS = (
    "文字不见", "文字描述不见", "文字消失", "文本不见", "文本消失", "文案不见",
    "把文字", "文字被去", "文字去掉", "内容不见", "内容丢失",
    "恢复原", "恢复文字", "恢复内容", "找回文字",
)
EDIT_MARKERS = (
    "改写", "精简", "补充文案", "修改文字", "润色文案", "删掉文字", "删除文字",
    "措辞", "表达", "语句", "用词", "扩写", "缩写", "改字", "改文案",
)
# 布局/排版/留白/分布类诉求：只调整几何与间距，不改语义文字。
LAYOUT_MARKERS = (
    "布局", "排版", "页面分布", "分布", "版式", "间距", "间隔", "留白", "空白",
    "太挤", "太密", "拥挤", "松散", "居中", "对齐", "字距", "行距", "挤成一团",
    "挤在一起", "堆积", "空着", "太空",
)

# 前端单页范围选择：消息前缀 [范围:布局/文字/图片] 显式限定模态（modality）。
_MODALITY_PREFIXES = {
    "布局": "layout",
    "文字": "text",
    "图片": "image",
}


def _modality_from_instruction(instruction: str) -> str:
    """解析消息前缀 [范围:布局/文字/图片] → modality；未指定返回 auto。"""
    match = re.search(r"\[范围:([^\]\s]+)\]", instruction or "")
    if not match:
        return "auto"
    return _MODALITY_PREFIXES.get(match.group(1), "auto")


# 几何/结构性 QA 规则：修复路径不需要重新调用 LLM 换版式，直接对受影响页用引擎
# 按规则换参重编译（确定性收敛），避免审美 LLM 在同一缺陷上反复空转。
DETERMINISTIC_RULES = frozenset({
    "geometry.overlap", "geometry.out_of_bounds", "geometry.text_overflow",
    "geometry.font_too_small", "geometry.min_margin", "geometry.min_gap",
    "geometry.title_in_rail", "layout.vertical_underuse", "layout.cluster_cramming",
    "layout.column_balance", "layout.blank_region", "layout.monotony",
})


def _is_restore_request(text: str) -> bool:
    return any(marker in text for marker in RESTORE_MARKERS) or (
        any(action in text for action in ("恢复", "找回"))
        and any(subject in text for subject in ("文字", "文本", "文案", "内容"))
    )


def _has_positive_edit_request(text: str) -> bool:
    """Recognize explicit edits without treating “不要/不得改写” as permission."""
    import re

    negations = ("不", "不要", "不得", "禁止", "不可", "无需", "不应", "勿")
    for marker in EDIT_MARKERS:
        for match in re.finditer(re.escape(marker), text):
            prefix = text[max(0, match.start() - 4):match.start()]
            if not any(prefix.endswith(negation) for negation in negations):
                return True
    return False


def _has_layout_request(text: str) -> bool:
    return any(marker in text for marker in LAYOUT_MARKERS)


def normalize_agent_plan(intent: str, agents: list[str], content_policy: str = "edit") -> list[str]:
    """Keep dynamic planning, but enforce the dependencies required to mutate slides."""
    filtered = [key for key in dict.fromkeys(agents) if key in AGENT_BY_KEY]
    if content_policy == "restore":
        return ["layout", "ppt_editor", "visual_qa"]
    if intent == "IMAGE_UPDATE":
        return ["visual_plan", "layout", "media", "ppt_editor", "visual_qa"]
    if intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}:
        return ["template_analysis", "layout", "ppt_editor", "visual_qa"]
    if intent == "LAYOUT_ONLY":
        return ["layout", "ppt_editor", "visual_qa"]
    if intent not in {"MODIFY", "LOCAL_REGENERATE"}:
        return filtered
    optional = [
        key for key in filtered
        if key in {"template_analysis", "visual_plan", "media"}
    ]
    return ["slide_content", *optional, "layout", "ppt_editor", "visual_qa"]


def infer_intent(trigger_type: str, instruction: str = "", selected_slide_ids: list[str] | None = None) -> PPTIntent:
    text = instruction.lower()
    # A repair request may mention the image that caused the regression.  The
    # requested action is still text/layout restoration, never another image run.
    if _is_restore_request(text):
        return "LOCAL_REGENERATE" if selected_slide_ids else "MODIFY"
    if "模板" in text or "template" in text:
        return "TEMPLATE_SWITCH"
    if any(marker in text for marker in ("图片", "配图", "插图", "插画", "示意图", "视觉图", "image")):
        return "IMAGE_UPDATE"
    if "检查" in text or "qa" in text or "质检" in text:
        return "VISUAL_QA"
    # 布局/排版/留白/分布类诉求：只改几何与间距，不重写文字，不重生成配图。
    if _has_layout_request(text) and not _has_positive_edit_request(text):
        return "LAYOUT_ONLY"
    if selected_slide_ids:
        return "LOCAL_REGENERATE"
    if trigger_type == "message":
        return "MODIFY"
    if trigger_type in {"sync_context", "sync_dependencies"}:
        return "CONTENT_UPDATE"
    return "GENERATE"


def infer_content_policy(intent: str, instruction: str = "") -> str:
    text = instruction.lower()
    if _has_positive_edit_request(text):
        return "edit"
    if _is_restore_request(text):
        return "restore"
    if intent in {"LAYOUT_ONLY", "IMAGE_UPDATE", "TEMPLATE_SWITCH", "STYLE_CHANGE", "GLOBAL_OPTIMIZE", "VISUAL_QA", "EXPORT"}:
        return "preserve"
    return "edit"


@dataclass
class PPTAgentRuntime:
    pipeline: PipelineRuntime
    skill_registry: SkillRegistry | None = None
    persistent_checkpoints: bool = True

    def __post_init__(self):
        self.skill_registry = self.skill_registry or get_skill_registry()

    def initial_state(self, *, selected_slide_ids: list[str] | None = None) -> PPTAgentState:
        intent = infer_intent(self.pipeline.trigger_type, self.pipeline.context.user_instruction, selected_slide_ids)
        content_policy = infer_content_policy(intent, self.pipeline.context.user_instruction)
        source_slides = runtime_baseline_slides(self.pipeline)
        target_ids = set(selected_slide_ids or [str(item.get("id") or "") for item in source_slides])
        baseline_hashes = {
            str(item.get("id") or ""): semantic_content_hash(item)
            for item in source_slides if str(item.get("id") or "") in target_ids
        }
        return PPTAgentState(
            run_id=self.pipeline.generation_run.id,
            course_id=self.pipeline.course.id,
            artifact_id=getattr(self.pipeline.source_artifact, "id", None),
            user_request=self.pipeline.context.user_instruction,
            intent=intent,
            trigger_type=self.pipeline.trigger_type,
            template_id=self.pipeline.preferred_template,
            selected_slide_ids=selected_slide_ids or [],
            affected_slide_ids=[], draft_artifact_id=None, mutation_applied=False,
            content_policy=content_policy, baseline_content_hashes=baseline_hashes, render_coverage={},
            expected_visual_requests=[], generated_asset_ids=[], mutation_evidence=[],
            publishable=False, blocking_issues=[],
            selected_skills=[], loaded_skills={}, tool_results=[], assets=[], qa_results=[],
            planned_agents=[], remaining_agents=[], completed_agents=[],
            token_usage=dict(self.pipeline.token_usage), repair_round=0,
            current_agent="", next_agent=None, status="running", error=None,
        )

    async def _prepare_restore_baseline(self, selected_slide_ids: list[str] | None) -> None:
        """Build an in-memory authoritative baseline for a restore run.

        Current semantic fields win.  Only fields that are actually empty are
        filled from the newest earlier slide revision that passed QA.  Neither
        the current Artifact nor its V34 database row is modified.
        """
        current = [
            dict(item) for item in
            ((getattr(self.pipeline.source_artifact, "content_json", {}) or {}).get("slides") or [])
        ]
        self.pipeline.baseline_slides = current
        if self.pipeline.content_policy != "restore" or not current:
            return
        target_ids = set(selected_slide_ids or [str(item.get("id") or "") for item in current])
        semantic_fields = ("title", "purpose", "body", "blocks", "speaker_notes")
        missing_by_id = {
            str(item.get("id") or ""): [
                field for field in semantic_fields
                if item.get(field) is None or item.get(field) == "" or item.get(field) == []
            ]
            for item in current
            if str(item.get("id") or "") in target_ids
        }
        missing_by_id = {slide_id: fields for slide_id, fields in missing_by_id.items() if fields}
        if not missing_by_id:
            return

        previous: dict[str, dict[str, Any]] = {}
        source = self.pipeline.source_artifact
        course_id = str(getattr(source, "course_id", "") or getattr(self.pipeline.course, "id", ""))
        source_version = int(getattr(source, "version", 0) or 0)
        if course_id and source_version:
            from sqlalchemy import select
            from app.core.database import SessionLocal
            from app.models.entities import PPTRevision, PPTSlideArtifact, PPTSlideRevision
            async with SessionLocal() as db:
                rows = (await db.execute(
                    select(PPTSlideRevision, PPTSlideArtifact.slide_id, PPTRevision.version)
                    .join(PPTSlideArtifact, PPTSlideArtifact.id == PPTSlideRevision.slide_artifact_id)
                    .join(PPTRevision, PPTRevision.id == PPTSlideArtifact.ppt_revision_id)
                    .where(
                        PPTRevision.course_id == course_id,
                        PPTRevision.version < source_version,
                        PPTSlideArtifact.slide_id.in_(list(missing_by_id)),
                        PPTSlideArtifact.status == "ready",
                        PPTSlideArtifact.qa_status == "passed",
                    )
                    .order_by(PPTRevision.version.desc(), PPTSlideRevision.revision.desc())
                )).all()
            for revision, slide_id, _version in rows:
                previous.setdefault(str(slide_id), dict(revision.data_json or {}))

        restored_ids: list[str] = []
        effective: list[dict[str, Any]] = []
        for item in current:
            slide_id = str(item.get("id") or "")
            merged = dict(item)
            old = previous.get(slide_id)
            for field in missing_by_id.get(slide_id, []):
                previous_value = old.get(field) if old is not None else None
                if previous_value is not None and previous_value != "" and previous_value != []:
                    merged[field] = previous_value
            if merged != item:
                restored_ids.append(slide_id)
            effective.append(merged)
        self.pipeline.baseline_slides = effective
        if self.pipeline.builder is not None:
            effective_by_id = {str(item.get("id") or ""): item for item in effective}
            for slide in self.pipeline.builder.slides:
                baseline = effective_by_id.get(str(slide.get("id") or ""))
                if baseline:
                    for field in semantic_fields:
                        slide[field] = baseline.get(field, slide.get(field))
        if restored_ids:
            self.pipeline.context.add_note(f"已从上一条有效页面修订恢复缺失语义字段：{restored_ids}")

    def _build_graph(self, checkpointer):
        graph = StateGraph(PPTAgentState)

        async def load_context(state: PPTAgentState) -> dict[str, Any]:
            return {
                "course_context": {"course_id": state["course_id"]},
                "current_ppt": getattr(self.pipeline.source_artifact, "content_json", {}) if self.pipeline.source_artifact else {},
                "teaching_design": self.pipeline.context.upstream,
                "status": "running",
            }

        async def orchestrator(state: PPTAgentState) -> dict[str, Any]:
            planned = list(state.get("planned_agents") or [])
            remaining = list(state.get("remaining_agents") or [])
            completed = list(state.get("completed_agents") or [])
            selected = list(state.get("selected_skills") or [])
            loaded = dict(state.get("loaded_skills") or {})
            messages = list(state.get("messages") or [])
            selected_slide_ids = list(state.get("selected_slide_ids") or [])
            effective_intent = state.get("intent", "GENERATE")
            queued_received = False
            from sqlalchemy import select
            from app.core.database import SessionLocal
            from app.models.entities import PPTAgentInstruction, PipelineRun
            async with SessionLocal() as db:
                queued = list(await db.scalars(select(PPTAgentInstruction).where(
                    PPTAgentInstruction.pipeline_run_id == self.pipeline.pipeline_run.id,
                    PPTAgentInstruction.disposition == "queued",
                ).order_by(PPTAgentInstruction.created_at)))
                queued_received = bool(queued)
                for instruction in queued:
                    urgent = any(word in instruction.content for word in ("立即", "先停止", "优先处理"))
                    instruction.disposition = "interrupted" if urgent else "merged"
                    self.pipeline.context.user_instruction = "\n".join(filter(None, [self.pipeline.context.user_instruction, instruction.content]))
                    selected_slide_ids = list(dict.fromkeys([*selected_slide_ids, *instruction.selected_slide_ids_json]))
                    messages.append({"role": "user", "content": instruction.content, "instruction_id": instruction.id})
                    await self.pipeline.emitter.emit_domain(
                        "run.instruction.interrupted" if urgent else "run.instruction.merged",
                        message="新指令已合并到当前计划" if not urgent else "新指令将在当前 Agent 边界优先执行",
                        payload={"instruction_id": instruction.id, "selected_slide_ids": instruction.selected_slide_ids_json},
                    )
                    effective_intent = infer_intent("message", instruction.content, selected_slide_ids)
                    self.pipeline.active_intent = effective_intent
                    self.pipeline.content_policy = infer_content_policy(effective_intent, instruction.content)
                    instruction_agents = normalize_agent_plan(
                        effective_intent,
                        [key for key in INTENT_AGENTS[effective_intent] if key in AGENT_BY_KEY],
                        self.pipeline.content_policy,
                    )
                    # 新指令必须重新运行受影响 Agent；不能因它们在旧计划中 completed 而直接结束。
                    completed = [key for key in completed if key not in instruction_agents]
                    remaining = list(dict.fromkeys(
                        [*instruction_agents, *remaining] if urgent else [*remaining, *instruction_agents]
                    ))
                if queued:
                    row = await db.get(PipelineRun, self.pipeline.pipeline_run.id)
                    if row:
                        row.checkpoint_json = {**(row.checkpoint_json or {}), "queued_instruction_ids": [item.id for item in queued]}
                    await db.commit()
            if not planned:
                fallback_agents = [key for key in INTENT_AGENTS.get(effective_intent, INTENT_AGENTS["GENERATE"]) if key in AGENT_BY_KEY]
                capabilities = INTENT_CAPABILITIES.get(effective_intent, [])
                plan_summary = "已根据任务意图创建执行计划"
                if not isinstance(self.pipeline.provider, MockProvider):
                    try:
                        decision = await self.pipeline.provider.structured(
                            "你是 PPT Runtime Orchestrator。只规划必要 Agent 和 Skill capability，不输出隐藏推理。",
                            "任务状态：" + str({
                                "intent": effective_intent, "request": state.get("user_request", ""),
                                "selected_slide_ids": selected_slide_ids,
                                "available_agents": list(AGENT_BY_KEY),
                                "available_skill_metadata": [item.public_dict() for item in self.skill_registry.all_metadata()],
                            }),
                            OrchestratorPlanDecision,
                        )
                        self.pipeline.token_usage["llm_calls"] += 1
                        planned = list(dict.fromkeys(key for key in decision.agents if key in AGENT_BY_KEY)) or fallback_agents
                        capabilities = decision.skill_capabilities or capabilities
                        plan_summary = decision.summary or plan_summary
                    except Exception:
                        planned = fallback_agents
                else:
                    planned = fallback_agents
                planned = normalize_agent_plan(effective_intent, planned, self.pipeline.content_policy)
                remaining = list(planned)
                candidates = self.skill_registry.discover(capabilities)
                selected = [item.name for item in candidates]
                await self.pipeline.emitter.emit_domain("plan.created", message=plan_summary, payload={"agents": planned, "skills": selected})
                async with SessionLocal() as db:
                    row = await db.get(PipelineRun, self.pipeline.pipeline_run.id)
                    if row:
                        row.plan_json = {"agents": planned, "skills": selected, "intent": effective_intent}
                        await db.commit()
                for item in candidates:
                    await self.pipeline.emitter.emit_domain("skill.discovered", message=f"发现 Skill：{item.name}", payload=item.public_dict())
            handoff = self.pipeline.requested_handoff
            self.pipeline.requested_handoff = None
            strict_order = effective_intent == "IMAGE_UPDATE" and self.pipeline.content_policy != "restore"
            if handoff and not strict_order and handoff in AGENT_BY_KEY and handoff not in completed:
                remaining = [handoff, *[key for key in remaining if key != handoff]]
                await self.pipeline.emitter.emit_domain("agent.handoff", agent={"id": state.get("current_agent", "")}, message=f"交接给 {handoff}", payload={"to": handoff})
            if not remaining:
                if effective_intent in MUTATION_INTENTS and not self.pipeline.mutation_applied:
                    required = normalize_agent_plan(effective_intent, INTENT_AGENTS.get(effective_intent, []), self.pipeline.content_policy)
                    remaining = [key for key in required if key not in completed or key == "ppt_editor"]
                    completed = [key for key in completed if key not in set(remaining)]
                if not remaining:
                    return {"planned_agents": planned, "remaining_agents": [], "completed_agents": completed,
                            "selected_skills": selected, "loaded_skills": loaded, "next_agent": None,
                            "status": "completed", "intent": effective_intent, "messages": messages,
                            "selected_slide_ids": selected_slide_ids,
                            "affected_slide_ids": list(self.pipeline.affected_slide_ids),
                            "draft_artifact_id": self.pipeline.draft_artifact_id,
                            "mutation_applied": self.pipeline.mutation_applied,
                            "content_policy": self.pipeline.content_policy,
                            "baseline_content_hashes": dict(self.pipeline.baseline_content_hashes),
                            "render_coverage": dict(self.pipeline.render_coverage),
                            "expected_visual_requests": list(self.pipeline.expected_visual_requests),
                            "generated_asset_ids": list(self.pipeline.generated_asset_ids),
                            "mutation_evidence": list(self.pipeline.mutation_evidence),
                            "publishable": self.pipeline.publishable,
                            "blocking_issues": list(self.pipeline.blocking_issues)}
            next_agent = remaining[0]
            if not strict_order and not isinstance(self.pipeline.provider, MockProvider) and len(remaining) > 1:
                try:
                    action = await self.pipeline.provider.structured(
                        "你是 PPT Runtime Orchestrator。根据已完成产物选择下一位必要 Agent；不要输出隐藏推理。",
                        "当前状态：" + str({
                            "intent": state.get("intent"), "completed_agents": completed,
                            "remaining_agents": remaining, "latest_decisions": self.pipeline.context.decisions[-4:],
                            "latest_tool_results": [self.pipeline.context._block_dict(item) for item in self.pipeline.context.tool_results[-4:]],
                        }),
                        OrchestratorActionDecision,
                    )
                    self.pipeline.token_usage["llm_calls"] += 1
                    required_before_finish = {"ppt_editor", "visual_qa"} if effective_intent in MUTATION_INTENTS else set()
                    if action.action == "finish" and completed and required_before_finish <= set(completed) and not queued_received and (
                        effective_intent not in MUTATION_INTENTS or self.pipeline.mutation_applied
                    ):
                        remaining = []
                        return {"planned_agents": planned, "remaining_agents": [], "completed_agents": completed,
                                "selected_skills": selected, "loaded_skills": loaded, "next_agent": None,
                                "status": "completed", "messages": messages, "selected_slide_ids": selected_slide_ids}
                    if action.next_agent in remaining:
                        next_agent = action.next_agent
                    for item in self.skill_registry.discover(action.discover_capabilities):
                        if item.name not in selected:
                            selected.append(item.name)
                            await self.pipeline.emitter.emit_domain("skill.discovered", message=f"运行中发现 Skill：{item.name}", payload=item.public_dict())
                except Exception:
                    pass
            remaining = [key for key in remaining if key != next_agent]
            relevant = [name for name in selected if not self.skill_registry.is_loaded(name)]
            for name in relevant[:2]:
                body = self.skill_registry.load(name)
                loaded[name] = body
                self.pipeline.context.add_note(f"已加载 Skill {name}：\n{body}")
                await self.pipeline.emitter.emit_domain("skill.loaded", message=f"已加载 Skill：{name}", payload={"name": name})
            return {"planned_agents": planned, "remaining_agents": remaining, "completed_agents": completed,
                    "selected_skills": selected, "loaded_skills": loaded, "next_agent": next_agent,
                    "current_agent": next_agent, "messages": messages,
                    "selected_slide_ids": selected_slide_ids,
                    "intent": effective_intent,
                    "user_request": self.pipeline.context.user_instruction}

        async def execute_agent(state: PPTAgentState) -> dict[str, Any]:
            key = state.get("next_agent")
            if not key:
                return {"status": "completed"}
            agent = AGENT_BY_KEY[key]
            spec = AgentSpec(key=key, role=agent.role, description=agent.description, max_steps=8)
            await run_agent_loop(self.pipeline, PipelinePlan(agents=[spec], revision_rounds=self.pipeline.pipeline_run.max_revision_rounds), start_step=0)
            completed = [*state.get("completed_agents", []), key]
            update: dict[str, Any] = {
                "completed_agents": completed,
                "tool_results": [self.pipeline.context._block_dict(item) for item in self.pipeline.context.tool_results],
                "token_usage": dict(self.pipeline.token_usage), "next_agent": None,
                "affected_slide_ids": list(self.pipeline.affected_slide_ids),
                "draft_artifact_id": self.pipeline.draft_artifact_id,
                "mutation_applied": self.pipeline.mutation_applied,
                "content_policy": self.pipeline.content_policy,
                "baseline_content_hashes": dict(self.pipeline.baseline_content_hashes),
                "render_coverage": dict(self.pipeline.render_coverage),
                "expected_visual_requests": list(self.pipeline.expected_visual_requests),
                "generated_asset_ids": list(self.pipeline.generated_asset_ids),
                "mutation_evidence": list(self.pipeline.mutation_evidence),
                "publishable": self.pipeline.publishable,
                "blocking_issues": list(self.pipeline.blocking_issues),
            }
            if key == "visual_qa" and self.pipeline.artifacts is not None:
                live_visual = self.pipeline.context.get_tool_output("run_qa") or {}
                live_content = self.pipeline.context.get_tool_output("run_content_qa") or {}
                qa_datasets = [live_visual]
                if self.pipeline.active_intent in CONTENT_REPAIR_INTENTS and self.pipeline.content_policy == "edit":
                    qa_datasets.append(live_content)
                issues = [
                    item for data in qa_datasets
                    for item in data.get("issues", [])
                    if item.get("severity") in {"critical", "major"}
                    and (
                        not self.pipeline.selected_slide_ids
                        or str(item.get("slide_id") or "") in set(self.pipeline.selected_slide_ids)
                    )
                ]
                repair_round = int(state.get("repair_round") or 0)
                if issues and repair_round < self.pipeline.pipeline_run.max_revision_rounds:
                    deterministic = [i for i in issues if i.get("rule_id") in DETERMINISTIC_RULES]
                    aesthetic = [i for i in issues if i.get("rule_id") not in DETERMINISTIC_RULES]
                    targets = (
                        ["layout"]
                        if self.pipeline.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}
                        else list(dict.fromkeys(item.get("target_agent", "layout") for item in issues))
                    )
                    if self.pipeline.content_policy in {"preserve", "restore"}:
                        targets = ["layout" if target == "slide_content" else target for target in targets]
                    targets = [target for target in targets if target in AGENT_BY_KEY and target != "visual_qa"]
                    if deterministic and not aesthetic:
                        # 几何类 → 不重调 LLM，直接对受影响页用引擎按规则换参重编译（确定性收敛）。
                        # repair_mode 同时写入 pipeline 与 state（state 由 LangGraph 忽略未声明键，
                        # 布局引擎经 runtime 读取确定性分支参数）。
                        self.pipeline.repair_mode = "deterministic"
                        update["repair_mode"] = "deterministic"
                        update["remaining_agents"] = list(dict.fromkeys(["layout", "ppt_editor", "visual_qa"]))
                    else:
                        # 审美类 → LLM 换版式（带上一版失败反馈）。
                        feedback = "；".join(f"{i.get('rule_id')}:{i.get('message','')[:60]}" for i in issues[:8])
                        self.pipeline.context.add_note(f"视觉自检反馈：{feedback}，请更换版式或调整参数")
                        self.pipeline.repair_mode = "llm_feedback"
                        update["repair_mode"] = "llm_feedback"
                        update["remaining_agents"] = list(dict.fromkeys(["revision", *targets, "ppt_editor", "visual_qa"]))
                    update["repair_round"] = repair_round + 1
                    from app.renderers.presentation_builder import PresentationBuilder
                    current_content = self.pipeline.builder.to_ppt_content() if self.pipeline.builder is not None else (
                        getattr(self.pipeline.source_artifact, "content_json", {}) or {}
                    )
                    self.pipeline.builder = PresentationBuilder(self.pipeline.preferred_template).from_ppt_content(current_content)
                    self.pipeline.tool_context.builder = self.pipeline.builder
                    self.pipeline.mutation_applied = False
                    # QA tools are idempotent only for one builder revision. Remove
                    # their previous results so the repaired revision is checked once.
                    self.pipeline.context.tool_results = [
                        block for block in self.pipeline.context.tool_results
                        if block.tool_name not in {"render_preview", "run_qa", "run_content_qa"}
                    ]
                    await self.pipeline.emitter.emit_domain("repair.started", message=f"开始第 {repair_round + 1} 轮页面修复", payload={"target_agents": targets, "issues": issues[:20]})
                elif issues:
                    self.pipeline.blocking_issues = list(issues)
                    if self.pipeline.active_intent == "IMAGE_UPDATE":
                        rules = {str(item.get("rule_id") or "") for item in issues}
                        if "layout.incomplete_absolute" in rules:
                            error_code, error_message = "layout_incomplete", "图片布局没有覆盖页面全部必要文字，已保留原 PPT 版本。"
                        elif "content.not_rendered" in rules:
                            error_code, error_message = "content_not_rendered", "页面文字没有完整进入最终渲染层，已保留原 PPT 版本。"
                        elif "content.accidentally_removed" in rules:
                            error_code, error_message = "content_accidentally_removed", "图片润色意外修改了页面文字，已保留原 PPT 版本。"
                        else:
                            error_code, error_message = "qa_blocked", "生成图片未通过目标页质量检查，已保留原 PPT 版本。"
                        raise PPTAgentError(
                            error_code, error_message,
                            retryable=True, details={"issues": issues[:20]},
                        )
                    if self.pipeline.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}:
                        raise PPTAgentError(
                            "template_switch_qa_failed", "新模板布局未通过视觉质量检查，已保留原 PPT 版本。",
                            retryable=True, details={"issues": issues[:20]},
                        )
                    from app.models.entities import PPTHumanRequest
                    from app.core.database import SessionLocal
                    async with SessionLocal() as db:
                        request = PPTHumanRequest(
                            pipeline_run_id=self.pipeline.pipeline_run.id,
                            request_type="repair_limit",
                            prompt="自动修复已达到上限，是否保留当前版本？",
                            options_json=[
                                {"id": "keep", "label": "保留当前版本"},
                                {"id": "review", "label": "进入人工检查"},
                            ],
                        )
                        db.add(request)
                        await db.commit()
                        request_id = request.id
                    await self.pipeline.emitter.emit_domain(
                        "human.required", message="自动修复达到上限，需要教师确认",
                        payload={"request_id": request_id, "issues": issues[:20], "options": [
                            {"id": "keep", "label": "保留当前版本"},
                            {"id": "review", "label": "进入人工检查"},
                        ]},
                    )
            return update

        def route(state: PPTAgentState) -> str:
            return "finish" if state.get("status") == "completed" else "agent"

        graph.add_node("load_context", load_context)
        graph.add_node("orchestrator", orchestrator)
        graph.add_node("agent_executor", execute_agent)
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "orchestrator")
        graph.add_conditional_edges("orchestrator", route, {"agent": "agent_executor", "finish": END})
        graph.add_edge("agent_executor", "orchestrator")
        return graph.compile(checkpointer=checkpointer)

    async def run(self, *, selected_slide_ids: list[str] | None = None) -> PPTAgentState:
        self.pipeline.selected_slide_ids = list(selected_slide_ids or [])
        provisional_intent = infer_intent(
            self.pipeline.trigger_type, self.pipeline.context.user_instruction, selected_slide_ids,
        )
        self.pipeline.active_intent = provisional_intent
        self.pipeline.content_policy = infer_content_policy(
            provisional_intent, self.pipeline.context.user_instruction,
        )
        await self._prepare_restore_baseline(selected_slide_ids)
        initial = self.initial_state(selected_slide_ids=selected_slide_ids)
        self.pipeline.active_intent = initial["intent"]
        self.pipeline.content_policy = initial["content_policy"]
        self.pipeline.baseline_content_hashes = dict(initial["baseline_content_hashes"])
        # Task 7: LLM 结构化意图提取；Mock/失败返回 None，由关键词 infer_intent 兜底。
        # modality 显式覆盖：前端单页范围选择（[范围:布局/文字/图片]）优先于意图提取。
        from app.agent.intents import dimension_to_engine_params, extract_polish_intent

        self.pipeline.modality = _modality_from_instruction(self.pipeline.context.user_instruction)
        self.pipeline.polish_intent = await extract_polish_intent(self.pipeline)
        if self.pipeline.polish_intent is not None:
            params = dimension_to_engine_params(self.pipeline.polish_intent)
            if params:
                self.pipeline.context.add_note(
                    f"润色意图：{self.pipeline.polish_intent.summary}；引擎参数 {params}"
                )
        modality = getattr(self.pipeline, "modality", "auto")
        if modality in {"layout", "text", "image"}:
            self.pipeline.active_intent = {
                "layout": "LAYOUT_ONLY", "text": "MODIFY", "image": "IMAGE_UPDATE",
            }[modality]
            self.pipeline.content_policy = "preserve" if modality in {"layout", "image"} else "edit"
        config = {"configurable": {"thread_id": self.pipeline.generation_run.id}, "recursion_limit": 100}
        if not self.persistent_checkpoints:
            final = await self._build_graph(MemorySaver()).ainvoke(initial, config)
            await self._assert_publishable(final)
            for name in final.get("selected_skills", []):
                await self.pipeline.emitter.skill_completed(name)
            return final
        checkpoint_path = Path(self.pipeline.workspace_root) / "checkpoints.sqlite"
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            graph = self._build_graph(saver)
            existing = await saver.aget_tuple(config)
            final = await graph.ainvoke(None if existing else initial, config)
            await self._assert_publishable(final)
            for name in final.get("selected_skills", []):
                await self.pipeline.emitter.skill_completed(name)
            return final

    async def _assert_publishable(self, final: PPTAgentState) -> None:
        """Apply the strict publish gate before the domain Artifact can be saved."""
        if self.pipeline.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}:
            self._assert_template_switch_integrity(final)
            return
        if self.pipeline.active_intent != "IMAGE_UPDATE":
            qa_data = self.pipeline.context.get_tool_output("run_qa") or {}
            blocking = [
                item for item in qa_data.get("issues", [])
                if item.get("severity") in {"critical", "major"}
                and (
                    not self.pipeline.selected_slide_ids
                    or str(item.get("slide_id") or "") in set(self.pipeline.selected_slide_ids)
                )
            ]
            self.pipeline.blocking_issues = blocking
            if blocking:
                rules = {str(item.get("rule_id") or "") for item in blocking}
                if "layout.incomplete_absolute" in rules:
                    error_code = "layout_incomplete"
                    error_message = "绝对布局没有覆盖页面全部必要文字，已保留原 PPT 版本。"
                elif "content.not_rendered" in rules:
                    error_code = "content_not_rendered"
                    error_message = "页面文字没有完整进入最终版式，已保留原 PPT 版本。"
                elif "content.accidentally_removed" in rules:
                    error_code = "content_accidentally_removed"
                    error_message = "页面语义内容被意外修改，已保留原 PPT 版本。"
                else:
                    error_code = "qa_blocked"
                    error_message = "页面未通过发布前质量检查，已保留原 PPT 版本。"
                raise PPTAgentError(
                    error_code, error_message,
                    retryable=True, details={"issues": blocking[:20]},
                )
            if self.pipeline.content_policy in {"preserve", "restore"}:
                source_slides = {
                    str(item.get("id") or ""): item
                    for item in runtime_baseline_slides(self.pipeline)
                }
                current_slides = {
                    str(item.get("id") or ""): item
                    for item in ((self.pipeline.builder.to_ppt_content() if self.pipeline.builder is not None else {}).get("slides") or [])
                }
                target_ids = set(self.pipeline.selected_slide_ids or source_slides)
                changed = [
                    slide_id for slide_id in target_ids
                    if slide_id not in source_slides or slide_id not in current_slides
                    or semantic_content_changed(source_slides[slide_id], current_slides[slide_id])
                ]
                if changed:
                    raise PPTAgentError(
                        "content_accidentally_removed", "视觉或恢复任务意外修改了页面文字，已保留原 PPT 版本。",
                        retryable=True, details={"slides": sorted(changed)},
                    )
                coverage = {
                    slide_id: render_coverage(current_slides[slide_id], baseline=source_slides[slide_id])
                    for slide_id in target_ids if slide_id in source_slides and slide_id in current_slides
                }
                self.pipeline.render_coverage = coverage
                missing = {slide_id: item["missing_refs"] for slide_id, item in coverage.items() if item["missing_refs"]}
                if missing:
                    incomplete_absolute = any(coverage[slide_id]["mode"] == "absolute" for slide_id in missing)
                    raise PPTAgentError(
                        "layout_incomplete" if incomplete_absolute else "content_not_rendered",
                        "绝对布局没有覆盖页面全部必要文字，已保留原 PPT 版本。" if incomplete_absolute
                        else "页面文字没有完整进入最终版式，已保留原 PPT 版本。",
                        retryable=True, details={"missing": missing},
                    )
                # 单调性门禁：preserve/restore 必须产生实际几何变化，否则视为修复收敛到空转。
                unchanged = [
                    slide_id for slide_id in target_ids
                    if slide_id in source_slides and slide_id in current_slides
                    and semantic_geometry_hash(source_slides[slide_id]) == semantic_geometry_hash(current_slides[slide_id])
                ]
                if unchanged:
                    self.pipeline.blocking_issues.append({
                        "severity": "major", "slide_id": unchanged[0], "rule_id": "layout.monotony",
                        "message": "润色后页面布局没有实际变化", "target_agent": "layout",
                    })
                    raise PPTAgentError(
                        "layout_monotony", "润色后页面布局没有实际变化，已保留原 PPT 版本。",
                        retryable=True, details={"slides": sorted(unchanged)},
                    )
            self.pipeline.publishable = True
            final["publishable"] = True
            return
        expected = list(self.pipeline.expected_visual_requests)
        expected_slides = {str(item.get("slide_id") or "") for item in expected if item.get("slide_id")}
        if not expected or expected_slides != set(self.pipeline.selected_slide_ids or expected_slides):
            raise PPTAgentError(
                "visual_plan_invalid", "图片生成计划没有完整覆盖目标页面，已保留原 PPT 版本。",
                retryable=True, details={"expected_slides": sorted(expected_slides)},
            )
        if len(set(self.pipeline.generated_asset_ids)) < len(expected):
            raise PPTAgentError(
                "image_generation_failed", "目标页面没有获得本轮真实生成的图片，已保留原 PPT 版本。",
                retryable=True, details={"generated_asset_ids": self.pipeline.generated_asset_ids},
            )
        applied_slides = {
            str(item.get("slide_id") or "") for item in self.pipeline.mutation_evidence
            if item.get("kind") == "image" and item.get("asset_id") in set(self.pipeline.generated_asset_ids)
        }
        if expected_slides - applied_slides or not self.pipeline.mutation_applied:
            raise PPTAgentError(
                "image_not_applied", "生成图片没有真实写入全部目标页面，已保留原 PPT 版本。",
                retryable=True, details={"missing_slides": sorted(expected_slides - applied_slides)},
            )
        if expected_slides - set(self.pipeline.affected_slide_ids):
            raise PPTAgentError(
                "image_not_applied", "目标页面没有产生有效页面 Patch，已保留原 PPT 版本。",
                retryable=True,
            )
        source_slides = {
            str(item.get("id") or ""): item
            for item in runtime_baseline_slides(self.pipeline)
        }
        current_slides = {
            str(item.get("id") or ""): item
            for item in ((self.pipeline.builder.to_ppt_content() if self.pipeline.builder is not None else {}).get("slides") or [])
        }
        self._assert_image_scope_integrity(source_slides, current_slides, expected_slides)
        changed_content = [
            slide_id for slide_id in expected_slides
            if slide_id not in current_slides or slide_id not in source_slides
            or semantic_content_changed(source_slides[slide_id], current_slides[slide_id])
        ]
        if changed_content:
            raise PPTAgentError(
                "content_accidentally_removed", "图片润色意外修改了页面文字，已保留原 PPT 版本。",
                retryable=True, details={"slides": sorted(changed_content)},
            )
        coverage = {
            slide_id: render_coverage(current_slides[slide_id], baseline=source_slides[slide_id])
            for slide_id in expected_slides if slide_id in current_slides and slide_id in source_slides
        }
        self.pipeline.render_coverage = coverage
        missing_content = {slide_id: item["missing_refs"] for slide_id, item in coverage.items() if item["missing_refs"]}
        if missing_content:
            incomplete_absolute = any(coverage[slide_id]["mode"] == "absolute" for slide_id in missing_content)
            raise PPTAgentError(
                "layout_incomplete" if incomplete_absolute else "content_not_rendered",
                "图片布局没有覆盖页面全部必要文字，已保留原 PPT 版本。" if incomplete_absolute
                else "图片已生成，但页面文字没有完整进入最终版式，已保留原 PPT 版本。",
                retryable=True, details={"missing": missing_content},
            )
        qa_data = self.pipeline.context.get_tool_output("run_qa") or {}
        if not qa_data or "score" not in qa_data or "issues" not in qa_data:
            raise PPTAgentError(
                "qa_unavailable", "目标页面没有获得本轮有效质量检查，已保留原 PPT 版本。",
                retryable=True,
            )
        blocking = [item for item in qa_data.get("issues", []) if item.get("severity") in {"critical", "major"}]
        self.pipeline.blocking_issues = blocking
        if blocking:
            raise PPTAgentError(
                "qa_blocked", "生成图片未通过目标页质量检查，已保留原 PPT 版本。",
                retryable=True, details={"issues": blocking[:20]},
            )
        self.pipeline.publishable = True
        final["publishable"] = True
        final["blocking_issues"] = []

    @staticmethod
    def _assert_image_scope_integrity(
        source_slides: dict[str, dict[str, Any]],
        current_slides: dict[str, dict[str, Any]],
        target_ids: set[str],
    ) -> None:
        """An image-only run may change geometry/assets only on target pages."""
        if list(source_slides) != list(current_slides):
            raise PPTAgentError(
                "content_accidentally_removed", "图片润色改变了页面数量或顺序，已保留原 PPT 版本。",
                retryable=True,
                details={"source_slide_ids": list(source_slides), "current_slide_ids": list(current_slides)},
            )
        stable_fields = (
            "page_type", "title", "purpose", "body", "blocks", "layout",
            "visual_suggestion", "speaker_notes", "duration_seconds",
            "script_segment_ids", "elements",
        )
        changed_non_targets = [
            slide_id for slide_id in source_slides if slide_id not in target_ids
            if any(
                source_slides[slide_id].get(field, [] if field in {"body", "blocks", "script_segment_ids", "elements"} else "")
                != current_slides[slide_id].get(field, [] if field in {"body", "blocks", "script_segment_ids", "elements"} else "")
                for field in stable_fields
            )
        ]
        if changed_non_targets:
            raise PPTAgentError(
                "content_accidentally_removed", "图片润色修改了目标页之外的内容或元素，已保留原 PPT 版本。",
                retryable=True, details={"slides": changed_non_targets},
            )

    def _assert_template_switch_integrity(self, final: PPTAgentState) -> None:
        """模板切换只能改变设计系统和几何，不得丢页、改内容或丢视觉资源。"""
        source = getattr(self.pipeline.source_artifact, "content_json", {}) or {}
        source_slides = list(source.get("slides") or [])
        current = self.pipeline.builder.to_ppt_content() if self.pipeline.builder is not None else {}
        current_slides = list(current.get("slides") or [])
        source_ids = [str(item.get("id") or "") for item in source_slides]
        current_ids = [str(item.get("id") or "") for item in current_slides]
        if source_ids != current_ids:
            raise PPTAgentError(
                "template_switch_content_changed", "模板切换改变了页面数量或顺序，已保留原 PPT 版本。",
                retryable=True, details={"source_slide_ids": source_ids, "current_slide_ids": current_ids},
            )
        current_by_id = {str(item.get("id") or ""): item for item in current_slides}
        content_fields = ("title", "purpose", "body", "blocks", "speaker_notes", "duration_seconds")
        defaults: dict[str, Any] = {
            "title": "", "purpose": "", "body": [], "blocks": [],
            "speaker_notes": "", "duration_seconds": 0,
        }
        changed = [
            slide_id for slide_id, source_slide in zip(source_ids, source_slides)
            if any(
                source_slide.get(field, defaults[field]) != current_by_id[slide_id].get(field, defaults[field])
                for field in content_fields
            )
        ]
        if changed:
            raise PPTAgentError(
                "template_switch_content_changed", "模板切换意外修改了课件内容，已保留原 PPT 版本。",
                retryable=True, details={"slides": changed},
            )
        missing_visuals: list[dict[str, str]] = []
        for slide_id, source_slide in zip(source_ids, source_slides):
            target_elements = current_by_id[slide_id].get("elements") or []
            target_images = {
                (str(item.get("asset_id") or ""), str(item.get("asset_path") or ""))
                for item in target_elements if item.get("kind") == "image"
            }
            target_chart_count = sum(item.get("kind") == "chart" for item in target_elements)
            source_charts = [item for item in (source_slide.get("elements") or []) if item.get("kind") == "chart"]
            for image in [item for item in (source_slide.get("elements") or []) if item.get("kind") == "image"]:
                identity = (str(image.get("asset_id") or ""), str(image.get("asset_path") or ""))
                if identity not in target_images:
                    missing_visuals.append({"slide_id": slide_id, "asset_id": identity[0], "asset_path": identity[1]})
            if len(source_charts) > target_chart_count:
                missing_visuals.append({"slide_id": slide_id, "asset_id": "chart", "asset_path": ""})
        if missing_visuals:
            raise PPTAgentError(
                "template_switch_visual_lost", "模板切换未能保留全部图片或图表，已保留原 PPT 版本。",
                retryable=True, details={"missing_visuals": missing_visuals[:20]},
            )
        if not self.pipeline.mutation_applied or current.get("theme") != self.pipeline.preferred_template:
            raise PPTAgentError(
                "template_switch_not_applied", "新模板没有完整应用，已保留原 PPT 版本。",
                retryable=True,
            )
        self.pipeline.publishable = True
        final["publishable"] = True
        final["blocking_issues"] = []
