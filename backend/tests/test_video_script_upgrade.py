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
    recalculate_scene_timelines,
    to_markdown,
)
from app.models.entities import CourseProject
from app.renderers.docx_renderer import render_video_script_docx
from app.schemas.artifact import (
    AnimationCue,
    LegacyVideoScriptContent,
    PauseCue,
    SubtitleChunk,
    VideoAudioTrack,
    VideoScene,
    VideoScriptContent,
    VideoTextTrack,
    VideoVisualTrack,
)
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


def test_script_v1_prompt_file_exists_and_contains_pedagogical_actions_and_rules():
    prompt_path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "script" / "v1.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    assert len(prompt) > 0

    # Test all 8 pedagogical actions
    actions = [
        "hook", "objective_guide", "scenario_connect", "metaphor_explain",
        "misconception_alert", "step_demonstration", "check_in", "summary_recap"
    ]
    for action in actions:
        assert action in prompt

    # Test speech rate and delivery tone guidance
    assert "speaking_rate_cps" in prompt
    assert "delivery_tone" in prompt
    assert "pause_cues" in prompt

    # Test timeline calculation rules
    assert "start_seconds" in prompt
    assert "end_seconds" in prompt
    assert "subtitle_chunks" in prompt


def _scene(
    scene_id: str,
    narration: str,
    pause_duration: float = 0.0,
    wait_seconds: float = 0.0,
) -> VideoScene:
    return VideoScene(
        id=scene_id,
        sequence=1,
        title="测试分镜",
        pedagogical_role="概念讲解",
        lesson_stage_id="ACT-01",
        slide_id="S01",
        objective_ids=["OBJ-01"],
        knowledge_point_ids=["KP-01"],
        start_seconds=0.0,
        end_seconds=1000.0,
        learning_purpose="测试",
        visual_track=VideoVisualTrack(
            composition="主画面",
            animation_cues=[AnimationCue(offset_seconds=999, target="页", action="高亮", instruction="测试")],
        ),
        audio_track=VideoAudioTrack(
            narration_text=narration,
            pedagogical_action="hook",
            delivery_tone="生动",
            pause_cues=[PauseCue(offset_seconds=0, duration_seconds=pause_duration, purpose="思考")] if pause_duration else [],
        ),
        text_track=VideoTextTrack(
            on_screen_text=["测试"],
            subtitle_chunks=[
                SubtitleChunk(start_offset_seconds=0, end_offset_seconds=30, text=narration),
            ],
        ),
        interaction=None if not wait_seconds else type(
            "Interaction", (), {"prompt": "请思考", "wait_seconds": wait_seconds,
                                "expected_response": "说出依据", "feedback_transition": "继续" })(),
    )


def test_recalculate_scene_timelines_recomputes_continuous_axis():
    # 第一镜旁白 6 字 @4cps => 1.5s，不足下限取 3.0s；第二镜 11 字 => 2.75s 口播 + 2.0s 停顿 => 4.75s
    scenes = [
        _scene("VS-01", "欢迎来到本课。", pause_duration=0.0),
        _scene("VS-02", "今天我们学习核心概念。", pause_duration=2.0),
    ]
    updated = recalculate_scene_timelines(scenes, chars_per_minute=240)

    assert updated[0].start_seconds == 0.0
    assert updated[0].end_seconds == 3.0
    assert updated[1].start_seconds == 3.0
    assert updated[1].end_seconds == 7.8  # 3.0 + 2.75s 口播 + 2.0s 停顿
    # 越界的动效与停顿 Cue 被裁剪到新时长内
    assert all(cue.offset_seconds <= 3.0 for cue in updated[0].visual_track.animation_cues)
    assert updated[1].audio_track.pause_cues and all(
        cue.offset_seconds + cue.duration_seconds <= 4.75 for cue in updated[1].audio_track.pause_cues
    )
    # 字幕块被重新对齐到新时长内
    assert updated[0].text_track.subtitle_chunks[-1].end_offset_seconds == 3.0
    assert updated[1].text_track.subtitle_chunks[-1].end_offset_seconds == 4.75


def test_make_video_script_populates_pedagogical_fields():
    bp = make_blueprint(sample_course())
    lesson, ppt = make_lesson_plan(bp), make_ppt(bp)
    script = make_video_script(bp, lesson, ppt)

    assert script.scenes[0].audio_track.pedagogical_action == "hook"
    assert script.scenes[-1].audio_track.pedagogical_action == "summary_recap"
    assert all(scene.audio_track.speaking_rate_cps == 4.0 for scene in script.scenes)
    assert validate_video_script(bp, script.model_dump(), lesson.model_dump(), ppt.model_dump()) == []


def test_make_verbatim_populates_pedagogical_and_timing_metadata():
    bp = make_blueprint(sample_course())
    lesson, ppt = make_lesson_plan(bp), make_ppt(bp)
    script = make_video_script(bp, lesson, ppt)
    verbatim = make_verbatim(bp, ppt, script)

    first = verbatim.sections[0]
    assert first.scene_id == script.scenes[0].id
    assert first.pedagogical_action == script.scenes[0].audio_track.pedagogical_action
    assert first.key_emphasis == script.scenes[0].audio_track.emphasis_terms
    narration_len = len(script.scenes[0].audio_track.narration_text)
    assert first.word_count == narration_len
    assert first.estimated_duration_seconds == round(narration_len / 4.0, 1)
    assert len(verbatim.sections) == len(script.scenes)

