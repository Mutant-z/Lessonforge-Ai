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


def canonical_slide_id(raw_id: Any, canonical_ids: list[str] | set[str]) -> str | None:
    """Resolve model aliases such as S02 to the unique ID owned by the deck."""
    raw = str(raw_id or "").strip()
    ids = [str(value) for value in canonical_ids if str(value)]
    if raw in ids:
        return raw
    match = re.search(r"(\d+)$", raw)
    if not match:
        return None
    number = int(match.group(1))
    matches = []
    for candidate in ids:
        suffix = re.search(r"(\d+)$", candidate)
        if suffix and int(suffix.group(1)) == number:
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


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


def objective_result_passed(result: dict[str, Any]) -> bool:
    """Read the canonical V2 objective result with legacy aliases.

    The compiler emits ``passed``.  ``met`` and ``achieved`` remain accepted
    for historical artifacts, but must never cause a successful V2 objective
    to be rejected at the editor or final publish gate.
    """
    return bool(result.get("passed", result.get("met", result.get("achieved", False))))


def semantic_geometry_hash(slide: dict[str, Any]) -> str:
    """把 elements 的 kind/content_ref/x/y/w/h 序列化哈希，忽略文本样式细节。

    用于收敛性修复的单调性判定：preserve 模式润色后页面布局没有实际几何变化时，
    视为空转并触发 layout.monotony 门禁。
    """
    elements = sorted(
        (
            (str(e.get("kind") or ""), str(e.get("content_ref") or ""),
             round(float(e.get("x") or 0), 3), round(float(e.get("y") or 0), 3),
             round(float(e.get("w") or 0), 3), round(float(e.get("h") or 0), 3))
            for e in slide.get("elements") or []
        ),
        key=lambda t: t,
    )
    return hashlib.sha256(json.dumps(elements, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def semantic_visual_hash(slide: dict[str, Any]) -> str:
    """Hash visible layout and styling while ignoring element ids and copy.

    Layout-only requests may legitimately change typography, color or shape
    treatment without moving boxes.  The old geometry-only publish gate called
    those successful edits a no-op.  Text is intentionally excluded because
    preserve/restore runs validate semantic copy independently.
    """
    elements = []
    for element in slide.get("elements") or []:
        style = element.get("style") or {}
        elements.append({
            "kind": str(element.get("kind") or ""),
            "role": str(element.get("role") or ""),
            "content_ref": str(element.get("content_ref") or ""),
            "shape_type": str(element.get("shape_type") or ""),
            "x": round(float(element.get("x") or 0), 3),
            "y": round(float(element.get("y") or 0), 3),
            "w": round(float(element.get("w") or 0), 3),
            "h": round(float(element.get("h") or 0), 3),
            "style": {
                key: style.get(key)
                for key in ("font", "size", "color", "bold", "align", "valign")
                if key in style
            },
            "fill": element.get("fill"),
            "line": element.get("line"),
            "visual_slot": str(element.get("visual_slot") or ""),
        })
    elements.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    payload = json.dumps(elements, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
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


def semantic_ref_details(slide: dict[str, Any], refs: list[str]) -> list[dict[str, str]]:
    """Return human-readable evidence for missing semantic references."""
    wanted = set(refs)
    return [
        {"ref": ref, "text": text[:120]}
        for ref, text in semantic_text_refs(slide)
        if ref in wanted
    ]


def semantic_body_texts(slide: dict[str, Any]) -> list[str]:
    """Canonical visible body projection used by both layout and PPTX render.

    The legacy ``_blocks_flat_text`` projection intentionally omitted step
    details and quote citations.  That is acceptable for a terse summary, but
    not for rendering or content-visibility QA.
    """
    texts: list[str] = []
    # Structured blocks commonly mirror the top-level title/body fields.  A
    # ``lead`` block in particular often repeats the slide title; treating it
    # as body makes an absolute ``content_ref=body`` textbox render the title a
    # second time.  Seed the de-duplication set with separately rendered
    # semantic fields before projecting body + blocks.
    seen: set[str] = {
        normalized
        for normalized in (
            _normalized_text(slide.get("title")),
            _normalized_text(slide.get("purpose")),
        )
        if normalized
    }
    for ref, text in semantic_text_refs(slide):
        if ref in {"title", "purpose"}:
            continue
        normalized = _normalized_text(text)
        if normalized and normalized not in seen:
            seen.add(normalized)
            texts.append(text)
    return texts


def semantic_body_refs(slide: dict[str, Any]) -> list[tuple[str, str]]:
    """Canonical visible body column as ``(content_ref, text)`` pairs.

    Mirrors ``semantic_body_texts`` de-duplication while preserving the exact
    ``content_ref`` of each surviving text, so a layout can render the left
    column as separate, vertically-spaced textboxes instead of one cramped
    ``\n``-joined paragraph.  This is what lets "文字间隔/太单调" style requests
    produce a visible change.
    """
    seen: set[str] = {
        normalized
        for normalized in (
            _normalized_text(slide.get("title")),
            _normalized_text(slide.get("purpose")),
        )
        if normalized
    }
    items: list[tuple[str, str]] = []
    for ref, text in semantic_text_refs(slide):
        if ref in {"title", "purpose"}:
            continue
        normalized = _normalized_text(text)
        if normalized and normalized not in seen:
            seen.add(normalized)
            items.append((ref, text))
    return items


# 单条和条目数用于生成提示；页面总承载量由真实渲染判断。
DENSITY_ITEM_CHARS = 25
DENSITY_BODY_ITEMS = 6
# 常见装饰前缀（emoji/项目符号），会虚增密度字符数。
_PREFIX_STRIP_CHARS = "•-*●○◆◇🔹🔸💡⚓🎈✨✅📌✏️💬⭐🔥🎯💪📚🧠👀⚠️❓❗❗️💡"


def _strip_text_prefix(text: str) -> str:
    result = str(text or "").lstrip(" \t")
    while result:
        char = result[0]
        if char in _PREFIX_STRIP_CHARS:
            result = result[1:].lstrip(" \t:")
        else:
            break
    return result


def _clip_text_unit(text: str, limit: int = DENSITY_ITEM_CHARS) -> str:
    """柔和清洗装饰符号，保留模型生成的完整教学表达，避免暴力截断破坏关键语义。"""
    text = _strip_text_prefix(text)
    # 仅作首尾空白微调，不再强制暴力截断并追加省略号
    return text.strip()


def sanitize_slide_density(slide: dict[str, Any]) -> bool:
    """柔性收敛页面密度，清洗前缀符号并保持教学内容语义完整，不再粗暴 pop 移除块。

    返回 True 表示发生了清洗/调整。
    """
    changed = False
    body = slide.get("body")
    if isinstance(body, list):
        clipped = [_clip_text_unit(item) for item in body]
        if clipped != body:
            slide["body"] = clipped
            changed = True
    blocks = slide.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get("kind")
            if kind == "lead":
                for key in ("text", "sub"):
                    if block.get(key):
                        new_val = _clip_text_unit(block[key])
                        if new_val != block[key]:
                            block[key] = new_val
                            changed = True
            elif kind == "bullets":
                for item in block.get("items") or []:
                    if isinstance(item, dict) and item.get("text"):
                        new_val = _clip_text_unit(item["text"])
                        if new_val != item["text"]:
                            item["text"] = new_val
                            changed = True
            elif kind == "steps":
                for step in block.get("steps") or []:
                    for key in ("title", "detail"):
                        if isinstance(step, dict) and step.get(key):
                            new_val = _clip_text_unit(step[key])
                            if new_val != step[key]:
                                step[key] = new_val
                                changed = True
            elif kind == "compare":
                for column in (block.get("left"), block.get("right")):
                    if not isinstance(column, dict):
                        continue
                    if column.get("heading"):
                        new_val = _clip_text_unit(column["heading"])
                        if new_val != column["heading"]:
                            column["heading"] = new_val
                            changed = True
                    items = column.get("items") or []
                    clipped_items = [_clip_text_unit(item) for item in items]
                    if clipped_items != items:
                        column["items"] = clipped_items
                        changed = True
            elif kind == "quote":
                for key in ("text", "citation"):
                    if block.get(key):
                        new_val = _clip_text_unit(block[key])
                        if new_val != block[key]:
                            block[key] = new_val
                            changed = True
            elif kind == "note":
                if block.get("text"):
                    new_val = _clip_text_unit(block["text"])
                    if new_val != block["text"]:
                        block["text"] = new_val
                        changed = True
            elif kind == "visual":
                if block.get("caption"):
                    new_val = _clip_text_unit(block["caption"])
                    if new_val != block["caption"]:
                        block["caption"] = new_val
                        changed = True
        slide["blocks"] = [b for b in blocks if isinstance(b, dict) and b.get("kind")]
    return changed


def _density_units(blocks: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Return (text, block_index) pairs per visible text unit for density accounting."""
    units: list[tuple[str, int]] = []
    for block_index, block in enumerate(blocks):
        kind = block.get("kind")
        contributed: list[str] = []
        if kind == "lead":
            contributed = [str(block.get("text") or ""), str(block.get("sub") or "")]
        elif kind == "bullets":
            contributed = [str(item.get("text") or "") for item in (block.get("items") or [])]
        elif kind == "steps":
            for step in block.get("steps") or []:
                contributed.append(str(step.get("title") or ""))
                detail = step.get("detail")
                if detail:
                    contributed.append(str(detail))
        elif kind == "compare":
            for column in (block.get("left"), block.get("right")):
                if not column:
                    continue
                if column.get("heading"):
                    contributed.append(str(column["heading"]))
                contributed.extend(str(value) for value in (column.get("items") or []))
        elif kind == "quote":
            contributed = [str(block.get("text") or ""), str(block.get("citation") or "")]
        elif kind == "visual":
            if block.get("caption"):
                contributed = [str(block["caption"])]
        elif kind == "note":
            contributed = [str(block.get("text") or "")]
        for unit in contributed:
            if unit:
                units.append((unit, block_index))
    return units


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
    # body 聚合引用，或任一 body.N 单项文本框，都视为覆盖正文/内容块引用。
    # 文本是否真正覆盖由 render_coverage 的 expected_text 匹配兜底，因此
    # 布局可以把正文拆成多个独立文本框而不误报内容缺失。
    if element_ref.startswith("body") and (expected_ref.startswith("body.") or expected_ref.startswith("blocks.")):
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
