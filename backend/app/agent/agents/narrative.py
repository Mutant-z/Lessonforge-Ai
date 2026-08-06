"""叙事 Agent：决定整套 PPT 的叙事结构、章节划分、页面顺序与每页目标。

Mock 路径：从 make_ppt 派生（与现有测试的 15 页角色结构对齐，保持 parity）；
LLM 路径：可产出任意页数的动态结构（不固定 15 页）。
"""
from app.agent.agents.base import Agent
from app.agent.registry import ToolContext, register_tool
from app.agent.schemas import AgentDecision, ToolCall
from app.schemas.blueprint import CourseBlueprintSchema

DEFAULT_THEME = "lessonforge_deck_academic"


def _bp_dict(ctx) -> dict:
    bp = ctx.blueprint
    if bp is None:
        return {}
    if isinstance(bp, CourseBlueprintSchema):
        return bp.model_dump()
    if isinstance(bp, dict):
        return bp
    return getattr(bp, "content_json", {})


class NarrativeAgent(Agent):
    key = "narrative"
    name = "演示叙事 Agent"
    role = "读取蓝图与上游产物，决定章节、总页数、页面顺序与每页目标"
    required_artifacts = ["source_snapshot"]
    produced_artifacts = ["presentation_narrative"]
    allowed_tools = ["get_blueprint", "get_upstream_artifacts", "get_template_design"]

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        if not ctx.has_tool_result("get_blueprint") or not ctx.has_tool_result("get_template_design"):
            return AgentDecision(
                tool_calls=[
                    ToolCall(tool_name="get_blueprint", input={}),
                    ToolCall(tool_name="get_upstream_artifacts", input={"kinds": ["lesson_plan"]}),
                    ToolCall(tool_name="get_template_design", input={}),
                ],
                message="正在读取蓝图与模板设计系统，规划演示叙事结构",
            )
        bp = _bp_dict(ctx)
        theme = (ctx.template or {}).get("id") or DEFAULT_THEME
        slides = self._derive_slides(bp, theme)
        sections = self._derive_sections(bp, slides)
        narrative = {
            "title": (bp.get("course_identity") or {}).get("title", "课程"),
            "strategy": "按导入→建构→应用→总结组织页面；每页一个核心信息层级",
            "total_slides": len(slides),
            "sections": sections,
            "slides": slides,
        }
        return AgentDecision(
            completed=True,
            output=narrative,
            summary=f"已规划演示叙事：{len(sections)} 个章节、{len(slides)} 页",
            message="演示结构规划完成",
        )

    @staticmethod
    def _derive_slides(bp: dict, theme: str) -> list[dict]:
        from app.agents.generators import _PAGE_PURPOSE, make_ppt
        from app.schemas.blueprint import CourseBlueprintSchema
        bp_model = CourseBlueprintSchema.model_validate(bp)
        content = make_ppt(bp_model, theme).model_dump()
        slides = []
        for index, slide in enumerate(content.get("slides") or []):
            slides.append({
                "slideId": slide["id"], "order": index + 1,
                "sectionId": _section_for_page(slide.get("page_type", "concept")),
                "purpose": slide.get("purpose") or _PAGE_PURPOSE.get(slide.get("page_type"), "讲解要点"),
                "keyMessage": slide.get("title", ""),
                "visualIntent": slide.get("visual_suggestion", ""),
            })
        return slides

    @staticmethod
    def _derive_sections(bp: dict, slides: list[dict]) -> list[dict]:
        timeline = (bp.get("timeline") or [])
        sections = [{"id": "sec-cover", "title": "封面", "order": 1}]
        for index, segment in enumerate(timeline[:3]):
            sections.append({"id": f"sec-{index + 1}", "title": segment.get("name", f"环节{index + 1}"), "order": index + 2})
        if not timeline:
            sections.append({"id": "sec-content", "title": "正文", "order": 2})
        return sections


def _section_for_page(page_type: str) -> str:
    mapping = {
        "cover": "sec-cover", "objectives": "sec-1", "scenario": "sec-1",
        "concept": "sec-2", "process": "sec-2", "comparison": "sec-2", "case": "sec-2",
        "question": "sec-3", "exercise": "sec-3", "homework": "sec-3",
        "summary": "sec-3",
    }
    return mapping.get(page_type, "sec-content")


NARRATIVE_AGENT = NarrativeAgent()
