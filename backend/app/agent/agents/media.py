"""媒体 Agent：根据视觉规划与页面布局生成图片 / 图表 / 流程图。

提示词必须包含：页面主题、核心信息、用途、留白方向、模板主色、禁止元素。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall


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
        plans = (visual_plan or {}).get("data", {}).get("slides") or []
        slides_by_id = {slide.get("id"): slide for slide in ((slide_content or {}).get("data", {}).get("slides") or [])}
        palette = (tc.ctx.template or {}).get("palette") or {}
        primary = palette.get("primary", "#1F4E79")
        pending = [item for item in plans if item.get("visualRequired")]
        if pending and not tc.ctx.has_tool_result("generate_image") and not tc.ctx.has_tool_result("render_diagram"):
            calls = []
            for item in pending:
                slide_id = item["slideId"]
                slide = slides_by_id.get(slide_id, {})
                visual_type = item.get("visualType", "ai_image")
                if visual_type == "diagram":
                    calls.append(ToolCall(tool_name="render_diagram", input={
                        "diagram_type": "flow",
                        "spec": {"nodes": [
                            {"id": "n1", "label": "问题", "detail": "识别任务与条件"},
                            {"id": "n2", "label": "方法", "detail": "选择核心概念"},
                            {"id": "n3", "label": "检查", "detail": "验证结论一致"},
                        ], "edges": [["n1", "n2"], ["n2", "n3"]]},
                        "asset_name": f"diagram_{slide_id}", "width": 960, "height": 540,
                    }))
                elif visual_type == "chart":
                    calls.append(ToolCall(tool_name="generate_chart_png", input={
                        "chart_type": "bar",
                        "data": {"categories": ["目标", "现状"], "series": [{"name": "对比", "values": [80, 45]}]},
                        "asset_name": f"chart_{slide_id}", "width": 960, "height": 540,
                    }))
                else:
                    calls.append(ToolCall(tool_name="generate_image", input={
                        "prompt": (
                            f"为 PPT 页面「{slide.get('title', '')}」生成配图。页面目标：{item.get('purpose', '')}。"
                            f"主色调 #{primary}。主体位于画面右侧，左侧保持干净留白。"
                            "不要生成文字、Logo、水印或复杂 UI。构图适合 4:3 PPT 裁剪。"
                        ),
                        "slide_id": slide_id, "asset_name": f"visual_{slide_id}", "size": "1024x768",
                    }))
            return AgentDecision(
                tool_calls=calls,
                message=f"正在为 {len(pending)} 页生成视觉素材",
            )
        assets = await tc.artifacts.list_all()
        generated = [item for item in assets if item["artifact_type"] == "visual_asset"]
        return AgentDecision(
            completed=True,
            output={"assets": [{"slide_id": item["data"].get("slide_id"), "file_path": item["file_path"],
                                "asset_id": item["id"]} for item in generated]},
            summary=f"已生成 {len(generated)} 个视觉素材",
            message="视觉素材生成完成",
        )


MEDIA_AGENT = MediaAgent()
