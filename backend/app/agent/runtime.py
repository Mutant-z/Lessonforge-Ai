"""LangGraph-backed PPT Agentic Runtime.

The graph chooses one agent at a time, observes its persisted artifacts/tool results,
honours explicit handoffs, and returns to the orchestrator before the next action.
"""
from __future__ import annotations

import asyncio
import json
import re
from copy import deepcopy
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
    canonical_slide_id, render_coverage,
    runtime_baseline_slides,
    semantic_content_changed,
    semantic_content_hash,
    semantic_visual_hash,
    objective_result_passed,
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
    "挤在一起", "堆积", "空着", "太空", "放大", "缩小", "字号", "字体大小",
    "卡片大小", "元素大小", "大一点", "小一点",
)

POLISH_ACTION_INTENTS: dict[str, PPTIntent] = {
    "layout_only": "LAYOUT_ONLY",
    "text_polish": "MODIFY",
    "image_only": "IMAGE_UPDATE",
    "template_switch": "TEMPLATE_SWITCH",
    "full_regenerate": "MODIFY",
    "restore": "MODIFY",
    "visual_qa": "VISUAL_QA",
    "export": "EXPORT",
}

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
    "layout.incomplete_absolute", "content.not_rendered",
})


def qa_issue_fingerprint(issues: list[dict[str, Any]]) -> str:
    """Stable identity for detecting a repair round that made no progress."""
    return json.dumps(sorted(
        (
            str(item.get("slide_id") or ""),
            str(item.get("rule_id") or ""),
            tuple(str(ref) for ref in (item.get("missing_refs") or [])),
        )
        for item in issues
    ), ensure_ascii=False)


def should_retry_qa_issues(
    *, issues: list[dict[str, Any]], repair_round: int, max_rounds: int,
    fingerprint: str, previous_fingerprint: str, repair_mode: str,
) -> bool:
    """Allow one deterministic fallback, then stop an identical repair loop."""
    if not issues or repair_round >= max_rounds:
        return False
    repeated = bool(fingerprint and fingerprint == previous_fingerprint)
    return not (repeated and repair_mode == "deterministic")


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


def deterministic_layout_engine_params(intent: str, instruction: str) -> dict[str, Any]:
    """Fallback semantics for size requests when structured extraction is unavailable."""
    if intent != "LAYOUT_ONLY":
        return {}
    if any(marker in instruction for marker in ("放大", "大一点", "字号", "字体大小", "卡片大小", "元素大小")):
        return {
            "target_dimension": "size", "font_tier": "spacious",
            "font_scale": 1.10, "size_scale": 1.10,
        }
    if any(marker in instruction for marker in ("缩小", "小一点")):
        return {
            "target_dimension": "size", "font_tier": "compact",
            "font_scale": 0.90, "size_scale": 0.90,
        }
    return {}


def _resolved_command_runtime(command: Any) -> tuple[PPTIntent, str, list[str], dict[str, Any]]:
    """Translate the canonical V2 command into one minimal executable chain."""
    domains = {str(item.domain) for item in command.operations}
    if "restore" in domains:
        intent: PPTIntent = "MODIFY"
        policy = "restore"
        chain = ["layout", "ppt_editor", "visual_qa"]
    elif "template" in domains:
        intent = "TEMPLATE_SWITCH"
        policy = "preserve"
        chain = ["template_analysis", "layout", "ppt_editor", "visual_qa"]
    elif "image_asset" in domains:
        intent = "IMAGE_UPDATE"
        policy = "preserve"
        chain = ["visual_plan", "layout", "media", "ppt_editor", "visual_qa"]
    elif domains & {"image_geometry"}:
        # Existing images are repositioned through a visual_region-aware layout
        # directive; the media generator must never run for geometry-only work.
        intent = "LAYOUT_ONLY"
        policy = "preserve"
        chain = ["layout", "ppt_editor", "visual_qa"]
    elif "text" in domains:
        intent = "MODIFY"
        policy = "edit"
        chain = ["slide_content"]
        if domains & {"layout", "typography", "style"}:
            chain.append("layout")
        chain.extend(["ppt_editor", "visual_qa"])
    elif domains & {"layout", "typography", "style"}:
        intent = "LAYOUT_ONLY"
        policy = "preserve"
        chain = ["layout", "ppt_editor", "visual_qa"]
    elif "qa" in domains:
        intent = "VISUAL_QA"
        policy = "preserve"
        chain = ["visual_qa"]
    elif "export" in domains:
        intent = "EXPORT"
        policy = "preserve"
        chain = ["ppt_editor", "visual_qa"]
    else:
        intent = "LAYOUT_ONLY"
        policy = "preserve"
        chain = ["layout", "ppt_editor", "visual_qa"]

    objectives = [item.model_dump() for item in command.objectives]
    operations = [item.model_dump() for item in command.operations]
    params: dict[str, Any] = {
        "quality_mode": "polish_v2",
        "objectives": objectives,
        "operations": operations,
        "strength": next((item.strength for item in command.operations), "moderate"),
        "minimum_quality_delta": 8.0,
    }
    # A generic aesthetic polish has no single user metric, but it still must
    # prove a meaningful deterministic improvement.  The command resolver
    # intentionally keeps its inferred whitespace/alignment objectives soft;
    # add the global quality objective only to the executable directive.
    layout_domains = domains & {"layout", "typography", "style"}
    if layout_domains and not any(bool(item.get("hard_requirement", True)) for item in objectives):
        params["objectives"] = [
            *objectives,
            {
                "metric": "layout_quality", "direction": "increase",
                "minimum_delta": 8.0, "priority": 100,
                "hard_requirement": True, "source": "runtime_gate",
            },
        ]
        params["polish_mode"] = True
    font = next((item for item in command.objectives if item.metric == "font_size"), None)
    if font is not None:
        delta = max(float(font.minimum_delta or 0.05), 0.10 if params["strength"] == "subtle" else 0.05)
        params.update({
            "target_dimension": "size",
            "font_scale": 1.0 - delta if font.direction == "decrease" else 1.0 + delta,
            "size_scale": 1.0 - delta if font.direction == "decrease" else 1.0 + delta,
            "font_tier": "compact" if font.direction == "decrease" else "spacious",
        })
    spacing = next((item for item in command.objectives if item.metric == "spacing"), None)
    if spacing is not None:
        params["gap_scale"] = 0.9 if spacing.direction == "decrease" else 1.2
    if any(item.metric in {"vertical_utilization", "horizontal_utilization", "whitespace_balance"} for item in command.objectives):
        params["prefer_columns"] = True
        params.setdefault("target_dimension", "overall")
    if "style" in domains or any(item.metric == "contrast" for item in command.objectives):
        params["highlight"] = True
    if "image_geometry" in domains:
        image_operation = next(
            (item for item in command.operations if item.domain == "image_geometry"), None,
        )
        image_objective = next(
            (item for item in command.objectives if item.metric == "image_scale"), None,
        )
        direction = str(getattr(image_objective, "direction", "optimize"))
        delta = max(float(getattr(image_objective, "minimum_delta", 0.10) or 0.10), 0.02)
        params.update({
            "image_geometry_only": True,
            "image_geometry_action": str(getattr(image_operation, "action", "polish")),
            "target_dimension": "image_scale" if image_objective is not None else "image_geometry",
            "image_scale": (
                1.0 - delta if direction == "decrease"
                else 1.0 + delta if direction == "increase"
                else 1.08
            ),
        })
    return intent, policy, chain, params


def invalidate_revision_evidence(pipeline: Any) -> None:
    """Invalidate builder-bound evidence before executing a merged command."""
    pipeline.context.tool_results = [
        block for block in pipeline.context.tool_results
        if block.tool_name not in {
            "render_preview", "run_qa", "run_content_qa", "get_qa_report",
        }
    ]
    pipeline.render_coverage = {}
    pipeline.blocking_issues = []
    pipeline.layout_compile_results = []
    pipeline.affected_slide_ids = []
    pipeline.mutation_applied = False
    pipeline.mutation_evidence = []
    pipeline.result_status = "applied"
    pipeline.publishable = False


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
            repair_mode="", repair_issue_fingerprint="",
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
            queued_confirmation = None
            queued_analysis_refresh = False
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
                    instruction_metadata = dict(
                        (instruction.result_json or {}).get("request_metadata") or {}
                    )
                    if instruction_metadata:
                        self.pipeline.request_metadata = instruction_metadata
                    urgent = any(word in instruction.content for word in ("立即", "先停止", "优先处理"))
                    instruction.disposition = "interrupted" if urgent else "merged"
                    self.pipeline.context.user_instruction = "\n".join(filter(None, [self.pipeline.context.user_instruction, instruction.content]))
                    instruction_scope = list(instruction.selected_slide_ids_json or [])
                    if instruction_scope:
                        canonical = [
                            str(item.get("id") or "") for item in runtime_baseline_slides(self.pipeline)
                        ]
                        # During initial generation the canonical deck does not
                        # exist yet.  Keep the queued scope for the later page
                        # agents; strict alias validation starts as soon as a
                        # source PPT is present for a revision run.
                        if canonical:
                            normalized = [canonical_slide_id(value, canonical) for value in instruction_scope]
                            if any(value is None for value in normalized):
                                raise PPTAgentError(
                                    "invalid_slide_scope", "追加指令包含不属于当前 PPT 的页面范围。",
                                    retryable=False, details={"requested_slide_ids": instruction_scope},
                                )
                            instruction_scope = [str(value) for value in normalized if value]
                    if not instruction_scope and any(
                        marker in instruction.content for marker in ("本页", "当前页", "这一页", "该页")
                    ):
                        active_id = str(instruction_metadata.get("active_slide_id") or "")
                        if not active_id:  # compatibility for historical rows
                            active_match = re.search(r"\[活动页面:([^\]]+)\]", instruction.content)
                            active_id = active_match.group(1).strip() if active_match else ""
                        canonical = {str(item.get("id") or "") for item in runtime_baseline_slides(self.pipeline)}
                        if active_id in canonical:
                            instruction_scope = [active_id]
                    messages.append({"role": "user", "content": instruction.content, "instruction_id": instruction.id})
                    await self.pipeline.emitter.emit_domain(
                        "run.instruction.interrupted" if urgent else "run.instruction.merged",
                        message="新指令已合并到当前计划" if not urgent else "新指令将在当前 Agent 边界优先执行",
                        payload={"instruction_id": instruction.id, "selected_slide_ids": instruction.selected_slide_ids_json},
                    )
                    canonical = [
                        str(item.get("id") or "") for item in runtime_baseline_slides(self.pipeline)
                    ]
                    if canonical:
                        # New runs and queued follow-ups share the same V2
                        # resolver.  Structured scope/modality is authoritative;
                        # the visible message remains untouched.
                        from app.agent.intents import (
                            resolve_polish_command, resolved_command_to_polish_intent,
                        )
                        from app.agent.polish_command import apply_polish_options
                        previous = (
                            self.pipeline.resolved_polish_command
                            or await self._previous_resolved_command()
                        )
                        command = resolve_polish_command(
                            instruction.content,
                            target_slide_ids=(
                                instruction_metadata.get("target_slide_ids")
                                or instruction_metadata.get("selected_slide_ids")
                                or instruction_scope
                            ),
                            active_slide_id=(
                                str(instruction_metadata.get("active_slide_id") or "") or None
                            ),
                            modality=str(instruction_metadata.get("modality") or "auto"),
                            canonical_ids=canonical,
                            previous_command=previous,
                        )
                        command = apply_polish_options(
                            command,
                            instruction_metadata.get("polish_options") or {},
                            canonical_ids=canonical,
                        )
                        self.pipeline.resolved_polish_command = command.model_dump()
                        self.pipeline.polish_intent = resolved_command_to_polish_intent(command)
                        instruction_scope = list(command.scope.target_slide_ids)
                        selected_slide_ids = list(instruction_scope)
                        self.pipeline.selected_slide_ids = list(selected_slide_ids)
                        self.pipeline.baseline_content_hashes = {
                            str(item.get("id") or ""): semantic_content_hash(item)
                            for item in runtime_baseline_slides(self.pipeline)
                            if not selected_slide_ids
                            or str(item.get("id") or "") in set(selected_slide_ids)
                        }
                        (
                            effective_intent,
                            self.pipeline.content_policy,
                            self.pipeline.operation_agent_chain,
                            self.pipeline.layout_engine_params,
                        ) = _resolved_command_runtime(command)
                        self.pipeline.active_intent = effective_intent
                        self.pipeline.context.add_note(command.summary)
                        instruction_agents = list(self.pipeline.operation_agent_chain)
                        queued_analysis_refresh = True
                        if command.needs_confirmation:
                            queued_confirmation = command
                    else:
                        # Initial generation has no authoritative slide IDs yet;
                        # retain the compatible router until the deck exists.
                        selected_slide_ids = list(dict.fromkeys([
                            *selected_slide_ids, *instruction_scope,
                        ]))
                        self.pipeline.selected_slide_ids = list(selected_slide_ids)
                        instruction_modality = str(instruction_metadata.get("modality") or "auto")
                        effective_intent = {
                            "layout": "LAYOUT_ONLY", "text": "MODIFY", "image": "IMAGE_UPDATE",
                        }.get(
                            instruction_modality,
                            infer_intent("message", instruction.content, selected_slide_ids),
                        )
                        self.pipeline.active_intent = effective_intent
                        self.pipeline.content_policy = infer_content_policy(
                            effective_intent, instruction.content,
                        )
                        queued_params = deterministic_layout_engine_params(
                            effective_intent, instruction.content,
                        )
                        if queued_params:
                            self.pipeline.layout_engine_params = queued_params
                        instruction_agents = normalize_agent_plan(
                            effective_intent,
                            [key for key in INTENT_AGENTS[effective_intent] if key in AGENT_BY_KEY],
                            self.pipeline.content_policy,
                        )
                    # 新指令必须重新运行受影响 Agent；不能因它们在旧计划中 completed 而直接结束。
                    completed = [key for key in completed if key not in instruction_agents]
                    if canonical:
                        # Do not let an older plan re-introduce content/media
                        # agents outside the resolved operation domains.
                        planned = list(instruction_agents)
                        remaining = list(instruction_agents)
                    else:
                        remaining = list(dict.fromkeys(
                            [*instruction_agents, *remaining] if urgent else [*remaining, *instruction_agents]
                        ))
                if queued:
                    # Tool results are valid only for the builder revision that
                    # produced them.  A merged instruction changes scope and/or
                    # objectives, so reusing an older run_qa would bypass the
                    # new page's render gate entirely.
                    invalidate_revision_evidence(self.pipeline)
                    row = await db.get(PipelineRun, self.pipeline.pipeline_run.id)
                    if row:
                        row.checkpoint_json = {**(row.checkpoint_json or {}), "queued_instruction_ids": [item.id for item in queued]}
                        if self.pipeline.resolved_polish_command:
                            row.plan_json = {
                                **(row.plan_json or {}),
                                "resolved_polish_command": self.pipeline.resolved_polish_command,
                                "effective_scope": list(selected_slide_ids),
                                "content_policy": self.pipeline.content_policy,
                            }
                    await db.commit()
            if queued_analysis_refresh and queued_confirmation is None:
                await self._prepare_target_slide_analysis()
            if queued_confirmation is not None:
                await self._request_intent_confirmation(queued_confirmation)
                self.pipeline.result_status = "needs_confirmation"
                self.pipeline.publishable = True
                return {
                    "planned_agents": planned, "remaining_agents": [],
                    "completed_agents": completed, "selected_skills": selected,
                    "loaded_skills": loaded, "next_agent": None,
                    "status": "completed", "intent": effective_intent,
                    "messages": messages, "selected_slide_ids": selected_slide_ids,
                    "publishable": True, "result_status": "needs_confirmation",
                }
            if getattr(self.pipeline, "result_status", "applied") == "needs_confirmation":
                return {
                    "planned_agents": planned, "remaining_agents": [],
                    "completed_agents": completed, "selected_skills": selected,
                    "loaded_skills": loaded, "next_agent": None,
                    "status": "completed", "intent": effective_intent,
                    "messages": messages, "selected_slide_ids": selected_slide_ids,
                    "publishable": True, "result_status": "needs_confirmation",
                }
            if getattr(self.pipeline, "result_status", "applied") == "no_change":
                self.pipeline.publishable = True
                return {
                    "planned_agents": planned, "remaining_agents": [],
                    "completed_agents": completed, "selected_skills": selected,
                    "loaded_skills": loaded, "next_agent": None,
                    "status": "completed", "intent": effective_intent,
                    "messages": messages, "selected_slide_ids": selected_slide_ids,
                    "publishable": True, "result_status": "no_change",
                }
            if not planned:
                fallback_agents = [
                    key for key in (
                        self.pipeline.operation_agent_chain
                        or INTENT_AGENTS.get(effective_intent, INTENT_AGENTS["GENERATE"])
                    ) if key in AGENT_BY_KEY
                ]
                capabilities = INTENT_CAPABILITIES.get(effective_intent, [])
                plan_summary = "已根据任务意图创建执行计划"
                if self.pipeline.operation_agent_chain:
                    planned = fallback_agents
                    plan_summary = "已按结构化润色操作生成最小 Agent 链"
                elif not isinstance(self.pipeline.provider, MockProvider):
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
                        effective_scope = list(selected_slide_ids) or [
                            str(item.get("id") or "") for item in runtime_baseline_slides(self.pipeline)
                        ]
                        row.plan_json = {
                            **(row.plan_json or {}),
                            "agents": planned, "skills": selected, "intent": effective_intent,
                            "effective_scope": effective_scope,
                            "scope_mode": "selected" if selected_slide_ids else "all",
                            "content_policy": self.pipeline.content_policy,
                        }
                        await db.commit()
                for item in candidates:
                    await self.pipeline.emitter.emit_domain("skill.discovered", message=f"发现 Skill：{item.name}", payload=item.public_dict())
            handoff = self.pipeline.requested_handoff
            self.pipeline.requested_handoff = None
            strict_order = bool(self.pipeline.operation_agent_chain) or (
                effective_intent == "IMAGE_UPDATE" and self.pipeline.content_policy != "restore"
            )
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
            if key == "layout" and await self._request_candidate_confirmation_if_needed():
                self.pipeline.result_status = "needs_confirmation"
                self.pipeline.publishable = True
                update.update({
                    "remaining_agents": [], "status": "running",
                    "result_status": "needs_confirmation", "publishable": True,
                })
                return update
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
                issue_fingerprint = qa_issue_fingerprint(issues)
                previous_fingerprint = str(state.get("repair_issue_fingerprint") or "")
                repeated_issue = bool(
                    issue_fingerprint and issue_fingerprint == previous_fingerprint
                )
                repeated_layout_issue = repeated_issue and all(
                    str(item.get("target_agent") or "layout") == "layout" for item in issues
                )
                update["repair_issue_fingerprint"] = issue_fingerprint
                self.pipeline.repair_issue_fingerprint = issue_fingerprint
                if should_retry_qa_issues(
                    issues=issues,
                    repair_round=repair_round,
                    max_rounds=self.pipeline.pipeline_run.max_revision_rounds,
                    fingerprint=issue_fingerprint,
                    previous_fingerprint=previous_fingerprint,
                    repair_mode=self.pipeline.repair_mode,
                ):
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
                    if (deterministic and not aesthetic) or repeated_layout_issue:
                        # 几何类 → 不重调 LLM，直接对受影响页用引擎按规则换参重编译（确定性收敛）。
                        # repair_mode 同时写入 pipeline 与 state，布局引擎经 runtime
                        # 读取确定性分支参数。
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

    async def _prepare_target_slide_analysis(self) -> None:
        from app.agent.slide_analysis import build_slide_analysis
        from app.renderers.ppt_visual_qa import PPTVisualQARenderer

        slides = runtime_baseline_slides(self.pipeline)
        target_ids = set(self.pipeline.selected_slide_ids or [
            str(slide.get("id") or "") for slide in slides
        ])
        reference_ids = set(
            ((self.pipeline.resolved_polish_command or {}).get("scope") or {}).get("reference_slide_ids") or []
        )
        analysis_ids = target_ids | reference_ids
        png_by_id: dict[str, str] = {}
        if (
            self.pipeline.builder is not None
            and self.pipeline.workspace_root is not None
            and PPTVisualQARenderer.is_available()
        ):
            try:
                root = Path(self.pipeline.workspace_root) / "analysis" / "baseline-render"
                pptx = root / "baseline.pptx"
                await asyncio.to_thread(self.pipeline.builder.render, pptx)
                images = await asyncio.to_thread(
                    PPTVisualQARenderer.convert_pptx_to_images, pptx, root / "images", 120,
                )
                png_by_id = {
                    str(slide.get("id") or ""): str(images[index])
                    for index, slide in enumerate(self.pipeline.builder.slides)
                    if index < len(images)
                }
            except Exception as exc:  # noqa: BLE001
                self.pipeline.context.add_note(f"baseline PNG 渲染失败，页面分析降级：{str(exc)[:180]}")

        objectives = list((self.pipeline.layout_engine_params or {}).get("objectives") or [])
        analyses: list[dict[str, Any]] = []
        for slide in slides:
            slide_id = str(slide.get("id") or "")
            if slide_id not in analysis_ids:
                continue
            analysis = build_slide_analysis(
                slide, self.pipeline.preferred_template,
                objectives=objectives, baseline_png=png_by_id.get(slide_id, ""),
            )
            analysis["scope_role"] = "reference" if slide_id in reference_ids else "target"
            analyses.append(analysis)
            if self.pipeline.artifacts is not None:
                await self.pipeline.artifacts.create(
                    "slide_analysis", slide_id, analysis,
                    producer_agent="slide_analyzer", producer_tool="deterministic_analysis",
                )
        # A whole-deck polish can target many pages.  Persist the complete
        # artifact for observability, but give the LLM a compact per-page view
        # so every target remains present instead of truncating the deck after
        # the first few pages.  Single-page polish keeps the full analysis.
        if len(analyses) <= 2:
            prompt_analyses = analyses
        else:
            prompt_analyses = [self._compact_slide_analysis(item) for item in analyses]
        self.pipeline.context.target_slide_analysis = prompt_analyses

    async def _ensure_required_final_qa(self, final: PPTAgentState) -> None:
        """Guarantee that a mutating run cannot exit the graph before QA.

        LangGraph normally carries ``visual_qa`` as the last remaining agent.
        A media/editor handoff or a resumed legacy checkpoint can nevertheless
        exhaust that list after the mutation is committed.  The publication
        gate must rely on actual QA evidence, so execute the same registered
        agent once when neither live nor persisted evidence exists.
        """
        if getattr(self.pipeline, "result_status", "applied") in {
            "no_change", "needs_confirmation",
        }:
            return
        requires_qa = (
            "visual_qa" in (self.pipeline.operation_agent_chain or [])
            or self.pipeline.active_intent in {
                "GENERATE", "MODIFY", "LOCAL_REGENERATE", "LAYOUT_ONLY",
                "GLOBAL_OPTIMIZE", "STYLE_CHANGE", "TEMPLATE_SWITCH",
                "CONTENT_UPDATE", "IMAGE_UPDATE",
            }
        )
        if not requires_qa or self.pipeline.builder is None or not self.pipeline.builder.slides:
            return
        qa_data = self.pipeline.context.get_tool_output("run_qa") or {}
        if not qa_data and self.pipeline.artifacts is not None:
            artifact = await self.pipeline.artifacts.latest("visual_qa")
            qa_data = dict((artifact or {}).get("data") or {})
        if qa_data:
            return
        agent = AGENT_BY_KEY["visual_qa"]
        await run_agent_loop(
            self.pipeline,
            PipelinePlan(agents=[AgentSpec(
                key="visual_qa", role=agent.role,
                description=agent.description, max_steps=8,
            )], revision_rounds=self.pipeline.pipeline_run.max_revision_rounds),
            start_step=0,
        )
        completed = list(final.get("completed_agents") or [])
        if "visual_qa" not in completed:
            final["completed_agents"] = [*completed, "visual_qa"]

    @staticmethod
    def _compact_slide_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
        """Keep all target pages in context while retaining layout essentials."""
        content = dict(analysis.get("content") or {})
        graph = dict(analysis.get("semantic_graph") or {})
        compact_units = [
            {
                "semantic_id": unit.get("semantic_id"),
                "text": str(unit.get("text") or "")[:220],
                "role": unit.get("role"),
                "group_id": unit.get("group_id"),
                "reading_order": unit.get("reading_order"),
                "locked": unit.get("locked", True),
            }
            for unit in (graph.get("units") or [])
        ]
        compact_elements = [
            {
                "kind": element.get("kind"),
                "role": element.get("role"),
                "content_ref": element.get("content_ref"),
                "x": element.get("x"), "y": element.get("y"),
                "w": element.get("w"), "h": element.get("h"),
                "font_size": (element.get("style") or {}).get("size"),
            }
            for element in (analysis.get("elements") or [])
        ]
        return {
            "slide_id": analysis.get("slide_id"),
            "scope_role": analysis.get("scope_role", "target"),
            "page_type": analysis.get("page_type"),
            "teaching_task": analysis.get("teaching_task"),
            "content": {
                "title": content.get("title"),
                "body": [str(value)[:260] for value in (content.get("body") or [])],
                "block_kinds": [item.get("kind") for item in (content.get("blocks") or [])],
            },
            "semantic_graph": {
                "units": compact_units,
                "groups": graph.get("groups") or [],
                "reading_order": graph.get("reading_order") or [],
                "semantic_alias_groups": graph.get("semantic_alias_groups") or [],
            },
            "elements": compact_elements,
            "template": analysis.get("template") or {},
            "baseline_png": analysis.get("baseline_png", ""),
            "baseline_metrics": analysis.get("baseline_metrics") or {},
            "detected_defects": analysis.get("detected_defects") or [],
            "objectives": analysis.get("objectives") or [],
        }

    async def _previous_resolved_command(self) -> dict[str, Any] | None:
        source = getattr(self.pipeline, "source_artifact", None)
        if source is None:
            return None
        from sqlalchemy import select
        from app.core.database import SessionLocal
        from app.models.entities import PipelineRun, PPTRevision
        async with SessionLocal() as db:
            revision = await db.scalar(select(PPTRevision).where(
                PPTRevision.artifact_id == source.id,
            ).order_by(PPTRevision.version.desc()).limit(1))
            previous = (
                await db.get(PipelineRun, revision.pipeline_run_id)
                if revision and revision.pipeline_run_id else None
            )
        return dict(((previous.plan_json if previous else {}) or {}).get("resolved_polish_command") or {}) or None

    async def _validated_confirmed_command(self, metadata: dict[str, Any]) -> Any | None:
        """Load a server-issued confirmation; never trust a client token alone."""
        snapshot = metadata.get("confirmed_resolved_command")
        link = metadata.get("human_confirmation")
        if not isinstance(snapshot, dict) or not isinstance(link, dict):
            return None
        from sqlalchemy import select
        from app.agent.intents import ResolvedPolishCommandV2
        from app.core.database import SessionLocal
        from app.models.entities import PPTHumanRequest, PipelineRun

        request_id = str(link.get("request_id") or "")
        source_run_id = str(link.get("source_run_id") or "")
        token = str(link.get("confirmation_token") or "")
        options_token = str(
            ((metadata.get("polish_options") or {}).get("confirmation_token") or "")
        )
        if not request_id or not source_run_id or not token or token != options_token:
            raise PPTAgentError(
                "invalid_confirmation", "人机确认凭证不完整，请重新确认。",
                retryable=False,
            )
        async with SessionLocal() as db:
            request = await db.get(PPTHumanRequest, request_id)
            source_pipeline = await db.scalar(select(PipelineRun).where(
                PipelineRun.generation_run_id == source_run_id,
            ))
        response = dict((request.response_json if request else {}) or {})
        valid = bool(
            request is not None
            and request.status == "resolved"
            and source_pipeline is not None
            and request.pipeline_run_id == source_pipeline.id
            and str(response.get("confirmation_token") or "") == token
            and str(response.get("source_run_id") or "") == source_run_id
            and str(response.get("continuation_run_id") or "")
            == str(self.pipeline.generation_run.id)
            and str(response.get("selected_candidate_id") or "")
            == str(link.get("selected_candidate_id") or "")
        )
        if not valid:
            raise PPTAgentError(
                "invalid_confirmation", "人机确认凭证无效或已失配，请重新确认。",
                retryable=False,
            )
        command = ResolvedPolishCommandV2.model_validate(snapshot)
        selected_candidate_id = str(link.get("selected_candidate_id") or "")
        if selected_candidate_id:
            option = next((
                dict(item) for item in (request.options_json or [])
                if str((item or {}).get("candidate_id") or "") == selected_candidate_id
            ), None)
            if option is None or not isinstance(option.get("candidate"), dict):
                raise PPTAgentError(
                    "invalid_candidate_confirmation", "已确认的布局候选不存在，请重新选择。",
                    retryable=False,
                )
            metadata["validated_selected_candidate"] = dict(option["candidate"])
        return command

    async def _request_intent_confirmation(self, command: Any) -> None:
        from app.core.database import SessionLocal
        from app.models.entities import PPTHumanRequest
        async with SessionLocal() as db:
            request = PPTHumanRequest(
                pipeline_run_id=self.pipeline.pipeline_run.id,
                request_type="polish_intent_confirmation",
                prompt=command.summary,
                options_json=[
                    {"id": "confirm", "label": "按此范围执行"},
                    {"id": "edit", "label": "重新指定范围或要求"},
                ],
                response_json={"resolved_command": command.model_dump()},
            )
            db.add(request)
            await db.commit()
            await db.refresh(request)
        await self.pipeline.emitter.emit_domain(
            "human.required", message=command.summary,
            payload={
                "request_id": request.id,
                "type": "polish_intent_confirmation",
                "summary": command.summary,
                "ambiguities": list(command.ambiguities),
                "options": request.options_json,
            },
        )

    async def _render_candidate_preview(
        self, slide_id: str, candidate: dict[str, Any], option_id: str,
    ) -> str:
        """Render one candidate with the real template/assets for confirmation."""
        from app.renderers.ppt_visual_qa import PPTVisualQARenderer
        from app.renderers.presentation_builder import PresentationBuilder
        if self.pipeline.workspace_root is None or not PPTVisualQARenderer.is_available():
            return ""
        source = next((
            deepcopy(item) for item in runtime_baseline_slides(self.pipeline)
            if str(item.get("id") or "") == slide_id
        ), None)
        if source is None:
            return ""

        def render() -> str:
            from app.agent.tools.editing_tools import _apply_layout_to_builder
            root = Path(self.pipeline.workspace_root) / "qa" / "candidate-previews"
            builder = PresentationBuilder().from_ppt_content({
                "theme": self.pipeline.preferred_template, "slides": [source],
            })
            _apply_layout_to_builder(builder, candidate, preserve_visuals=True)
            pptx = root / f"{slide_id}-{option_id}.pptx"
            builder.render(pptx)
            images = PPTVisualQARenderer.convert_pptx_to_images(
                pptx, root / f"{slide_id}-{option_id}", dpi=120,
            )
            return str(images[0]) if images else ""

        try:
            return await asyncio.to_thread(render)
        except Exception as exc:  # noqa: BLE001
            self.pipeline.context.add_note(
                f"候选 {option_id} 预览渲染失败：{str(exc)[:180]}"
            )
            return ""

    async def _request_candidate_confirmation_if_needed(self) -> bool:
        """Pause a single-page polish when two safe candidates are too close."""
        if (self.pipeline.request_metadata or {}).get("selected_candidate_id"):
            return False
        pending = [
            item for item in (self.pipeline.layout_compile_results or [])
            if item.get("requires_candidate_confirmation")
            and item.get("status") != "preserved"
        ]
        # Multi-page candidate combinations need a dedicated batch chooser;
        # never silently narrow a whole-deck run to one page here.
        if len(pending) != 1 or len(self.pipeline.selected_slide_ids) != 1:
            return False
        record = pending[0]
        rankings = [
            dict(item) for item in (record.get("candidate_rankings") or [])
            if item.get("elements")
            and all(
                objective_result_passed(result)
                for result in (item.get("objective_results") or [])
                if bool(result.get("hard_requirement", True))
            )
        ][:2]
        if len(rankings) < 2:
            return False
        slide_id = str(record.get("slide_id") or "")
        layout_artifact = (
            await self.pipeline.artifacts.latest("slide_layout")
            if self.pipeline.artifacts is not None else None
        )
        artifact_page = next((
            dict(item) for item in ((layout_artifact or {}).get("data", {}).get("slides") or [])
            if str(item.get("slide_id") or "") == slide_id
        ), {})
        options: list[dict[str, Any]] = []
        for index, ranking in enumerate(rankings):
            option_id = f"candidate-{chr(ord('a') + index)}"
            candidate_id = str(ranking.get("candidate_id") or option_id)
            candidate = {
                "slide_id": slide_id,
                "layout_type": str(ranking.get("layout_type") or artifact_page.get("layout_type") or "bullet_flow"),
                "designRationale": f"教师候选 {index + 1}：{ranking.get('layout_type') or ''}",
                "elements": list(ranking.get("elements") or []),
                "visual_region": artifact_page.get("visual_region"),
                "visual_type": artifact_page.get("visual_type"),
                "render_mode": "absolute", "compile_status": "applied",
                "requested_style": dict(record.get("requested_style") or {}),
                "effective_style": dict(ranking.get("style") or {}),
                "warnings": [],
                "content_allocation": dict(artifact_page.get("content_allocation") or {}),
                "compile_attempts": [],
                "baseline_metrics": dict(record.get("baseline_metrics") or {}),
                "final_metrics": {
                    **dict(record.get("final_metrics") or {}),
                    "quality_score": ranking.get("quality_score"),
                },
                "quality_delta": float(ranking.get("quality_delta") or 0),
                "objective_results": list(ranking.get("objective_results") or []),
                "requested_objectives": list(record.get("requested_objectives") or []),
                "candidate_rankings": [], "material_change": True,
                "selected_candidate_id": candidate_id,
                "candidate_score_gap": None,
                "requires_candidate_confirmation": False,
            }
            preview_path = await self._render_candidate_preview(slide_id, candidate, option_id)
            options.append({
                "id": option_id, "candidate_id": candidate_id,
                "label": f"方案 {chr(ord('A') + index)} · {candidate['layout_type']}",
                "slide_id": slide_id,
                "score": ranking.get("quality_score"),
                "quality_delta": ranking.get("quality_delta"),
                "style": ranking.get("style") or {},
                "objective_results": ranking.get("objective_results") or [],
                "render_path": preview_path,
                "candidate": candidate,
            })
        options.append({"id": "reject", "label": "保留原版", "action": "no_change"})

        from app.core.database import SessionLocal
        from app.models.entities import PPTHumanRequest, PipelineRun
        async with SessionLocal() as db:
            request = PPTHumanRequest(
                pipeline_run_id=self.pipeline.pipeline_run.id,
                request_type="layout_candidate_selection",
                prompt=f"第 {slide_id} 页有两个质量接近的安全候选，请选择。",
                # Assign the final JSON only after ``request.id`` exists and
                # the authenticated preview URLs can be constructed.  Mutating
                # a plain JSON list in place is not tracked by SQLAlchemy.
                options_json=[],
                response_json={
                    "resolved_command": dict(self.pipeline.resolved_polish_command or {}),
                    "target_slide_ids": [slide_id],
                },
            )
            db.add(request)
            await db.flush()
            for option in options:
                if option.get("render_path"):
                    option["preview_url"] = (
                        f"/api/v1/ppt-agent/runs/{self.pipeline.generation_run.id}"
                        f"/candidate-previews/{request.id}/{option['id']}"
                    )
            request.options_json = deepcopy(options)
            row = await db.get(PipelineRun, self.pipeline.pipeline_run.id)
            if row is not None:
                row.plan_json = {
                    **(row.plan_json or {}), "result_status": "needs_confirmation",
                    "candidate_request_id": request.id,
                }
            await db.commit()
            await db.refresh(request)
        public_options = [
            {key: value for key, value in option.items() if key != "candidate"}
            for option in (request.options_json or [])
        ]
        self.pipeline.candidate_request_id = request.id
        self.pipeline.candidate_options = deepcopy(public_options)
        await self.pipeline.emitter.emit_domain(
            "human.required",
            message="两个布局候选质量接近，请选择后再发布",
            payload={
                "request_id": request.id, "type": "layout_candidate_selection",
                "slide_id": slide_id, "options": public_options,
                "candidate_rankings": public_options[:2],
            },
        )
        return True

    async def run(self, *, selected_slide_ids: list[str] | None = None) -> PPTAgentState:
        instruction = self.pipeline.context.user_instruction
        self.pipeline.selected_slide_ids = list(selected_slide_ids or [])
        self.pipeline.layout_engine_params = {}
        self.pipeline.operation_agent_chain = []

        if self.pipeline.trigger_type == "message":
            from app.agent.intents import resolve_polish_command, resolved_command_to_polish_intent
            from app.agent.polish_command import apply_polish_options
            metadata = dict(getattr(self.pipeline, "request_metadata", None) or {})
            canonical_ids = [
                str(item.get("id") or "") for item in runtime_baseline_slides(self.pipeline)
            ]
            command = await self._validated_confirmed_command(metadata)
            if command is None:
                command = resolve_polish_command(
                    instruction,
                    target_slide_ids=(
                        metadata.get("target_slide_ids")
                        or metadata.get("selected_slide_ids")
                        or selected_slide_ids
                        or []
                    ),
                    active_slide_id=str(metadata.get("active_slide_id") or "") or None,
                    modality=str(metadata.get("modality") or "auto"),
                    canonical_ids=canonical_ids,
                    previous_command=await self._previous_resolved_command(),
                )
                command = apply_polish_options(
                    command, metadata.get("polish_options") or {}, canonical_ids=canonical_ids,
                )
            self.pipeline.resolved_polish_command = command.model_dump()
            self.pipeline.polish_intent = resolved_command_to_polish_intent(command)
            self.pipeline.selected_slide_ids = list(command.scope.target_slide_ids)
            selected_slide_ids = list(self.pipeline.selected_slide_ids)
            (
                self.pipeline.active_intent,
                self.pipeline.content_policy,
                self.pipeline.operation_agent_chain,
                self.pipeline.layout_engine_params,
            ) = _resolved_command_runtime(command)
            if isinstance(metadata.get("validated_selected_candidate"), dict):
                candidate = dict(metadata["validated_selected_candidate"])
                self.pipeline.layout_engine_params.update({
                    "confirmed_candidate": candidate,
                    "confirmed_candidate_id": str(
                        candidate.get("selected_candidate_id")
                        or metadata.get("selected_candidate_id")
                        or ""
                    ),
                })
            self.pipeline.context.add_note(command.summary)
            self.pipeline.context.add_note(
                "结构化润色命令：" + json.dumps(command.model_dump(), ensure_ascii=False)
            )
            from app.core.database import SessionLocal
            from app.models.entities import PipelineRun
            async with SessionLocal() as db:
                row = await db.get(PipelineRun, self.pipeline.pipeline_run.id)
                if row:
                    row.plan_json = {
                        **(row.plan_json or {}),
                        "resolved_polish_command": command.model_dump(),
                        "effective_scope": list(command.scope.target_slide_ids),
                        "scope_mode": command.scope.source,
                        "content_policy": self.pipeline.content_policy,
                    }
                    await db.commit()
        else:
            provisional_intent = infer_intent(
                self.pipeline.trigger_type, instruction, selected_slide_ids,
            )
            self.pipeline.active_intent = provisional_intent
            self.pipeline.content_policy = infer_content_policy(provisional_intent, instruction)
            self.pipeline.layout_engine_params = deterministic_layout_engine_params(
                provisional_intent, instruction,
            )

        await self._prepare_restore_baseline(self.pipeline.selected_slide_ids)
        initial = self.initial_state(selected_slide_ids=self.pipeline.selected_slide_ids)
        self.pipeline.baseline_content_hashes = dict(initial["baseline_content_hashes"])
        initial["intent"] = self.pipeline.active_intent
        initial["content_policy"] = self.pipeline.content_policy
        initial["selected_slide_ids"] = list(self.pipeline.selected_slide_ids)

        command_data = getattr(self.pipeline, "resolved_polish_command", None) or {}
        if command_data.get("needs_confirmation"):
            from app.agent.intents import ResolvedPolishCommandV2
            command = ResolvedPolishCommandV2.model_validate(command_data)
            await self._request_intent_confirmation(command)
            self.pipeline.result_status = "needs_confirmation"
            self.pipeline.publishable = True
            initial.update({
                "status": "completed", "publishable": True,
                "result_status": "needs_confirmation",
            })
            return initial

        if self.pipeline.trigger_type == "message" and self.pipeline.operation_agent_chain:
            await self._prepare_target_slide_analysis()

        if self.pipeline.content_policy == "restore" and initial.get("content_policy") != "restore":
            await self._prepare_restore_baseline(self.pipeline.selected_slide_ids)
            target_ids = set(self.pipeline.selected_slide_ids or [
                str(item.get("id") or "") for item in runtime_baseline_slides(self.pipeline)
            ])
            self.pipeline.baseline_content_hashes = {
                str(item.get("id") or ""): semantic_content_hash(item)
                for item in runtime_baseline_slides(self.pipeline)
                if str(item.get("id") or "") in target_ids
            }
            initial["baseline_content_hashes"] = dict(self.pipeline.baseline_content_hashes)
        initial["intent"] = self.pipeline.active_intent
        initial["content_policy"] = self.pipeline.content_policy
        initial["selected_slide_ids"] = list(self.pipeline.selected_slide_ids)
        config = {"configurable": {"thread_id": self.pipeline.generation_run.id}, "recursion_limit": 100}
        if not self.persistent_checkpoints:
            final = await self._build_graph(MemorySaver()).ainvoke(initial, config)
            await self._ensure_required_final_qa(final)
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
            await self._ensure_required_final_qa(final)
            await self._assert_publishable(final)
            for name in final.get("selected_skills", []):
                await self.pipeline.emitter.skill_completed(name)
            return final

    async def _assert_publishable(self, final: PPTAgentState) -> None:
        """Apply the strict publish gate before the domain Artifact can be saved."""
        if getattr(self.pipeline, "result_status", "applied") == "needs_confirmation":
            self.pipeline.publishable = True
            final["publishable"] = True
            final["result_status"] = "needs_confirmation"
            return
        if self.pipeline.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}:
            self._assert_template_switch_integrity(final)
            return
        if self.pipeline.active_intent != "IMAGE_UPDATE":
            qa_data = self.pipeline.context.get_tool_output("run_qa") or {}
            artifacts = getattr(self.pipeline, "artifacts", None)
            if not qa_data and artifacts is not None:
                qa_artifact = await artifacts.latest("visual_qa")
                qa_data = dict((qa_artifact or {}).get("data") or {})
            qa_scope = set(
                getattr(self.pipeline, "affected_slide_ids", [])
                if hasattr(self.pipeline, "affected_slide_ids")
                else (getattr(self.pipeline, "selected_slide_ids", None) or [])
            )
            blocking = [
                item for item in qa_data.get("issues", [])
                if item.get("severity") in {"critical", "major"}
                and (
                    not qa_scope
                    or str(item.get("slide_id") or "") in qa_scope
                )
            ]
            if getattr(self.pipeline, "result_status", None) == "no_change" and not qa_scope:
                blocking = []
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
                    retryable=False, details={"issues": blocking[:20]},
                )
            source_slide_list = runtime_baseline_slides(self.pipeline)
            current_slide_list = list(
                ((self.pipeline.builder.to_ppt_content() if self.pipeline.builder is not None else {}).get("slides") or [])
            )
            source_slides = {
                str(item.get("id") or ""): item for item in source_slide_list
            }
            current_slides = {
                str(item.get("id") or ""): item for item in current_slide_list
            }
            target_ids = set(self.pipeline.selected_slide_ids or source_slides)
            operation_domains = {
                str(item.get("domain") or "")
                for item in ((getattr(self.pipeline, "layout_engine_params", None) or {}).get("operations") or [])
                if isinstance(item, dict)
            }
            if self.pipeline.active_intent != "GENERATE" and source_slide_list:
                PPTAgentRuntime._assert_revision_scope_integrity(
                    source_slide_list, current_slide_list, target_ids,
                )
            if self.pipeline.content_policy in {"preserve", "restore"}:
                changed = [
                    slide_id for slide_id in target_ids
                    if slide_id not in source_slides or slide_id not in current_slides
                    or semantic_content_changed(source_slides[slide_id], current_slides[slide_id])
                ]
                if changed:
                    raise PPTAgentError(
                        "content_accidentally_removed", "视觉或恢复任务意外修改了页面文字，已保留原 PPT 版本。",
                        retryable=False, details={"slides": sorted(changed)},
                    )
                if "image_geometry" in operation_domains:
                    non_media_changes = [
                        slide_id for slide_id in target_ids
                        if slide_id in source_slides and slide_id in current_slides
                        and [
                            item for item in (source_slides[slide_id].get("elements") or [])
                            if item.get("kind") not in {"image", "chart"}
                        ] != [
                            item for item in (current_slides[slide_id].get("elements") or [])
                            if item.get("kind") not in {"image", "chart"}
                        ]
                    ]
                    if non_media_changes:
                        raise PPTAgentError(
                            "image_geometry_scope_changed",
                            "图片几何任务意外修改了文字或页面装饰，已保留原 PPT 版本。",
                            retryable=False, details={"slides": sorted(non_media_changes)},
                        )
                changed_visual = {
                    slide_id for slide_id in target_ids
                    if slide_id in source_slides and slide_id in current_slides
                    and semantic_visual_hash(source_slides[slide_id]) != semantic_visual_hash(current_slides[slide_id])
                }
                compile_by_id = {
                    str(item.get("slide_id") or ""): item
                    for item in (getattr(self.pipeline, "layout_compile_results", None) or [])
                }
                weak_changes = {
                    slide_id for slide_id in changed_visual
                    if slide_id in compile_by_id and (
                        compile_by_id[slide_id].get("material_change") is False
                        or any(
                            not objective_result_passed(result)
                            and bool(result.get("hard_requirement", True))
                            for result in (compile_by_id[slide_id].get("objective_results") or [])
                        )
                    )
                }
                if weak_changes and self.pipeline.builder is not None:
                    # Last-resort monotonicity guard. Staging normally rejects
                    # these pages; if a legacy editor path bypasses staging,
                    # restore them here before final content is serialized.
                    for index, slide in enumerate(self.pipeline.builder.slides):
                        slide_id = str(slide.get("id") or "")
                        if slide_id in weak_changes:
                            self.pipeline.builder.slides[index] = deepcopy(source_slides[slide_id])
                    self.pipeline.affected_slide_ids = [
                        value for value in self.pipeline.affected_slide_ids
                        if value not in weak_changes
                    ]
                    for slide_id in weak_changes:
                        item = compile_by_id[slide_id]
                        item["status"] = "preserved"
                        item["warnings"] = list(dict.fromkeys([
                            *(item.get("warnings") or []),
                            "未达到显式目标或可感知改善阈值，已保留原布局",
                        ]))
                    current_slides = {
                        str(item.get("id") or ""): item
                        for item in self.pipeline.builder.to_ppt_content().get("slides", [])
                    }
                    changed_visual -= weak_changes
                coverage = {
                    slide_id: render_coverage(current_slides[slide_id], baseline=source_slides[slide_id])
                    for slide_id in changed_visual if slide_id in source_slides and slide_id in current_slides
                }
                self.pipeline.render_coverage = coverage
                missing = {slide_id: item["missing_refs"] for slide_id, item in coverage.items() if item["missing_refs"]}
                if missing:
                    incomplete_absolute = any(coverage[slide_id]["mode"] == "absolute" for slide_id in missing)
                    raise PPTAgentError(
                        "layout_incomplete" if incomplete_absolute else "content_not_rendered",
                        "绝对布局没有覆盖页面全部必要文字，已保留原 PPT 版本。" if incomplete_absolute
                        else "页面文字没有完整进入最终版式，已保留原 PPT 版本。",
                        retryable=False, details={"missing": missing},
                    )
                # 单调性门禁：preserve/restore 必须产生实际可见变化。
                # 字号、颜色等样式调整也是合法的排版结果，不能只比较几何。
                unchanged = sorted(target_ids - changed_visual)
                if not changed_visual:
                    self.pipeline.result_status = "no_change"
                elif unchanged:
                    self.pipeline.result_status = "partial"
                else:
                    self.pipeline.result_status = "applied"
            elif self.pipeline.content_policy == "edit" and source_slides:
                semantic_changes = {
                    slide_id for slide_id in target_ids
                    if slide_id in source_slides and slide_id in current_slides
                    and semantic_content_changed(source_slides[slide_id], current_slides[slide_id])
                }
                visual_changes = {
                    slide_id for slide_id in target_ids
                    if slide_id in source_slides and slide_id in current_slides
                    and semantic_visual_hash(source_slides[slide_id]) != semantic_visual_hash(current_slides[slide_id])
                }
                text_only = bool(operation_domains) and operation_domains <= {"text", "qa", "export"}
                if text_only:
                    from app.agent.slide_rendering import semantic_geometry_hash
                    geometry_changes = sorted(
                        slide_id for slide_id in target_ids
                        if slide_id in source_slides and slide_id in current_slides
                        and semantic_geometry_hash(source_slides[slide_id])
                        != semantic_geometry_hash(current_slides[slide_id])
                    )
                    if geometry_changes:
                        raise PPTAgentError(
                            "content_geometry_changed",
                            "只改文字的任务意外调整了页面几何，已保留原 PPT 版本。",
                            retryable=False, details={"slides": geometry_changes},
                        )
                changed_ids = semantic_changes | visual_changes
                if not changed_ids:
                    self.pipeline.result_status = "no_change"
                    self.pipeline.affected_slide_ids = []
                    self.pipeline.mutation_applied = True
                elif target_ids - changed_ids:
                    self.pipeline.result_status = "partial"
                else:
                    self.pipeline.result_status = "applied"
            self.pipeline.publishable = True
            final["publishable"] = True
            final["result_status"] = getattr(self.pipeline, "result_status", "applied")
            final["layout_compile_results"] = list(
                getattr(self.pipeline, "layout_compile_results", None) or []
            )
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
                retryable=False, details={"slides": sorted(changed_content)},
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
                retryable=False, details={"missing": missing_content},
            )
        qa_data = self.pipeline.context.get_tool_output("run_qa") or {}
        artifacts = getattr(self.pipeline, "artifacts", None)
        if not qa_data and artifacts is not None:
            # Tool context is intentionally bounded and may evict ``run_qa``
            # after a media-heavy run.  The persisted visual_qa Artifact is
            # the durable evidence source and must remain publishable.
            qa_artifact = await artifacts.latest("visual_qa")
            qa_data = dict((qa_artifact or {}).get("data") or {})
        if not qa_data or "score" not in qa_data or "issues" not in qa_data:
            raise PPTAgentError(
                "qa_unavailable", "目标页面没有获得本轮有效质量检查，已保留原 PPT 版本。",
                retryable=True, details={
                    "available_tool_results": [
                        str(getattr(item, "tool_name", ""))
                        for item in getattr(self.pipeline.context, "tool_results", [])
                    ],
                    "has_visual_qa_artifact": bool(qa_data),
                },
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
    def _media_preservation_signature(slide: dict[str, Any]) -> str:
        """Hash image/chart identity, crop and logical slot, but not geometry."""
        media: list[dict[str, Any]] = []
        for element in slide.get("elements") or []:
            if element.get("kind") not in {"image", "chart"}:
                continue
            # Geometry may be adjusted by layout/image_geometry, but every
            # other property belongs to the protected asset/editability layer.
            record = {
                str(key): value for key, value in element.items()
                if key not in {"x", "y", "w", "h", "z"}
            }
            media.append(record)
        media.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
        return json.dumps(media, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def _assert_revision_scope_integrity(
        cls,
        source_slides: list[dict[str, Any]],
        current_slides: list[dict[str, Any]],
        target_ids: set[str],
    ) -> None:
        """Revision runs cannot change page identity or pages outside scope."""
        source_ids = [str(item.get("id") or "") for item in source_slides]
        current_ids = [str(item.get("id") or "") for item in current_slides]
        if source_ids != current_ids:
            raise PPTAgentError(
                "revision_structure_changed",
                "润色任务改变了页面数量或顺序，已保留原 PPT 版本。",
                retryable=False,
                details={"source_slide_ids": source_ids, "current_slide_ids": current_ids},
            )
        current_by_id = {str(item.get("id") or ""): item for item in current_slides}
        changed_non_targets = [
            slide_id for slide_id, source in zip(source_ids, source_slides)
            if slide_id not in target_ids and source != current_by_id[slide_id]
        ]
        if changed_non_targets:
            raise PPTAgentError(
                "revision_scope_changed",
                "润色任务修改了目标页之外的页面，已保留原 PPT 版本。",
                retryable=False, details={"slides": changed_non_targets},
            )
        changed_media = [
            slide_id for slide_id, source in zip(source_ids, source_slides)
            if slide_id in target_ids
            and cls._media_preservation_signature(source)
            != cls._media_preservation_signature(current_by_id[slide_id])
        ]
        if changed_media:
            raise PPTAgentError(
                "media_preservation_failed",
                "润色任务改变了受保护的图片资源、裁切或视觉槽位，已保留原 PPT 版本。",
                retryable=False, details={"slides": changed_media},
            )

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
