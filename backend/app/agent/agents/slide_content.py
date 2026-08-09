"""页面内容 Agent：把上游完整内容压缩/重组为适合演示的每页内容。

Mock 路径：直接复用 make_ppt 的 15 页角色内容（保持测试 parity）；
LLM 路径：读取叙事 Artifact 动态决定每页内容（禁止照搬上游长文本）。
"""
from copy import deepcopy

from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.schemas.blueprint import CourseBlueprintSchema

DEFAULT_THEME = "lessonforge_deck_academic"


class SlideContentAgent(Agent):
    key = "slide_content"
    name = "页面内容 Agent"
    role = "将上游内容压缩、重组、提炼核心观点，生成符合密度上限的页面级内容"
    required_artifacts = ["presentation_narrative"]
    produced_artifacts = ["slide_content"]
    allowed_tools = ["get_blueprint", "get_template_design", "get_ppt_source"]

    def build_system_prompt(self, tc: ToolContext) -> str:
        targets = list(getattr(tc.runtime, "selected_slide_ids", []) or [])
        return super().build_system_prompt(tc) + (
            "\ncompleted.output 必须严格符合 SlideContentPatch："
            "{slides:[{id,changed_fields,title?,purpose?,body?,blocks?,speaker_notes?}]}。"
            "changed_fields 只能列出且必须完整列出本项实际提供的语义字段。"
            + (f"只能返回这些目标页：{targets}。" if targets else "首次生成时每页列出全部语义字段。")
        )

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        if ctx.user_instruction and ctx.source_artifact is not None:
            content = deepcopy(getattr(ctx.source_artifact, "content_json", {}) or {})
            slides = list(content.get("slides") or [])
            targets = set(tc.runtime.selected_slide_ids or [str(item.get("id")) for item in slides])
            patches = []
            for slide in slides:
                if str(slide.get("id")) not in targets:
                    continue
                if "润色" in ctx.user_instruction:
                    slide["title"] = f"{str(slide.get('title') or '').removesuffix('（润色版）')}（润色版）"
                patches.append({
                    "id": str(slide.get("id") or ""),
                    "changed_fields": ["title", "purpose", "body", "blocks", "speaker_notes"],
                    "title": str(slide.get("title") or ""),
                    "purpose": str(slide.get("purpose") or ""),
                    "body": list(slide.get("body") or []),
                    "blocks": list(slide.get("blocks") or []),
                    "speaker_notes": str(slide.get("speaker_notes") or ""),
                })
            return AgentDecision(
                completed=True,
                output={"slides": patches},
                summary=f"已按教师指令更新 {len(targets)} 页页面内容",
                message="目标页面内容润色完成",
            )
        if not ctx.has_tool_result("get_blueprint"):
            return AgentDecision(
                tool_calls=[
                    ToolCall(tool_name="get_blueprint", input={}),
                    ToolCall(tool_name="get_template_design", input={}),
                ],
                message="正在读取蓝图与模板，压缩重组页面内容",
            )
        bp = ctx.blueprint
        bp_model = bp if isinstance(bp, CourseBlueprintSchema) else CourseBlueprintSchema.model_validate(bp)
        theme = (ctx.template or {}).get("id") or DEFAULT_THEME
        from app.agents.generators import make_ppt
        content = make_ppt(bp_model, theme).model_dump()
        slides = content.get("slides") or []
        for slide in slides:
            slide["changed_fields"] = ["title", "purpose", "body", "blocks", "speaker_notes"]
        return AgentDecision(
            completed=True,
            output={"slides": slides},
            summary=f"已将上游内容压缩重组为 {len(slides)} 页页面内容，符合密度上限",
            message="页面内容生成完成",
        )


SLIDE_CONTENT_AGENT = SlideContentAgent()
