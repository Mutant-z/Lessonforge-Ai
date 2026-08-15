import pytest
from app.agent.layouts.metrics import estimate_text_height
from app.agent.layouts.zones import LayoutZones, zones_for
from app.agent.layouts.engine import adaptive_quality_delta


def test_academic_content_page_zones():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=False)
    assert z.content_x == 2.2
    assert z.title_rail.y == 0.55
    assert z.body_column.y == 1.7
    assert z.body_column.bottom == 6.8
    # 无视觉槽时正文列右缘 = 画布宽 - content_x - 0.78
    assert z.body_column.right == pytest.approx(13.333 - 2.2 - 0.78)
    assert z.visual_slot is None


def test_smart_ai_cover_zones_content_x():
    assert zones_for("lessonforge_deck_smart_ai", "cover", has_visual=False).content_x == 2.95
    assert zones_for("lessonforge_deck_smart_ai", "concept", has_visual=False).content_x == 2.45


def test_visual_slot_narrows_body_column():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=True,
                  visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    assert z.visual_slot is not None
    assert z.body_column.right == pytest.approx(7.4 - 0.4)


def test_estimate_text_height_multiline_and_min():
    # 单行 10 个 CJK 字符 @18pt 在 3in 宽框内：每行约可放 int(3/(18/72*0.98))=12 字
    assert estimate_text_height("十个中文字符十个中文字符十个中文字符十个中文字符", 3.0, 18) > 0.6
    assert estimate_text_height("短", 3.0, 18) == 0.6  # 最小高度
    multi = estimate_text_height("一二三\n四五六", 3.0, 18)
    single = estimate_text_height("一二三", 3.0, 18)
    assert multi > single  # 换行增加行数


def test_estimate_text_height_aggregate_box_is_sum_not_max():
    # layout 的 >6 条聚合单框回退需要整框高度 = 各条目高度之和，而非单条最大值。
    # 每条约 2 行（24 个 CJK 字符 @18pt / 3in 宽框，每行 12 字）。
    items = ["十个中文字符" * 4] * 7
    joined = "\n".join(items)
    total = sum(estimate_text_height(item, 3.0, 18) for item in items)
    assert estimate_text_height(joined, 3.0, 18) == total
    assert total > estimate_text_height(items[0], 3.0, 18)  # 求和 > 最大单条


from app.agent.layouts.presets import PRESETS


def _slide(body=None, blocks=None, page_type="concept"):
    return {"page_type": page_type, "title": "核心概念", "purpose": "",
            "body": body or ["第一条正文要点，围绕核心概念展开。", "第二条正文要点，说明适用条件。", "第三条正文要点，给出一个教学例子。"],
            "blocks": blocks or []}


def _invariants(elements, require_vertical_fill=True):
    assert all(e["x"] >= 0 and e["y"] >= 0 and e["x"] + e["w"] <= 13.333 + 1e-6 and e["y"] + e["h"] <= 7.5 + 1e-6 for e in elements), "越界"
    boxes = [(e["x"], e["y"], e["w"], e["h"]) for e in elements if e["kind"] in {"textbox", "note"}]
    for i, (ax, ay, aw, ah) in enumerate(boxes):
        for bx, by, bw, bh in boxes[i + 1:]:
            ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            oy = max(0, min(ay + ah, by + bh) - max(ay, by))
            assert ox * oy <= 1e-6, f"重叠 {i}"
    text_items = [e for e in elements if e["kind"] == "textbox"]
    text_y = [e["y"] for e in text_items if e["content_ref"] != "title"]
    text_bottom = [e["y"] + e["h"] for e in text_items if e["content_ref"] != "title"]
    if text_y and require_vertical_fill:
        assert max(text_bottom) - min(text_y) >= (6.8 - 1.7) * 0.45 - 1e-6, "正文纵向未铺满"
    for e in text_items:
        if e.get("text"):
            from app.agent.layouts.metrics import estimate_text_height
            assert estimate_text_height(e["text"], e["w"], (e.get("style") or {}).get("size", 18)) <= e["h"] * 1.15, "溢出"


def test_bullet_flow_invariants():
    _invariants(PRESETS["bullet_flow"](zones_for("lessonforge_deck_academic", "concept"), _slide(), {}))


def test_split_two_column_invariants():
    _invariants(PRESETS["split_two_column"](zones_for("lessonforge_deck_academic", "concept"), _slide(body=[f"要点 {i}" for i in range(6)]), {}))


def test_steps_horizontal_invariants():
    blocks = [{"kind": "steps", "steps": [
        {"title": "第一步", "detail": "建立概念"},
        {"title": "第二步", "detail": "给出示例"},
        {"title": "第三步", "detail": "迁移应用"},
    ]}]
    _invariants(PRESETS["steps_horizontal"](zones_for("lessonforge_deck_academic", "process"), _slide(blocks=blocks, page_type="process"), {}), require_vertical_fill=False)


def test_steps_horizontal_caps_cards_at_four():
    blocks = [{"kind": "steps", "steps": [
        {"title": f"第 {i} 步", "detail": f"要点 {i}"} for i in range(6)
    ]}]
    elements = PRESETS["steps_horizontal"](zones_for("lessonforge_deck_academic", "process"), _slide(blocks=blocks, page_type="process"), {})
    _invariants(elements, require_vertical_fill=False)
    assert max(e["x"] + e["w"] for e in elements) <= 13.333 + 1e-6
    assert sum(1 for e in elements if e["content_ref"].startswith("blocks.0.steps.")) <= 8


def test_compare_columns_invariants():
    blocks = [{"kind": "compare", "left": {"heading": "传统教学", "items": ["讲授为主", "统一进度"]},
               "right": {"heading": "探究教学", "items": ["任务驱动", "个性化"]}}]
    _invariants(PRESETS["compare_columns"](zones_for("lessonforge_deck_academic", "comparison"), _slide(blocks=blocks, page_type="comparison"), {}), require_vertical_fill=False)


def test_left_text_right_visual_invariants():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=True, visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    _invariants(PRESETS["left_text_right_visual"](z, _slide(), {}))


def test_quote_center_invariants():
    blocks = [{"kind": "quote", "text": "教育的本质意味着一棵树摇动另一棵树。", "citation": "雅斯贝尔斯"}]
    _invariants(PRESETS["quote_center"](zones_for("lessonforge_deck_academic", "concept"), _slide(blocks=blocks), {}), require_vertical_fill=False)


def test_agenda_list_invariants():
    _invariants(PRESETS["agenda_list"](zones_for("lessonforge_deck_academic", "agenda"), _slide(page_type="agenda"), {}))


def test_cover_left_invariants():
    z = zones_for("lessonforge_deck_academic", "cover", has_visual=True, visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    slide = {"page_type": "cover", "title": "课程封面", "purpose": "单元导入", "body": ["目标一", "目标二"], "blocks": []}
    _invariants(PRESETS["cover_left"](z, slide, {}), require_vertical_fill=False)


def test_cover_center_invariants():
    z = zones_for("lessonforge_deck_academic", "cover", has_visual=True, visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    slide = {"page_type": "cover", "title": "课程封面", "purpose": "单元导入", "body": ["目标一", "目标二"], "blocks": []}
    _invariants(PRESETS["cover_center"](z, slide, {}), require_vertical_fill=False)


def test_long_cover_with_visual_preserves_purpose_and_all_body_copy():
    """Regression for 2fa1a91a: rebound third body line overflowed fixed cover boxes."""
    from app.agent.slide_rendering import render_coverage

    slide = {
        "id": "slide_01", "page_type": "cover",
        "title": "探秘浮力成因与阿基米德原理",
        "purpose": "创设潜水艇下潜情境，明确翻转预习目标，激发探究兴趣",
        "body": [
            "八年级物理 · 10分钟翻转预习微课",
            "核心思考：潜水艇向深水下潜，受到的浮力会变大吗？",
            "探究路径：解构液体上下压力差，实验推导阿基米德原理",
        ],
        "blocks": [],
    }
    out = compile_layout("lessonforge_deck_smart_ai", slide, {
        "slide_id": "slide_01", "layout_type": "cover_left",
        "style": {"font_tier": "spacious", "font_scale": 1.10, "gap_scale": 1.20},
        "visual_region": {"x": 7.5, "y": 1.15, "w": 5.0, "h": 4.4},
        "visual_type": "image",
    })

    assert render_coverage({**slide, **out}, baseline=slide)["missing_refs"] == []
    assert {item.get("content_ref") for item in out["elements"]} >= {"title", "body", "purpose"}
    selected = next(
        item for item in out["compile_attempts"]
        if item["candidate_id"] == out["selected_candidate_id"]
    )
    assert selected["geometry_failures"] == []
    assert max(item["y"] + item["h"] for item in out["elements"]) <= 7.01

    subtitle = next(item for item in out["elements"] if item.get("content_ref") == "body")
    assert subtitle["text"] == "\n".join(slide["body"])


def test_cover_search_adds_purpose_aware_recipe_for_generic_model_choice():
    slide = {
        "id": "slide_01", "page_type": "cover", "title": "浮力探秘",
        "purpose": "建立探究情境", "body": ["八年级物理", "核心问题"], "blocks": [],
    }
    out = compile_layout("lessonforge_deck_smart_ai", slide, {
        "slide_id": "slide_01", "layout_type": "left_text_right_visual",
        "visual_region": {"x": 7.5, "y": 1.15, "w": 5.0, "h": 4.4},
        "visual_type": "image",
    })

    assert out["layout_type"] == "cover_left"
    assert any(item.get("content_ref") == "purpose" for item in out["elements"])


def test_cover_body_subtitle_counts_as_body_quality_evidence():
    from app.agent.layouts.analysis import analyze_layout
    from app.agent.layouts.zones import zones_for

    slide = {
        "id": "slide_01", "page_type": "cover", "title": "浮力探秘",
        "purpose": "建立探究情境", "body": ["八年级物理", "核心问题"], "blocks": [],
    }
    zones = zones_for(
        "lessonforge_deck_smart_ai", "cover", has_visual=True,
        visual_region={"x": 7.5, "y": 1.15, "w": 5.0, "h": 4.4},
    )
    elements = PRESETS["cover_left"](zones, slide, {})
    metrics = analyze_layout(elements, zones, slide=slide, layout_type="cover_left")

    assert metrics["body_element_count"] == 2
    assert metrics["body_vertical_utilization"] > 0.20
    assert metrics["quality_components"]["semantic_grouping"] == 10.0


from app.agent.layouts.engine import compile_layout, normalize_layout_params


def test_compile_layout_unknown_type_falls_back_to_bullet():
    slide = _slide()
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "not_a_preset", "style": {}})
    assert out["layout_type"] == "bullet_flow"
    assert out["slide_id"] == "S01"
    assert out["elements"]


def test_compile_layout_aliases_old_names():
    slide = _slide()
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "title_and_body", "style": {}})
    assert out["layout_type"] == "bullet_flow"


def test_normalize_layout_params_bounds():
    assert normalize_layout_params({"gap_scale": 5.0})["gap_scale"] == 1.5
    assert normalize_layout_params({"gap_scale": 0.1})["gap_scale"] == 0.8
    assert normalize_layout_params({})["font_tier"] == "default"


def test_failed_run_agenda_layout_falls_back_on_canvas_with_spacious_typography():
    """Regression for fe88007e: nine agenda refs must not extend below 7.5in."""
    slide = _slide(
        page_type="objectives",
        body=[
            "解析受力本质：看清上下表面压力差",
            "澄清深度误区：理解完全浸没后浮力不变",
            "推导物理规律：通过溢水实验归纳阿基米德原理",
        ],
        blocks=[{"kind": "steps", "steps": [
            {"title": "任务一：看清物理本质", "detail": "分析立方体受力，推导 F浮 = F下 - F上"},
            {"title": "任务二：破解深度错觉", "detail": "辨析潜水艇下潜，明确浸没后浮力不变"},
            {"title": "任务三：推导核心原理", "detail": "观察四步溢水实验，归纳 F浮 = G排"},
        ]}],
    )

    out = compile_layout("lessonforge_deck_smart_ai", slide, {
        "slide_id": "slide_03", "layout_type": "agenda_list",
        "style": {"font_tier": "spacious", "gap_scale": 1.25},
    })

    assert out["layout_type"] == "split_two_column"
    assert max(item["y"] + item["h"] for item in out["elements"]) <= 7.0 + 1e-6
    assert {
        item["style"].get("size") for item in out["elements"]
        if item.get("content_ref") != "title"
    } == {20}


# ---------- Task 6: LayoutDirective schema + 引擎编译为可执行坐标 ----------

from app.agent.schemas import LayoutDirectiveArtifact, SlideLayoutArtifact


def test_layout_directive_artifact_parses():
    art = LayoutDirectiveArtifact.model_validate({"slides": [
        {"slide_id": "S01", "layout_type": "bullet_flow", "style": {"gap_scale": 1.2}},
    ]})
    assert art.slides[0].layout_type == "bullet_flow"


def test_compile_layout_output_is_page_layout_spec_compatible():
    out = compile_layout("lessonforge_deck_academic", _slide(), {"slide_id": "S01", "layout_type": "bullet_flow"})
    spec = SlideLayoutArtifact.model_validate({"slides": [out]})
    assert spec.slides[0].elements


def test_steps_layout_covers_body_and_legacy_step_text_from_failed_run():
    """Regression for run 9263fbc8: body and step copy must both be visible."""
    from app.agent.schemas import SlideContentPatch
    from app.agent.slide_rendering import render_coverage

    patch = SlideContentPatch.model_validate({"slides": [{
        "id": "slide_03", "changed_fields": ["title", "body", "blocks"],
        "title": "预习目标：三步解锁浮力奥秘",
        "body": [
            "理解浮力成因：推导上下表面压力差",
            "澄清深度误区：完全浸没后浮力不变",
            "掌握推导逻辑：溢水实验得出阿基米德原理",
        ],
        "blocks": [{"kind": "steps", "steps": [
            {"title": "看本质", "text": "分析立方体水下受力，得出压力差公式"},
            {"title": "破误区", "text": "剖析潜水艇下潜轨迹，说明浮力与深度无关"},
            {"title": "推原理", "text": "观察溢水实验四步法，推导阿基米德原理"},
        ]}],
    }]}).slides[0].model_dump(exclude_none=True)
    slide = {
        **patch, "page_type": "objectives", "purpose": "", "layout": "bullet",
        "visual_suggestion": "", "speaker_notes": "", "duration_seconds": 45,
    }

    out = compile_layout(
        "lessonforge_deck_smart_ai", slide,
        {"slide_id": "slide_03", "layout_type": "steps_horizontal"},
    )

    assert out["layout_type"] == "steps_horizontal"
    assert slide["blocks"][0]["steps"][0]["detail"].startswith("分析立方体")
    assert render_coverage({**slide, **out}, baseline=slide)["missing_refs"] == []
    assert {f"body.{index}" for index in range(3)} <= {
        item.get("content_ref") for item in out["elements"]
    }


def test_steps_layout_keeps_body_items_beyond_four_step_cards():
    """Regression for run 56c065d4: slide_04 lost body.4/body.5."""
    from app.agent.slide_rendering import render_coverage

    slide = {
        "id": "slide_04", "page_type": "concept",
        "title": "阿基米德原理推导：四步溢水实验法", "purpose": "",
        "body": [
            "步骤1：用弹簧测力计测出物体重力 G物",
            "步骤2：将物体浸没在装满水的溢水杯中",
            "算出浮力：F浮 = G物 - F示",
            "步骤3：收集物体排开的水",
            "步骤4：测出排开水的重力",
            "算出排开水重：G排 = G总 - G杯",
        ],
        "blocks": [{"kind": "steps", "steps": [
            {"title": "步骤一：测物重", "detail": "记录物体在空气中的重力"},
            {"title": "步骤二：浸没物体", "detail": "记录浸没后的弹簧测力计示数"},
            {"title": "步骤三：收集排水", "detail": "用空杯接住全部溢出的水"},
            {"title": "步骤四：测排水重", "detail": "称量水杯并计算排开水重"},
        ]}],
    }

    out = compile_layout(
        "lessonforge_deck_smart_ai", slide,
        {"slide_id": "slide_04", "layout_type": "steps_horizontal"},
    )

    refs = {item.get("content_ref") for item in out["elements"]}
    assert out["layout_type"] == "steps_horizontal"
    assert {"body.4", "body.5"} <= refs
    assert render_coverage({**slide, **out}, baseline=slide)["missing_refs"] == []
    assert max(item["y"] + item["h"] for item in out["elements"]) <= 7.0 + 1e-6


def test_analysis_fallback_reports_layout_page_and_missing_copy():
    from types import SimpleNamespace

    from app.agent.layouts.engine import LayoutCompileError
    from app.agent.pipeline import _compile_layout_from_analysis
    from app.agent.schemas import AgentDecision, PPTAgentError

    slide = {
        "id": "slide_04", "page_type": "concept", "title": "实验推导",
        "purpose": "", "body": ["必要结论一", "必要结论二"], "blocks": [],
    }
    runtime = SimpleNamespace(
        baseline_slides=[slide], content_policy="preserve", active_intent="GLOBAL_OPTIMIZE",
        expected_visual_requests=[], preferred_template="lessonforge_deck_smart_ai",
    )

    class BrokenLayoutAgent:
        @staticmethod
        def _layout_slide(_slide, _visual, _template):
            raise LayoutCompileError([], ["body.1"], True)

    with pytest.raises(PPTAgentError) as raised:
        _compile_layout_from_analysis(
            runtime, AgentDecision(completed=True, output={"slides": []}), [slide], BrokenLayoutAgent(),
        )

    assert raised.value.code == "layout_incomplete"
    assert "第 4 页" in raised.value.user_message
    assert raised.value.details["slide_id"] == "slide_04"
    assert raised.value.details["missing_refs"] == ["body.1"]
    assert raised.value.details["missing_text"] == [{"ref": "body.1", "text": "必要结论二"}]


def test_structured_preset_uses_real_block_index_and_mixed_content_falls_back_safely():
    from app.agent.slide_rendering import render_coverage

    blocks = [
        {"kind": "quote", "text": "先提出问题", "citation": "导入"},
        {"kind": "steps", "steps": [
            {"title": "第一步", "detail": "观察"},
            {"title": "第二步", "detail": "归纳"},
        ]},
    ]
    slide = _slide(body=["观察现象", "归纳规律"], blocks=blocks, page_type="process")
    direct = PRESETS["steps_horizontal"](
        zones_for("lessonforge_deck_academic", "process"), slide, {},
    )
    assert any(
        str(item.get("content_ref") or "").startswith("blocks.1.steps.")
        for item in direct
    )

    out = compile_layout(
        "lessonforge_deck_academic", slide,
        {"slide_id": "S01", "layout_type": "steps_horizontal"},
    )
    assert out["layout_type"] == "split_two_column"
    assert render_coverage({**slide, **out}, baseline=slide)["missing_refs"] == []


def test_more_than_four_steps_falls_back_without_losing_tail_steps():
    from app.agent.slide_rendering import render_coverage

    blocks = [{"kind": "steps", "steps": [
        {"title": f"第 {index + 1} 步", "detail": f"步骤说明 {index + 1}"}
        for index in range(6)
    ]}]
    slide = _slide(body=[f"正文 {index + 1}" for index in range(6)], blocks=blocks, page_type="process")
    out = compile_layout(
        "lessonforge_deck_academic", slide,
        {"slide_id": "S01", "layout_type": "steps_horizontal"},
    )
    assert out["layout_type"] == "split_two_column"
    assert render_coverage({**slide, **out}, baseline=slide)["missing_refs"] == []


async def test_ensure_executable_layout_compiles_directive_via_engine():
    """新路径：LayoutDirective（layout_type/style）→ 引擎编译为可执行坐标。

    旧路径会忽略 directive 的 layout_type 而按内容确定性选择版式；
    新路径必须让 directive 指定的版式经引擎编译生效。
    """
    from types import SimpleNamespace

    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _ensure_executable_layout
    from app.agent.schemas import AgentDecision

    source = {
        "id": "slide_01", "page_type": "concept", "title": "浮力成因",
        "purpose": "", "body": ["上下压力差产生浮力", "液体密度越大浮力越大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
    }

    class Artifacts:
        async def latest(self, artifact_type):
            return None

    runtime = SimpleNamespace(
        selected_slide_ids=["slide_01"], content_policy="preserve",
        active_intent="LAYOUT_ONLY", baseline_slides=[source], artifacts=Artifacts(),
        emitter=None, preferred_template="lessonforge_deck_academic",
        expected_visual_requests=[], builder=None,
    )
    decision = AgentDecision(completed=True, output={"slides": [
        {"slide_id": "slide_01", "layout_type": "split_two_column",
         "style": {"gap_scale": 1.2}, "rationale": "引擎编译验证"},
    ]})
    normalized = await _ensure_executable_layout(runtime, LAYOUT_AGENT, decision)
    slide = normalized.output["slides"][0]
    assert slide["slide_id"] == "slide_01"
    assert slide["layout_type"] == "split_two_column", "directive 的 layout_type 必须经引擎编译生效"
    spec = SlideLayoutArtifact.model_validate({"slides": [slide]})
    body = [el for el in spec.slides[0].elements if str(el.content_ref or "").startswith("body")]
    assert len(body) == 2
    xs = {round(float(el.x), 1) for el in body}
    assert len(xs) == 2, "split_two_column 应生成左右双栏"


@pytest.mark.asyncio
async def test_layout_only_ignores_phantom_visual_region_from_structured_model():
    """Regression for b2ae2c7b: optional model fields must not invent an image slot."""
    from types import SimpleNamespace

    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _ensure_executable_layout
    from app.agent.schemas import AgentDecision

    source = {
        **_slide(
            page_type="objectives",
            body=["目标一", "目标二", "目标三"],
            blocks=[{"kind": "steps", "steps": [
                {"title": "任务一", "detail": "说明一"},
                {"title": "任务二", "detail": "说明二"},
                {"title": "任务三", "detail": "说明三"},
            ]}],
        ),
        "id": "slide_03",
    }

    class Artifacts:
        async def latest(self, artifact_type):
            return None

    runtime = SimpleNamespace(
        selected_slide_ids=["slide_03"], content_policy="preserve",
        active_intent="LAYOUT_ONLY", baseline_slides=[source], artifacts=Artifacts(),
        emitter=None, preferred_template="lessonforge_deck_smart_ai",
        expected_visual_requests=[], builder=None,
    )
    decision = AgentDecision(completed=True, output={"slides": [{
        "slide_id": "slide_03", "layout_type": "bullet_flow",
        "style": {"font_tier": "spacious", "gap_scale": 1.3},
        "visual_region": {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2},
        "visual_type": "image",
    }]})

    normalized = await _ensure_executable_layout(runtime, LAYOUT_AGENT, decision)
    layout = normalized.output["slides"][0]
    assert layout["layout_type"] == "split_two_column"
    assert layout.get("visual_region") is None
    assert max(element["y"] + element["h"] for element in layout["elements"]) <= 7.0


@pytest.mark.asyncio
async def test_deterministic_repair_does_not_return_to_identical_source_geometry():
    from types import SimpleNamespace

    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.layouts.engine import compile_layout
    from app.agent.slide_rendering import semantic_geometry_hash

    source = {
        **_slide(
            page_type="objectives",
            body=["目标一", "目标二", "目标三"],
            blocks=[{"kind": "steps", "steps": [
                {"title": "任务一", "detail": "说明一"},
                {"title": "任务二", "detail": "说明二"},
                {"title": "任务三", "detail": "说明三"},
            ]}],
        ),
        "id": "slide_03",
    }
    original = compile_layout("lessonforge_deck_smart_ai", source, {
        "slide_id": "slide_03", "layout_type": "steps_horizontal",
    })
    source = {**source, "render_mode": "absolute", "elements": original["elements"]}

    class Artifacts:
        async def latest(self, artifact_type):
            return None

    tc = SimpleNamespace(
        ctx=SimpleNamespace(has_tool_result=lambda _name: True, template={}),
        artifacts=Artifacts(),
        runtime=SimpleNamespace(
            selected_slide_ids=["slide_03"], baseline_slides=[source],
            active_intent="LAYOUT_ONLY", content_policy="preserve",
            repair_mode="deterministic", preferred_template="lessonforge_deck_smart_ai",
        ),
    )

    decision = await LAYOUT_AGENT.decide(tc)
    repaired = decision.output["slides"][0]
    assert repaired["layout_type"] == "split_two_column"
    assert semantic_geometry_hash(source) != semantic_geometry_hash({"elements": repaired["elements"]})


@pytest.mark.asyncio
async def test_deterministic_repair_compiles_only_selected_slides(monkeypatch):
    """A full-deck slide_content snapshot must not widen a one-page repair."""
    from types import SimpleNamespace

    from app.agent.agents.layout import LAYOUT_AGENT

    unselected = {
        "id": "slide_01", "page_type": "cover", "title": "未选中的封面",
        "purpose": "不可触碰", "body": ["原文"], "blocks": [], "elements": [],
    }
    selected = {
        "id": "slide_05", "page_type": "concept", "title": "目标页",
        "purpose": "", "body": ["润色后的正文"], "blocks": [],
        "elements": [{
            "kind": "textbox", "content_ref": "title", "text": "目标页",
            "x": 2.2, "y": 0.55, "w": 10.0, "h": 0.8,
        }],
    }

    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "slide_content":
                return {"data": {"slides": [unselected, selected]}}
            return None

    compiled_ids = []

    def compile_selected_only(slide, _visual, _template_id, *, style=None):
        compiled_ids.append(slide["id"])
        return {
            "slide_id": slide["id"], "layout_type": "bullet_flow",
            "elements": [{
                "kind": "textbox", "content_ref": "title", "text": slide["title"],
                "x": 2.45, "y": 0.55, "w": 10.0, "h": 0.8,
            }],
        }

    monkeypatch.setattr(LAYOUT_AGENT, "_layout_slide", compile_selected_only)
    tc = SimpleNamespace(
        ctx=SimpleNamespace(has_tool_result=lambda _name: True, template={}),
        artifacts=Artifacts(),
        runtime=SimpleNamespace(
            selected_slide_ids=["slide_05"], baseline_slides=[unselected, selected],
            active_intent="MODIFY", content_policy="edit",
            repair_mode="deterministic", preferred_template="lessonforge_deck_smart_ai",
            layout_engine_params={},
        ),
    )

    decision = await LAYOUT_AGENT.decide(tc)

    assert compiled_ids == ["slide_05"]
    assert [item["slide_id"] for item in decision.output["slides"]] == ["slide_05"]


@pytest.mark.asyncio
async def test_deterministic_repair_failure_restores_baseline_and_editor_skips_rejected_copy(monkeypatch):
    from types import SimpleNamespace

    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.agents.ppt_editor import PPT_EDITOR_AGENT
    from app.agent.layouts.engine import LayoutCompileError
    from app.renderers.presentation_builder import PresentationBuilder

    baseline = {
        "id": "slide_05", "page_type": "concept", "title": "实验推理",
        "purpose": "", "body": ["原始精炼正文"], "blocks": [],
        "render_mode": "absolute",
        "elements": [{
            "kind": "textbox", "content_ref": "title", "text": "实验推理",
            "x": 2.45, "y": 0.55, "w": 10.0, "h": 0.8,
        }, {
            "kind": "textbox", "content_ref": "body", "text": "原始精炼正文",
            "x": 2.45, "y": 1.7, "w": 4.6, "h": 3.2,
        }],
    }
    edited = {
        **baseline,
        "body": ["润色后但无法安全排布的超长正文" for _ in range(12)],
    }

    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "slide_content":
                return {"data": {"slides": [edited]}}
            if artifact_type == "slide_layout":
                return {"data": {"slides": [preserved_layout]}}
            return None

        async def list_all(self):
            return []

    def fail_layout(*_args, **_kwargs):
        raise LayoutCompileError([], [], False, attempts=[{
            "candidate_id": "split_two_column:1", "geometry_safe": False,
            "geometry_failures": ["overlap"],
        }])

    builder = PresentationBuilder().from_ppt_content({"slides": [edited]})
    runtime = SimpleNamespace(
        selected_slide_ids=["slide_05"], baseline_slides=[baseline],
        active_intent="MODIFY", content_policy="edit",
        repair_mode="deterministic", preferred_template="lessonforge_deck_smart_ai",
        layout_engine_params={}, repair_reverted_slide_ids=[],
        affected_slide_ids=["slide_05"], mutation_applied=False,
        layout_compile_results=[],
    )
    tc = SimpleNamespace(
        ctx=SimpleNamespace(has_tool_result=lambda _name: True, template={}),
        artifacts=Artifacts(), runtime=runtime, builder=builder,
    )
    monkeypatch.setattr(LAYOUT_AGENT, "_layout_slide", fail_layout)

    layout_decision = await LAYOUT_AGENT.decide(tc)
    preserved_layout = layout_decision.output["slides"][0]

    assert preserved_layout["compile_status"] == "preserved"
    assert runtime.repair_reverted_slide_ids == ["slide_05"]
    assert runtime.affected_slide_ids == []
    assert builder.slides[0]["body"] == baseline["body"]

    editor_decision = await PPT_EDITOR_AGENT.decide(tc)
    assert editor_decision.completed is True
    assert editor_decision.output["result_status"] == "no_change"
    assert editor_decision.tool_calls == []
    assert runtime.mutation_applied is True


def test_v60_slide_02_quote_compare_spacious_is_complete_and_safe():
    """Regression for e957210c: V60 slide_02 lost five body refs and quote copy."""
    from app.agent.slide_rendering import render_coverage

    slide = {
        "id": "slide_02", "page_type": "scenario",
        "title": "潜水艇下潜之谜：水压变大，浮力也变大吗？",
        "purpose": "创设下潜情境，引发水压与浮力的认知冲突",
        "body": [
            "直觉误区：潜水艇从10m下潜到30m",
            "根据 p=ρgh 水压增大，易误认为浮力变大",
            "理性疑问：完全浸没后浮力真的变大吗？",
            "压强增大是否等同于浮力增大？",
            "浮力产生的物理本质究竟是什么？",
        ],
        "blocks": [
            {"kind": "quote", "text": "潜水艇越往下潜，受到的浮力就越大？", "citation": "直觉思维误区"},
            {"kind": "compare",
             "left": {"heading": "直觉误区与现象", "items": [
                 "潜水艇从10m下潜至30m", "根据p=ρgh，水压显著增大", "容易误以为浮力随水压变大",
             ]},
             "right": {"heading": "理性疑问与思考", "items": [
                 "完全浸没后浮力真的变大吗？", "水压增大是否等于浮力增大？", "浮力产生的物理本质是什么？",
             ]}},
        ],
    }

    out = compile_layout("lessonforge_deck_smart_ai", slide, {
        "slide_id": "slide_02", "layout_type": "compare_columns",
        "style": {"font_tier": "spacious", "font_scale": 1.10, "gap_scale": 1.20},
    })

    assert out["layout_type"] == "quote_compare"
    assert out["compile_status"] == "fallback"
    assert render_coverage({**slide, **out}, baseline=slide)["missing_refs"] == []
    assert max(item["y"] + item["h"] for item in out["elements"]) <= 7.01
    first_compare = next(item for item in out["compile_attempts"] if item["layout_type"] == "compare_columns")
    assert {
        "body.0", "body.1", "body.2", "body.3", "body.4",
        "blocks.0.text", "blocks.0.citation",
    } <= set(first_compare["missing_refs"])
    assert first_compare["geometry_safe"] is True
    assert out["compile_attempts"][-1]["missing_refs"] == []
    assert out["compile_attempts"][-1]["geometry_failures"] == []


def test_v60_analysis_fallback_injects_size_target_instead_of_preserving_page():
    """The provider-compatible prose-analysis branch must also receive the 1.10 goal."""
    from types import SimpleNamespace

    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _average_text_size, _compile_layout_from_analysis
    from app.agent.schemas import AgentDecision

    slide = {
        "id": "slide_02", "page_type": "scenario", "title": "潜水艇下潜之谜",
        "purpose": "", "body": [f"正文 {index}" for index in range(5)],
        "blocks": [
            {"kind": "quote", "text": "越深浮力越大？", "citation": "直觉误区"},
            {"kind": "compare",
             "left": {"heading": "直觉", "items": ["现象一", "现象二", "现象三"]},
             "right": {"heading": "疑问", "items": ["疑问一", "疑问二", "疑问三"]}},
        ],
        # Legacy V60 elements had no canonical refs, so in-place enlargement
        # cannot prove coverage and must fall through to the compound preset.
        "render_mode": "absolute", "elements": [
            {"kind": "textbox", "text": "潜水艇下潜之谜", "x": 2.2, "y": 0.6, "w": 9, "h": .8, "style": {"size": 22}},
            {"kind": "textbox", "text": "越深浮力越大？", "x": 2.2, "y": 1.5, "w": 9, "h": .6, "style": {"size": 15}},
            *[
                {"kind": "textbox", "text": f"旧框 {index}", "x": 2.2 + (index % 2) * 5.2,
                 "y": 2.4 + (index // 2) * .8, "w": 4.7, "h": .7,
                 "style": {"size": 18 if index < 2 else 14}}
                for index in range(8)
            ],
        ],
    }
    runtime = SimpleNamespace(
        baseline_slides=[slide], content_policy="preserve", active_intent="LAYOUT_ONLY",
        expected_visual_requests=[], preferred_template="lessonforge_deck_smart_ai",
        layout_engine_params={
            "target_dimension": "size", "font_tier": "spacious",
            "font_scale": 1.10, "size_scale": 1.10,
        },
        layout_compile_results=[],
    )

    compiled = _compile_layout_from_analysis(
        runtime,
        AgentDecision(completed=True, output={"slides": [{
            "slide_id": "slide_02", "layout_type": "compare_columns",
        }]}),
        [slide], LAYOUT_AGENT,
    ).model_dump()["slides"][0]

    assert compiled["layout_type"] in {"quote_compare", "split_two_column"}
    assert compiled["compile_status"] == "fallback"
    assert _average_text_size(compiled["elements"]) >= _average_text_size(slide["elements"]) * 1.01
    assert runtime.layout_compile_results[0]["requested_layout"] == "compare_columns"
    assert runtime.layout_compile_results[0]["effective_layout"] in {
        "quote_compare", "split_two_column",
    }


def test_compare_columns_honors_font_and_gap_scale():
    slide = _slide(body=[], blocks=[{
        "kind": "compare",
        "left": {"heading": "原观点", "items": ["观点一", "观点二"]},
        "right": {"heading": "新观点", "items": ["结论一", "结论二"]},
    }], page_type="comparison")
    default = PRESETS["compare_columns"](
        zones_for("lessonforge_deck_academic", "comparison"), slide,
        {"font_tier": "default", "font_scale": 1.0, "gap_scale": 1.0},
    )
    spacious = PRESETS["compare_columns"](
        zones_for("lessonforge_deck_academic", "comparison"), slide,
        {"font_tier": "spacious", "font_scale": 1.1, "gap_scale": 1.2},
    )
    default_sizes = [item["style"]["size"] for item in default if item.get("kind") == "textbox"]
    spacious_sizes = [item["style"]["size"] for item in spacious if item.get("kind") == "textbox"]
    assert sum(spacious_sizes) / len(spacious_sizes) > sum(default_sizes) / len(default_sizes)
    default_y = [item["y"] for item in default if ".items." in str(item.get("content_ref"))]
    spacious_y = [item["y"] for item in spacious if ".items." in str(item.get("content_ref"))]
    assert max(spacious_y) - min(spacious_y) > max(default_y) - min(default_y)


# ---------- V2 candidate scoring / material-change gates ----------


def test_layout_analysis_excludes_wide_title_from_body_utilization():
    """A full-width title must not hide body copy clustered in the top third."""
    from app.agent.layouts.analysis import analyze_layout

    zones = zones_for("lessonforge_deck_academic", "concept")
    elements = [
        {"kind": "textbox", "role": "title", "content_ref": "title", "text": "宽标题",
         "x": zones.title_rail.x, "y": zones.title_rail.y,
         "w": zones.title_rail.w, "h": zones.title_rail.h, "style": {"size": 30}},
        {"kind": "textbox", "role": "body", "content_ref": "body.0", "text": "正文一",
         "x": zones.body_column.x, "y": 1.7, "w": zones.body_column.w / 3, "h": 0.6,
         "style": {"size": 16}},
        {"kind": "textbox", "role": "body", "content_ref": "body.1", "text": "正文二",
         "x": zones.body_column.x + zones.body_column.w / 3, "y": 1.7,
         "w": zones.body_column.w / 3, "h": 0.6, "style": {"size": 16}},
        {"kind": "textbox", "role": "body", "content_ref": "body.2", "text": "正文三",
         "x": zones.body_column.x + zones.body_column.w * 2 / 3, "y": 1.7,
         "w": zones.body_column.w / 3, "h": 0.6, "style": {"size": 16}},
    ]

    metrics = analyze_layout(elements, zones, slide=_slide(), layout_type="split_two_column")

    assert metrics["body_horizontal_utilization"] > 0.95
    assert metrics["body_vertical_utilization"] < 0.15
    assert metrics["max_blank_region_ratio"] > 0.75


def test_compile_layout_ranks_three_to_five_viable_candidates_before_selecting():
    out = compile_layout(
        "lessonforge_deck_academic", _slide(),
        {"slide_id": "S01", "layout_type": "bullet_flow", "style": {}},
    )
    viable = [attempt for attempt in out["compile_attempts"] if attempt.get("viable")]

    assert 3 <= len(viable) <= 5
    assert out["compile_attempts"][-1]["selected"] is True
    assert out["selected_candidate_id"] == out["compile_attempts"][-1]["candidate_id"]
    assert all("metrics" in attempt and "quality_score" in attempt for attempt in viable)


def test_underused_baseline_cannot_use_existing_absolute_scaled_shortcut():
    zones = zones_for("lessonforge_deck_academic", "concept")
    slide = {
        **_slide(), "id": "slide_03", "render_mode": "absolute",
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "核心概念",
             "x": zones.title_rail.x, "y": zones.title_rail.y, "w": zones.title_rail.w,
             "h": zones.title_rail.h, "style": {"size": 30}},
            *[
                {"kind": "textbox", "role": "body", "content_ref": f"body.{index}", "text": text,
                 "x": zones.body_column.x + index * zones.body_column.w / 3,
                 "y": zones.body_column.y, "w": zones.body_column.w / 3 - 0.1,
                 "h": 0.7, "style": {"size": 16}}
                for index, text in enumerate(_slide()["body"])
            ],
        ],
    }

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": "slide_03", "layout_type": "bullet_flow",
        "style": {"font_scale": 1.10}, "target_dimension": "size",
    })

    assert not any(
        attempt["layout_type"] == "existing_absolute_scaled"
        for attempt in out["compile_attempts"]
    )
    assert out["final_metrics"]["body_vertical_utilization"] >= 0.60


def test_layout_polish_without_adaptive_gain_is_preserved_no_change():
    semantic = {**_slide(), "id": "slide_03"}
    baseline = compile_layout(
        "lessonforge_deck_academic", semantic,
        {"slide_id": "slide_03", "layout_type": "bullet_flow"},
    )
    slide = {**semantic, "render_mode": "absolute", "elements": baseline["elements"]}

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": "slide_03", "layout_type": "bullet_flow",
        "polish_mode": True,
    })

    assert out["compile_status"] == "preserved"
    assert out["layout_type"] == "preserve_original"
    assert out["quality_delta"] == 0.0
    assert out["elements"] == baseline["elements"]
    assert out["objective_results"][0]["metric"] == "layout_quality"
    assert out["objective_results"][0]["passed"] is False


@pytest.mark.parametrize(
    ("baseline", "minimum_delta"),
    [(74.99, 8.0), (75.0, 5.0), (84.99, 5.0), (85.0, 3.0), (95.0, 3.0)],
)
def test_adaptive_quality_gate_by_baseline_tier(baseline, minimum_delta):
    assert adaptive_quality_delta(baseline) == minimum_delta


def test_v64_high_quality_page_gain_of_three_passes_adaptive_gate():
    from app.agent.layouts.engine import _evaluate_objectives

    results, passed = _evaluate_objectives(
        [{
            "metric": "layout_quality", "direction": "increase",
            "minimum_delta": 0.0, "hard_requirement": True,
            "source": "runtime_gate", "adaptive": True,
        }],
        {"quality_score": 85.47},
        {"quality_score": 89.31},
        baseline_elements=[], candidate_elements=[],
        zones=zones_for("lessonforge_deck_academic"),
    )

    assert passed is True
    assert results[0]["delta"] == pytest.approx(3.84)
    assert results[0]["evidence"]["quality_gate_threshold"] == 3.0


def test_candidate_confirmation_ignores_close_candidate_that_failed_hard_objective(monkeypatch):
    import app.agent.layouts.engine as engine

    semantic = {**_slide(), "id": "slide_03"}
    baseline = compile_layout(
        "lessonforge_deck_academic", semantic,
        {"slide_id": "slide_03", "layout_type": "bullet_flow"},
    )
    slide = {**semantic, "render_mode": "absolute", "elements": baseline["elements"]}
    calls = {"count": 0}

    def constant_metrics(*_args, **_kwargs):
        return {"quality_score": 80.0}

    def only_third_candidate_passes(objectives, *_args, **_kwargs):
        calls["count"] += 1
        passed = calls["count"] == 3
        return ([{
            "metric": objectives[0]["metric"], "direction": "increase",
            "passed": passed, "hard_requirement": True,
            "baseline_value": 0.2, "candidate_value": 0.4 if passed else 0.25,
            "delta": 0.2 if passed else 0.05, "evidence": {},
            "requirement": "test hard gate",
        }], passed)

    monkeypatch.setattr(engine, "analyze_layout", constant_metrics)
    monkeypatch.setattr(engine, "_evaluate_objectives", only_third_candidate_passes)
    out = engine.compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": "slide_03", "layout_type": "bullet_flow",
        "objectives": [{
            "metric": "vertical_utilization", "direction": "increase",
            "minimum_delta": 0.12, "hard_requirement": True,
        }],
    })

    publishable = [
        candidate for candidate in out["candidate_rankings"]
        if all(
            not result.get("hard_requirement") or result.get("passed")
            for result in candidate["objective_results"]
        )
    ]
    assert len(publishable) == 1
    assert any(
        candidate["rank_score"] > publishable[0]["rank_score"]
        and not candidate["objective_results"][0]["passed"]
        for candidate in out["candidate_rankings"]
    )
    assert out["candidate_score_gap"] is None
    assert out["requires_candidate_confirmation"] is False


def _image_geometry_slide():
    return {
        "id": "slide_08",
        "page_type": "concept",
        "title": "浮力实验",
        "purpose": "",
        "body": ["观察量筒中的排水量并记录实验结果。"],
        "blocks": [],
        "render_mode": "absolute",
        "elements": [
            {
                "id": "T01", "kind": "textbox", "role": "title",
                "content_ref": "title", "text": "浮力实验",
                "x": 2.2, "y": 0.55, "w": 9.8, "h": 0.8,
                "style": {"size": 30, "bold": True, "color": "primary"},
            },
            {
                "id": "B01", "kind": "textbox", "role": "body",
                "content_ref": "body.0", "text": "观察量筒中的排水量并记录实验结果。",
                "x": 2.2, "y": 1.7, "w": 4.0, "h": 3.5,
                "style": {"size": 18, "color": "text"},
            },
            {
                "id": "I01", "kind": "image", "role": "visual",
                "x": 7.5, "y": 1.8, "w": 4.0, "h": 3.0,
                "asset_id": "asset-buoyancy", "asset_path": "/tmp/buoyancy.png",
                "visual_slot": "primary_visual",
                "crop": {"left": 0.05, "right": 0.05, "top": 0.0, "bottom": 0.0},
                "style": {"radius": 0.12, "shadow": True},
            },
        ],
    }


@pytest.mark.parametrize(
    ("direction", "requested_scale", "comparison"),
    [("increase", 1.10, "increase"), ("decrease", 0.90, "decrease")],
)
def test_image_geometry_only_scales_visual_and_keeps_text_and_asset_locked(
    direction, requested_scale, comparison,
):
    slide = _image_geometry_slide()
    baseline = slide["elements"]

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"],
        "layout_type": "left_text_right_visual",
        "image_geometry_only": True,
        "image_geometry_action": "resize",
        "image_scale": requested_scale,
        "objectives": [{
            "metric": "image_scale", "direction": direction,
            "minimum_delta": 0.05, "hard_requirement": True,
        }],
    })

    assert out["compile_status"] == "applied"
    assert out["layout_type"] == "existing_image_geometry"
    assert out["material_change"] is True
    assert out["objective_results"][0]["metric"] == "image_scale"
    assert out["objective_results"][0]["passed"] is True
    assert out["elements"][:2] == baseline[:2]

    before_image, after_image = baseline[2], out["elements"][2]
    before_locked = {key: value for key, value in before_image.items() if key not in {"x", "y", "w", "h"}}
    after_locked = {key: value for key, value in after_image.items() if key not in {"x", "y", "w", "h"}}
    assert after_locked == before_locked
    assert after_image["x"] + after_image["w"] / 2 == pytest.approx(
        before_image["x"] + before_image["w"] / 2, abs=1e-4,
    )
    assert after_image["y"] + after_image["h"] / 2 == pytest.approx(
        before_image["y"] + before_image["h"] / 2, abs=1e-4,
    )
    if comparison == "increase":
        assert after_image["w"] / before_image["w"] >= 1.05
    else:
        assert after_image["w"] / before_image["w"] <= 0.95
    assert all(attempt["layout_type"] == "existing_image_geometry" for attempt in out["compile_attempts"])


def test_image_reposition_only_translates_visual_inside_template_safe_area():
    slide = _image_geometry_slide()
    before = slide["elements"][2]
    before_locked = {
        key: value for key, value in before.items() if key not in {"x", "y"}
    }

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"],
        "image_geometry_only": True,
        "image_geometry_action": "reposition",
        # A stale upstream resize objective must be ignored for reposition.
        "image_scale": 1.20,
        "objectives": [{
            "metric": "image_scale", "direction": "increase",
            "minimum_delta": 0.10, "hard_requirement": True,
        }],
    })

    assert out["compile_status"] == "applied"
    assert out["material_change"] is True
    assert out["requested_objectives"] == []
    after = out["elements"][2]
    assert (after["x"], after["y"]) != (before["x"], before["y"])
    assert {key: value for key, value in after.items() if key not in {"x", "y"}} == before_locked
    zones = zones_for("lessonforge_deck_academic", slide["page_type"])
    assert after["x"] >= zones.body_column.x
    assert after["y"] >= zones.body_column.y
    assert after["x"] + after["w"] <= zones.body_column.right + 1e-4
    assert after["y"] + after["h"] <= zones.body_column.bottom + 1e-4
    assert all(
        attempt["style"]["image_geometry_action"] == "reposition"
        and "image_scale" not in attempt["style"]
        for attempt in out["compile_attempts"]
    )


def test_image_crop_without_focus_evidence_is_preserved_and_never_scaled():
    slide = _image_geometry_slide()

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"],
        "image_geometry_only": True,
        "image_geometry_action": "crop",
        "image_scale": 1.25,
        "objectives": [{
            "metric": "image_scale", "direction": "increase",
            "minimum_delta": 0.10, "hard_requirement": True,
        }],
    })

    assert out["compile_status"] == "preserved"
    assert out["layout_type"] == "preserve_original"
    assert out["material_change"] is False
    assert out["elements"] == slide["elements"]
    assert out["requested_objectives"] == []
    assert out["compile_attempts"] == []
    assert "未自动裁切" in out["warnings"][0]


def test_image_polish_retains_scale_behavior_without_claiming_resize_objective():
    slide = _image_geometry_slide()

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"],
        "image_geometry_only": True,
        "image_geometry_action": "polish",
        "image_scale": 1.08,
        "objectives": [{
            "metric": "image_scale", "direction": "increase",
            "minimum_delta": 0.05, "hard_requirement": True,
        }],
    })

    assert out["compile_status"] == "applied"
    assert out["elements"][2]["w"] > slide["elements"][2]["w"]
    assert out["requested_objectives"] == []
    assert out["effective_style"]["image_geometry_action"] == "polish"


def test_image_geometry_only_optimize_is_a_real_safe_visual_change():
    slide = _image_geometry_slide()
    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"],
        "image_geometry_only": True,
        "image_scale": 1.08,
        "objectives": [{
            "metric": "image_scale", "direction": "optimize",
            "minimum_delta": 0.03, "hard_requirement": True,
        }],
    })

    assert out["compile_status"] == "applied"
    assert abs(out["objective_results"][0]["delta"]) >= 0.03
    assert out["elements"][:2] == slide["elements"][:2]


def test_image_geometry_only_supports_chart_without_mutating_chart_data():
    slide = _image_geometry_slide()
    chart = slide["elements"][2]
    chart.update({
        "kind": "chart", "chart_type": "bar",
        "data": {"categories": ["A", "B"], "series": [{"name": "受力", "values": [3, 5]}]},
    })
    before_locked = {key: value for key, value in chart.items() if key not in {"x", "y", "w", "h"}}

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"], "image_geometry_only": True,
        "image_scale": 1.10,
        "objectives": [{
            "metric": "image_scale", "direction": "increase",
            "minimum_delta": 0.05, "hard_requirement": True,
        }],
    })

    after_chart = out["elements"][2]
    assert out["compile_status"] == "applied"
    assert after_chart["w"] > chart["w"]
    assert {key: value for key, value in after_chart.items() if key not in {"x", "y", "w", "h"}} == before_locked
    assert out["elements"][:2] == slide["elements"][:2]


def test_image_geometry_only_without_visual_is_preserved_no_change():
    slide = _image_geometry_slide()
    slide["elements"] = slide["elements"][:2]

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"], "image_geometry_only": True,
        "objectives": [{"metric": "image_scale", "direction": "increase"}],
    })

    assert out["compile_status"] == "preserved"
    assert out["layout_type"] == "preserve_original"
    assert out["material_change"] is False
    assert out["elements"] == slide["elements"]
    assert "没有可调整" in out["warnings"][0]


def test_image_geometry_only_unsafe_resize_is_preserved_instead_of_reflowing():
    slide = {
        "id": "slide_visual_only", "page_type": "concept", "title": "",
        "purpose": "", "body": [], "blocks": [], "render_mode": "absolute",
        "elements": [{
            "id": "I01", "kind": "image", "role": "visual",
            "x": 0.49, "y": 0.49, "w": 12.353, "h": 6.52,
            "asset_id": "asset-full", "asset_path": "/tmp/full.png",
            "visual_slot": "full_bleed_safe", "crop": {"mode": "cover"},
        }],
    }

    out = compile_layout("lessonforge_deck_academic", slide, {
        "slide_id": slide["id"], "image_geometry_only": True,
        "image_scale": 1.10,
        "objectives": [{
            "metric": "image_scale", "direction": "increase",
            "minimum_delta": 0.02, "hard_requirement": True,
        }],
    })

    assert out["compile_status"] == "preserved"
    assert out["material_change"] is False
    assert out["elements"] == slide["elements"]
    assert out["compile_attempts"]
    assert all(not attempt["geometry_safe"] for attempt in out["compile_attempts"])
    assert all(attempt["layout_type"] == "existing_image_geometry" for attempt in out["compile_attempts"])


def test_steps_cards_and_highlight_have_real_visual_effect():
    blocks = [{"kind": "steps", "steps": [
        {"title": "观察", "detail": "记录现象"},
        {"title": "归纳", "detail": "形成结论"},
        {"title": "迁移", "detail": "解决问题"},
    ]}]
    zones = zones_for("lessonforge_deck_academic", "process")
    elements = PRESETS["steps_horizontal"](
        zones, _slide(blocks=blocks, page_type="process"), {"highlight": True},
    )
    cards = [item for item in elements if item.get("role") == "step_card"]
    emphasized = next(item for item in elements if item.get("content_ref") == "blocks.0.steps.0.title")

    assert len(cards) == 3
    assert min(item["h"] for item in cards) >= zones.body_column.h * 0.80
    assert cards[0]["line"] == "primary"
    assert emphasized["style"]["bold"] is True
    assert any(item.get("role") == "highlight_panel" for item in elements)
