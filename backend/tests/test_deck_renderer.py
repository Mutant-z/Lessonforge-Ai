from pathlib import Path

from app.agents.generators import make_blueprint, make_deck
from app.models.entities import CourseProject
from app.renderers.deck_renderer import deck_template_path, render_deck, role_order, slot_counts


def _course():
    return CourseProject(
        owner_id="u", title="浮力原理", subject="初中物理", grade_level="八年级",
        audience="学生", duration_minutes=15, scenario="课堂讲解",
        language="中文", settings_json={"key_points": "浮力产生的原因与阿基米德原理"},
    )


def test_make_deck_adapts_body_to_template_slot_counts():
    bp = make_blueprint(_course())
    order = role_order()
    assert len(order) == 15
    # 不同模板槽位数不同，make_deck 按模板整形内容
    for template_id in ("lessonforge_deck_academic", "lessonforge_deck_ai_future", "lessonforge_deck_business"):
        deck = make_deck(bp, template_id)
        assert len(deck) == 15
        counts = slot_counts(template_id)
        for index, role in enumerate(order):
            assert len(deck[index]["body"]) == counts.get(role, 0), f"{template_id} {role}"


def test_render_deck_fills_slots_and_preserves_design():
    from pptx import Presentation

    bp = make_blueprint(_course())
    for template_id in ("lessonforge_deck_academic", "lessonforge_deck_business"):
        deck = make_deck(bp, template_id)
        out = Path(f"/tmp/test_deck_{template_id.split('_')[-1]}.pptx")
        render_deck(deck_template_path(template_id), deck, out, template_id)
        prs = Presentation(str(out))
        assert len(prs.slides) == 15
        slide3_texts = [sh.text_frame.text for sh in prs.slides[2].shapes if sh.has_text_frame]
        assert any(text == "学习目标" for text in slide3_texts)
        assert any("OBJ" in text for text in slide3_texts)


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
