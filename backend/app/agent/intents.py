"""LLM 结构化润色意图提取。

关键词 infer_intent 只能做粗粒度路由（布局/文字/图片/恢复），无法表达用户
对"分布/间距/对齐/平衡"等目标维度的偏好。extract_polish_intent 让 LLM 从
用户指令中提取结构化 PolishIntent；Mock 或任何失败返回 None，由关键词
infer_intent 兜底，保证确定性路径行为不变。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.providers.llm.mock import MockProvider

# V2 is a deterministic canonical command used by the runtime/publish gates.
# Re-export it here so callers can migrate from the legacy one-dimensional
# ``PolishIntent`` without changing their import root.
from app.agent.polish_command import (
    ParsedPageReferences,
    PolishObjective,
    PolishOperation,
    PolishPreservation,
    PolishScope,
    ResolvedPolishCommandV2,
    parse_page_references,
    resolve_polish_command,
)


class PolishIntent(BaseModel):
    action: Literal[
        "layout_only", "text_polish", "image_only", "template_switch",
        "full_regenerate", "restore", "visual_qa", "export",
    ] = "layout_only"
    target_dimension: Literal[
        "distribution", "spacing", "alignment", "balance", "size", "color",
        "overall", "none",
    ] = "overall"
    preserve_text: bool = True
    scope_slide_ids: list[str] = Field(default_factory=list)
    size_scale: float | None = Field(default=None, ge=0.8, le=1.25)
    summary: str = ""


_INTENT_SYSTEM = "你是 PPT 润色意图识别器。只输出结构化意图，不输出隐藏推理。"


async def extract_polish_intent(runtime: Any) -> PolishIntent | None:
    """LLM 结构化意图提取；Mock 或失败返回 None（由关键词 infer_intent 兜底）。"""
    provider = getattr(runtime, "provider", None)
    if provider is None or isinstance(provider, MockProvider):
        return None
    instruction = str(getattr(getattr(runtime, "context", None), "user_instruction", "") or "")
    selected = list(getattr(runtime, "selected_slide_ids", None) or [])
    try:
        intent = await provider.structured(
            _INTENT_SYSTEM,
            "用户指令：" + instruction + "\n当前选中页面：" + ",".join(selected or []),
            PolishIntent,
        )
        return intent
    except Exception:
        return None


def dimension_to_engine_params(intent: PolishIntent | None) -> dict[str, Any]:
    """把用户目标维度映射为引擎参数，注入布局 agent 上下文。"""
    if intent is None:
        return {}
    params: dict[str, Any] = {"target_dimension": intent.target_dimension}
    if intent.target_dimension == "distribution":
        params["gap_scale"] = 1.2
        params["prefer_columns"] = True
    elif intent.target_dimension == "spacing":
        params["gap_scale"] = 1.4
    elif intent.target_dimension == "balance":
        params["gap_scale"] = 1.1
        params["prefer_columns"] = True
    elif intent.target_dimension == "size":
        params["font_scale"] = intent.size_scale or 1.1
        params["size_scale"] = intent.size_scale or 1.1
        params["font_tier"] = "spacious" if (intent.size_scale or 1.1) >= 1.0 else "compact"
    return params


def resolved_command_to_polish_intent(command: ResolvedPolishCommandV2) -> PolishIntent:
    """Compatibility projection for code paths that still consume PolishIntent.

    Multi-objective information intentionally remains on ``command``; when it
    cannot be represented faithfully, the legacy dimension is ``overall``.
    """
    domains = {operation.domain for operation in command.operations}
    if "restore" in domains:
        action = "restore"
    elif "export" in domains:
        action = "export"
    elif "qa" in domains and not domains - {"qa"}:
        action = "visual_qa"
    elif "template" in domains:
        action = "template_switch"
    elif domains and domains <= {"text"}:
        action = "text_polish"
    elif domains and domains <= {"image_asset", "image_geometry"}:
        action = "image_only"
    else:
        action = "layout_only"

    metric_dimensions = {
        "vertical_utilization": "distribution",
        "horizontal_utilization": "distribution",
        "whitespace_balance": "balance",
        "spacing": "spacing",
        "alignment": "alignment",
        "font_size": "size",
        "image_scale": "size",
        "contrast": "color",
    }
    dimensions = {
        metric_dimensions[objective.metric]
        for objective in command.objectives
        if objective.metric in metric_dimensions
    }
    target_dimension = dimensions.pop() if len(dimensions) == 1 else "overall"
    font_objective = next(
        (item for item in command.objectives if item.metric == "font_size"), None,
    )
    size_scale = None
    if font_objective and font_objective.direction in {"increase", "decrease"}:
        delta = font_objective.minimum_delta or 0.05
        size_scale = 1.0 + delta if font_objective.direction == "increase" else 1.0 - delta
    return PolishIntent(
        action=action,
        target_dimension=target_dimension,
        preserve_text=command.preservation.semantic_text,
        scope_slide_ids=list(command.scope.target_slide_ids),
        size_scale=size_scale,
        summary=command.summary,
    )


__all__ = [
    "ParsedPageReferences",
    "PolishIntent",
    "PolishObjective",
    "PolishOperation",
    "PolishPreservation",
    "PolishScope",
    "ResolvedPolishCommandV2",
    "dimension_to_engine_params",
    "extract_polish_intent",
    "parse_page_references",
    "resolve_polish_command",
    "resolved_command_to_polish_intent",
]
