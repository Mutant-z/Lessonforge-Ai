"""PPT 编辑 Agent：根据内容/布局/视觉素材动态创建与编辑 PPT 页面。

Mock 路径：通过 write_slide_batch + layout_slide_batch + add_image 真实执行编辑工具，
把内容、布局与素材落到 PresentationBuilder（不是填占位符）。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, PPTAgentError, ToolCall
from app.agent.slide_rendering import runtime_baseline_slides


def _visual_regions(data: dict) -> dict[str, dict]:
    regions: dict[str, dict] = {}
    for item in data.get("requests") or []:
        slide_id = str(item.get("slide_id") or item.get("slideId") or "")
        region = item.get("placement") or item.get("visual_region")
        if slide_id and isinstance(region, dict):
            regions[slide_id] = region
    for item in data.get("visual_plans") or []:
        slide_id = str(item.get("slide_id") or item.get("slideId") or item.get("id") or "")
        region = item.get("visual_region") or item.get("placement")
        if slide_id and isinstance(region, dict):
            regions[slide_id] = region
    for slide_plan in data.get("slides_visual_plan") or []:
        slide_id = str(slide_plan.get("slide_id") or slide_plan.get("slideId") or slide_plan.get("id") or "")
        for item in slide_plan.get("visual_items") or []:
            region = item.get("placement") or item.get("visual_region")
            if slide_id and isinstance(region, dict):
                regions[slide_id] = region
                break
    for item in data.get("slides") or []:
        slide_id = str(item.get("slide_id") or item.get("slideId") or item.get("id") or "")
        region = item.get("visual_region") or item.get("placement")
        if slide_id and slide_id not in regions and isinstance(region, dict):
            regions[slide_id] = region
    return regions


def _region_from_existing_slide(tc: ToolContext, slide_id: str) -> dict | None:
    if tc.builder is None:
        return None
    try:
        slide = tc.builder.get_slide(slide_id)
    except KeyError:
        return None
    candidates = [
        element for element in (slide.get("elements") or [])
        if element.get("role") in {"visual_panel", "visual", "image"}
    ]
    if not candidates:
        return None
    element = candidates[0]
    x, y = float(element.get("x") or 0), float(element.get("y") or 0)
    w, h = float(element.get("w") or 0), float(element.get("h") or 0)
    caption = next((item for item in (slide.get("elements") or []) if item.get("role") == "visual_caption"), None)
    if element.get("role") == "visual_panel":
        x, y, w = x + 0.2, y + 0.2, max(0.4, w - 0.4)
        bottom = float(caption.get("y")) - 0.2 if caption and caption.get("y") is not None else y + h - 0.4
        h = max(0.4, bottom - y)
    return {"x": x, "y": y, "w": w, "h": h}


def _keep_region_above_caption(tc: ToolContext, slide_id: str, region: dict) -> dict:
    """图片可覆盖视觉底板，但不能覆盖独立的说明文字。"""
    if tc.builder is None:
        return region
    try:
        slide = tc.builder.get_slide(slide_id)
    except KeyError:
        return region
    caption = next((item for item in (slide.get("elements") or []) if item.get("role") == "visual_caption"), None)
    if not caption or caption.get("y") is None:
        return region
    result = dict(region)
    y = float(result.get("y") or 0)
    height_key = "h" if "h" in result else "height"
    height = float(result.get(height_key) or 0)
    safe_bottom = float(caption["y"]) - 0.15
    if y + height > safe_bottom:
        result[height_key] = max(0.4, safe_bottom - y)
    return result


class PptEditorAgent(Agent):
    key = "ppt_editor"
    name = "PPT 编辑 Agent"
    role = "动态创建/移动/缩放/删除元素，应用设计系统构建最终 PPT"
    required_artifacts = ["slide_content", "slide_layout", "visual_asset"]
    produced_artifacts = ["presentation_file"]
    allowed_tools = ["write_slide_batch", "layout_slide_batch", "add_image", "add_chart", "set_background", "add_notes"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        if not tc.artifacts:
            return AgentDecision(completed=True, output={}, summary="编辑层无产物")
        strict_image = getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE"
        if strict_image:
            expected_slides = {str(item.get("slide_id") or "") for item in (getattr(tc.runtime, "expected_visual_requests", []) or [])}
            applied_slides = {
                str(item.get("slide_id") or "") for item in (getattr(tc.runtime, "mutation_evidence", []) or [])
                if item.get("kind") == "image" and item.get("asset_id") in set(getattr(tc.runtime, "generated_asset_ids", []) or [])
            }
            tc.runtime.mutation_applied = bool(expected_slides) and expected_slides <= applied_slides
        if tc.runtime.mutation_applied:
            return AgentDecision(
                completed=True,
                output={"slide_count": len(tc.builder.slides)},
                summary=f"已更新 {len(tc.runtime.affected_slide_ids) or len(tc.builder.slides)} 页 PPT",
                message="PPT 页面更新完成",
            )
        slide_content = await tc.artifacts.latest("slide_content")
        slide_layout = await tc.artifacts.latest("slide_layout")
        visual_plan = await tc.artifacts.latest("visual_plan")
        slides = (slide_content or {}).get("data", {}).get("slides") or runtime_baseline_slides(tc.runtime)
        layouts = (slide_layout or {}).get("data", {}).get("slides") or []
        if not slides:
            return AgentDecision(completed=True, output={}, summary="没有可编辑的页面内容")
        assets = await tc.artifacts.list_all()
        asset_by_slide: dict[str, dict] = {}
        for item in assets:
            if item["artifact_type"] == "visual_asset":
                data = item.get("data") or {}
                slide_id = data.get("slide_id")
                # PipelineArtifact.file_path 指向 visual_asset 的 JSON 描述文件；图片路径必须取 data.file_path。
                if slide_id and data.get("file_path"):
                    asset_by_slide[slide_id] = data
        layout_by_slide = {item.get("slide_id"): item for item in layouts}
        visual_regions = _visual_regions((visual_plan or {}).get("data", {}))
        target_ids = set(tc.runtime.selected_slide_ids or [])
        target_slides = [slide for slide in slides if not target_ids or slide.get("id") in target_ids]
        target_layouts = [layout for layout in layouts if not target_ids or layout.get("slide_id") in target_ids]
        calls = [] if strict_image else [ToolCall(tool_name="write_slide_batch", input={"slides": target_slides})]
        # IMAGE_UPDATE 也必须先应用经过内容覆盖校验的完整布局，再写入视觉槽位。
        # 该布局 Patch 在工具层被抑制，直到 add_image 成功后才一次性发送完整页面。
        if target_layouts:
            calls.append(ToolCall(tool_name="layout_slide_batch", input={"layouts": target_layouts}))
        for slide in target_slides:
            slide_id = slide.get("id", "")
            layout = layout_by_slide.get(slide_id, {})
            if getattr(tc.runtime, "active_intent", "") == "IMAGE_UPDATE":
                region = visual_regions.get(slide_id) or layout.get("visual_region") or _region_from_existing_slide(tc, slide_id)
            else:
                region = layout.get("visual_region") or visual_regions.get(slide_id) or _region_from_existing_slide(tc, slide_id)
            asset = asset_by_slide.get(slide_id)
            if region and asset:
                region = _keep_region_above_caption(tc, slide_id, region)
                x, y = region.get("x"), region.get("y")
                width, height = region.get("w", region.get("width")), region.get("h", region.get("height"))
                if None in {x, y, width, height}:
                    continue
                calls.append(ToolCall(tool_name="add_image", input={
                    "slide_id": slide_id, "file_path": asset["file_path"],
                    "x": x, "y": y, "width": width, "height": height,
                    "role": "visual", "asset_id": asset.get("asset_id", ""),
                    "provider": asset.get("provider", ""), "degraded": bool(asset.get("degraded")),
                    "visual_slot": asset.get("visual_slot") or "primary_visual",
                }))
        if strict_image:
            expected_slides = {str(item.get("slide_id") or "") for item in (getattr(tc.runtime, "expected_visual_requests", []) or [])}
            if not expected_slides:
                expected_slides = set(target_ids or asset_by_slide)
            generated_ids = set(getattr(tc.runtime, "generated_asset_ids", []) or [])
            if not generated_ids:
                generated_ids = {str(data.get("asset_id") or "") for data in asset_by_slide.values() if data.get("asset_id")}
            available_slides = {
                slide_id for slide_id, data in asset_by_slide.items()
                if data.get("asset_id") in generated_ids and not data.get("degraded")
            }
            missing = sorted(expected_slides - available_slides)
            if missing:
                raise PPTAgentError(
                    "image_not_applied", "图片已规划但尚未获得当前运行生成的有效素材。",
                    retryable=True, details={"slides": missing},
                )
            if not calls:
                raise PPTAgentError("image_not_applied", "没有生成可应用到目标页的图片写入操作。", retryable=True)
        notes_calls = [] if strict_image else [ToolCall(tool_name="add_notes", input={"slide_id": s.get("id", ""), "notes_text": s.get("speaker_notes", "")})
                       for s in target_slides if s.get("speaker_notes")]
        calls.extend(notes_calls)
        return AgentDecision(
            tool_calls=calls,
            message=f"正在更新 {len(target_slides)} 页 PPT 并应用 LLM 设计的布局与素材",
        )


PPT_EDITOR_AGENT = PptEditorAgent()
