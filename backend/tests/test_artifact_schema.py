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


from app.schemas.artifact import Slide


def test_slide_blocks_discriminated_union():
    slide = Slide(
        id="S05", page_type="process", title="应用三步",
        purpose="形成可迁移方法", body=["第一步", "第二步", "第三步"], layout="steps",
        visual_suggestion="用三步横向流程线展示应用步骤。", speaker_notes="逐步示范。",
        duration_seconds=40,
        blocks=[
            {"kind": "lead", "text": "先识别任务与条件", "sub": "再选择核心概念"},
            {"kind": "steps", "steps": [{"title": "识别", "detail": "找出已知与所求"}, {"title": "选择", "detail": "匹配核心概念"}]},
            {"kind": "note", "text": "检查结论是否合理"},
        ],
    )
    assert slide.blocks[0].kind == "lead"
    assert slide.blocks[1].kind == "steps"
    assert slide.blocks[2].kind == "note"
    assert slide.blocks[1].steps[0].title == "识别"


def test_slide_blocks_default_empty_and_body_kept():
    slide = Slide(
        id="S01", page_type="cover", title="阿基米德原理",
        purpose="建立课程主题", body=["物理", "八年级"], layout="cover",
        visual_suggestion="封面左侧放置课程主题大标题。", speaker_notes="围绕主题建立情境。",
        duration_seconds=20,
    )
    assert slide.blocks == []
    assert slide.body == ["物理", "八年级"]


def test_slide_block_unknown_kind_rejected():
    with pytest.raises(Exception):
        Slide(
            id="S01", page_type="concept", title="核心概念", purpose="p",
            body=["a"], layout="split", visual_suggestion="x" * 12, speaker_notes="y" * 30,
            duration_seconds=20,
            blocks=[{"kind": "video", "text": "不该存在"}],
        )


def test_slide_compare_quote_visual_blocks_parse():
    slide = Slide(
        id="S06", page_type="concept", title="概念与关系", purpose="p",
        body=["a"], layout="split", visual_suggestion="x" * 12, speaker_notes="y" * 30,
        duration_seconds=20,
        blocks=[
            {"kind": "compare", "left": {"heading": "适用时", "items": ["A"]}, "right": {"heading": "不适用", "items": ["B"]}},
            {"kind": "quote", "text": "先判断，再说明依据", "citation": "课堂任务"},
            {"kind": "visual", "diagram": "flow", "caption": "推理路径"},
        ],
    )
    assert slide.blocks[0].kind == "compare"
    assert slide.blocks[0].left.items == ["A"]
    assert slide.blocks[1].kind == "quote"
    assert slide.blocks[2].kind == "visual"
    assert slide.blocks[2].diagram == "flow"
