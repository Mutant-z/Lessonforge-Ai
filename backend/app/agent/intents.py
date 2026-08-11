"""LLM 结构化润色意图提取。

关键词 infer_intent 只能做粗粒度路由（布局/文字/图片/恢复），无法表达用户
对"分布/间距/对齐/平衡"等目标维度的偏好。extract_polish_intent 让 LLM 从
用户指令中提取结构化 PolishIntent；Mock 或任何失败返回 None，由关键词
infer_intent 兜底，保证确定性路径行为不变。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.providers.llm.mock import MockProvider


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
    return params
