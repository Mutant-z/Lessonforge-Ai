"""Canonical slide render-mode and content-preservation helpers.

Slides keep semantic teaching content (title/body/blocks) separately from the
editable geometry layer.  A media-only overlay must never make that semantic
content disappear.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal


SlideRenderMode = Literal["semantic", "hybrid", "absolute"]
SEMANTIC_FIELDS = ("title", "purpose", "body", "blocks", "speaker_notes", "duration_seconds")


def infer_render_mode(slide: dict[str, Any]) -> SlideRenderMode:
    declared = str(slide.get("render_mode") or "")
    if declared in {"semantic", "hybrid", "absolute"}:
        return declared  # type: ignore[return-value]
    elements = list(slide.get("elements") or [])
    if not elements:
        return "semantic"
    # Historical image updates stored only a media element.  Treat those
    # artifacts as an overlay on the still-present semantic content.
    if all(item.get("kind") in {"image", "chart"} for item in elements):
        return "hybrid"
    return "absolute"


def semantic_snapshot(slide: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(slide.get("title") or ""),
        "purpose": str(slide.get("purpose") or ""),
        "body": list(slide.get("body") or []),
        "blocks": list(slide.get("blocks") or []),
        "speaker_notes": str(slide.get("speaker_notes") or ""),
        "duration_seconds": int(slide.get("duration_seconds") or 0),
    }


def runtime_baseline_slides(runtime: Any) -> list[dict[str, Any]]:
    """Return the immutable semantic baseline selected for this run.

    Restore runs may fill fields from an earlier valid slide revision without
    mutating the current database Artifact.  All agents and gates must consume
    that same in-memory baseline rather than independently rereading V34.
    """
    prepared = getattr(runtime, "baseline_slides", None)
    if prepared is not None:
        return [dict(item) for item in prepared]
    source = getattr(runtime, "source_artifact", None) or getattr(getattr(runtime, "context", None), "source_artifact", None)
    return [dict(item) for item in ((getattr(source, "content_json", {}) or {}).get("slides") or [])]


def semantic_content_hash(slide: dict[str, Any]) -> str:
    payload = json.dumps(semantic_snapshot(slide), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _block_texts(block: dict[str, Any], prefix: str) -> list[tuple[str, str]]:
    kind = block.get("kind")
    refs: list[tuple[str, str]] = []
    if kind == "lead":
        refs.extend([(f"{prefix}.text", str(block.get("text") or "")), (f"{prefix}.sub", str(block.get("sub") or ""))])
    elif kind == "bullets":
        refs.extend((f"{prefix}.items.{index}.text", str(item.get("text") or "")) for index, item in enumerate(block.get("items") or []))
    elif kind == "steps":
        for index, item in enumerate(block.get("steps") or []):
            refs.extend([
                (f"{prefix}.steps.{index}.title", str(item.get("title") or "")),
                (f"{prefix}.steps.{index}.detail", str(item.get("detail") or "")),
            ])
    elif kind == "compare":
        for side in ("left", "right"):
            column = block.get(side) or {}
            refs.append((f"{prefix}.{side}.heading", str(column.get("heading") or "")))
            refs.extend((f"{prefix}.{side}.items.{index}", str(value)) for index, value in enumerate(column.get("items") or []))
    elif kind == "quote":
        refs.extend([(f"{prefix}.text", str(block.get("text") or "")), (f"{prefix}.citation", str(block.get("citation") or ""))])
    elif kind == "visual":
        refs.append((f"{prefix}.caption", str(block.get("caption") or "")))
    elif kind == "note":
        refs.append((f"{prefix}.text", str(block.get("text") or "")))
    return [(ref, text.strip()) for ref, text in refs if text and text.strip()]


def semantic_text_refs(slide: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    title = str(slide.get("title") or "").strip()
    if title:
        refs.append(("title", title))
    refs.extend(
        (f"body.{index}", str(value).strip())
        for index, value in enumerate(slide.get("body") or []) if str(value).strip()
    )
    blocks = list(slide.get("blocks") or [])
    if blocks:
        for index, block in enumerate(blocks):
            refs.extend(_block_texts(block, f"blocks.{index}"))
    # Purpose is visible semantic copy only on cover pages.  On content pages
    # it is planning metadata and is protected by the content hash instead.
    purpose = str(slide.get("purpose") or "").strip()
    if purpose and str(slide.get("page_type") or "") == "cover":
        refs.append(("purpose", purpose))
    return refs


def semantic_body_texts(slide: dict[str, Any]) -> list[str]:
    """Canonical visible body projection used by both layout and PPTX render.

    The legacy ``_blocks_flat_text`` projection intentionally omitted step
    details and quote citations.  That is acceptable for a terse summary, but
    not for rendering or content-visibility QA.
    """
    texts: list[str] = []
    seen: set[str] = set()
    for ref, text in semantic_text_refs(slide):
        if ref in {"title", "purpose"}:
            continue
        normalized = _normalized_text(text)
        if normalized and normalized not in seen:
            seen.add(normalized)
            texts.append(text)
    return texts


def resolve_content_ref(slide: dict[str, Any], content_ref: str) -> str | None:
    """Resolve a model-supplied reference to canonical source text.

    ``body`` and ``blocks`` are aggregate display aliases.  Fine-grained refs
    such as ``blocks.0.steps.1.detail`` follow normal dotted list/dict paths.
    Unknown refs return ``None`` so a content-locked layout can be rejected.
    """
    ref = str(content_ref or "").strip()
    if not ref:
        return None
    if ref in {"body", "blocks"}:
        return "\n".join(semantic_body_texts(slide))
    if ref == "title":
        return str(slide.get("title") or "")
    if ref == "purpose":
        return str(slide.get("purpose") or "")
    if ref == "speaker_notes":
        return str(slide.get("speaker_notes") or "")

    node: Any = slide
    for part in ref.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return str(node)
    # Allow a parent block/list ref while preserving the same canonical order.
    if ref.startswith("blocks"):
        matching = [text for item_ref, text in semantic_text_refs(slide) if item_ref == ref or item_ref.startswith(ref + ".")]
        return "\n".join(matching) if matching else None
    if ref.startswith("body") and isinstance(node, list):
        return "\n".join(str(item) for item in node)
    return None


def bind_content_refs(
    slide: dict[str, Any], elements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Inject canonical text into layout elements and report invalid refs."""
    bound: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for element in elements:
        item = dict(element)
        ref = str(item.get("content_ref") or "").strip()
        if item.get("kind") in {"textbox", "note"} and ref:
            value = resolve_content_ref(slide, ref)
            if value is None:
                unresolved.append(ref)
            else:
                # Never trust the model to copy teaching text verbatim.
                item["text"] = value
        bound.append(item)
    return bound, list(dict.fromkeys(unresolved))


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _ref_covers(element_ref: str, expected_ref: str) -> bool:
    if element_ref == expected_ref:
        return True
    if element_ref == "body" and (expected_ref.startswith("body.") or expected_ref.startswith("blocks.")):
        return True
    if element_ref == "blocks" and expected_ref.startswith("blocks."):
        return True
    return expected_ref.startswith(element_ref + ".")


def render_coverage(slide: dict[str, Any], *, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    source = baseline or slide
    expected = semantic_text_refs(source)
    mode = infer_render_mode(slide)
    if mode in {"semantic", "hybrid"}:
        return {"mode": mode, "expected_refs": [ref for ref, _ in expected], "rendered_refs": [ref for ref, _ in expected], "missing_refs": []}

    text_elements = [item for item in (slide.get("elements") or []) if item.get("kind") in {"textbox", "note"}]
    rendered_text = _normalized_text("\n".join(str(item.get("text") or "") for item in text_elements))
    missing: list[str] = []
    for ref, text in expected:
        expected_text = _normalized_text(text)
        matched_ref = any(
            _ref_covers(str(item.get("content_ref") or ""), ref)
            and expected_text
            and expected_text in _normalized_text(item.get("text"))
            for item in text_elements if item.get("content_ref")
        )
        # Legacy absolute Artifacts may predate content_ref.  Exact visible
        # text remains a safe compatibility proof, but an empty/wrong textbox
        # can no longer pass merely by carrying the expected ref.
        if not matched_ref and (not expected_text or expected_text not in rendered_text):
            missing.append(ref)
    rendered = [ref for ref, _ in expected if ref not in missing]
    return {"mode": mode, "expected_refs": [ref for ref, _ in expected], "rendered_refs": rendered, "missing_refs": missing}


def semantic_content_changed(source: dict[str, Any], current: dict[str, Any]) -> bool:
    return semantic_snapshot(source) != semantic_snapshot(current)
