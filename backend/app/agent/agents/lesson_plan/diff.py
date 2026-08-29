"""Canonical, ID-aware diff for lesson-plan V2 candidates."""

from __future__ import annotations

import json
import re
from typing import Any


def _visible_value(value: Any) -> str:
    """Return user-visible text from block payloads, excluding structural keys."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_visible_value(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            _visible_value(child)
            for key, child in value.items()
            if key not in {"kind", "id", "stage_id", "objective_id", "knowledge_point_ids"}
        )
    return "" if value is None else str(value)


def section_visible_text(section: dict[str, Any]) -> str:
    text = "\n".join([
        str(section.get("summary") or ""),
        _visible_value(section.get("blocks") or []),
    ])
    return re.sub(r"\s+", "", text)


def visible_content_chars(content: dict[str, Any]) -> int:
    total = 0

    def visit(items: list[dict[str, Any]]) -> None:
        nonlocal total
        for item in items:
            total += len(section_visible_text(item))
            visit(list(item.get("children") or []))

    visit(list((content.get("outline") or {}).get("sections") or []))
    return total


def empty_leaf_section_ids(content: dict[str, Any]) -> list[str]:
    result: list[str] = []

    def visit(items: list[dict[str, Any]]) -> None:
        for item in items:
            children = list(item.get("children") or [])
            if not children and not section_visible_text(item):
                result.append(str(item.get("id") or ""))
            visit(children)

    visit(list((content.get("outline") or {}).get("sections") or []))
    return sorted(item for item in result if item)


def _outline_records(sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}

    def visit(items: list[dict[str, Any]], parent_id: str, depth: int) -> None:
        for index, item in enumerate(items):
            section_id = str(item.get("id") or "")
            if not section_id:
                continue
            records[section_id] = {
                "id": section_id,
                "parent_id": parent_id,
                "index": index,
                "depth": depth,
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "coverage_refs": list(item.get("coverage_refs") or []),
                "blocks": list(item.get("blocks") or []),
            }
            visit(list(item.get("children") or []), section_id, depth + 1)

    visit(list(sections or []), "", 1)
    return records


def diff_lesson_plans(
    source: dict[str, Any],
    candidate: dict[str, Any],
    *,
    mutable_section_ids: set[str] | None = None,
) -> dict[str, Any]:
    source_records = _outline_records((source.get("outline") or {}).get("sections") or [])
    candidate_records = _outline_records((candidate.get("outline") or {}).get("sections") or [])
    source_ids = set(source_records)
    candidate_ids = set(candidate_records)
    added = sorted(candidate_ids - source_ids)
    removed = sorted(source_ids - candidate_ids)
    shared = source_ids & candidate_ids
    moved = sorted(
        section_id for section_id in shared
        if (source_records[section_id]["parent_id"], source_records[section_id]["index"])
        != (candidate_records[section_id]["parent_id"], candidate_records[section_id]["index"])
    )
    renamed = sorted(
        section_id for section_id in shared
        if source_records[section_id]["title"] != candidate_records[section_id]["title"]
    )
    coverage_changed = sorted(
        section_id for section_id in shared
        if source_records[section_id]["coverage_refs"] != candidate_records[section_id]["coverage_refs"]
    )
    section_content_changed = sorted(set(
        [
            section_id for section_id in shared
            if source_records[section_id]["summary"] != candidate_records[section_id]["summary"]
            or source_records[section_id]["blocks"] != candidate_records[section_id]["blocks"]
        ]
        + [
            section_id for section_id in added
            if section_visible_text(candidate_records[section_id])
        ]
    ))
    emptied_sections = sorted(
        section_id for section_id in shared
        if section_visible_text(source_records[section_id])
        and not section_visible_text(candidate_records[section_id])
    )
    preserved_sections = sorted(
        section_id for section_id in shared
        if source_records[section_id]["summary"] == candidate_records[section_id]["summary"]
        and source_records[section_id]["blocks"] == candidate_records[section_id]["blocks"]
    )
    mutable = set(mutable_section_ids or set())
    unexpected_content_changes = sorted(
        section_id for section_id in section_content_changed
        if mutable_section_ids is not None and section_id not in mutable
    )
    block_count_before = sum(len(record["blocks"]) for record in source_records.values())
    block_count_after = sum(len(record["blocks"]) for record in candidate_records.values())
    visible_before = visible_content_chars(source)
    visible_after = visible_content_chars(candidate)
    content_loss_ratio = (
        max(0.0, (visible_before - visible_after) / visible_before)
        if visible_before else 0.0
    )

    source_core = source.get("pedagogical_core") or {}
    candidate_core = candidate.get("pedagogical_core") or {}
    core_fields = sorted(set(source_core) | set(candidate_core))
    core_changed_fields = [key for key in core_fields if source_core.get(key) != candidate_core.get(key)]
    source_info = source.get("course_info") or {}
    candidate_info = candidate.get("course_info") or {}
    course_info_changed_fields = sorted(
        key for key in set(source_info) | set(candidate_info)
        if source_info.get(key) != candidate_info.get(key)
    )

    def timing_snapshot(content: dict[str, Any]) -> tuple[Any, list[tuple[str, Any]]]:
        info = content.get("course_info") or {}
        stages = (content.get("pedagogical_core") or {}).get("stages") or []
        return info.get("duration_minutes"), [
            (str(item.get("id") or ""), item.get("duration_minutes")) for item in stages
        ]

    timing_changed = timing_snapshot(source) != timing_snapshot(candidate)
    outline_structure_changed = bool(added or removed or moved or renamed or coverage_changed)
    changed_section_ids = sorted(set(added + removed + moved + renamed + coverage_changed + section_content_changed))
    changed_paths = [f"$.outline.sections[{section_id}]" for section_id in changed_section_ids]
    changed_paths.extend(f"$.pedagogical_core.{key}" for key in core_changed_fields)
    changed_paths.extend(f"$.course_info.{key}" for key in course_info_changed_fields)
    changed = bool(changed_paths)
    return {
        "changed": changed,
        "outline_structure_changed": outline_structure_changed,
        "section_content_changed": bool(section_content_changed),
        "core_content_changed": bool(core_changed_fields),
        "timing_changed": timing_changed,
        "added_sections": added,
        "removed_sections": removed,
        "moved_sections": moved,
        "renamed_sections": renamed,
        "coverage_changed_sections": coverage_changed,
        "content_changed_sections": section_content_changed,
        "emptied_sections": emptied_sections,
        "block_count_before": block_count_before,
        "block_count_after": block_count_after,
        "visible_content_chars_before": visible_before,
        "visible_content_chars_after": visible_after,
        "content_loss_ratio": round(content_loss_ratio, 6),
        "unexpected_content_changes": unexpected_content_changes,
        "preserved_section_ids": preserved_sections,
        "changed_sections": changed_section_ids,
        "core_changed_fields": core_changed_fields,
        "course_info_changed_fields": course_info_changed_fields,
        "changed_paths": changed_paths,
    }


def distinct_top_level_fact_sections(content: dict[str, Any], facts: list[str]) -> dict[str, str]:
    """Return fact -> top-level section id when every fact has a distinct owner."""
    owners: dict[str, str] = {}
    for section in (content.get("outline") or {}).get("sections") or []:
        refs = set(section.get("coverage_refs") or [])
        for fact in facts:
            if fact in refs and fact not in owners:
                owners[fact] = str(section.get("id") or "")
    if len(owners) != len(facts) or len(set(owners.values())) != len(facts):
        return {}
    return owners
