"""页面布局 Agent：为每页动态计算元素位置与几何（坐标英寸，安全边距内）。

Mock 路径：按标准版式策略（标题 + 正文流 / 左文右图）确定性计算；
LLM 路径：可基于内容与设计系统选择任意版式策略并输出元素几何。
"""
import math
from copy import deepcopy
from typing import Any

from app.agent.agents.base import Agent
from app.agent.registry import ToolContext
from app.agent.schemas import AgentDecision, ToolCall
from app.agent.slide_rendering import runtime_baseline_slides, semantic_body_refs
from app.agent.layouts.engine import LayoutCompileError, PRESET_KEYS, compile_layout
from app.renderers.presentation_builder import SLIDE_HEIGHT, SLIDE_WIDTH

MARGIN_X = 0.65
MARGIN_Y = 1.7
BODY_FONT = 18
BODY_ITEM_GAP = 0.3
MAX_BODY_ITEMS = 6
# 正文列必须纵向铺满内容区，禁止把所有文字挤在一角。
MIN_BODY_VERTICAL_USAGE = 0.45
SAFE_CONTENT_BOTTOM = SLIDE_HEIGHT - 0.7  # 6.8


def _is_body_content_ref(ref: Any) -> bool:
    ref = str(ref or "")
    return ref == "body" or ref.startswith("body.") or ref.startswith("blocks.")


def canonicalize_spatial_layout(
    template_id: str, slide: dict[str, Any], layout: dict[str, Any],
) -> dict[str, Any]:
    """确定性重排被“挤成一团”的正文列。

    LLM 输出的绝对布局只要 schema 合法就会被信任，但一个把全部文字堆在
    左上角、其余空白一片的布局能通过内容覆盖检查。这里在发布前把“既没有
    纵向铺满、也没有横向展开”的正文强制重排为逐条独立文本框 + 均匀纵向
    分布。多列/横向卡片等真正利用横向空间的版式（span_w 达标）原样保留。
    """
    page_type = str(slide.get("page_type") or "concept")
    if page_type == "cover":
        return layout
    elements = list(layout.get("elements") or [])
    body_indexes = [
        index for index, element in enumerate(elements)
        if element.get("kind") in {"textbox", "note"} and _is_body_content_ref(element.get("content_ref"))
    ]
    if not body_indexes:
        return layout
    body_refs = semantic_body_refs(slide)
    if not body_refs:
        return layout
    body_elements = [elements[index] for index in body_indexes]
    min_y = min(float(item.get("y") or 0) for item in body_elements)
    max_bottom = max(float(item.get("y") or 0) + float(item.get("h") or 0) for item in body_elements)
    min_x = min(float(item.get("x") or 0) for item in body_elements)
    max_right = max(float(item.get("x") or 0) + float(item.get("w") or 0) for item in body_elements)
    available_h = SAFE_CONTENT_BOTTOM - MARGIN_Y
    content_x = _content_start_x(template_id, page_type)
    visual_region = layout.get("visual_region") or {}
    visual_x = float(visual_region.get("x") or 0) if visual_region else 0.0
    body_w = max(3.2, visual_x - content_x - 0.4) if visual_x > content_x + 1 else SLIDE_WIDTH - content_x - 0.78
    vertical_underused = max_bottom - min_y < available_h * MIN_BODY_VERTICAL_USAGE
    horizontal_clustered = max_right - min_x < body_w * 0.6
    if not (vertical_underused and horizontal_clustered):
        return layout
    items: list[tuple[str, str, float]] = []
    for ref, text in body_refs:
        item_h = max(0.5, _estimate_height([text], body_w, BODY_FONT))
        items.append((ref, text, item_h))
    total_h = sum(item_h for _ref, _text, item_h in items) + BODY_ITEM_GAP * max(0, len(items) - 1)
    gap = BODY_ITEM_GAP
    target_h = available_h * MIN_BODY_VERTICAL_USAGE
    if len(items) > 1 and total_h < target_h:
        gap = BODY_ITEM_GAP + (target_h - total_h) / (len(items) - 1)

    kept = [element for index, element in enumerate(elements) if index not in body_indexes]
    title_index = next((index for index, element in enumerate(kept) if element.get("content_ref") == "title"), None)
    if title_index is not None:
        kept[title_index] = {
            **kept[title_index],
            "x": content_x, "y": 0.55, "w": SLIDE_WIDTH - content_x - 0.78, "h": 0.8,
        }
    cursor_y = MARGIN_Y
    for ref, text, item_h in items:
        kept.append({"kind": "textbox", "role": "body", "text": text, "content_ref": ref,
                     "x": round(content_x, 3), "y": round(cursor_y, 3),
                     "w": round(body_w, 3), "h": round(item_h, 3),
                     "style": {"size": BODY_FONT, "color": "text"}})
        cursor_y += item_h + gap
    return {**layout, "elements": kept}


def clamp_template_rail(template_id: str, page_type: str, elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把越出模板安全导轨的文本元素钳回内容区（确定性兜底，原地修改）。

    LLM 绝对布局可能把正文放进模板左栏装饰区（visual.overlaps_template）。
    相比整页退回确定性版式（丢失设计意图），优先平移回安全区：
    x 钳到 content_start_x，w 收窄避免越出右缘。
    """
    safe_x = _content_start_x(template_id, page_type)
    max_w = SLIDE_WIDTH - safe_x - 0.35
    for element in elements:
        if element.get("kind") not in {"textbox", "note"} or not element.get("content_ref"):
            continue
        try:
            x = float(element.get("x") or 0)
            w = float(element.get("w") or 0)
        except (TypeError, ValueError):
            continue
        if x < safe_x - 0.01:
            element["x"] = round(safe_x, 3)
        if w > max_w:
            element["w"] = round(max(1.0, max_w), 3)
    return elements


def _content_start_x(template_id: str, page_type: str = "concept") -> float:
    """模板安全内容区左边界：统一由 TEMPLATE_DECOR 装饰几何推导。

    布局引擎、zones、QA（visual.overlaps_template）共用同一推导，
    保证"摆放"与"检查"一致；不再维护每模板硬编码特例。
    """
    from app.renderers.presentation_builder import template_content_start_x

    return template_content_start_x(template_id, page_type)


def normalize_visual_region(
    region: dict[str, Any] | None,
    template_id: str = "",
    page_type: str = "concept",
) -> dict[str, float]:
    """Clamp an image slot away from the title/text rails and slide edges.

    LLM visual plans are useful for composition, but their coordinates are not
    trusted layout primitives.  In particular, a perfectly valid-looking
    ``y=1.2`` placement overlaps the bottom of the standard title box
    (``y=.55..1.35``).  Normalize once at the visual-plan boundary so layout,
    editor and QA all consume the same safe slot, including repair rounds.
    """
    raw = region if isinstance(region, dict) else {}
    canvas_right = SLIDE_WIDTH - 0.65
    canvas_bottom = SLIDE_HEIGHT - 0.7
    try:
        x = float(raw.get("x", raw.get("left", 7.4)))
        y = float(raw.get("y", raw.get("top", 1.7)))
        w = float(raw.get("w", raw.get("width", 5.2)))
        h = float(raw.get("h", raw.get("height", 4.2)))
    except (TypeError, ValueError):
        x, y, w, h = 7.4, 1.7, 5.2, 4.2
    values = (x, y, w, h)
    if not all(math.isfinite(value) for value in values):
        x, y, w, h = 7.4, 1.7, 5.2, 4.2

    # Cover layouts compute title width from the visual slot, so keep their
    # more flexible composition while still keeping the image on-canvas.
    if page_type != "cover":
        content_x = _content_start_x(template_id, page_type)
        # Keep a readable left text column plus a visible inter-column gap.
        min_x = max(7.0, content_x + 4.55 + 0.4)
        max_w = max(3.2, canvas_right - min_x)
        w = min(max(3.2, w), max_w)
        x = max(min_x, min(x, canvas_right - w))
        min_y = 1.7
        max_h = max(2.0, canvas_bottom - min_y)
        h = min(max(2.0, h), max_h)
        y = max(min_y, min(y, canvas_bottom - h))
    else:
        x = max(0.65, x)
        y = max(1.15, y)
        w = min(max(3.2, w), canvas_right - 0.65)
        h = min(max(2.0, h), canvas_bottom - 1.15)
        x = min(x, canvas_right - w)
        y = min(y, canvas_bottom - h)
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def _estimate_height(texts: list[str], box_width: float, font_size: float) -> float:
    from app.agent.layouts.metrics import estimate_item_height
    return estimate_item_height(list(texts), box_width, font_size)


class LayoutAgent(Agent):
    key = "layout"
    name = "页面布局 Agent"
    role = "为每页选择版式策略并计算元素位置（标题/正文/图片区域），避免越界与重叠"
    required_artifacts = ["slide_content", "visual_plan"]
    produced_artifacts = ["slide_layout"]
    allowed_tools = ["get_template_design", "get_knowledge_base"]

    def build_system_prompt(self, tc: ToolContext) -> str:
        targets = list(getattr(tc.runtime, "selected_slide_ids", []) or [])
        scope = "、".join(targets) if targets else "全部页面"
        return super().build_system_prompt(tc) + (
            "\n你必须真实分析当前页面已有元素、文字层级、留白、对齐、模板配色与视觉重心，"
            "并从预设版式库中为每页选择一种版式与风格参数，不输出具体像素坐标（坐标由引擎计算）。\n"
            f"本轮唯一允许设计的页面：{scope}。不得输出其他页面。\n"
            "预设版式库（layout_type 只能取以下 key）："
            + "、".join(sorted(PRESET_KEYS)) + "\n"
            "completed.output 必须严格为 {slides:[{slide_id, layout_type, content_allocation:{区域→content_refs}, "
            "style:{font_tier: default|compact|spacious, font_scale: 0.8..1.25, gap_scale: 0.8..1.5, highlight: bool}, "
            "visual_region:{x,y,w,h}, visual_type, rationale}]}。\n"
            "· 文字必须逐字来自当前页面内容，不得自撰措辞；content_ref 用 title/body.N/blocks.*。\n"
            "· 普通内容页默认用 bullet_flow 或 split_two_column；有图片诉求用 left_text_right_visual；"
            "steps 块用 steps_horizontal；compare 块用 compare_columns；quote 块用 quote_center；"
            "quote+compare 混合页用 quote_compare；封面用 cover_left/cover_center。\n"
            "· content_allocation 必须覆盖页面全部可见语义引用；引擎会验证并补齐遗漏，但禁止故意省略正文。\n"
            "· 如果当前页面空间分布已合理，可以选择与当前相同的版式但调整 gap_scale/字号档来体现间距诉求；"
            "如果页面明显拥挤或空白失衡，选择能改善分布的版式。"
        )

    async def decide(self, tc: ToolContext) -> AgentDecision:
        ctx = tc.ctx
        confirmed_candidate = (
            (getattr(tc.runtime, "layout_engine_params", None) or {}).get("confirmed_candidate")
        )
        if isinstance(confirmed_candidate, dict):
            # The candidate was generated by this compiler, stored in a
            # PPTHumanRequest, and reloaded only after server-side token
            # validation.  Reusing it avoids another non-deterministic LLM call
            # and guarantees that the teacher receives the option they saw.
            return AgentDecision(
                completed=True,
                output={"slides": [confirmed_candidate]},
                summary="已采用教师确认的页面候选",
                message="已锁定所选布局候选",
            )
        if not ctx.has_tool_result("get_template_design"):
            return AgentDecision(
                tool_calls=[ToolCall(tool_name="get_template_design", input={})],
                message="正在读取模板设计系统，计算页面布局",
            )
        slide_content = await tc.artifacts.latest("slide_content") if tc.artifacts else None
        visual_plan = await tc.artifacts.latest("visual_plan") if tc.artifacts else None
        source_slides = runtime_baseline_slides(tc.runtime)
        slides = (slide_content or {}).get("data", {}).get("slides") or source_slides
        # ``slide_content`` is persisted as a full-deck snapshot even for a
        # single-page edit.  Deterministic QA repair calls ``decide`` directly,
        # so it does not pass through the later artifact scope filter.  Keep
        # the compiler inside the confirmed page scope here; otherwise an
        # unrelated page can fail layout compilation and abort the selected
        # page's repair.
        selected_ids = set(getattr(tc.runtime, "selected_slide_ids", []) or [])
        if selected_ids:
            slides = [
                slide for slide in slides
                if str(slide.get("id") or "") in selected_ids
            ]
        visual_by_slide = {}
        if visual_plan:
            visual_data = visual_plan.get("data", {})
            for item in (visual_data.get("requests") or []):
                slide_id = str(item.get("slide_id") or "")
                if slide_id:
                    visual_by_slide[slide_id] = {
                        "visualType": item.get("visual_type") or "ai_image",
                        "placement": item.get("placement"),
                    }
            for item in (visual_data.get("slides") or []):
                if item.get("visualRequired"):
                    visual_by_slide[item["slideId"]] = item
        if (
            getattr(tc.runtime, "active_intent", "") in {
                "MODIFY", "LOCAL_REGENERATE", "CONTENT_UPDATE", "GLOBAL_OPTIMIZE",
                "STYLE_CHANGE", "TEMPLATE_SWITCH",
            }
            or getattr(tc.runtime, "content_policy", "edit") in {"preserve", "restore"}
        ):
            for slide in source_slides:
                if any(element.get("kind") in {"image", "chart"} for element in (slide.get("elements") or [])):
                    visual_by_slide.setdefault(str(slide.get("id") or ""), {"visualType": "image"})
        layouts = []
        template_id = str(
            getattr(tc.runtime, "preferred_template", "")
            or (getattr(ctx, "template", {}) or {}).get("id")
            or ""
        )
        engine_style = {
            key: value for key, value in (
                getattr(tc.runtime, "layout_engine_params", None) or {}
            ).items() if key in {"font_tier", "font_scale", "gap_scale", "highlight"}
        }
        for index, slide in enumerate(slides):
            slide_id = str(slide.get("id") or "")
            try:
                layout = self._layout_slide(
                    slide, visual_by_slide.get(slide_id), template_id,
                    style=engine_style,
                )
                # A deterministic QA repair must not compile straight back to the
                # exact source geometry.  That previously turned an invalid LLM
                # proposal into the original steps layout, scored 100 in QA, then
                # failed the final monotony gate.  Prefer the generic safe column
                # layout when the content-aware preset is a geometric no-op.
                if getattr(tc.runtime, "repair_mode", "") == "deterministic":
                    from app.agent.slide_rendering import semantic_geometry_hash

                    candidate = {"elements": list(layout.get("elements") or [])}
                    if semantic_geometry_hash(slide) == semantic_geometry_hash(candidate):
                        alternate = (
                            "bullet_flow"
                            if str(layout.get("layout_type") or "") == "split_two_column"
                            else "split_two_column"
                        )
                        layout = compile_layout(template_id, slide, {
                            "slide_id": slide_id,
                            "layout_type": alternate,
                            "style": {"font_tier": "spacious", "gap_scale": 1.0},
                            "rationale": "QA 确定性修复：避免回退到原页相同版式",
                        })
            except LayoutCompileError as exc:
                if getattr(tc.runtime, "repair_mode", "") != "deterministic":
                    raise
                # The edited copy can be denser than every safe preset.  A QA
                # repair that cannot place it must revert this page to the
                # immutable run baseline and finish as no_change/partial.  It
                # must not abort the whole task or leave the overflowing edited
                # text in the live builder.
                baseline = next((
                    item for item in source_slides
                    if str(item.get("id") or "") == slide_id
                ), slide)
                if tc.builder is not None:
                    for builder_index, builder_slide in enumerate(tc.builder.slides):
                        if str(builder_slide.get("id") or "") == slide_id:
                            tc.builder.slides[builder_index] = deepcopy(baseline)
                            break
                reverted = list(getattr(tc.runtime, "repair_reverted_slide_ids", []) or [])
                if slide_id not in reverted:
                    reverted.append(slide_id)
                tc.runtime.repair_reverted_slide_ids = reverted
                tc.runtime.affected_slide_ids = [
                    value for value in (getattr(tc.runtime, "affected_slide_ids", []) or [])
                    if value != slide_id
                ]
                layout = {
                    "slide_id": slide_id,
                    "layout_type": "preserve_original",
                    "designRationale": "QA 安全修复无可行布局，已恢复该页原版本",
                    "elements": deepcopy(list(baseline.get("elements") or [])),
                    "render_mode": str(baseline.get("render_mode") or "absolute"),
                    "compile_status": "preserved",
                    "warnings": [f"{slide_id} 润色内容无法安全排布，已恢复原页"],
                    "compile_attempts": list(exc.attempts)[-12:],
                    "material_change": False,
                    "requires_candidate_confirmation": False,
                }
            layouts.append(layout)
        return AgentDecision(
            completed=True,
            output={"slides": layouts},
            summary=f"已为 {len(layouts)} 页计算元素几何",
            message="页面布局设计完成",
        )

    @staticmethod
    def _layout_slide(
        slide: dict, visual: dict | None, template_id: str = "",
        *, style: dict[str, Any] | None = None,
    ) -> dict:
        directive = {"slide_id": str(slide.get("id") or ""),
                     "layout_type": LayoutAgent._preset_for_page(slide, visual),
                     "style": dict(style or {}),
                     "rationale": "确定性版式（引擎编译）"}
        page_type = str(slide.get("page_type") or "concept")
        if visual and visual.get("visualType") not in {"none", ""}:
            placement = visual.get("placement") or {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}
            directive["visual_region"] = placement
            directive["visual_type"] = visual.get("visualType", "image")
        return compile_layout(template_id, slide, directive)

    @staticmethod
    def _preset_for_page(slide: dict, visual: dict | None) -> str:
        page_type = str(slide.get("page_type") or "concept")
        if page_type == "cover":
            return "cover_left" if visual and visual.get("visualType") not in {"none", ""} else "cover_center"
        blocks = slide.get("blocks") or []
        if any(b.get("kind") == "steps" for b in blocks):
            return "steps_horizontal"
        if any(b.get("kind") == "compare" for b in blocks):
            return "compare_columns"
        if any(b.get("kind") == "quote" for b in blocks):
            return "quote_center"
        if visual and visual.get("visualType") not in {"none", ""}:
            return "left_text_right_visual"
        body = [t for t in (slide.get("body") or []) if str(t).strip()]
        return "split_two_column" if len(body) >= 6 else "bullet_flow"


LAYOUT_AGENT = LayoutAgent()
