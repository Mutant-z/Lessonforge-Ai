"""PPT edit V3: LLM-first intent grounding and element-level mutation plans.

The V3 boundary deliberately projects back to ``ResolvedPolishCommandV2`` so
the existing agent graph remains executable while richer intent/target/change
artifacts become available to the UI and precision editor.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.polish_command import (
    PolishObjective,
    PolishOperation,
    PolishPreservation,
    PolishScope,
    ResolvedPolishCommandV2,
    resolve_polish_command,
)
from app.agent.slide_rendering import canonical_slide_id, resolve_content_ref, semantic_text_refs
from app.providers.llm.mock import MockProvider


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentEvidence(StrictModel):
    text: str = ""
    conclusion: str = ""


class EditTarget(StrictModel):
    slide_id: str
    element_ids: list[str] = Field(default_factory=list)
    content_refs: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class EditOperationV3(StrictModel):
    operation_id: str
    domain: Literal[
        "layout", "typography", "text", "image_asset", "image_geometry", "style",
        "template", "notes", "timing", "restore", "qa", "export",
    ]
    action: Literal[
        "polish", "rearrange", "resize", "align", "adjust_spacing", "rewrite",
        "shorten", "expand", "create", "replace", "remove", "reposition", "crop",
        "recolor", "switch", "restore", "review", "export", "undo", "redo",
    ]
    object_targets: list[Literal[
        "title", "body", "cards", "image", "content_refs", "slide", "background",
        "notes", "duration", "theme",
    ]] = Field(default_factory=list)
    targets: list[EditTarget] = Field(default_factory=list)
    strength: Literal["subtle", "moderate", "strong"] = "moderate"
    parameters: dict[str, Any] = Field(default_factory=dict)
    execution_order: int = Field(default=10, ge=0, le=100)


class AcceptanceCriterion(StrictModel):
    metric: str
    direction: Literal["increase", "decrease", "preserve", "optimize", "replace"] = "optimize"
    minimum_delta: float = Field(default=0.0, ge=0.0, le=2.0)
    target: str = ""


class PPTEditIntentV3(StrictModel):
    raw_text: str
    relation: Literal["new", "refine_previous", "alternative", "undo", "redo"] = "new"
    scope: PolishScope = Field(default_factory=PolishScope)
    operations: list[EditOperationV3] = Field(default_factory=list)
    preserve: PolishPreservation = Field(default_factory=PolishPreservation)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    evidence: list[IntentEvidence] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    fallback_used: bool = False

    @model_validator(mode="after")
    def unique(self) -> "PPTEditIntentV3":
        self.warnings = list(dict.fromkeys(value for value in self.warnings if value))
        seen: set[str] = set()
        operations: list[EditOperationV3] = []
        for index, item in enumerate(sorted(self.operations, key=lambda op: op.execution_order), 1):
            operation_id = item.operation_id.strip() or f"op-{index}"
            if operation_id in seen:
                operation_id = f"{operation_id}-{index}"
            seen.add(operation_id)
            item.operation_id = operation_id
            operations.append(item)
        self.operations = operations
        return self


class MutationStep(StrictModel):
    operation_id: str
    slide_id: str
    element_ids: list[str] = Field(default_factory=list)
    content_refs: list[str] = Field(default_factory=list)
    before: dict[str, Any] = Field(default_factory=dict)
    before_hash: str = ""
    fields: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    preserve_fields: list[str] = Field(default_factory=list)
    tool_name: str
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)


class PPTMutationPlan(StrictModel):
    intent_summary: str
    target_slide_ids: list[str] = Field(default_factory=list)
    steps: list[MutationStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ensure_stable_element_identity(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add durable semantic identity to historical elements in memory."""
    for slide in slides:
        slide_id = str(slide.get("id") or "")
        for index, element in enumerate(slide.get("elements") or []):
            element_id = str(element.get("id") or f"E{index + 1:02d}")
            element["id"] = element_id
            ref = str(element.get("content_ref") or "")
            role = str(element.get("role") or element.get("kind") or "element")
            element.setdefault("semantic_id", f"{slide_id}:{ref or role}:{element_id}")
            element.setdefault("origin_content_ref", ref)
            element["revision_hash"] = stable_hash({
                key: element.get(key)
                for key in ("kind", "role", "content_ref", "text", "x", "y", "w", "h", "style", "asset_id")
            })
    return slides


def _inventory(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "slide_id": slide.get("id"),
        "title": slide.get("title"),
        "page_type": slide.get("page_type"),
        "content_refs": [{"ref": ref, "text": text[:180]} for ref, text in semantic_text_refs(slide)],
        "elements": [{
            "id": item.get("id"), "semantic_id": item.get("semantic_id"),
            "kind": item.get("kind"), "role": item.get("role"),
            "content_ref": item.get("content_ref"), "text": str(item.get("text") or "")[:120],
            "x": item.get("x"), "y": item.get("y"), "w": item.get("w"), "h": item.get("h"),
        } for item in slide.get("elements") or []],
    } for slide in slides]


def _operation_from_v2(item: PolishOperation, index: int) -> EditOperationV3:
    return EditOperationV3(
        operation_id=f"op-{index}", domain=item.domain, action=item.action,
        object_targets=list(item.object_targets), strength=item.strength,
        parameters=deepcopy(item.parameters), execution_order=item.execution_order,
    )


def intent_from_command(command: ResolvedPolishCommandV2, *, fallback_used: bool) -> PPTEditIntentV3:
    criteria = [AcceptanceCriterion(
        metric=item.metric, direction=item.direction,
        minimum_delta=item.minimum_delta, target=item.metric,
    ) for item in command.objectives]
    return PPTEditIntentV3(
        raw_text=command.raw_text, relation=command.turn_relation,
        scope=command.scope.model_copy(deep=True),
        operations=[_operation_from_v2(item, index) for index, item in enumerate(command.operations, 1)],
        preserve=command.preservation.model_copy(deep=True),
        acceptance_criteria=criteria,
        confidence=command.confidence, warnings=list(command.ambiguities),
        summary=command.summary, fallback_used=fallback_used,
    )


def _allowed_domains(modality: str) -> set[str] | None:
    return {
        "layout": {"layout", "typography", "style", "qa", "restore", "export"},
        "text": {"text", "qa", "restore", "export"},
        "image": {"image_asset", "image_geometry", "qa", "restore", "export"},
    }.get(modality)


def ground_intent(
    intent: PPTEditIntentV3, *, fallback: ResolvedPolishCommandV2,
    slides: list[dict[str, Any]], metadata: dict[str, Any],
) -> PPTEditIntentV3:
    """Ground scope/modality and drop invented element IDs."""
    canonical = [str(slide.get("id") or "") for slide in slides]
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    supplied = list(metadata.get("target_slide_ids") or metadata.get("selected_slide_ids") or [])
    active = str(metadata.get("active_slide_id") or "")
    explicit_all = any(token in intent.raw_text for token in ("整套", "全部页面", "所有页面", "整个PPT", "整个 PPT"))
    if fallback.scope.source == "explicit_text":
        # Keep an invalid explicit page expression invalid.  An empty target
        # here must never be interpreted as an implicit request for the deck.
        targets = [
            str(value) for value in fallback.scope.target_slide_ids
            if str(value) in by_id
        ]
        source = "explicit_text"
    elif supplied:
        targets = [canonical_slide_id(value, canonical) for value in supplied]
        targets = [str(value) for value in targets if value]
        source = "explicit_selection"
    elif fallback.scope.source == "active_page":
        resolved = canonical_slide_id(active, canonical) if active else None
        targets = [str(resolved)] if resolved else []
        source = "active_page"
    elif fallback.scope.source == "inherited":
        targets = [
            str(value) for value in fallback.scope.target_slide_ids
            if str(value) in by_id
        ]
        source = "inherited"
    elif active and not explicit_all:
        resolved = canonical_slide_id(active, canonical)
        targets = [str(resolved)] if resolved else []
        source = "active_page"
    else:
        targets = []
        source = "all"
    intent.scope = PolishScope(
        target_slide_ids=list(dict.fromkeys(targets)),
        reference_slide_ids=[value for value in fallback.scope.reference_slide_ids if value in by_id],
        source=source,
    )

    allowed = _allowed_domains(str(metadata.get("modality") or "auto"))
    if allowed is not None:
        removed = [item.domain for item in intent.operations if item.domain not in allowed]
        intent.operations = [item for item in intent.operations if item.domain in allowed]
        if removed:
            intent.warnings.append("modality_filtered:" + ",".join(sorted(set(removed))))
    if not intent.operations:
        intent.operations = [_operation_from_v2(item, index) for index, item in enumerate(fallback.operations, 1)]
        if allowed is not None:
            intent.operations = [item for item in intent.operations if item.domain in allowed]
        intent.warnings.append("intent_operations_filled_from_fallback")

    scoped_source = intent.scope.source
    effective_targets = (
        intent.scope.target_slide_ids
        if scoped_source != "all"
        else (intent.scope.target_slide_ids or canonical)
    )
    for operation in intent.operations:
        requested = operation.targets or [EditTarget(slide_id=slide_id) for slide_id in effective_targets]
        grounded: list[EditTarget] = []
        for target in requested:
            slide_id = canonical_slide_id(target.slide_id, canonical)
            if not slide_id or str(slide_id) not in effective_targets:
                intent.warnings.append(f"invalid_or_out_of_scope_target:{target.slide_id}")
                continue
            slide = by_id[str(slide_id)]
            valid_elements = {str(item.get("id") or "") for item in slide.get("elements") or []}
            valid_refs = {ref for ref, _text in semantic_text_refs(slide)}
            refs = [ref for ref in target.content_refs if ref in valid_refs]
            element_ids = [value for value in target.element_ids if value in valid_elements]
            if operation.object_targets and not refs and operation.domain in {"text", "typography"}:
                if "title" in operation.object_targets:
                    refs.append("title")
                if any(value in operation.object_targets for value in ("body", "content_refs")):
                    refs.extend(ref for ref in valid_refs if ref not in {"title", "purpose"})
            if operation.domain in {"image_asset", "image_geometry"} and not element_ids:
                element_ids.extend(
                    str(item.get("id") or "") for item in slide.get("elements") or []
                    if item.get("kind") in {"image", "chart"}
                )
            if operation.domain == "style" and not element_ids:
                element_ids.extend(
                    str(item.get("id") or "") for item in slide.get("elements") or []
                    if item.get("kind") in {"textbox", "note", "shape"}
                )
            if refs and not element_ids:
                element_ids.extend(
                    str(item.get("id") or "") for item in slide.get("elements") or []
                    if str(item.get("content_ref") or "") in set(refs)
                )
            grounded.append(EditTarget(
                slide_id=str(slide_id), element_ids=list(dict.fromkeys(element_ids)),
                content_refs=list(dict.fromkeys(refs)), roles=list(dict.fromkeys(target.roles)),
            ))
        if not grounded:
            # UI scope wins over an LLM/user-text conflict. Re-ground the
            # semantic object on the authoritative page instead of silently
            # dropping the requested operation.
            for slide_id in effective_targets:
                slide = by_id.get(slide_id)
                if slide is None:
                    continue
                refs: list[str] = []
                element_ids: list[str] = []
                if operation.domain in {"text", "typography"}:
                    if "title" in operation.object_targets:
                        refs.append("title")
                    if any(value in operation.object_targets for value in ("body", "content_refs")):
                        refs.extend(ref for ref, _ in semantic_text_refs(slide) if ref not in {"title", "purpose"})
                if operation.domain in {"image_asset", "image_geometry"}:
                    element_ids.extend(str(item.get("id") or "") for item in slide.get("elements") or [] if item.get("kind") in {"image", "chart"})
                if refs:
                    element_ids.extend(str(item.get("id") or "") for item in slide.get("elements") or [] if str(item.get("content_ref") or "") in set(refs))
                grounded.append(EditTarget(
                    slide_id=slide_id, element_ids=list(dict.fromkeys(element_ids)),
                    content_refs=list(dict.fromkeys(refs)), roles=[],
                ))
        operation.targets = grounded
    intent.preserve = fallback.preservation.model_copy(deep=True)
    intent.warnings = list(dict.fromkeys([*intent.warnings, *fallback.ambiguities]))
    intent.summary = fallback.summary.removesuffix("；执行前需要确认。") or fallback.summary
    return intent


def validate_intent_scope(intent: PPTEditIntentV3, canonical_ids: list[str]) -> None:
    """Reject an explicitly scoped edit that resolved to no valid page."""
    validate_command_scope(intent.scope, canonical_ids)


def validate_command_scope(scope: PolishScope, canonical_ids: list[str]) -> None:
    """Enforce scope provenance after every command transformation."""
    source = str(scope.source or "all")
    targets = {str(value) for value in scope.target_slide_ids}
    canonical = {str(value) for value in canonical_ids}
    if source != "all" and not targets:
        from app.agent.schemas import PPTAgentError
        raise PPTAgentError(
            "invalid_slide_scope",
            "指定的 PPT 页面不存在或无法解析，请重新指定页面范围。",
            retryable=False,
            details={"scope_source": source, "requested_slide_ids": []},
        )
    if not targets.issubset(canonical):
        from app.agent.schemas import PPTAgentError
        raise PPTAgentError(
            "invalid_slide_scope",
            "修改范围包含不属于当前 PPT 的页面。",
            retryable=False,
            details={"scope_source": source, "requested_slide_ids": sorted(targets)},
        )


def command_from_intent(intent: PPTEditIntentV3, fallback: ResolvedPolishCommandV2) -> ResolvedPolishCommandV2:
    operations: list[PolishOperation] = []
    for item in intent.operations:
        operations.append(PolishOperation(
            domain=item.domain, action=item.action, object_targets=item.object_targets,
            strength=item.strength, hard_requirement=True,
            parameters=deepcopy(item.parameters), execution_order=item.execution_order,
        ))
    objective_by_metric = {item.metric: item for item in fallback.objectives}
    allowed_metrics = {
        "font_size", "vertical_utilization", "horizontal_utilization",
        "whitespace_balance", "spacing", "alignment", "density",
        "image_scale", "contrast",
    }
    for criterion in intent.acceptance_criteria:
        if criterion.metric in allowed_metrics:
            objective_by_metric[criterion.metric] = PolishObjective(
                metric=criterion.metric, direction=criterion.direction if criterion.direction != "replace" else "optimize",
                minimum_delta=criterion.minimum_delta, priority=90, hard_requirement=False,
                source="explicit",
            )
    return ResolvedPolishCommandV2(
        raw_text=intent.raw_text, turn_relation=intent.relation,
        scope=intent.scope.model_copy(deep=True), operations=operations or fallback.operations,
        objectives=list(objective_by_metric.values()), preservation=intent.preserve.model_copy(deep=True),
        confidence=intent.confidence, ambiguities=[], needs_confirmation=False, summary=intent.summary,
    )


async def resolve_edit_intent_v3(
    runtime: Any, *, instruction: str, slides: list[dict[str, Any]],
    metadata: dict[str, Any], previous_command: dict[str, Any] | None,
) -> tuple[PPTEditIntentV3, ResolvedPolishCommandV2]:
    ensure_stable_element_identity(slides)
    canonical = [str(slide.get("id") or "") for slide in slides]
    fallback = resolve_polish_command(
        instruction,
        target_slide_ids=metadata.get("target_slide_ids") or metadata.get("selected_slide_ids") or [],
        active_slide_id=str(metadata.get("active_slide_id") or "") or None,
        modality=str(metadata.get("modality") or "auto"), canonical_ids=canonical,
        previous_command=previous_command,
    )
    provider = getattr(runtime, "provider", None)
    if provider is None or isinstance(provider, MockProvider):
        intent = intent_from_command(fallback, fallback_used=True)
        intent = ground_intent(intent, fallback=fallback, slides=slides, metadata=metadata)
        validate_intent_scope(intent, canonical)
        return intent, command_from_intent(intent, fallback)

    system = (
        "你是 PPT 编辑需求解析器。只输出 PPTEditIntentV3。必须识别页面范围、操作对象、"
        "否定/保留约束、连续对话关系和可验证目标；不得发明不存在的 slide_id、element_id 或 content_ref。"
    )
    prompt = json.dumps({
        "instruction": instruction, "ui": metadata,
        "previous_command": previous_command or {}, "slides": _inventory(slides),
    }, ensure_ascii=False)
    fallback_used = False
    try:
        intent = await provider.structured(system, prompt, PPTEditIntentV3)
        runtime.token_usage["llm_calls"] = runtime.token_usage.get("llm_calls", 0) + 1
    except Exception:
        intent = intent_from_command(fallback, fallback_used=True)
        fallback_used = True
    intent.fallback_used = fallback_used
    intent = ground_intent(intent, fallback=fallback, slides=slides, metadata=metadata)
    validate_intent_scope(intent, canonical)

    # One bounded critic pass for genuinely complex or uncertain requests.
    if not fallback_used and (intent.confidence < 0.80 or intent.warnings or len(intent.operations) > 1):
        try:
            critique_prompt = json.dumps({
                "instruction": instruction, "grounded_intent": intent.model_dump(),
                "rule": "修正冲突和不存在的对象；明确自然语言页码优先于 UI 页面范围，保留 modality，不增加未请求操作。",
                "slides": _inventory(slides),
            }, ensure_ascii=False)
            corrected = await provider.structured(system, critique_prompt, PPTEditIntentV3)
            runtime.token_usage["llm_calls"] = runtime.token_usage.get("llm_calls", 0) + 1
            intent = ground_intent(corrected, fallback=fallback, slides=slides, metadata=metadata)
            validate_intent_scope(intent, canonical)
        except Exception:
            intent.warnings.append("intent_critic_failed")
    return intent, command_from_intent(intent, fallback)


def _tool_for(operation: EditOperationV3) -> tuple[str, list[str]]:
    if operation.domain == "text":
        return "patch_text_by_ref", ["text"]
    if operation.domain in {"typography", "style"}:
        return "patch_element_style", ["style"]
    if operation.domain == "image_asset":
        if operation.action == "remove":
            return "remove_image_asset", []
        if operation.action == "create":
            return "add_image", ["asset_path", "asset_id"]
        return "replace_image_asset", ["asset_path", "asset_id"]
    if operation.domain == "image_geometry":
        return ("resize_elements" if operation.action == "resize" else "move_elements"), ["x", "y", "w", "h"]
    return "apply_slide_relayout", ["elements"]


def build_mutation_plan(intent: PPTEditIntentV3, slides: list[dict[str, Any]]) -> PPTMutationPlan:
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    steps: list[MutationStep] = []
    for operation in intent.operations:
        tool, fields = _tool_for(operation)
        criteria = [item for item in intent.acceptance_criteria]
        for target in operation.targets:
            slide = by_id.get(target.slide_id)
            if slide is None:
                continue
            before: dict[str, Any] = {
                "content": {ref: resolve_content_ref(slide, ref) for ref in target.content_refs},
                "elements": [deepcopy(item) for item in slide.get("elements") or [] if str(item.get("id") or "") in set(target.element_ids)],
            }
            steps.append(MutationStep(
                operation_id=operation.operation_id, slide_id=target.slide_id,
                element_ids=target.element_ids, content_refs=target.content_refs,
                before=before, before_hash=stable_hash(before), fields=fields,
                expected=deepcopy(operation.parameters),
                preserve_fields=[key for key, value in intent.preserve.model_dump().items() if value],
                tool_name=tool, acceptance_criteria=criteria,
            ))
    return PPTMutationPlan(
        intent_summary=intent.summary, target_slide_ids=list(intent.scope.target_slide_ids),
        steps=steps, warnings=list(intent.warnings),
    )


def build_change_set(
    before_slides: list[dict[str, Any]], after_slides: list[dict[str, Any]],
    target_slide_ids: list[str], diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    before = {str(item.get("id") or ""): item for item in before_slides}
    after = {str(item.get("id") or ""): item for item in after_slides}
    pages: list[dict[str, Any]] = []
    for slide_id in target_slide_ids or list(before):
        old, new = before.get(slide_id), after.get(slide_id)
        if old is None or new is None:
            continue
        changes: list[dict[str, Any]] = []
        old_refs, new_refs = dict(semantic_text_refs(old)), dict(semantic_text_refs(new))
        for ref in sorted(set(old_refs) | set(new_refs)):
            if old_refs.get(ref) != new_refs.get(ref):
                changes.append({"kind": "text", "content_ref": ref, "before": old_refs.get(ref), "after": new_refs.get(ref)})
        old_elements = {str(item.get("id") or ""): item for item in old.get("elements") or []}
        new_elements = {str(item.get("id") or ""): item for item in new.get("elements") or []}
        for element_id in sorted(set(old_elements) | set(new_elements)):
            left, right = old_elements.get(element_id), new_elements.get(element_id)
            if left != right:
                changes.append({"kind": "element", "element_id": element_id, "before": left, "after": right})
        pages.append({"slide_id": slide_id, "changed": bool(changes), "changes": changes})
    return {
        "pages": pages,
        "changed_slide_ids": [item["slide_id"] for item in pages if item["changed"]],
        "diagnostics": list(diagnostics or []),
    }
