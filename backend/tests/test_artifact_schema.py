import pytest
from app.schemas.artifact import VideoAudioTrack, VerbatimSection, PedagogicalActionType


def test_video_audio_track_pedagogical_action():
    track = VideoAudioTrack(
        narration_text="同学们好，今天我们来看一下这个核心概念。",
        pedagogical_action="hook",
        delivery_tone="生动导入，引发好奇",
        speaking_rate_cps=4.0,
        emphasis_terms=["核心概念"],
    )
    assert track.pedagogical_action == "hook"
    assert track.speaking_rate_cps == 4.0
    assert "核心概念" in track.emphasis_terms


def test_video_audio_track_defaults():
    track = VideoAudioTrack(
        narration_text="这是一段简单的讲解文本。",
        delivery_tone="平稳讲解",
    )
    assert track.pedagogical_action is None
    assert track.speaking_rate_cps == 4.0
    assert track.emphasis_terms == []


def test_video_audio_track_invalid_pedagogical_action():
    with pytest.raises(Exception):
        VideoAudioTrack(
            narration_text="测试文本内容。",
            delivery_tone="平稳讲解",
            pedagogical_action="invalid_action",
        )


def test_verbatim_section_fields():
    section = VerbatimSection(
        id="VSEC-01",
        scene_id="VS-01",
        slide_ids=["S-01"],
        time_range="00:00—00:15",
        pedagogical_action="metaphor_explain",
        required_text="这里我们可以把变量想象成一个贴着标签的盒子。",
        optional_text="比如装玩具的盒子里放着数值。",
        key_emphasis=["变量", "盒子"],
        word_count=20,
        estimated_duration_seconds=5.0,
        interaction="思考：如果是空盒子会怎样？",
    )
    assert section.pedagogical_action == "metaphor_explain"
    assert section.word_count == 20
    assert section.estimated_duration_seconds == 5.0


def test_verbatim_section_defaults():
    section = VerbatimSection(
        id="VSEC-02",
        slide_ids=["S-02"],
        time_range="00:15—00:30",
        required_text="必须说的内容。",
        optional_text="",
        interaction="",
    )
    assert section.pedagogical_action is None
    assert section.scene_id is None
    assert section.key_emphasis == []
    assert section.word_count is None
    assert section.estimated_duration_seconds is None


def test_pedagogical_action_type_values():
    valid_actions = [
        "hook",
        "objective_guide",
        "scenario_connect",
        "metaphor_explain",
        "misconception_alert",
        "step_demonstration",
        "check_in",
        "summary_recap",
    ]
    for action in valid_actions:
        track = VideoAudioTrack(
            narration_text="测试讲解文本。",
            delivery_tone="平稳讲解",
            pedagogical_action=action,
        )
        assert track.pedagogical_action == action
