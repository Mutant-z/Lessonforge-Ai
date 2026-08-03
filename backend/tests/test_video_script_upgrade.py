from pathlib import Path

import pytest
from docx import Document
from pydantic import ValidationError

from app.agents.generators import (
    make_blueprint,
    make_lesson_plan,
    make_ppt,
    make_verbatim,
    make_video_script,
    to_markdown,
)
from app.models.entities import CourseProject
from app.renderers.docx_renderer import render_video_script_docx
from app.schemas.artifact import LegacyVideoScriptContent, VideoScriptContent
from app.services.quality_service import validate_video_script


def sample_course():
    return CourseProject(
        owner_id="u", title="牛顿第二定律", subject="高中物理", grade_level="高一",
        audience="已学习运动学基础的学生", duration_minutes=15, scenario="课堂讲解",
        language="中文", settings_json={"course_task": "解释力、质量与加速度的关系"},
    )


def test_video_script_v2_schema_quality_and_verbatim_handoff():
    bp = make_blueprint(sample_course())
    lesson, ppt = make_lesson_plan(bp), make_ppt(bp)
    script = make_video_script(bp, lesson, ppt)

    assert script.schema_version == "2.0"
    assert script.production_settings.mode == "ppt_screen_recording"
    assert script.scenes[-1].end_seconds == bp.course_identity.duration_minutes * 60
    assert {scene.slide_id for scene in script.scenes} == {slide.id for slide in ppt.slides}
    assert validate_video_script(bp, script.model_dump(), lesson.model_dump(), ppt.model_dump()) == []

    verbatim = make_verbatim(bp, ppt, script)
    assert len(verbatim.sections) == len(script.scenes)
    assert verbatim.sections[0].slide_ids == [script.scenes[0].slide_id]
    assert script.scenes[0].audio_track.narration_text in verbatim.sections[0].required_text


def test_video_script_schema_rejects_broken_timeline_and_cues():
    bp = make_blueprint(sample_course())
    lesson, ppt = make_lesson_plan(bp), make_ppt(bp)
    payload = make_video_script(bp, lesson, ppt).model_dump()
    payload["scenes"][1]["start_seconds"] = payload["scenes"][0]["start_seconds"]
    with pytest.raises(ValidationError, match="重叠|倒序"):
        VideoScriptContent.model_validate(payload)

    payload = make_video_script(bp, lesson, ppt).model_dump()
    payload["scenes"][0]["visual_track"]["animation_cues"][0]["offset_seconds"] = 999
    with pytest.raises(ValidationError, match="动效提示超出"):
        VideoScriptContent.model_validate(payload)


def test_video_script_quality_reports_external_reference_and_subtitle_errors():
    bp = make_blueprint(sample_course())
    lesson, ppt = make_lesson_plan(bp), make_ppt(bp)
    payload = make_video_script(bp, lesson, ppt).model_dump()
    payload["scenes"][0]["slide_id"] = "S404"
    payload["scenes"][0]["lesson_stage_id"] = "ACT-404"
    payload["scenes"][0]["objective_ids"] = ["OBJ-404"]
    payload["scenes"][0]["knowledge_point_ids"] = ["KP-404"]
    payload["scenes"][1]["text_track"]["subtitle_chunks"][0]["text"] = "字幕不一致"

    issues = validate_video_script(bp, payload, lesson.model_dump(), ppt.model_dump())
    descriptions = "\n".join(item["description"] for item in issues)
    assert all(item["target_agent"] == "video_script_agent" for item in issues)
    assert "S404" in descriptions
    assert "ACT-404" in descriptions
    assert "OBJ-404" in descriptions
    assert "KP-404" in descriptions
    assert "字幕未完整" in descriptions


def test_legacy_video_script_remains_readable_and_requests_v2_upgrade():
    bp = make_blueprint(sample_course())
    lesson, ppt = make_lesson_plan(bp), make_ppt(bp)
    legacy = {
        "segments": [{
            "id": "VS-01", "time_range": "00:00—00:20", "stage": "导入",
            "slide_ids": ["S01"], "visual": "显示封面", "narration": "欢迎学习",
            "action": "淡入", "on_screen_text": "课程标题", "pause": "自然停顿",
            "production_notes": "保持 16:9",
        }],
    }
    assert LegacyVideoScriptContent.model_validate(legacy).segments[0].id == "VS-01"
    issues = validate_video_script(bp, legacy, lesson.model_dump(), ppt.model_dump())
    assert issues[0]["dimension"] == "compatibility"


def test_video_script_markdown_and_docx_cover_production_tracks(tmp_path: Path):
    bp = make_blueprint(sample_course())
    lesson, ppt = make_lesson_plan(bp), make_ppt(bp)
    script = make_video_script(bp, lesson, ppt)
    markdown = to_markdown("video_script", script)
    for marker in ("制作方式", "学习目的", "画面", "动效", "旁白", "字幕", "教学环节"):
        assert marker in markdown

    path = render_video_script_docx(
        "微课视频脚本", script.model_dump(), tmp_path / "video-script.docx", "V2",
        {"lesson_plan": 2, "ppt": 3},
    )
    document = Document(path)
    assert len(document.tables) >= 1 + len(script.scenes) * 2
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "微课视频脚本" in text
    assert script.scenes[0].title in text
