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
        ctx = tc.ctx
        is_revision = bool(ctx and getattr(ctx, "source_artifact", None) is not None)
        if targets:
            scope = f"只能返回这些目标页：{targets}，且必须完整覆盖全部目标页。"
        elif is_revision:
            scope = "修订任务：必须覆盖全部页面。"
        else:
            scope = "首次生成时每页列出全部语义字段。"
        revision_rule = (
            "\n这是对已有 PPT 的修订：必须按「用户/教师指令」实际改写文字措辞"
            "（润色/精简/调整表达等），保持页面结构与教学信息，不得增删页面。\n"
            "如需补写或填充内容，用更多短条目承载而非加长单条：每页≤6条、"
            "每条≤25字、正文与内容块合计≤120字，严格遵守 ppt_design_knowledge 密度上限。\n"
            "内容块只能使用这些结构：lead/bullets/steps/compare/quote/visual/note，"
            "不要发明其他结构类型（如 cards）。\n"
            "正文与内容块条目不要加装饰符号（🔹/•/-/* 等），每条含任何符号在内不超过25字。"
            if is_revision else ""
        )
        # 首次生成且模板为真实 deck：声明 15 页角色结构，让模型按模板槽位产出内容。
        # 即使模型未完全遵守，pipeline 也会用确定性 _align_initial_deck 对齐页序。
        deck_rule = ""
        if not targets and not is_revision:
            from app.renderers.deck_renderer import deck_structure
            from app.services.ppt_template_service import resolve_ppt_template
            template_id = getattr(tc.runtime, "preferred_template", None) or DEFAULT_THEME
            if resolve_ppt_template(template_id).get("composition") == "deck":
                structure = deck_structure(template_id)
                roles_text = "；".join(
                    f"第{r['index']}页 {r['role']}（{r['page_type']}，{r['slot_count']} 个内容槽）"
                    for r in structure["roles"]
                )
                deck_rule = (
                    f"\n本模板是真实 PPT 模板（deck），共 {structure['page_count']} 页，页面与模板槽位一一对应："
                    f"completed.output.slides 必须恰好 {structure['page_count']} 页，"
                    "slides[i] 对应模板第 i+1 页，页序不可更改、不可增删页。"
                    f"模板角色与槽位：{roles_text}。"
                    "每页正文与内容块展平后的条目数不得超过该页槽位数 slot_count；"
                    "封面页 body 填课程副标题，目标页给出编号目标，案例页给出步骤，末页给出收束语。"
                )
        return super().build_system_prompt(tc) + (
            "\ncompleted.output 必须严格符合 SlideContentPatch："
            "{slides:[{id,changed_fields,title?,purpose?,body?,blocks?,speaker_notes?}]}。"
            "changed_fields 只能列出且必须完整列出本项实际提供的语义字段。"
            + revision_rule + scope + deck_rule
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
