from app.schemas.artifact import Slide
from app.services.ppt_knowledge_service import load_ppt_design_knowledge


def test_knowledge_json_is_valid_and_loadable():
    knowledge = load_ppt_design_knowledge()
    assert knowledge["version"] == "1.0.0"
    limits = knowledge["density_limits"]
    assert limits == {
        "title_chars": 30, "body_chars": 120, "body_items": 6,
        "item_chars": 25, "speaker_notes_chars": 30,
    }
    assert len(knowledge["design_principles"]) >= 3
    assert len(knowledge["layout_library"]) >= 8
    assert len(knowledge["visual_suggestion_guidelines"]) >= 2
    assert len(knowledge["diagram_guidance"]) >= 4
    assert len(knowledge["quality_checklist"]) >= 4


def test_page_type_guidance_matches_slide_schema():
    literal_members = set(Slide.model_fields["page_type"].annotation.__args__)
    assert set(load_ppt_design_knowledge()["page_type_guidance"]) == literal_members


def test_every_page_type_has_layouts_from_library():
    knowledge = load_ppt_design_knowledge()
    library = set(knowledge["layout_library"])
    for page_type, guidance in knowledge["page_type_guidance"].items():
        assert guidance["layouts"], f"{page_type} 缺少建议版式"
        assert set(guidance["layouts"]) <= library, f"{page_type} 引用了版式库外的版式"


from app.services.ppt_knowledge_service import check_ppt_against_knowledge


def compliant_ppt_content():
    return {
        "theme": "lessonforge_swiss_blue",
        "slides": [
            {
                "id": "S01", "page_type": "cover", "title": "阿基米德原理",
                "purpose": "建立课程主题", "body": ["物理", "八年级"], "layout": "cover",
                "visual_suggestion": "封面左侧放置课程主题大标题，右侧留白，用一条主题色细线建立视觉锚点。",
                "speaker_notes": "围绕本课主题建立情境与期待，说明本节将回答的核心问题，用提问唤起学生的既有经验。",
                "duration_seconds": 20,
            },
            {
                "id": "S02", "page_type": "objectives", "title": "本课学习目标：可观察、可检验",
                "purpose": "明确可观察成果", "body": ["OBJ-01：解释浮力原理", "OBJ-02：完成浮力计算"],
                "layout": "bullet",
                "visual_suggestion": "用编号列表按目标顺序纵向排列，目标编号使用主题色圆形徽章。",
                "speaker_notes": "逐一说明每条学习目标，指出目标与课堂环节的对应关系，检查学生是否明确本课要达成的结果。",
                "duration_seconds": 40,
            },
        ],
    }


def violating_ppt_content():
    return {
        "theme": "lessonforge_swiss_blue",
        "slides": [
            {
                "id": "S01", "page_type": "objectives", "title": "学习目标",
                "purpose": "x", "body": ["这是一条非常长的正文条目内容，长度明显超过了单条二十五字的上限要求"],
                "layout": "numbered", "visual_suggestion": "简单", "speaker_notes": "太短",
                "duration_seconds": 0,
            },
        ],
    }


def test_compliant_ppt_passes_all_rules():
    assert check_ppt_against_knowledge(compliant_ppt_content()) == []


def test_violating_ppt_reports_expected_rules():
    violations = check_ppt_against_knowledge(violating_ppt_content())
    assert {item.rule_id for item in violations} == {
        "title.conclusion", "density.item_chars", "density.speaker_notes",
        "layout.valid", "visual.suggestion_length", "duration.positive",
    }
    assert {item.slide_id for item in violations} == {"S01"}


def test_cover_title_exempt_from_conclusion_rule():
    content = compliant_ppt_content()
    content["slides"][0]["title"] = "学习目标"
    assert check_ppt_against_knowledge(content) == []


def test_layout_page_type_mismatch_reported():
    content = compliant_ppt_content()
    content["slides"][1]["layout"] = "steps"
    rules = {item.rule_id for item in check_ppt_against_knowledge(content)}
    assert "layout.valid" not in rules
    assert "layout.page_type_match" in rules


def test_unknown_page_type_reported():
    content = compliant_ppt_content()
    content["slides"][0]["page_type"] = "diagram"
    rules = {item.rule_id for item in check_ppt_against_knowledge(content)}
    assert "page_type.unknown" in rules


import pytest
from sqlalchemy import select

from app.agents.generators import make_blueprint
from app.core.database import SessionLocal
from app.models.entities import CourseProject, PromptTemplate
from app.services.agent_initialization_service import deterministic_bundle
from app.services.agent_prompt_service import (
    active_prompt_template, ensure_prompt_templates, prepare_profile_prompts,
)


def sample_course():
    return CourseProject(
        owner_id="u", title="牛顿第二定律", subject="高中物理", grade_level="高一",
        audience="已学习运动学基础的学生", duration_minutes=15, scenario="课堂讲解",
        language="中文", settings_json={},
    )


@pytest.mark.asyncio
async def test_ppt_agent_v2_active_and_knowledge_injected(client):
    async with SessionLocal() as db:
        await ensure_prompt_templates(db)
        v2 = await db.scalar(select(PromptTemplate).where(
            PromptTemplate.agent_type == "ppt_agent", PromptTemplate.version == "v2"))
        assert v2 is not None, "ppt_agent 缺少 v2 模板"
        active = await active_prompt_template(db, "ppt_agent")
        assert active.version == "v2", "ppt_agent 激活版本应为 v2"
        v1 = await db.scalar(select(PromptTemplate).where(
            PromptTemplate.agent_type == "ppt_agent", PromptTemplate.version == "v1"))
        course = sample_course()
        bp = make_blueprint(course)
        context = next(
            profile for profile in deterministic_bundle(bp, course, {}, {}).profiles
            if profile.task_type == "ppt"
        ).model_dump()
        sys_v2, _, _ = prepare_profile_prompts(v2, context, course, bp.model_dump(), 1)
        assert "ppt_design_knowledge" in sys_v2
        assert load_ppt_design_knowledge()["version"] in sys_v2
        sys_v1, _, _ = prepare_profile_prompts(v1, context, course, bp.model_dump(), 1)
        assert "ppt_design_knowledge" not in sys_v1
        assert "设计知识" in sys_v2


from app.agents.generators import make_blueprint, make_ppt


def test_mock_ppt_passes_all_knowledge_rules():
    content = make_ppt(make_blueprint(sample_course())).model_dump()
    violations = check_ppt_against_knowledge(content)
    assert violations == []


def test_mock_ppt_passes_rules_with_long_blueprint_content():
    course = CourseProject(
        owner_id="u", title="牛顿第二定律的应用场景与解题方法研究",
        subject="高中物理", grade_level="高一",
        audience="已学习运动学基础的学生", duration_minutes=15, scenario="课堂讲解",
        language="中文",
        settings_json={
            "course_task": "解释力、质量与加速度的关系及其在复杂情境中的应用",
            "key_points": "牛顿第二定律的核心概念及其适用条件在复杂情境中的应用方法",
        },
    )
    content = make_ppt(make_blueprint(course)).model_dump()
    violations = check_ppt_against_knowledge(content)
    assert violations == []
