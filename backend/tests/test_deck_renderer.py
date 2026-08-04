from pathlib import Path

from app.agents.generators import make_blueprint, make_deck
from app.models.entities import CourseProject
from app.renderers.deck_renderer import _load_slots, deck_template_path, render_deck


def _course():
    return CourseProject(
        owner_id="u", title="浮力原理", subject="初中物理", grade_level="八年级",
        audience="学生", duration_minutes=15, scenario="课堂讲解",
        language="中文", settings_json={"key_points": "浮力产生的原因与阿基米德原理"},
    )


def test_make_deck_produces_15_role_pages():
    deck = make_deck(make_blueprint(_course()))
    slots = _load_slots()
    assert len(deck) == len(slots["role_order"]) == 15
    for index, role in enumerate(slots["role_order"]):
        assert len(deck[index]["body"]) >= len(slots["roles"][role]["content"]), role


def test_render_deck_fills_slots_and_preserves_design():
    from pptx import Presentation

    deck = make_deck(make_blueprint(_course()))
    for template_id in ("Academic_Template", "Business_Template"):
        out = Path(f"/tmp/test_deck_{template_id}.pptx")
        render_deck(deck_template_path(template_id), deck, out)
        prs = Presentation(str(out))
        assert len(prs.slides) == 15
        slide3_texts = [sh.text_frame.text for sh in prs.slides[2].shapes if sh.has_text_frame]
        assert any(text == "学习目标" for text in slide3_texts)
        assert any("OBJ-01" in text for text in slide3_texts)


def test_export_builds_deck_package_for_deck_theme(tmp_path):
    from app.agents.generators import make_blueprint, make_ppt
    from app.services.export_service import build_course_package
    from pptx import Presentation

    course = _course()
    bp = make_blueprint(course).model_dump()
    ppt = make_ppt(make_blueprint(course)).model_dump()
    ppt["theme"] = "lessonforge_deck_academic"
    build_course_package(
        "c1", "浮力原理", bp, 1,
        {"ppt": {"content_json": ppt, "version": 1}}, tmp_path,
    )
    pptx = tmp_path / "浮力原理_微课资源包" / "02_课件.pptx"
    assert pptx.exists()
    prs = Presentation(str(pptx))
    assert len(prs.slides) == 15
    slide3_texts = [sh.text_frame.text for sh in prs.slides[2].shapes if sh.has_text_frame]
    assert any(text == "学习目标" for text in slide3_texts)
    assert any("OBJ" in text for text in slide3_texts)
