"""媒体 Agent：根据视觉规划与页面布局生成图片 / 图表 / 流程图。

提示词必须包含：页面主题、核心信息、用途、留白方向、模板主色、禁止元素。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from pathlib import Path

from app.agent.schemas import AgentDecision, PPTAgentError, ToolCall, VisualPlanArtifact


def normalize_visual_requests(data: dict) -> list[dict]:
    """兼容旧 visual_plan 与 LLM 当前输出的 slides_visual_plan 结构。"""
    requests: list[dict] = []
    for item in data.get("requests") or []:
        slide_id = str(item.get("slide_id") or item.get("slideId") or "")
        if slide_id:
            requests.append({
                "slide_id": slide_id,
                "visual_type": item.get("visual_type") or "ai_image",
                "purpose": item.get("purpose") or "",
                "prompt": item.get("prompt") or "",
                "asset_name": item.get("asset_name") or f"visual_{slide_id}",
                "placement": item.get("placement") or item.get("visual_region"),
                "aspect_ratio": item.get("aspect_ratio") or "4:3",
                "visual_slot": item.get("visual_slot") or "primary_visual",
            })
    # 显式视觉规划必须优先于同时存在的内容页；内容页本身不能被误当作通用图片请求。
    for item in data.get("visual_plans") or []:
        slide_id = str(item.get("slideId") or item.get("slide_id") or item.get("id") or "")
        if slide_id:
            requests.append({
                "slide_id": slide_id,
                "visual_type": item.get("visualType") or item.get("visual_type") or "ai_image",
                "purpose": item.get("purpose") or "",
                "prompt": item.get("prompt") or "",
                "asset_name": item.get("image_id") or f"visual_{slide_id}",
                "placement": item.get("placement") or item.get("visual_region"),
                "aspect_ratio": item.get("aspect_ratio") or "4:3",
                "visual_slot": item.get("visual_slot") or "primary_visual",
            })
    for slide_plan in data.get("slides_visual_plan") or []:
        slide_id = str(slide_plan.get("slide_id") or slide_plan.get("slideId") or slide_plan.get("id") or "")
        for item in slide_plan.get("visual_items") or []:
            if not slide_id:
                continue
            requests.append({
                "slide_id": slide_id,
                "visual_type": item.get("visual_type") or item.get("type") or "ai_image",
                "purpose": item.get("purpose") or slide_plan.get("purpose") or "",
                "prompt": item.get("prompt") or "",
                "asset_name": item.get("image_id") or item.get("asset_name") or f"visual_{slide_id}",
                "placement": item.get("placement") or item.get("visual_region") or slide_plan.get("placement"),
                "aspect_ratio": item.get("aspect_ratio") or "4:3",
                "visual_slot": item.get("visual_slot") or slide_plan.get("visual_slot") or "primary_visual",
            })
    planned_slide_ids = {item["slide_id"] for item in requests}
    for item in data.get("slides") or []:
        slide_id = str(item.get("slideId") or item.get("slide_id") or item.get("id") or "")
        is_visual_request = any(key in item for key in ("visualRequired", "visual_required", "visualType", "visual_type", "prompt"))
        if slide_id and slide_id not in planned_slide_ids and is_visual_request and item.get(
            "visualRequired", item.get("visual_required", True)
        ):
            requests.append({
                "slide_id": slide_id,
                "visual_type": item.get("visualType") or item.get("visual_type") or "ai_image",
                "purpose": item.get("purpose") or "",
                "prompt": item.get("prompt") or "",
                "asset_name": item.get("image_id") or f"visual_{slide_id}",
                "placement": item.get("placement") or item.get("visual_region"),
                "aspect_ratio": item.get("aspect_ratio") or "4:3",
                "visual_slot": item.get("visual_slot") or "primary_visual",
            })
    return requests


_visual_requests = normalize_visual_requests


def _leaf_visual_assets(artifacts: list[dict], workspace_root: Path | None) -> list[dict]:
    """Only tool-produced current-run leaf assets can satisfy Media."""
    result: list[dict] = []
    for item in artifacts:
        if item.get("artifact_type") != "visual_asset" or item.get("name") == "default":
            continue
        if item.get("producer_tool") not in {"generate_image", "generate_chart_png", "render_diagram"}:
            continue
        data = item.get("data") or {}
        slide_id = str(data.get("slide_id") or "")
        file_path = str(data.get("file_path") or "")
        asset_id = str(data.get("asset_id") or "")
        if not slide_id or not file_path or not asset_id:
            continue
        candidate = Path(file_path)
        if workspace_root is not None and not candidate.is_absolute():
            candidate = workspace_root / candidate
        if not candidate.is_file():
            continue
        result.append(item)
    return result


class MediaAgent(Agent):
    key = "media"
    name = "图片与图表 Agent"
    role = "根据视觉规划生成与页面布局匹配的图片/图表/流程图，避免文字、Logo、水印"
    required_artifacts = ["visual_plan", "slide_content"]
    produced_artifacts = ["visual_asset"]
    allowed_tools = ["generate_image", "generate_chart_png", "render_diagram"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        if not tc.artifacts:
            return AgentDecision(completed=True, output={"assets": []}, summary="无视觉素材需求")
        visual_plan = await tc.artifacts.latest("visual_plan")
        slide_content = await tc.artifacts.latest("slide_content")
        plans = normalize_visual_requests((visual_plan or {}).get("data", {}))
        selected = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
        if selected:
            plans = [item for item in plans if item["slide_id"] in selected]
        if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE":
            try:
                plans = [item.model_dump() for item in VisualPlanArtifact.model_validate({"requests": plans}).requests]
            except Exception as exc:
                raise PPTAgentError(
                    "visual_plan_invalid", "图片生成计划缺少目标页、提示词或合法页面坐标。",
                    retryable=True, details={"validation_error": str(exc)[:300]},
                ) from exc
            tc.runtime.expected_visual_requests = list(plans)
        slides_by_id = {slide.get("id"): slide for slide in ((slide_content or {}).get("data", {}).get("slides") or [])}
        palette = (tc.ctx.template or {}).get("palette") or {}
        primary = palette.get("primary", "#1F4E79")
        artifacts = await tc.artifacts.list_all() if hasattr(tc.artifacts, "list_all") else []
        leaf_assets = _leaf_visual_assets(artifacts, tc.workspace_root)
        satisfied = {(str(item["data"].get("slide_id")), str(item["data"].get("asset_name") or item["name"].split(":", 1)[-1])) for item in leaf_assets}
        pending = [item for item in plans if (item["slide_id"], item.get("asset_name") or f"visual_{item['slide_id']}") not in satisfied]
        attempted = any(tc.ctx.has_tool_result(name) for name in ("generate_image", "generate_chart_png", "render_diagram"))
        if pending and not attempted:
            calls = []
            for item in pending:
                slide_id = item["slide_id"]
                slide = slides_by_id.get(slide_id, {})
                visual_type = item.get("visual_type", "ai_image")
                if visual_type == "diagram":
                    calls.append(ToolCall(tool_name="render_diagram", input={
                        "diagram_type": "flow",
                        "spec": {"nodes": [
                            {"id": "n1", "label": "问题", "detail": "识别任务与条件"},
                            {"id": "n2", "label": "方法", "detail": "选择核心概念"},
                            {"id": "n3", "label": "检查", "detail": "验证结论一致"},
                        ], "edges": [["n1", "n2"], ["n2", "n3"]]},
                        "asset_name": item.get("asset_name") or f"diagram_{slide_id}", "width": 960, "height": 540,
                    }))
                elif visual_type == "chart":
                    calls.append(ToolCall(tool_name="generate_chart_png", input={
                        "chart_type": "bar",
                        "data": {"categories": ["目标", "现状"], "series": [{"name": "对比", "values": [80, 45]}]},
                        "asset_name": item.get("asset_name") or f"chart_{slide_id}", "width": 960, "height": 540,
                    }))
                else:
                    calls.append(ToolCall(tool_name="generate_image", input={
                        "prompt": item.get("prompt") or (
                            f"为 PPT 页面「{slide.get('title', '')}」生成配图。页面目标：{item.get('purpose', '')}。"
                            f"主色调 #{primary}。主体位于画面右侧，左侧保持干净留白。"
                            "不要生成文字、Logo、水印或复杂 UI。构图适合 4:3 PPT 裁剪。"
                        ),
                        "slide_id": slide_id, "asset_name": item.get("asset_name") or f"visual_{slide_id}",
                        "visual_slot": item.get("visual_slot") or "primary_visual", "size": "1024x768",
                    }))
            return AgentDecision(
                tool_calls=calls,
                message=f"正在为 {len(pending)} 页生成视觉素材",
            )
        if pending and attempted and getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE":
            error_block = next((
                block for block in reversed(tc.ctx.tool_results)
                if block.tool_name in {"generate_image", "generate_chart_png", "render_diagram"}
                and isinstance(block.payload, dict) and not block.payload.get("ok")
            ), None)
            message = str((error_block.payload if error_block else {}).get("error") or "图片生成未返回有效素材")
            code = str((error_block.payload if error_block else {}).get("error_code") or "image_generation_failed")
            raise PPTAgentError(code, message, retryable=True, details={"slides": [item["slide_id"] for item in pending]})
        generated = leaf_assets
        generated_ids = [str(item["data"].get("asset_id")) for item in generated]
        previous_ids = list(getattr(tc.runtime, "generated_asset_ids", []) or [])
        tc.runtime.generated_asset_ids = list(dict.fromkeys([*previous_ids, *generated_ids]))
        return AgentDecision(
            completed=True,
            output={"assets": [{
                "slide_id": item["data"].get("slide_id"),
                "file_path": item["data"].get("file_path", ""),
                "asset_id": item["data"].get("asset_id", ""),
                "asset_name": item["data"].get("asset_name") or item["name"].split(":", 1)[-1],
                "provider": item["data"].get("provider", ""),
                "degraded": bool(item["data"].get("degraded")),
                "visual_slot": item["data"].get("visual_slot") or "primary_visual",
            } for item in generated]},
            summary=f"已生成 {len(generated)} 个视觉素材",
            message="视觉素材生成完成",
        )


MEDIA_AGENT = MediaAgent()
