"""PPT 编辑 Agent：根据内容/布局/视觉素材动态创建与编辑 PPT 页面。

Mock 路径：通过 write_slide_batch + layout_slide_batch + add_image 真实执行编辑工具，
把内容、布局与素材落到 PresentationBuilder（不是填占位符）。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall


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
        if tc.builder is not None and tc.builder.slides:
            # 已构建 → 完成
            return AgentDecision(
                completed=True,
                output={"slide_count": len(tc.builder.slides)},
                summary=f"已创建 {len(tc.builder.slides)} 页 PPT",
                message="PPT 页面创建完成",
            )
        slide_content = await tc.artifacts.latest("slide_content")
        slide_layout = await tc.artifacts.latest("slide_layout")
        slides = (slide_content or {}).get("data", {}).get("slides") or []
        layouts = (slide_layout or {}).get("data", {}).get("slides") or []
        if not slides:
            return AgentDecision(completed=True, output={}, summary="没有可编辑的页面内容")
        assets = await tc.artifacts.list_all()
        asset_by_slide: dict[str, str] = {}
        for item in assets:
            if item["artifact_type"] == "visual_asset":
                slide_id = (item.get("data") or {}).get("slide_id")
                if slide_id and item.get("file_path"):
                    asset_by_slide[slide_id] = item["file_path"]
        layout_by_slide = {item.get("slide_id"): item for item in layouts}
        calls = [ToolCall(tool_name="write_slide_batch", input={"slides": slides})]
        if layouts:
            calls.append(ToolCall(tool_name="layout_slide_batch", input={"layouts": layouts}))
        for slide in slides:
            slide_id = slide.get("id", "")
            layout = layout_by_slide.get(slide_id, {})
            region = layout.get("visual_region")
            asset_path = asset_by_slide.get(slide_id)
            if region and asset_path:
                calls.append(ToolCall(tool_name="add_image", input={
                    "slide_id": slide_id, "file_path": asset_path,
                    "x": region["x"], "y": region["y"], "width": region["w"], "height": region["h"],
                    "role": "visual",
                }))
        notes_calls = [ToolCall(tool_name="add_notes", input={"slide_id": s.get("id", ""), "notes_text": s.get("speaker_notes", "")})
                       for s in slides if s.get("speaker_notes")]
        calls.extend(notes_calls)
        return AgentDecision(
            tool_calls=calls,
            message=f"正在创建 {len(slides)} 页 PPT 并应用布局与素材",
        )


PPT_EDITOR_AGENT = PptEditorAgent()
