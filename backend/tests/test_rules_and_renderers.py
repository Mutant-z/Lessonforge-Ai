import zipfile
from pathlib import Path

from docx import Document
from pptx import Presentation

from app.agents.generators import make_blueprint, make_exercises, make_lesson_plan, make_ppt, make_task_sheet, make_verbatim, make_video_script, to_markdown
from app.models.entities import CourseProject
from app.renderers.docx_renderer import render_markdown_docx
from app.renderers.pptx_renderer import render_pptx
from app.services.export_service import build_course_package, safe_package_name
from app.services.material_service import safe_filename
from app.services.quality_service import estimate_chinese_minutes, validate_resources


def sample_course():
    return CourseProject(owner_id="u", title="牛顿第二定律", subject="高中物理", grade_level="高一", audience="已学习运动学基础的学生", duration_minutes=15, scenario="课堂讲解", language="中文", settings_json={"course_task": "解释力、质量与加速度的关系"})


def test_schemas_rules_and_timing():
    bp = make_blueprint(sample_course())
    ppt, exercise = make_ppt(bp), make_exercises(bp)
    script = make_video_script(bp, ppt)
    verbatim = make_verbatim(bp, ppt, script)
    data = {"ppt": ppt.model_dump(), "exercise": exercise.model_dump(), "video_script": script.model_dump(), "verbatim": verbatim.model_dump()}
    assert validate_resources(bp, data) == []
    assert sum(s.end_minute - s.start_minute for s in bp.timeline) == 15
    assert estimate_chinese_minutes("教" * 440) == 2


def test_safe_filenames():
    assert safe_filename("../../教案?.pdf").endswith(".pdf")
    assert "/" not in safe_package_name("物理/力学:第一课")


def test_docx_pptx_and_zip(tmp_path: Path):
    bp = make_blueprint(sample_course())
    values = {"lesson_plan": make_lesson_plan(bp), "ppt": make_ppt(bp), "task_sheet": make_task_sheet(bp), "exercise": make_exercises(bp)}
    values["video_script"] = make_video_script(bp, values["ppt"])
    values["verbatim"] = make_verbatim(bp, values["ppt"], values["video_script"])
    doc = render_markdown_docx("教学设计", to_markdown("lesson_plan", values["lesson_plan"]), tmp_path / "test.docx")
    ppt = render_pptx("测试课程", values["ppt"].model_dump(), tmp_path / "test.pptx")
    assert len(Document(doc).paragraphs) > 3
    assert len(Presentation(ppt).slides) == len(values["ppt"].slides)
    artifacts = {key: {"version": 1, "content_json": value.model_dump(), "content_markdown": to_markdown(key, value)} for key, value in values.items()}
    package, manifest = build_course_package("course", "测试课程", bp.model_dump(), 1, artifacts, tmp_path / "out")
    assert package.exists() and len(manifest["artifacts"]) >= 9
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None

