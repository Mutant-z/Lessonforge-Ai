"""PPT Edit V3: grounded intent, durable identity and minimal mutations."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.edit_v3 import (
    EditOperationV3,
    EditTarget,
    PPTEditIntentV3,
    build_change_set,
    build_mutation_plan,
    ensure_stable_element_identity,
    ground_intent,
    intent_from_command,
    validate_intent_scope,
)
from app.agent.polish_command import resolve_polish_command
from app.agent.registry import ToolContext, ensure_loaded, execute_tool
from app.agent.runtime import PPTAgentRuntime
from app.renderers.presentation_builder import PresentationBuilder


def _slides(count: int = 40) -> list[dict]:
    return [{
        "id": f"S{index:02d}", "page_type": "concept", "title": f"标题 {index}",
        "body": [f"要点 {index}-1", f"要点 {index}-2"], "blocks": [],
        "speaker_notes": f"备注 {index}", "duration_seconds": 30,
        "elements": [
            {"id": "T1", "kind": "textbox", "role": "title", "content_ref": "title", "text": f"标题 {index}", "x": 1, "y": .5, "w": 8, "h": .8, "style": {"size": 30}},
            {"id": "B1", "kind": "textbox", "role": "body", "content_ref": "body.0", "text": f"要点 {index}-1", "x": 1, "y": 1.6, "w": 8, "h": 1, "style": {"size": 20}},
            {"id": "I1", "kind": "image", "role": "visual", "x": 9.5, "y": 1.5, "w": 3, "h": 3, "asset_id": f"A{index}"},
        ],
    } for index in range(1, count + 1)]


def test_chinese_intent_corpus_has_200_grounded_scope_cases():
    slides = _slides()
    ids = [item["id"] for item in slides]
    templates = [
        "第{n}页只改标题",
        "请把第{n}页图片放大10%",
        "第{n}页正文间距大一些，不改图片",
        "润色第{n}页第二条要点，保留备注",
        "第{n}页重新排版但文字不要改",
    ]
    corpus = [(template.format(n=index), f"S{index:02d}") for template in templates for index in range(1, 41)]
    assert len(corpus) == 200
    for instruction, expected in corpus:
        command = resolve_polish_command(instruction, canonical_ids=ids)
        assert command.scope.target_slide_ids == [expected], instruction


def test_visual_golden_manifest_has_20_fixed_direction_cases():
    cases = json.loads((Path(__file__).parent / "fixtures" / "ppt_v3_golden_cases.json").read_text(encoding="utf-8"))
    assert len(cases) >= 20
    assert len({item["id"] for item in cases}) == len(cases)
    assert all(item.get("instruction") and item.get("changed") and item.get("preserve") for item in cases)


def test_invalid_grounded_explicit_scope_is_rejected_before_mutation():
    slides = _slides(2)
    fallback = resolve_polish_command("第99页重新排版", canonical_ids=["S01", "S02"])
    intent = intent_from_command(fallback, fallback_used=True)
    grounded = ground_intent(intent, fallback=fallback, slides=slides, metadata={})
    assert grounded.scope.source == "explicit_text"
    assert grounded.scope.target_slide_ids == []
    with pytest.raises(Exception) as caught:
        validate_intent_scope(grounded, ["S01", "S02"])
    assert getattr(caught.value, "code", "") == "invalid_slide_scope"


def test_explicit_text_scope_overrides_ui_scope_while_modality_remains_hard():
    slides = _slides(3)
    fallback = resolve_polish_command("第1页文字和图片都换掉", canonical_ids=["S01", "S02", "S03"])
    intent = PPTEditIntentV3(
        raw_text="第1页文字和图片都换掉",
        operations=[
            EditOperationV3(operation_id="text", domain="text", action="rewrite", object_targets=["title"], targets=[EditTarget(slide_id="S01")]),
            EditOperationV3(operation_id="image", domain="image_asset", action="replace", object_targets=["image"], targets=[EditTarget(slide_id="S01")]),
        ],
    )
    grounded = ground_intent(intent, fallback=fallback, slides=slides, metadata={
        "target_slide_ids": ["S02"], "active_slide_id": "S03", "modality": "image",
    })
    assert grounded.scope.target_slide_ids == ["S01"]
    assert grounded.scope.source == "explicit_text"
    assert [item.domain for item in grounded.operations] == ["image_asset"]
    assert grounded.operations[0].targets[0].slide_id == "S01"


def test_stable_identity_plan_and_change_set_are_element_level():
    before = _slides(1)
    ensure_stable_element_identity(before)
    title = before[0]["elements"][0]
    assert title["semantic_id"] and title["origin_content_ref"] == "title" and title["revision_hash"]
    fallback = resolve_polish_command("只改当前页标题", active_slide_id="S01", canonical_ids=["S01"])
    intent = intent_from_command(fallback, fallback_used=True)
    intent = ground_intent(intent, fallback=fallback, slides=before, metadata={"active_slide_id": "S01", "modality": "text"})
    plan = build_mutation_plan(intent, before)
    assert plan.steps and plan.steps[0].tool_name == "patch_text_by_ref"
    assert plan.steps[0].content_refs == ["title"]

    after = deepcopy(before)
    after[0]["title"] = "新标题"
    after[0]["elements"][0]["text"] = "新标题"
    change_set = build_change_set(before, after, ["S01"])
    assert change_set["changed_slide_ids"] == ["S01"]
    assert any(item.get("content_ref") == "title" for item in change_set["pages"][0]["changes"])


@pytest.mark.asyncio
async def test_patch_text_by_ref_changes_only_the_target_ref():
    ensure_loaded()
    source = _slides(1)[0]
    builder = PresentationBuilder().from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]})
    runtime = SimpleNamespace(selected_slide_ids=["S01"], affected_slide_ids=[], mutation_evidence=[], mutation_applied=False)
    before = deepcopy(builder.get_slide("S01"))
    result = await execute_tool("patch_text_by_ref", ToolContext(builder=builder, runtime=runtime), {
        "patches": [{"slide_id": "S01", "content_ref": "title", "replacement": "精准新标题"}],
    })
    after = builder.get_slide("S01")
    assert result.ok and after["title"] == "精准新标题"
    assert after["body"] == before["body"]
    assert next(item for item in after["elements"] if item["id"] == "I1") == next(item for item in before["elements"] if item["id"] == "I1")
    assert runtime.mutation_evidence[0]["tool_name"] == "patch_text_by_ref"


@pytest.mark.asyncio
async def test_v3_candidate_confirmation_hook_never_creates_a_request():
    runtime = SimpleNamespace(candidate_request_id="", candidate_options=[])
    assert await PPTAgentRuntime._request_candidate_confirmation_if_needed(
        SimpleNamespace(pipeline=runtime),
    ) is False
    assert runtime.candidate_request_id == ""
