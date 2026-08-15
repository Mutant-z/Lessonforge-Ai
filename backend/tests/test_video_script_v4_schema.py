"""视频脚本 V4 数据契约与确定性转换测试。"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.agents.generators import make_blueprint, make_lesson_plan, make_seedance_video_script
from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.video_script_v4 import (
    VIDEO_SCRIPT_V4,
    SeedanceVideoScriptContentV4,
    seedance_video_script_for_generation,
    upgrade_video_script_v4,
    video_script_v4_to_markdown,
)
from app.services.quality_service import validate_video_script

from tests.test_video_script_upgrade import sample_course  # noqa: E402


@pytest.fixture
def bp() -> CourseBlueprintSchema:
    return make_blueprint(sample_course())


@pytest.fixture
def v3_payload(bp) -> dict:
    lesson = make_lesson_plan(bp)
    return make_seedance_video_script(bp, lesson).model_dump()


@pytest.fixture
def v4(bp, v3_payload) -> SeedanceVideoScriptContentV4:
    lesson = make_lesson_plan(bp)
    return upgrade_video_script_v4(v3_payload, lesson.model_dump())


def test_v3_upgrade_is_lossless_and_adds_dynamic_sections(bp, v3_payload, v4):
    """V3→V4 无损升级：分镜 ID、口播、镜头、事实与时间轴全部保留，仅新增章节层。"""
    assert v4.schema_version == VIDEO_SCRIPT_V4
    assert len(v4.scenes) == len(v3_payload["scenes"])
    assert len(v4.outline.sections) >= 2
    for v3_scene, v4_scene in zip(v3_payload["scenes"], v4.scenes):
        assert v3_scene["id"] == v4_scene.id
        assert v3_scene["spoken_text"] == v4_scene.spoken_text
        assert v3_scene["visual_prompt"] == v4_scene.visual_prompt
        assert v3_scene["start_seconds"] == v4_scene.start_seconds
        assert v3_scene["end_seconds"] == v4_scene.end_seconds
        assert v4_scene.section_id
    # 章节标题来自教学设计真实环节名
    section_ids = {item.id for item in v4.outline.sections}
    lesson = make_lesson_plan(bp)
    stage_titles = {item.title for item in lesson.stages}
    assert any(item.title in stage_titles for item in v4.outline.sections)
    # 结构门禁通过
    SeedanceVideoScriptContentV4.model_validate(v4.model_dump())


def test_v4_structure_gate_rejects_orphan_scene(v4):
    data = copy.deepcopy(v4.model_dump())
    data["scenes"][0]["section_id"] = "SEC-999"
    with pytest.raises(ValidationError):
        SeedanceVideoScriptContentV4.model_validate(data)


def test_v4_structure_gate_rejects_interleaved_sections(v4):
    """同章分镜必须在时间轴上连续。"""
    data = copy.deepcopy(v4.model_dump())
    scenes = data["scenes"]
    # 把一个 SEC-01 分镜插入 SEC-02 分镜块中间 → 第一章节在时间轴上被第二章节打断
    first_section_id = scenes[0]["section_id"]
    first_block_end = next(
        index for index, scene in enumerate(scenes)
        if scene["section_id"] != first_section_id
    )
    moved = scenes.pop(0)
    moved["section_id"] = scenes[first_block_end - 1]["section_id"]
    scenes.insert(first_block_end, moved)
    with pytest.raises(ValidationError):
        SeedanceVideoScriptContentV4.model_validate(data)


def test_v4_structure_gate_rejects_sequence_mismatch(v4):
    data = copy.deepcopy(v4.model_dump())
    data["outline"]["sections"][0]["sequence"] = 99
    with pytest.raises(ValidationError):
        SeedanceVideoScriptContentV4.model_validate(data)


def test_v4_quality_passes_and_catches_bad_references(bp, v4):
    assert validate_video_script(bp, v4.model_dump(), make_lesson_plan(bp).model_dump(), None) == []
    bad = copy.deepcopy(v4.model_dump())
    bad["scenes"][0]["objective_ids"] = ["OBJ-NOPE"]
    issues = validate_video_script(bp, bad, make_lesson_plan(bp).model_dump(), None)
    assert any(item["severity"] == "critical" and item["dimension"] == "alignment" for item in issues)


def test_gemini_renderer_tightens_agent_qa_to_ten_seconds(bp, v4):
    from app.agent.agents.video_script.qa import validate_video_script_v4

    issues = validate_video_script_v4(
        bp, v4.model_dump(), make_lesson_plan(bp).model_dump(),
        max_scene_seconds=10,
    )
    assert any("4–10 秒窗口" in item["description"] for item in issues)


def test_flat_projection_is_v3_and_consumable(v4, bp):
    flat = seedance_video_script_for_generation(v4.model_dump())
    assert flat.schema_version == "3.0"
    assert len(flat.scenes) == len(v4.scenes)
    assert all("section_id" not in scene.model_dump() for scene in flat.scenes)
    # 扁平 V3 仍通过原有校验（视频生成下游）
    assert validate_video_script(bp, flat.model_dump(), make_lesson_plan(bp).model_dump(), None) == []


def test_v4_markdown_groups_by_section(v4):
    md = video_script_v4_to_markdown(v4.model_dump())
    assert "动态章节" in md
    assert "所属章节" in md
    for section in v4.outline.sections:
        assert f"{section.sequence} · {section.title}" in md


def test_v4_roundtrip_after_edit(bp, v4):
    """模拟工具链修改后 V4 仍可通过 Schema 与 QA 门禁。"""
    from app.agent.agents.video_script.builder import VideoScriptBuilder

    builder = VideoScriptBuilder(v4.model_dump())
    builder.delete_section(v4.outline.sections[0].id, move_scenes_to=v4.outline.sections[1].id)
    assert builder.validate_content()["ok"]
    new_section = builder.add_section("问题驱动的讨论", purpose="以真实问题引导学生思考")
    builder.move_scene(builder.scenes[0]["id"], new_section["id"])
    assert builder.validate_content()["ok"]
    content = builder.to_content()
    SeedanceVideoScriptContentV4.model_validate(content)
    assert validate_video_script(bp, content, make_lesson_plan(bp).model_dump(), None) == []
