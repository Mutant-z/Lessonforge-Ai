"""Focused tests for the deterministic PPTagent V2 command resolver."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.intents import resolved_command_to_polish_intent
from app.agent.polish_command import (
    apply_polish_options,
    PolishOperation,
    ResolvedPolishCommandV2,
    parse_page_references,
    resolve_polish_command,
)


DECK_IDS = [f"slide_{index:02d}" for index in range(1, 16)]


def _domains(command: ResolvedPolishCommandV2) -> set[str]:
    return {item.domain for item in command.operations}


def _objectives(command: ResolvedPolishCommandV2) -> dict[str, object]:
    return {item.metric: item for item in command.objectives}


def test_v2_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        PolishOperation.model_validate({
            "domain": "layout", "action": "polish", "invented": True,
        })


def test_compound_font_and_distribution_problem_becomes_two_hard_goals():
    command = resolve_polish_command(
        "字体偏小，布局利用不充分",
        target_slide_ids=["S03"],
        canonical_ids=DECK_IDS,
    )

    assert command.scope.target_slide_ids == ["slide_03"]
    assert command.scope.source == "explicit_selection"
    assert _domains(command) == {"typography", "layout"}
    objectives = _objectives(command)
    assert set(objectives) == {"font_size", "vertical_utilization"}
    assert objectives["font_size"].direction == "increase"
    assert objectives["font_size"].minimum_delta == pytest.approx(0.05)
    assert objectives["vertical_utilization"].minimum_delta == pytest.approx(0.12)
    assert all(item.hard_requirement for item in objectives.values())
    assert command.preservation.semantic_text is True
    assert command.preservation.images_and_assets is True
    assert command.needs_confirmation is False


@pytest.mark.parametrize(
    ("text", "targets", "references"),
    [
        ("调整第2、4、6页", [2, 4, 6], []),
        ("重排第4～7页", [4, 5, 6, 7], []),
        ("重排第4页到第7页", [4, 5, 6, 7], []),
        ("润色第三、五页", [3, 5], []),
        ("第3页参考第2页", [3], [2]),
        ("参考第2页的版式，调整第3页", [3], [2]),
        ("以第十二页为参考，润色第十页", [10], [12]),
    ],
)
def test_page_parser_supports_lists_ranges_chinese_and_references(text, targets, references):
    parsed = parse_page_references(text)
    assert parsed.target_page_numbers == targets
    assert parsed.reference_page_numbers == references


def test_page_numbers_resolve_to_real_canonical_ids_and_reference_is_separate():
    command = resolve_polish_command(
        "请修改第2、4～6页，并参考第3页的版式",
        canonical_ids=DECK_IDS,
    )

    assert command.scope.model_dump() == {
        "target_slide_ids": ["slide_02", "slide_04", "slide_05", "slide_06"],
        "reference_slide_ids": ["slide_03"],
        "source": "explicit_text",
    }
    assert _domains(command) == {"layout"}
    assert command.needs_confirmation is False


def test_explicit_text_scope_wins_over_stale_frontend_scope():
    command = resolve_polish_command(
        "重新排版第4页",
        target_slide_ids=["slide_03"],
        canonical_ids=DECK_IDS,
    )

    assert command.scope.target_slide_ids == ["slide_04"]
    assert "scope.selection_text_conflict:text_wins" in command.ambiguities
    assert command.confidence < 0.80
    assert command.needs_confirmation is True


def test_invalid_explicit_page_never_expands_to_whole_deck():
    command = resolve_polish_command("重新排版第99页", canonical_ids=DECK_IDS)

    assert command.scope.source == "explicit_text"
    assert command.scope.target_slide_ids == []
    assert "scope.invalid_page:99" in command.ambiguities
    assert command.needs_confirmation is True


def test_operation_parameters_preserve_timing_notes_and_style_intent():
    timing = resolve_polish_command("把第2页时长调整为45秒", canonical_ids=DECK_IDS)
    notes = resolve_polish_command("把第2页教师备注改为：强调压强差", canonical_ids=DECK_IDS)
    style = resolve_polish_command("优化第2页配色并突出重点", canonical_ids=DECK_IDS)

    assert timing.operations[0].parameters["duration_seconds"] == 45
    assert notes.operations[0].parameters["notes_text"] == "强调压强差"
    assert style.operations[0].parameters["style"] == {"color": "accent", "bold": True}


def test_current_page_uses_active_id_and_missing_active_id_requires_confirmation():
    resolved = resolve_polish_command(
        "润色本页", active_slide_id="S03", canonical_ids=DECK_IDS,
    )
    missing = resolve_polish_command("润色当前页", canonical_ids=DECK_IDS)

    assert resolved.scope.target_slide_ids == ["slide_03"]
    assert resolved.scope.source == "active_page"
    assert resolved.needs_confirmation is False
    assert missing.scope.source == "active_page"
    assert missing.scope.target_slide_ids == []
    assert "scope.active_slide_missing" in missing.ambiguities
    assert missing.needs_confirmation is True


def test_page_distribution_without_single_page_context_is_ambiguous():
    command = resolve_polish_command(
        "润色一下现在 PPT 的页面分布", canonical_ids=DECK_IDS,
    )

    assert command.scope.source == "all"
    assert "scope.page_distribution_ambiguous" in command.ambiguities
    assert command.needs_confirmation is True
    assert {"vertical_utilization", "whitespace_balance"} <= set(_objectives(command))


def test_negations_and_only_boundary_preserve_copy_and_images():
    command = resolve_polish_command(
        "保留当前配图，只改布局，不改写任何教学内容",
        target_slide_ids=["slide_03"],
        canonical_ids=DECK_IDS,
    )

    assert _domains(command) == {"layout"}
    assert command.operations[0].object_targets == ["content_refs"]
    assert command.preservation.semantic_text is True
    assert command.preservation.images_and_assets is True
    assert command.needs_confirmation is False


def test_negated_image_resize_does_not_hide_positive_text_resize():
    command = resolve_polish_command(
        "不要放大图片，只放大文字",
        target_slide_ids=["slide_03"],
        canonical_ids=DECK_IDS,
    )

    assert _domains(command) == {"typography"}
    assert command.operations[0].object_targets == ["body"]
    assert _objectives(command)["font_size"].direction == "increase"
    assert "image_scale" not in _objectives(command)
    assert command.preservation.images_and_assets is True


def test_action_level_negation_keeps_opposite_image_resize_request():
    command = resolve_polish_command(
        "不要放大图片，只缩小图片",
        target_slide_ids=["slide_03"],
        canonical_ids=DECK_IDS,
    )

    assert _domains(command) == {"image_geometry"}
    assert _objectives(command)["image_scale"].direction == "decrease"
    assert command.preservation.images_and_assets is True
    assert command.needs_confirmation is False


def test_preserving_image_asset_still_allows_explicit_geometry_change():
    command = resolve_polish_command(
        "保留当前配图，只调整图片位置",
        target_slide_ids=["slide_03"],
        canonical_ids=DECK_IDS,
    )

    assert _domains(command) == {"image_geometry"}
    assert command.operations[0].action == "reposition"
    assert command.preservation.images_and_assets is True


def test_image_asset_and_image_geometry_are_distinct_operations():
    replace = resolve_polish_command(
        "替换本页配图", active_slide_id="slide_03", canonical_ids=DECK_IDS,
    )
    geometry = resolve_polish_command(
        "放大本页图片并调整图片位置",
        active_slide_id="slide_03",
        canonical_ids=DECK_IDS,
    )

    assert _domains(replace) == {"image_asset"}
    assert replace.preservation.images_and_assets is False
    assert _domains(geometry) == {"image_geometry"}
    assert geometry.preservation.images_and_assets is True
    assert _objectives(geometry)["image_scale"].direction == "increase"


@pytest.mark.parametrize("instruction", ["优化一下图片布局", "润色本页配图"])
def test_image_specific_polish_does_not_fall_into_whole_page_layout(instruction):
    command = resolve_polish_command(
        instruction,
        active_slide_id="slide_03",
        canonical_ids=DECK_IDS,
    )

    assert _domains(command) == {"image_geometry"}
    assert command.preservation.semantic_text is True
    assert command.preservation.images_and_assets is True


def test_standalone_light_size_request_is_typography_with_measurable_delta():
    command = resolve_polish_command("可以放大一点", canonical_ids=DECK_IDS)

    assert command.scope.source == "all"
    assert _domains(command) == {"typography"}
    assert command.operations[0].strength == "subtle"
    assert _objectives(command)["font_size"].direction == "increase"
    assert _objectives(command)["font_size"].minimum_delta == pytest.approx(0.05)
    assert command.preservation.semantic_text is True


def test_text_plus_layout_unlocks_only_semantic_text():
    command = resolve_polish_command(
        "精简正文并重新排版，保留图片",
        target_slide_ids=["slide_03"],
        canonical_ids=DECK_IDS,
    )

    assert _domains(command) == {"text", "layout"}
    assert command.preservation.semantic_text is False
    assert command.preservation.images_and_assets is True
    assert command.preservation.page_count is True
    assert command.preservation.theme is True


def test_explicit_modality_is_a_hard_domain_boundary():
    command = resolve_polish_command(
        "改写文字并重新排版",
        target_slide_ids=["slide_03"],
        modality="layout",
        canonical_ids=DECK_IDS,
    )

    assert _domains(command) == {"layout"}
    assert command.preservation.semantic_text is True
    assert "modality.disallowed_request:text" in command.ambiguities
    assert command.needs_confirmation is True


@pytest.mark.parametrize(
    ("modality", "expected_domain"),
    [("layout", "layout"), ("text", "text"), ("image", "image_geometry")],
)
def test_generic_polish_uses_explicit_modality_without_false_conflict(modality, expected_domain):
    command = resolve_polish_command(
        "润色本页",
        active_slide_id="slide_03",
        modality=modality,
        canonical_ids=DECK_IDS,
    )

    assert expected_domain in _domains(command)
    assert not any(item.startswith("modality.") for item in command.ambiguities)
    assert command.needs_confirmation is False


def test_bare_alternative_inherits_previous_scope_operations_and_objectives():
    previous = resolve_polish_command(
        "第3页字体偏小，布局利用不充分", canonical_ids=DECK_IDS,
    )
    alternative = resolve_polish_command(
        "换一种试试", canonical_ids=DECK_IDS, previous_command=previous,
    )

    assert alternative.turn_relation == "alternative"
    assert alternative.scope.source == "inherited"
    assert alternative.scope.target_slide_ids == ["slide_03"]
    assert _domains(alternative) == _domains(previous)
    assert set(_objectives(alternative)) == set(_objectives(previous))
    assert all(item.source == "inherited" for item in alternative.objectives)
    assert alternative.needs_confirmation is False


def test_concrete_alternative_keeps_other_goals_from_previous_command():
    previous = resolve_polish_command(
        "第3页字体偏小，布局利用不充分", canonical_ids=DECK_IDS,
    )
    alternative = resolve_polish_command(
        "换一种版式", canonical_ids=DECK_IDS, previous_command=previous,
    )

    assert alternative.scope.target_slide_ids == ["slide_03"]
    assert _domains(alternative) == {"typography", "layout"}
    assert set(_objectives(alternative)) == {"font_size", "vertical_utilization"}


def test_elliptical_refinement_inherits_scope_but_has_new_measurable_goal():
    previous = resolve_polish_command(
        "放大第3页的文字", canonical_ids=DECK_IDS,
    )
    refined = resolve_polish_command(
        "再大一点", canonical_ids=DECK_IDS, previous_command=previous,
    )

    assert refined.turn_relation == "refine_previous"
    assert refined.scope.source == "inherited"
    assert refined.scope.target_slide_ids == ["slide_03"]
    assert _domains(refined) == {"typography"}
    assert _objectives(refined)["font_size"].direction == "increase"
    assert _objectives(refined)["font_size"].minimum_delta == pytest.approx(0.05)


def test_followup_without_previous_command_does_not_default_to_all_pages():
    command = resolve_polish_command("再松一点", canonical_ids=DECK_IDS)

    assert command.scope.source == "inherited"
    assert command.scope.target_slide_ids == []
    assert "scope.previous_command_missing" in command.ambiguities
    assert command.needs_confirmation is True


def test_stale_inherited_scope_is_rejected_instead_of_expanding_scope():
    previous = resolve_polish_command(
        "放大第3页文字", canonical_ids=DECK_IDS,
    )
    reduced_deck = [item for item in DECK_IDS if item != "slide_03"]
    command = resolve_polish_command(
        "再大一点", canonical_ids=reduced_deck, previous_command=previous,
    )

    assert command.scope.source == "inherited"
    assert command.scope.target_slide_ids == []
    assert "scope.invalid_inherited_target:slide_03" in command.ambiguities
    assert command.needs_confirmation is True


def test_legacy_scope_prefixes_are_consumed_without_polluting_raw_user_text():
    command = resolve_polish_command(
        "[活动页面:slide_03] [针对第3页] [范围:布局] 字体偏小，布局利用不充分",
        canonical_ids=DECK_IDS,
    )

    assert command.raw_text == "字体偏小，布局利用不充分"
    assert command.scope.target_slide_ids == ["slide_03"]
    assert command.scope.source == "explicit_text"
    assert _domains(command) == {"typography", "layout"}


def test_legacy_projection_is_explicitly_lossy_for_multiple_objectives():
    command = resolve_polish_command(
        "字体偏小，布局利用不充分",
        target_slide_ids=["slide_03"],
        canonical_ids=DECK_IDS,
    )
    legacy = resolved_command_to_polish_intent(command)

    assert legacy.action == "layout_only"
    assert legacy.target_dimension == "overall"
    assert legacy.preserve_text is True
    assert legacy.scope_slide_ids == ["slide_03"]


def test_polish_options_override_strength_and_permissions_without_expanding_scope():
    command = resolve_polish_command(
        "润色第3页文字", canonical_ids=DECK_IDS, modality="text",
    )
    resolved = apply_polish_options(
        command,
        {
            "strength": "subtle", "content_policy": "edit",
            "image_policy": "preserve", "page_count_policy": "preserve",
        },
        canonical_ids=DECK_IDS,
    )

    assert resolved.scope.target_slide_ids == ["slide_03"]
    assert all(item.strength == "subtle" for item in resolved.operations)
    assert resolved.preservation.semantic_text is False
    assert resolved.preservation.images_and_assets is True
    assert resolved.preservation.page_count is True
