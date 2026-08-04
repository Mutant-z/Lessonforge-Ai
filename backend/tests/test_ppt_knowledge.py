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
