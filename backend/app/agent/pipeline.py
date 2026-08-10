"""PPT Agent 流水线编排器。

- build_plan：按触发类型构建执行计划（AgentSpec 序列）
- run_agent_loop：顺序执行每个 Agent（内部小循环：工具调用 → 完成）
- run_revision_loop：QA 发现 critical/major 问题 → 修订 Agent 路由 → 重跑受影响 Agent → 再 QA（≤max_rounds）
- finalize：把 builder 输出组装为合法 PPTContent（锁定还原 + 确定性修复）
"""
import asyncio
import logging
import time
from uuid import uuid4
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.agent.artifacts import PipelineArtifactManager
from app.agent.context import ContextState, estimate_tokens
from app.agent.definitions import AGENT_BY_KEY, agent_specs_for_trigger
from app.agent.events import PipelineEventEmitter
from app.agent.registry import ToolContext, execute_tool, summarize
from app.agent.schemas import (
    AgentDecision, AgentSpec, PipelinePlan, PPTAgentError, SlideContentPatch, SlideLayoutArtifact, VisualPlanArtifact,
)
from app.agent.slide_rendering import runtime_baseline_slides, semantic_body_refs
from app.core.database import SessionLocal
from app.models.entities import GenerationRun, GenerationStep, PipelineRun
from app.providers.llm.mock import MockProvider

logger = logging.getLogger(__name__)

MAX_TOTAL_STEPS = 40
MAX_ESTIMATED_TOKENS = 60_000
RETRY_ATTEMPTS = 2

HANDOFF_ALIASES = {
    "image_generation": "media",
    "image_agent": "media",
    "visual_asset": "media",
    "visual_assets": "media",
    "builder": "ppt_editor",
    "editor": "ppt_editor",
    "qa": "visual_qa",
    "content": "slide_content",
}


def normalize_handoff(value: str | None) -> str | None:
    """把模型使用的能力名/角色名转换为可执行 Agent key。"""
    if not value:
        return None
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    canonical = HANDOFF_ALIASES.get(key, key)
    return canonical if canonical in AGENT_BY_KEY else None


class PipelinePaused(Exception):
    """Agent 边界暂停信号（由 execute_task_run 捕获持久化为 paused）。"""


@dataclass
class PipelineRuntime:
    """一次流水线运行的全部共享状态。"""

    course: Any
    task: Any
    blueprint: Any
    generation_run: GenerationRun
    pipeline_run: PipelineRun
    profile: Any
    provider: Any
    config: Any
    knowledge_context: dict[str, Any]
    source_versions: dict[str, Any]
    locks: list[Any]
    source_artifact: Any = None
    user_message: Any = None
    preferred_template: str = "lessonforge_deck_academic"
    trigger_type: str = "initial"

    context: ContextState = field(default_factory=ContextState)
    builder: Any = None
    artifacts: PipelineArtifactManager | None = None
    emitter: PipelineEventEmitter | None = None
    tool_context: ToolContext | None = None
    workspace_root: Any = None
    pause_event: asyncio.Event | None = None
    token_usage: dict[str, Any] = field(default_factory=lambda: {"llm_calls": 0, "tokens": 0})
    _steps: int = 0
    current_agent_key: str = ""
    checkpoint_start: int = 0
    dialogue_summary: str | None = None   # 对话单线完成时的正文（message/sync 触发用最终回复替换）
    requested_handoff: str | None = None
    cancel_event: asyncio.Event | None = None
    selected_slide_ids: list[str] = field(default_factory=list)
    affected_slide_ids: list[str] = field(default_factory=list)
    draft_artifact_id: str | None = None
    mutation_applied: bool = False
    active_intent: str = "GENERATE"
    expected_visual_requests: list[dict[str, Any]] = field(default_factory=list)
    generated_asset_ids: list[str] = field(default_factory=list)
    mutation_evidence: list[dict[str, Any]] = field(default_factory=list)
    publishable: bool = False
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    content_policy: str = "edit"
    baseline_content_hashes: dict[str, str] = field(default_factory=dict)
    render_coverage: dict[str, dict[str, Any]] = field(default_factory=dict)
    baseline_slides: list[dict[str, Any]] | None = None

    def request_pause(self):
        if self.pause_event is not None:
            self.pause_event.set()

    def pause_requested(self) -> bool:
        return self.pause_event is not None and self.pause_event.is_set()

    def cancel_requested(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()


def build_plan(runtime: PipelineRuntime, trigger: str) -> PipelinePlan:
    """构建执行计划（初始/同步 → 完整流水线；消息/同步上下文 → 精简）。"""
    from app.agent.definitions import agent_specs_for_trigger, spec_for
    keys = agent_specs_for_trigger(trigger)
    return PipelinePlan(agents=[AgentSpec(**spec_for(key)) for key in keys], revision_rounds=runtime.pipeline_run.max_revision_rounds)


def _mock_mode(runtime: PipelineRuntime) -> bool:
    return isinstance(runtime.provider, MockProvider)


async def _agent_call(runtime: PipelineRuntime, agent_key: str, agent, decision_count: int) -> AgentDecision:
    """调用 Agent：Mock 走确定性 decide（合成思考增量），LLM 走 stream_decision（流式思考 → 决策）。"""
    tc = runtime.tool_context
    # Media/Editor/QA/Revision are execution or control nodes: design decisions have
    # already been produced by real LLM agents. Keeping them deterministic prevents a model from
    # repeatedly issuing the same mutating/QA tools until the step budget is spent.
    if _mock_mode(runtime) or agent_key in {"media", "ppt_editor", "visual_qa", "revision"}:
        decision = await agent.decide(tc)
        if agent_key == "slide_content" and decision.completed:
            decision = _ensure_executable_slide_content(runtime, decision)
        if agent_key == "visual_plan" and decision.completed:
            decision = _ensure_executable_visual_plan(runtime, decision)
        if runtime.emitter is not None and decision.message:
            # 合成流式思考：把 mock Agent 的可见消息推送为一段思考文本（前端打字机负责逐字渲染）
            await runtime.emitter.agent_status_delta(agent_key, decision.message)
            await runtime.emitter.agent_thought_chunk(agent_key, decision.message, flush_now=True)
        return decision
    system = agent.build_system_prompt(tc)
    prompt = (
        "上下文：\n" + runtime.context.to_prompt(agent_key)
        + "\n可用工具 Schema：\n" + _tool_schemas_text(runtime, agent)
        + "\n页面作用域：" + (
            "本轮只能读取并修改这些目标页：" + ", ".join(runtime.selected_slide_ids)
            + "。可以参考相邻页保持连贯，但任何 output/tool_calls 都不得包含非目标页。"
            if runtime.selected_slide_ids else "本轮为全局任务，可以处理整套页面。"
        )
        + "\n请先输出可见执行摘要（简短说明当前阶段和下一步动作，不要输出隐式思维链或系统提示词），"
        "再输出决策：要么给出一批 tool_calls，要么 completed（含 output/summary）。"
        "只返回一个 AgentDecision JSON。"
    )
    runtime.token_usage["tokens"] += estimate_tokens(prompt)
    runtime.token_usage["llm_calls"] += 1
    decision = await _stream_agent_decision(runtime, agent_key, system, prompt)
    if agent_key == "slide_content" and decision.completed:
        try:
            decision = _ensure_executable_slide_content(runtime, decision, allow_safe_fallback=False)
        except PPTAgentError as first_error:
            import json
            correction_prompt = (
                prompt
                + "\n上一次 completed.output 未通过 SlideContentPatch 校验："
                + str(first_error.details.get("validation_error") or first_error)[:500]
                + "\n请只纠正结构并再次返回 AgentDecision；不得改写原意。SlideContentPatch Schema：\n"
                + json.dumps(SlideContentPatch.model_json_schema(), ensure_ascii=False)
            )
            runtime.token_usage["tokens"] += estimate_tokens(correction_prompt)
            runtime.token_usage["llm_calls"] += 1
            corrected = await _stream_agent_decision(runtime, agent_key, system, correction_prompt)
            decision = _ensure_executable_slide_content(runtime, corrected, allow_safe_fallback=True)
    if agent_key == "layout" and decision.completed:
        decision = await _ensure_executable_layout(runtime, agent, decision)
    if agent_key == "visual_plan" and decision.completed:
        decision = _ensure_executable_visual_plan(runtime, decision)
    if runtime.emitter is not None:
        await runtime.emitter.flush_thought()
    return decision


def _ensure_executable_slide_content(
    runtime: PipelineRuntime, decision: AgentDecision, *, allow_safe_fallback: bool = True,
) -> AgentDecision:
    """Reject empty content completions and safely restore content-locked pages."""
    targets = set(runtime.selected_slide_ids or [])
    try:
        parsed = SlideContentPatch.model_validate(decision.output or {})
        patch_slides = [item.model_dump(exclude_none=True) for item in parsed.slides]
        patch_ids = {str(item.get("id") or "") for item in patch_slides}
        if targets and patch_ids != targets:
            raise ValueError("页面内容结果必须且只能覆盖全部目标页面")
        source_slides = runtime_baseline_slides(runtime)
        source_by_id = {str(item.get("id") or ""): item for item in source_slides}
        slides: list[dict[str, Any]] = []
        for patch in patch_slides:
            slide_id = str(patch.get("id") or "")
            merged = dict(source_by_id.get(slide_id) or {})
            if merged:
                for field in patch.get("changed_fields") or []:
                    merged[field] = patch[field]
                merged["id"] = slide_id
                merged["changed_fields"] = list(patch.get("changed_fields") or [])
                slides.append(merged)
            else:
                slides.append(patch)
        # 首次生成且模板为真实 deck：把 LLM 输出对齐到 15 页角色结构
        # （页序 / 缺页兜底 / 每页 page_type），保证下游布局与渲染按模板版式工作。
        if not targets:
            from app.services.ppt_template_service import resolve_ppt_template
            if resolve_ppt_template(runtime.preferred_template).get("composition") == "deck":
                slides = _align_initial_deck(runtime, slides)
        # 编辑类内容先在语义层确定性收敛密度（逐条 ≤25 字、去装饰前缀、合计 ≤120 字），
        # 避免模型反复产出边缘超标条目（如 27>25）让 QA 门禁在修复轮内无法收敛而失败。
        if runtime.content_policy == "edit":
            from app.agent.slide_rendering import sanitize_slide_density
            for slide in slides:
                sanitize_slide_density(slide)
        return AgentDecision(
            completed=True, output={**(decision.output or {}), "slides": slides},
            summary=decision.summary, message=decision.message, handoff=decision.handoff,
        )
    except Exception as exc:
        if allow_safe_fallback and runtime.content_policy in {"preserve", "restore"}:
            source_slides = runtime_baseline_slides(runtime)
            safe = [item for item in source_slides if not targets or str(item.get("id") or "") in targets]
            if safe and (not targets or {str(item.get("id") or "") for item in safe} == targets):
                return AgentDecision(
                    completed=True, output={"slides": safe},
                    summary="已从当前正式版本恢复目标页文字", message="目标页面文字已安全恢复",
                )
        from app.agent.schemas import PPTAgentError
        raise PPTAgentError(
            "slide_content_invalid", "页面内容模型没有返回可应用的结构化页面，已保留原 PPT 版本。",
            retryable=True, details={"validation_error": str(exc)[:300]},
        ) from exc


def _align_initial_deck(runtime: PipelineRuntime, slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 LLM 首次生成结果对齐到真实模板的 15 页角色结构。

    模板页序即幻灯片页序（slides[i] ↔ 模板第 i+1 页）。优先按 id（S01..S15）
    或 slide_number 匹配；位置回填只在模型返回页数足够（≥15）时启用（此时位置=页序
    才是合理假设），不足 15 页的部分输出一律不按位置回填，缺页用 make_deck 对应
    角色的确定性内容兜底，避免把部分页内容错配到其它角色。统一写入该角色的
    page_type / purpose / layout / visual_suggestion，保证下游布局与渲染按模板版式工作。
    """
    from app.agents.generators import make_deck
    from app.renderers.deck_renderer import (
        PAGE_LAYOUT, PAGE_PURPOSE, PAGE_VISUAL, ROLE_PAGE_TYPE, deck_structure, role_order,
    )
    from app.schemas.blueprint import CourseBlueprintSchema

    structure = deck_structure(runtime.preferred_template)
    order = role_order()
    by_id = {str(slide.get("id")): slide for slide in slides}
    by_number: dict[int, dict[str, Any]] = {}
    for slide in slides:
        number = slide.get("slide_number")
        if isinstance(number, int) and not isinstance(number, bool):
            by_number.setdefault(number, slide)
    # 位置回填只对「页数足够」的输出生效：恰好 15 页或超量（如 18 页）时按页序取前 15；
    # 不足 15 页的部分输出（如模型只回 S05/S10/S15）禁止按位置回填，防止内容错配到封面等页。
    order_fallback = len(slides) >= len(order)
    fallback: list[dict[str, Any]] | None = None
    aligned: list[dict[str, Any]] = []
    for index, role in enumerate(order):
        page_type = ROLE_PAGE_TYPE.get(role, "concept")
        target_id = f"S{index + 1:02d}"
        chosen = by_id.get(target_id) or by_number.get(index + 1)
        if chosen is None and order_fallback:
            chosen = slides[index]
        if chosen is None:
            if fallback is None:
                bp = runtime.blueprint
                bp_model = bp if isinstance(bp, CourseBlueprintSchema) else CourseBlueprintSchema.model_validate(bp)
                fallback = make_deck(bp_model, runtime.preferred_template)
            page = fallback[index]
            title = str(page.get("title") or "")
            item = {
                "id": target_id, "page_type": page_type, "title": title,
                "purpose": PAGE_PURPOSE.get(page_type, "讲解要点"),
                "body": [str(value) for value in (page.get("body") or [])],
                "blocks": [], "speaker_notes": f"围绕「{title}」讲解核心要点，用提问确认学生理解。",
                "layout": PAGE_LAYOUT.get(page_type, "bullet"),
                "visual_suggestion": PAGE_VISUAL.get(page_type, "要点列表"),
            }
        else:
            title = str(chosen.get("title") or "")
            item = {
                "id": target_id, "page_type": page_type, "title": title,
                "purpose": str(chosen.get("purpose") or PAGE_PURPOSE.get(page_type, "讲解要点")),
                "body": [str(value) for value in (chosen.get("body") or [])],
                "blocks": list(chosen.get("blocks") or []),
                "speaker_notes": str(chosen.get("speaker_notes") or f"围绕「{title}」讲解核心要点，用提问确认学生理解。"),
                "layout": str(chosen.get("layout") or PAGE_LAYOUT.get(page_type, "bullet")),
                "visual_suggestion": str(chosen.get("visual_suggestion") or PAGE_VISUAL.get(page_type, "要点列表")),
            }
        item["changed_fields"] = ["title", "purpose", "body", "blocks", "speaker_notes"]
        aligned.append(item)
    return aligned


def _existing_visual_region(runtime: PipelineRuntime, slide_id: str) -> dict[str, float]:
    """Prefer the current page's visual panel so an image-only change preserves layout."""
    builder = runtime.builder
    if builder is not None:
        try:
            slide = builder.get_slide(slide_id)
        except KeyError:
            slide = None
        if slide:
            caption = next((item for item in slide.get("elements") or [] if item.get("role") == "visual_caption"), None)
            panel = next((item for item in slide.get("elements") or [] if item.get("role") in {"visual_panel", "visual", "image"}), None)
            if panel:
                x = float(panel.get("x") or 0)
                y = float(panel.get("y") or 0)
                w = float(panel.get("w") or 1)
                h = float(panel.get("h") or 1)
                if panel.get("role") == "visual_panel":
                    x, y, w = x + 0.2, y + 0.2, max(0.4, w - 0.4)
                    safe_bottom = float(caption.get("y")) - 0.15 if caption and caption.get("y") is not None else y + h - 0.35
                    h = max(0.4, safe_bottom - y)
                return {"x": x, "y": y, "w": w, "h": h}
    return {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}


def _ensure_executable_visual_plan(runtime: PipelineRuntime, decision: AgentDecision) -> AgentDecision:
    """Normalize arbitrary LLM output to the only shape Media/Editor may consume."""
    from app.agent.agents.media import normalize_visual_requests
    from app.agent.agents.layout import normalize_visual_region

    raw = decision.output or {}
    requests = normalize_visual_requests(raw)
    source_slides = runtime_baseline_slides(runtime)
    source_by_id = {str(item.get("id") or ""): item for item in source_slides}
    targets = list(runtime.selected_slide_ids or [])
    if not targets:
        targets = [str(item.get("slide_id") or "") for item in requests if item.get("slide_id")]
    if runtime.active_intent == "IMAGE_UPDATE" and not targets:
        raise PPTAgentError(
            "visual_plan_invalid", "图片润色没有明确目标页面，已保留原 PPT 版本。",
            retryable=False,
        )

    request_by_slide = {str(item.get("slide_id") or ""): item for item in requests}
    canonical: list[dict[str, Any]] = []
    for slide_id in targets:
        source = source_by_id.get(slide_id, {})
        proposed = request_by_slide.get(slide_id, {})
        prompt = str(proposed.get("prompt") or "").strip()
        if not prompt:
            prompt = (
                f"为 PPT 页面《{source.get('title', slide_id)}》生成一张教学配图。"
                f"教师要求：{runtime.context.user_instruction}。"
                f"页面目的：{source.get('purpose', '')}；视觉说明：{source.get('visual_suggestion', '')}。"
                "构图清晰、具有真实材质和教学可读性，不要文字、Logo、水印或复杂 UI。"
            )
        # The model may propose an aesthetically plausible slot that still
        # clips the title by a few pixels.  Canonicalize it before persisting
        # the visual plan so every downstream agent and repair round uses the
        # same non-overlapping coordinates.
        page_type = str(source.get("page_type") or "concept")
        placement = normalize_visual_region(
            proposed.get("placement") or proposed.get("visual_region") or _existing_visual_region(runtime, slide_id),
            getattr(runtime, "preferred_template", ""),
            page_type,
        )
        prompt = _harden_visual_prompt(prompt)
        canonical.append({
            "slide_id": slide_id,
            "asset_name": str(proposed.get("asset_name") or proposed.get("image_id") or f"visual_{slide_id}"),
            "visual_type": "ai_image" if runtime.active_intent == "IMAGE_UPDATE" else (proposed.get("visual_type") or "ai_image"),
            "prompt": prompt,
            "purpose": str(proposed.get("purpose") or source.get("purpose") or ""),
            "placement": placement,
            "aspect_ratio": str(proposed.get("aspect_ratio") or "4:3"),
            "visual_slot": str(proposed.get("visual_slot") or "primary_visual"),
        })
    parsed = VisualPlanArtifact.model_validate({"requests": canonical})
    runtime.expected_visual_requests = [item.model_dump() for item in parsed.requests]
    return AgentDecision(
        completed=True,
        output=parsed.model_dump(),
        summary=decision.summary or f"已规划 {len(parsed.requests)} 个可执行视觉素材",
        message=decision.message or "视觉生成需求与页面坐标已确认",
        handoff=decision.handoff,
    )


def _harden_visual_prompt(prompt: str) -> str:
    """Keep generated assets visual-only; page text belongs to the PPT layer."""
    suffix = (
        " 图片只承担视觉示意，不要在图片内渲染任何中文、英文、字母、数字、公式、"
        "箭头标签、图注、Logo、水印或 UI 文本；所有教学文字由 PPT 文本层负责。"
    )
    return prompt if suffix.strip() in prompt else f"{prompt.rstrip()}。{suffix}"


def _expand_aggregate_body_into_items(layout_slide: dict[str, Any], canonical: dict[str, Any]) -> dict[str, Any]:
    """把 LLM 布局里 ``content_ref=body`` 的聚合文本框拆成逐条、带留白的独立文本框。

    单行聚合文本框的行距固定（前端 preview 为 line-height 1.25），无法体现
    "文字间隔 / 太单调" 类诉求；逐条成框后间距由 y 坐标控制，PPTX 与前端
    预览都能直接呈现变化。封面副标题结构不同，保持聚合不动；条目过多（正文
    与结构化块叠加）时保持单框，避免逐条溢出画布底部。
    """
    if not canonical:
        return layout_slide
    if str(canonical.get("page_type") or "") == "cover":
        return layout_slide
    from app.agent.agents.layout import BODY_ITEM_GAP, MAX_BODY_ITEMS, _estimate_height

    elements = list(layout_slide.get("elements") or [])
    body_index = next((
        index for index, element in enumerate(elements)
        if str(element.get("content_ref") or "") == "body"
    ), None)
    if body_index is None:
        return layout_slide
    refs = semantic_body_refs(canonical)
    if len(refs) < 2 or len(refs) > MAX_BODY_ITEMS:
        return layout_slide
    body_element = elements[body_index]
    style = dict(body_element.get("style") or {})
    font_size = float(style.get("size") or 18)
    cursor_y = float(body_element.get("y") or 0)
    expanded: list[dict[str, Any]] = []
    for ref, text in refs:
        item_h = max(0.5, _estimate_height([text], float(body_element.get("w") or 1), font_size))
        item = {key: value for key, value in body_element.items()}
        item["content_ref"] = ref
        item["text"] = text
        item["x"] = round(float(body_element.get("x") or 0), 3)
        item["w"] = round(float(body_element.get("w") or 1), 3)
        item["y"] = round(cursor_y, 3)
        item["h"] = round(item_h, 3)
        expanded.append(item)
        cursor_y += item_h + BODY_ITEM_GAP
    elements[body_index:body_index + 1] = expanded
    return {**layout_slide, "elements": elements}


async def _ensure_executable_layout(runtime: PipelineRuntime, agent, decision: AgentDecision) -> AgentDecision:
    """Validate LLM aesthetics and compile semantic proposals to safe geometry."""
    targets = set(runtime.selected_slide_ids or [])
    from app.agent.agents.layout import normalize_visual_region
    try:
        parsed = SlideLayoutArtifact.model_validate(decision.output or {})
        if targets:
            parsed.slides = [item for item in parsed.slides if item.slide_id in targets]
            if {item.slide_id for item in parsed.slides} != targets:
                raise ValueError("布局结果未覆盖全部目标页面")
        else:
            deck_ids = {str(item.get("id") or "") for item in runtime_baseline_slides(runtime)}
            parsed.slides = [item for item in parsed.slides if item.slide_id in deck_ids]
    except Exception:
        slide_content = await runtime.artifacts.latest("slide_content") if runtime.artifacts else None
        source_slides = list((slide_content or {}).get("data", {}).get("slides") or []) or runtime_baseline_slides(runtime)
        scoped_slides = [item for item in source_slides if not targets or str(item.get("id")) in targets]
        if runtime.emitter is not None:
            await runtime.emitter.agent_status_delta(
                "layout", "模型已完成审美分析，正在把设计方案安全编译为可执行页面坐标。",
            )
        # Do not issue a second nested-schema request here. Several compatible
        # providers support AgentDecision JSON but reject arbitrary deep schemas
        # with upstream_schema_mismatch. The first call is the real LLM aesthetic
        # analysis; this compiler turns it into bounded, deterministic geometry.
        parsed = _compile_layout_from_analysis(runtime, decision, scoped_slides, agent)
        if targets:
            parsed.slides = [item for item in parsed.slides if item.slide_id in targets]
            if {item.slide_id for item in parsed.slides} != targets:
                raise RuntimeError("LLM 布局结果超出目标页范围或缺少目标页")
    # LLM geometry is usable only when every canonical text fragment for this
    # revision remains renderable. Preserve/restore compare against the locked
    # source; edit compares against the newly produced slide_content Artifact.
    # This prevents a schema-valid layout from silently copying the previous
    # version's textbox text over freshly edited semantic fields.
    from app.agent.agents.layout import _content_start_x
    from app.agent.slide_rendering import bind_content_refs, render_coverage
    canonical_slides = runtime_baseline_slides(runtime)
    if runtime.content_policy == "edit" and runtime.artifacts is not None:
        edited_content = await runtime.artifacts.latest("slide_content")
        canonical_slides = list((edited_content or {}).get("data", {}).get("slides") or []) or canonical_slides
    canonical_by_id = {str(item.get("id") or ""): item for item in canonical_slides}
    # 未指定目标页（整本修订）时，布局必须覆盖全部页面：LLM 常常只返回前几页，
    # 缺失页必须用确定性版式补齐，否则它们沿用旧元素、无法通过内容覆盖门禁。
    expected_ids = set(targets) if targets else {str(item.get("id") or "") for item in canonical_slides}
    incomplete: list[str] = []
    covered: set[str] = set()
    for item in parsed.model_dump().get("slides") or []:
        slide_id = str(item.get("slide_id") or "")
        baseline = canonical_by_id.get(slide_id)
        raw_elements = list(item.get("elements") or [])
        # LLM 常用自己的措辞或聚合框，直接按原始文本做覆盖检查会把精心设计的
        # 版式误判为不完整而退回朴素竖排。先绑定权威文字再校验，保留 LLM 版式。
        bound_elements, unresolved = (
            bind_content_refs(baseline, raw_elements) if baseline else (raw_elements, [])
        )
        safe_x = _content_start_x(
            runtime.preferred_template,
            str((baseline or {}).get("page_type") or "concept"),
        )
        text_under_template_rail = any(
            element.get("kind") in {"textbox", "note"}
            and float(element.get("x") or 0) < safe_x - 0.01
            for element in bound_elements
        )
        if baseline and (
            unresolved
            or render_coverage(
                {**baseline, "render_mode": "absolute", "elements": bound_elements},
                baseline=baseline,
            )["missing_refs"]
            or text_under_template_rail
        ):
            incomplete.append(slide_id)
        else:
            covered.add(slide_id)
    incomplete.extend(sorted(expected_ids - covered))
    if incomplete:
        scoped = [item for item in canonical_slides if str(item.get("id") or "") in set(incomplete)]
        safe = _compile_layout_from_analysis(runtime, decision, scoped, agent)
        safe_by_id = {item.slide_id: item for item in safe.slides}
        # 把确定性补齐的缺失页也并入结果：parsed 只含 LLM 返回的页，缺失页的
        # 编译版式必须追加进来，否则整本修订缺页仍沿用旧元素、无法通过覆盖门禁。
        merged: dict[str, Any] = {str(item.slide_id): item for item in parsed.slides}
        merged.update(safe_by_id)
        parsed.slides = [merged[slide_id] for slide_id in sorted(expected_ids)]
    # Normalize the visual slot even when the LLM returned a schema-valid
    # layout.  Schema validity only proves the rectangle is on-canvas; it does
    # not prove that its top edge clears the title/text region.
    normalized_slides = []
    for item in parsed.slides:
        data = item.model_dump()
        page_type = "concept"
        for source in runtime_baseline_slides(runtime):
            if str(source.get("id") or "") == str(item.slide_id):
                page_type = str(source.get("page_type") or "concept")
                break
        if data.get("visual_region"):
            data["visual_region"] = normalize_visual_region(
                data["visual_region"], runtime.preferred_template, page_type,
            )
        for element in data.get("elements") or []:
            if element.get("kind") == "image":
                region = normalize_visual_region(element, runtime.preferred_template, page_type)
                element.update(region)
        # 绑定权威文字：让通过校验的 LLM 版式使用规范内容，而不是模型自己编的措辞。
        canonical = canonical_by_id.get(str(item.slide_id))
        if canonical:
            bound, unresolved = bind_content_refs(canonical, list(data.get("elements") or []))
            if not unresolved:
                data["elements"] = bound
        normalized_slides.append(data)
    # 源页已有需要保留的图片/图表时，LLM 布局即使通过校验也必须预留视觉槽。
    # 否则 _layout_slide_batch 重建元素后会把保留图片放到旧坐标，与加宽的正文
    # 重叠（visual.overlaps_content / geometry.overlap），QA 直接拦截发布。
    # 缺槽页面用确定性版式补齐右侧视觉区并收窄正文栏。
    baseline_by_id = {
        str(item.get("id") or ""): item for item in runtime_baseline_slides(runtime)
    }
    preserve_mode = (
        runtime.content_policy in {"preserve", "restore"}
        or getattr(runtime, "active_intent", "") in {
            "MODIFY", "LOCAL_REGENERATE", "LAYOUT_ONLY", "CONTENT_UPDATE",
            "GLOBAL_OPTIMIZE", "STYLE_CHANGE", "TEMPLATE_SWITCH", "IMAGE_UPDATE",
        }
    )
    reserved_slides = []
    for data in normalized_slides:
        slide_id = str(data.get("slide_id") or "")
        baseline = baseline_by_id.get(slide_id)
        if (
            preserve_mode
            and baseline
            and any(el.get("kind") in {"image", "chart"} for el in (baseline.get("elements") or []))
            and not data.get("visual_region")
        ):
            canonical = canonical_by_id.get(slide_id) or baseline
            visual = {"visualType": "image", "placement": _existing_visual_region(runtime, slide_id)}
            fallback = agent._layout_slide(canonical, visual, runtime.preferred_template)
            if fallback.get("visual_region"):
                data = fallback
        # LLM 布局即使通过校验也常常把正文压成单个聚合文本框，无法体现文字间隔；
        # 拆成逐条、带留白的独立文本框后再交给编辑层。
        canonical = canonical_by_id.get(slide_id) or baseline
        if canonical:
            data = _expand_aggregate_body_into_items(data, canonical)
        reserved_slides.append(data)
    # 发布前最后一道确定性防线：把“挤成一团/大片空白”的正文列重排为均匀分布。
    # LLM 输出只要 schema 合法即可通过内容覆盖检查，因此必须在校验后再规范化一次。
    from app.agent.agents.layout import canonicalize_spatial_layout
    reserved_slides = [
        canonicalize_spatial_layout(
            runtime.preferred_template,
            canonical_by_id.get(str(item.get("slide_id") or "")) or {},
            item,
        )
        for item in reserved_slides
    ]
    parsed = SlideLayoutArtifact.model_validate({"slides": reserved_slides})
    return AgentDecision(
        completed=True,
        output=parsed.model_dump(),
        summary=decision.summary or f"已分析并生成 {len(parsed.slides)} 页可执行布局",
        message=decision.message or "页面审美与布局分析完成",
        handoff=decision.handoff,
    )


def _compile_layout_from_analysis(
    runtime: PipelineRuntime,
    decision: AgentDecision,
    scoped_slides: list[dict[str, Any]],
    agent,
) -> SlideLayoutArtifact:
    """Compile the LLM's semantic/aesthetic proposal into bounded geometry."""
    proposed = list((decision.output or {}).get("slides") or [])
    proposed_by_id = {str(item.get("id") or item.get("slide_id")): item for item in proposed}
    # scoped_slides 来自 slide_content 补丁（无 elements）。源页是否已有需要保留的
    # 图片/图表必须从 baseline（含元素层）读取，否则文字类修订不会预留视觉槽，
    # 保留的图片会被放到旧坐标并与加宽的正文重叠。
    baseline_by_id = {
        str(item.get("id") or ""): item for item in runtime_baseline_slides(runtime)
    }
    preserve_mode = (
        runtime.content_policy in {"preserve", "restore"}
        or getattr(runtime, "active_intent", "") in {
            "MODIFY", "LOCAL_REGENERATE", "LAYOUT_ONLY", "CONTENT_UPDATE",
            "GLOBAL_OPTIMIZE", "STYLE_CHANGE", "TEMPLATE_SWITCH", "IMAGE_UPDATE",
        }
    )
    layouts: list[dict[str, Any]] = []
    for source in scoped_slides:
        slide_id = str(source.get("id") or "")
        slide = {**source, **proposed_by_id.get(slide_id, {})}
        rationale = str(slide.get("visual_suggestion") or decision.summary or "")
        if slide.get("page_type") == "cover":
            from app.agent.agents.layout import _content_start_x, _estimate_height

            body = [str(item) for item in (slide.get("body") or [])]
            title = str(slide.get("title") or "")
            purpose = str(slide.get("purpose") or "")
            # The academic/smart templates reserve a decorative rail on the
            # left.  The previous fallback used x=.8 unconditionally, which
            # put canonical text underneath that rail and then made every QA
            # repair reproduce the same invalid geometry.  Keep the text
            # column inside the template-specific safe area and give the
            # aggregate body enough height for every canonical body item.
            content_x = _content_start_x(runtime.preferred_template, "cover")
            visual_x = 7.75
            content_w = max(3.6, visual_x - content_x - 0.4)
            body_h = max(1.65, min(2.0, _estimate_height(body, content_w, 17)))
            layouts.append({
                "slide_id": slide_id,
                "layout_type": "academic_split_hero",
                "designRationale": rationale or "LLM 审美分析：强化标题层级、视觉重心与安全留白",
                "elements": [
                    {"kind": "textbox", "role": "title", "text": title,
                     "content_ref": "title",
                     "x": content_x, "y": 1.15, "w": content_w, "h": 1.4,
                     "style": {"size": 34, "bold": True, "color": "primary"}},
                    {"kind": "textbox", "role": "body", "text": "\n".join(body),
                     "content_ref": "body",
                     "x": content_x, "y": 2.85, "w": content_w, "h": body_h,
                     "style": {"size": 17, "color": "muted"}},
                    {"kind": "shape", "role": "visual_panel", "x": visual_x, "y": 1.05, "w": 4.85, "h": 4.75,
                     "shape_type": "rounded", "fill": "surface", "line": "secondary"},
                    {"kind": "textbox", "role": "visual_caption", "text": "潜水艇水下受力 · 浮力矢量示意",
                     "x": visual_x + 0.2, "y": 5.05, "w": 4.45, "h": 0.42,
                     "style": {"size": 15, "bold": True, "color": "primary", "align": "center"}},
                    {"kind": "shape", "role": "purpose_card", "x": content_x, "y": 5.05, "w": content_w, "h": 1.0,
                     "shape_type": "rounded", "fill": "background", "line": "secondary"},
                    {"kind": "textbox", "role": "purpose", "text": purpose,
                     "content_ref": "purpose",
                     "x": content_x + 0.2, "y": 5.22, "w": content_w - 0.4, "h": 0.66,
                     "style": {"size": 15, "bold": True, "color": "text"}},
                ],
                "visual_region": {"x": visual_x + 0.25, "y": 1.35, "w": 4.35, "h": 3.4},
                "visual_type": "image",
            })
        else:
            visual = None
            expected = next((
                item for item in (runtime.expected_visual_requests or [])
                if str(item.get("slide_id") or "") == slide_id
            ), None)
            if expected:
                visual = {
                    "visualType": expected.get("visual_type") or "ai_image",
                    "placement": expected.get("placement") or _existing_visual_region(runtime, slide_id),
                }
            elif preserve_mode and any(
                item.get("kind") in {"image", "chart"}
                for item in ((baseline_by_id.get(slide_id) or source).get("elements") or [])
            ):
                visual = {"visualType": "image", "placement": _existing_visual_region(runtime, slide_id)}
            fallback = agent._layout_slide(slide, visual, runtime.preferred_template)
            fallback["designRationale"] = rationale or fallback.get("designRationale", "")
            layouts.append(fallback)
    return SlideLayoutArtifact.model_validate({"slides": layouts})


async def _stream_agent_decision(runtime: PipelineRuntime, agent_key: str, system: str, prompt: str) -> AgentDecision:
    """流式获取 AgentDecision：监听 thought_delta → 推送 SSE；decision_ready → 返回决策。

    流式不可用时（旧 provider 无 stream_decision / 异常）回退到阻塞式 structured()。
    """
    stream_method = getattr(runtime.provider, "stream_decision", None)
    if stream_method is None:
        return await runtime.provider.structured(system, prompt, AgentDecision)
    decision: AgentDecision | None = None
    try:
        async for kind, payload in stream_method(system, prompt, AgentDecision):
            if kind == "thought_delta" and runtime.emitter is not None and payload:
                await runtime.emitter.agent_status_delta(agent_key, str(payload))
                # Legacy event retained for historical clients and migrations.
                await runtime.emitter.agent_thought_chunk(agent_key, str(payload))
            elif kind == "decision_ready":
                decision = payload
    except Exception as exc:  # noqa: BLE001 流式异常回退阻塞式
        logger.warning("Agent %s 流式决策失败，回退 structured：%s", agent_key, exc)
    if decision is None:
        decision = await runtime.provider.structured(system, prompt, AgentDecision)
    return decision


def _tool_schemas_text(runtime: PipelineRuntime, agent=None) -> str:
    from app.agent.registry import all_tool_schemas
    import json
    return json.dumps(all_tool_schemas(getattr(agent, "allowed_tools", None)), ensure_ascii=False)


async def _checkpoint_agent(runtime: PipelineRuntime, agent_key: str, decision: AgentDecision, step_index: int, artifact_id: str | None):
    """Agent 完成时写入 checkpoint + generation_steps（单事务）。"""
    runtime.context.decisions.append({
        "agent": agent_key, "summary": decision.summary, "artifact_id": artifact_id,
    })
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, runtime.pipeline_run.id)
        if row:
            row.current_agent = agent_key
            row.current_step_index = step_index + 1
            row.status = "running"
            row.checkpoint_json = {
                "step_index": step_index + 1,
                "produced_artifact_ids": [artifact_id] if artifact_id else [],
                "context_hash": runtime.context.context_hash(),
                "user_instruction": runtime.context.user_instruction,
                "revision_round": row.revision_round,
                "locks": [getattr(lock, "json_path", "") for lock in runtime.locks],
                "agents_done": [item["agent"] for item in runtime.context.decisions],
            }
            row.token_usage_json = runtime.token_usage
            await db.commit()
        gen_step = GenerationStep(
            run_id=runtime.generation_run.id,
            node_name=agent_key,
            status="completed",
            output_ref=artifact_id,
            duration_ms=int(decision.__dict__.get("_duration_ms", 0) or 0),
        )
        db.add(gen_step)
        await db.commit()


async def _persist_decision_artifact(runtime: PipelineRuntime, agent_key: str, decision: AgentDecision, step_index: int) -> str | None:
    """把 completed 决策的 output 持久化为 Agent 产出的 Artifact。"""
    if decision.completed_artifact_id:
        return decision.completed_artifact_id
    if not decision.completed or decision.output is None:
        return None
    produced = AGENT_BY_KEY[agent_key].produced_artifacts
    artifact_type = produced[0] if produced else "note"
    if agent_key == "media" and not list((decision.output or {}).get("assets") or []):
        runtime.context.add_note("本轮没有有效视觉叶子素材，未创建空 visual_asset 汇总产物。")
        return None
    if agent_key == "revision" and isinstance(decision.output, dict) and decision.output.get("slides"):
        runtime.context.add_note("Revision Agent 返回了页面内容，已转交页面内容 Agent 重新校验并应用。")
        runtime.requested_handoff = "slide_content"
        return None
    if agent_key == "slide_content":
        output_slides = list((decision.output or {}).get("slides") or [])
        if not output_slides:
            raise PPTAgentError(
                "slide_content_invalid", "页面内容 Agent 未生成可应用的结构化页面，已保留原 PPT 版本。",
                retryable=True,
            )
        source_slides = runtime_baseline_slides(runtime)
        if runtime.selected_slide_ids and source_slides:
            replacements = {str(item.get("id")): item for item in output_slides if item.get("id")}
            selected = set(runtime.selected_slide_ids)
            decision.output = {
                **decision.output,
                "slides": [
                    replacements.get(str(item.get("id")), item) if str(item.get("id")) in selected else item
                    for item in source_slides
                ],
            }
        runtime.affected_slide_ids = list(runtime.selected_slide_ids) or [
            str(item.get("id")) for item in (decision.output or {}).get("slides", []) if item.get("id")
        ]
    if agent_key in {"layout", "visual_plan"} and runtime.selected_slide_ids:
        selected = set(runtime.selected_slide_ids)
        output = dict(decision.output or {})
        for collection_key in ("slides", "visual_plans", "slides_visual_plan", "requests"):
            if isinstance(output.get(collection_key), list):
                output[collection_key] = [
                    item for item in output[collection_key]
                    if str(item.get("slide_id") or item.get("slideId") or item.get("id")) in selected
                ]
        decision.output = output
    artifact = await runtime.artifacts.create(
        artifact_type, "default", decision.output,
        producer_agent=agent_key, step_index=step_index,
    )
    if runtime.emitter is not None:
        await runtime.emitter.artifact_created(artifact_type, artifact["id"], artifact["name"], artifact["version"], producer_agent=agent_key, file_path=artifact["file_path"])
    return artifact["id"]


async def _execute_tool_call(runtime: PipelineRuntime, agent_key: str, call, tool_context: ToolContext) -> None:
    started = time.monotonic()
    execution_id = str(uuid4())
    await runtime.emitter.tool_call_started(
        agent_key, call.tool_name, execution_id,
        input_summary=summarize(call.input, 200), input_json=call.input,
        model_call_id=call.id,
    )
    async with SessionLocal() as db:
        db.add(_tool_call_row(runtime, agent_key, call, execution_id, status="started"))
        await db.commit()
    result = await execute_tool(call.tool_name, tool_context, call.input)
    duration_ms = int((time.monotonic() - started) * 1000)
    runtime.context.append_tool_result(
        execution_id, agent_key, call.tool_name, result.output, result.error,
        result.error_code, result.retryable,
    )
    await runtime.emitter.tool_call_completed(
        agent_key, call.tool_name, execution_id, result.ok,
        output_summary=summarize(result.output, 300), duration_ms=duration_ms,
        error=result.error, output_json=result.output, model_call_id=call.id,
        error_code=result.error_code, retryable=result.retryable,
    )
    async with SessionLocal() as db:
        row = await db.scalar(select(_tool_call_model()).where(_tool_call_model().id == execution_id))
        if row:
            row.status = "completed" if result.ok else "failed"
            row.output_json = result.output
            row.duration_ms = duration_ms
            row.error_json = {
                "message": result.error, "code": result.error_code, "retryable": result.retryable,
            } if result.error else None
            await db.commit()
    if (
        not result.ok
        and runtime.active_intent == "IMAGE_UPDATE"
        and call.tool_name in {"layout_slide_batch", "generate_image", "add_image", "run_qa", "render_preview"}
    ):
        from app.agent.schemas import PPTAgentError
        default_code = {
            "layout_slide_batch": "layout_incomplete",
            "generate_image": "image_generation_failed",
            "add_image": "image_not_applied",
            "run_qa": "qa_unavailable",
            "render_preview": "qa_unavailable",
        }[call.tool_name]
        raise PPTAgentError(
            result.error_code or default_code,
            result.error or "图片生成、写入或质量检查失败。", retryable=result.retryable,
            details={"tool": call.tool_name, "output": result.output},
        )
    if (
        not result.ok
        and call.tool_name == "layout_slide_batch"
        and (
            runtime.content_policy in {"preserve", "restore"}
            or runtime.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}
        )
    ):
        raise PPTAgentError(
            result.error_code or "layout_incomplete",
            result.error or "页面布局没有覆盖全部必要内容，已保留原 PPT 版本。",
            retryable=result.retryable,
            details={"tool": call.tool_name, "output": result.output},
        )


def _tool_call_row(runtime: PipelineRuntime, agent_key: str, call, execution_id: str, status: str):
    from app.models.entities import PipelineToolCall
    return PipelineToolCall(
        id=execution_id, model_call_id=call.id, pipeline_run_id=runtime.pipeline_run.id, agent_key=agent_key,
        tool_name=call.tool_name, input_json=call.input, output_json={}, status=status,
    )


def _tool_call_model():
    from app.models.entities import PipelineToolCall
    return PipelineToolCall


async def run_agent_loop(runtime: PipelineRuntime, plan: PipelinePlan, start_step: int | None = None) -> None:
    """顺序执行计划中的每个 Agent（每个 Agent 内部小循环：工具调用 → 完成）。"""
    tc = runtime.tool_context
    if start_step is None:
        start_step = runtime.checkpoint_start
    for step_index in range(start_step, len(plan.agents)):
        spec = plan.agents[step_index]
        if runtime.pause_requested():
            await _persist_paused(runtime, step_index, spec.key)
            raise PipelinePaused()
        agent = AGENT_BY_KEY[spec.key]
        runtime.current_agent_key = spec.key
        if tc.ctx is not None:
            tc.ctx.current_agent = spec.key
        await runtime.emitter.agent_started(spec.key, agent.name, step_index, progress=10 + step_index * 5)
        step_started = time.monotonic()
        completed_artifact_id = None
        tool_rounds = 0
        while tool_rounds < spec.max_steps:
            runtime._steps += 1
            if runtime._steps > MAX_TOTAL_STEPS:
                raise RuntimeError(f"流水线超过最大步骤数 {MAX_TOTAL_STEPS}")
            if estimate_tokens(runtime.context.to_prompt(spec.key)) > MAX_ESTIMATED_TOKENS:
                raise RuntimeError("流水线上下文超过 token 估算上限")
            if runtime.pause_requested():
                await _persist_paused(runtime, step_index, spec.key)
                raise PipelinePaused()
            decision = None
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    decision = await _agent_call(runtime, spec.key, agent, tool_rounds)
                    break
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, PPTAgentError) and exc.code == "slide_content_invalid":
                        # _agent_call already performed the single protocol
                        # correction retry required by SlideContentPatch.
                        raise
                    if attempt == RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning("Agent %s 调用重试：%s", spec.key, exc)
            if decision is None:
                raise RuntimeError(f"Agent {spec.key} 调用失败")
            # 暂停可能在 LLM 请求期间到达；在执行任何 Tool 副作用前进入安全暂停点。
            if runtime.pause_requested():
                await _persist_paused(runtime, step_index, spec.key)
                raise PipelinePaused()
            decision.__dict__["_duration_ms"] = int((time.monotonic() - step_started) * 1000)
            if spec.key == "ppt_editor" and decision.completed and not runtime.mutation_applied:
                decision = await agent.decide(tc)
                decision.__dict__["_duration_ms"] = int((time.monotonic() - step_started) * 1000)
            if decision.tool_calls:
                for call in decision.tool_calls:
                    if runtime.pause_requested():
                        await _persist_paused(runtime, step_index, spec.key)
                        raise PipelinePaused()
                    await _execute_tool_call(runtime, spec.key, call, tc)
                tool_rounds += 1
                continue
            if decision.completed:
                if decision.handoff:
                    requested = decision.handoff
                    canonical_handoff = normalize_handoff(requested)
                    if canonical_handoff:
                        runtime.requested_handoff = canonical_handoff
                    else:
                        runtime.context.add_note(f"忽略无法识别的 handoff：{requested}")
                        if runtime.emitter is not None:
                            await runtime.emitter.emit_domain(
                                "agent.handoff.ignored",
                                agent={"id": spec.key},
                                message=f"无法识别交接目标 {requested}，已返回编排器继续计划",
                                payload={"requested": requested},
                            )
                completed_artifact_id = await _persist_decision_artifact(runtime, spec.key, decision, step_index)
                await _checkpoint_agent(runtime, spec.key, decision, step_index, completed_artifact_id)
                await runtime.emitter.agent_completed(spec.key, decision.summary,
                                                      duration_ms=int(decision.__dict__.get("_duration_ms", 0)),
                                                      artifact_id=completed_artifact_id)
                await runtime.emitter.agent_status_completed(spec.key, decision.summary)
                break
        # while 结束但未 completed（超过 max_steps 且一直工具调用）→ 视为完成并持久化当前产物
        if not decision or not decision.completed:
            if runtime.active_intent == "IMAGE_UPDATE" and spec.key in {"media", "ppt_editor", "visual_qa"}:
                from app.agent.schemas import PPTAgentError
                raise PPTAgentError(
                    "image_not_applied", f"{spec.key} 未在工具轮次上限内完成图片修改。",
                    retryable=True,
                )
            await runtime.emitter.agent_completed(spec.key, "已达工具轮次上限，跳过该 Agent 输出", artifact_id=completed_artifact_id)


async def _persist_paused(runtime: PipelineRuntime, step_index: int, agent_key: str):
    async with SessionLocal() as db:
        row = await db.get(PipelineRun, runtime.pipeline_run.id)
        if row:
            row.status = "paused"
            row.current_agent = agent_key
            row.current_step_index = step_index
            row.checkpoint_json = {**row.checkpoint_json, "step_index": step_index, "paused_agent": agent_key}
            await db.commit()


async def run_revision_loop(runtime: PipelineRuntime, plan: PipelinePlan) -> None:
    """执行计划并处理 QA → 修订闭环（修订 Agent 路由，≤max_revision_rounds）。"""
    from app.agent.agents.revision import REVISION_AGENT
    from app.renderers.presentation_builder import PresentationBuilder
    max_rounds = plan.revision_rounds
    await run_agent_loop(runtime, plan)
    for round_index in range(1, max_rounds + 1):
        qa_artifact = await runtime.artifacts.latest("visual_qa") if runtime.artifacts else None
        qa_data = runtime.context.get_tool_output("run_qa") or ((qa_artifact or {}).get("data") or {})
        if not qa_data:
            break
        issues = [item for item in qa_data.get("issues", [])
                  if item.get("severity") in {"critical", "major"}]
        # A runtime-swapped QA strategy invalidates the result produced by the
        # already-registered handler. Route one bounded revalidation pass rather
        # than silently accepting a report from stale QA code.
        if not issues:
            from app.agent.registry import get_tool
            from app.agent.tools import qa_tools
            registered_qa = get_tool("run_qa")
            if registered_qa is not None and registered_qa.handler is not qa_tools._run_qa:
                issues = [{
                    "severity": "major", "slide_id": "", "rule_id": "qa.strategy_changed",
                    "message": "QA 策略在运行中发生变化，需要重新验证", "target_agent": "layout",
                }]
        if not issues:
            break
        reason = "；".join(item.get("message", "")[:80] for item in issues[:3])
        revision_decision = await REVISION_AGENT.decide(runtime.tool_context)
        target_agents = list((revision_decision.output or {}).get("target_agents") or [])
        if not target_agents:
            target_agents = sorted({
                item.get("target_agent", "layout") for item in issues
                if item.get("target_agent", "layout") in AGENT_BY_KEY
            })
        if not target_agents:
            break
        await runtime.emitter.revision_started(round_index, max_rounds, reason=reason, target_agents=target_agents)
        # 重建 builder，让受影响 Agent 从最新 Artifact 重跑并重建页面
        runtime.builder = PresentationBuilder(runtime.preferred_template)
        runtime.tool_context.builder = runtime.builder
        runtime.mutation_applied = False
        sub_plan = PipelinePlan(
            agents=[_spec(agent_key) for agent_key in [*target_agents, "ppt_editor", "visual_qa"]],
            revision_rounds=max_rounds,
        )
        await run_agent_loop(runtime, sub_plan, start_step=0)
        await runtime.emitter.revision_completed(round_index, applied_changes=[f"重跑 {key}" for key in target_agents])


def _spec(agent_key: str) -> AgentSpec:
    info = AGENT_BY_KEY[agent_key]
    return AgentSpec(key=agent_key, role=info.role, description=info.description, max_steps=8)


def finalize_content(runtime: PipelineRuntime) -> dict[str, Any]:
    """把 builder 输出组装为合法 PPTContent（锁定还原 + 确定性修复 + 主题固定）。"""
    from app.renderers.presentation_builder import PresentationBuilder
    content = runtime.builder.to_ppt_content() if runtime.builder is not None else {}
    if not content.get("slides"):
        # builder 未构建（例如仅修订路径）→ 回退 source 内容
        if runtime.source_artifact is not None:
            content = dict(getattr(runtime.source_artifact, "content_json", {}))
    content["theme"] = runtime.preferred_template
    # 锁定路径还原
    if runtime.locks:
        from app.services.course_task_service import _restore_locked_paths
        source = getattr(runtime.source_artifact, "content_json", {}) if runtime.source_artifact else {}
        content = _restore_locked_paths(content, source, runtime.locks)
    if (
        runtime.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}
        or runtime.content_policy in {"preserve", "restore"}
    ):
        # 内容锁定任务不得在发布门禁之后借“确定性修复”修改
        # 标题、正文、备注、时长或任一非目标页；结构不合法就回滚。
        from app.schemas.artifact import PPTContent
        try:
            PPTContent.model_validate(content)
        except Exception as exc:
            is_template = runtime.active_intent in {"TEMPLATE_SWITCH", "STYLE_CHANGE"}
            raise PPTAgentError(
                "template_switch_invalid" if is_template else "slide_content_invalid",
                "新模板结果结构无效，已保留原 PPT 版本。" if is_template else "恢复后的页面结构无效，已保留原 PPT 版本。",
                retryable=True, details={"validation_error": str(exc)[:300]},
            ) from exc
        return content
    # 确定性修复（结构 + 知识规则）
    from app.services.course_task_service import _validate_and_repair_ppt
    repaired, repair_error = _validate_and_repair_ppt(content)
    if repaired is None:
        raise PPTAgentError(
            "ppt_structure_invalid", f"页面结构校验失败，已保留原 PPT 版本。{repair_error}",
            retryable=True,
        )
    return repaired
