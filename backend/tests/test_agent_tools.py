"""工具注册表与工具行为单测：入参校验、path-traversal 防护、图表/占位图、几何 QA。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.registry import ToolContext, ensure_loaded, execute_tool, get_tool
from app.agent.agents.ppt_editor import PptEditorAgent
from app.agent.agents.layout import LayoutAgent
from app.agent.agents.media import MediaAgent
from app.agent.agents.visual_qa import VisualQaAgent
from app.agent.schemas import AgentDecision, PPTAgentError, ToolResult, VisualPlanArtifact
from app.agent.pipeline import _ensure_executable_slide_content, _ensure_executable_visual_plan
from app.renderers.presentation_builder import PresentationBuilder
from PIL import Image


def _tc(tmp_path: Path) -> ToolContext:
    ensure_loaded()
    builder = PresentationBuilder("lessonforge_deck_academic")
    return ToolContext(builder=builder, workspace_root=tmp_path)


def test_semantic_body_projection_does_not_repeat_title_from_lead_block():
    from app.agent.slide_rendering import resolve_content_ref, semantic_body_texts

    slide = {
        "page_type": "cover",
        "title": "探秘浮力成因与阿基米德原理",
        "purpose": "激发探究兴趣",
        "body": ["八年级物理", "潜水艇下潜时浮力会变大吗？"],
        "blocks": [
            {"kind": "lead", "text": "探秘浮力成因与阿基米德原理", "sub": "八年级物理"},
            {"kind": "bullets", "items": [{"text": "潜水艇下潜时浮力会变大吗？"}]},
        ],
    }

    assert semantic_body_texts(slide) == ["八年级物理", "潜水艇下潜时浮力会变大吗？"]
    assert resolve_content_ref(slide, "body") == "八年级物理\n潜水艇下潜时浮力会变大吗？"


def test_revision_content_ids_are_normalized_without_initial_deck_alignment():
    baseline = [
        {"id": "slide_01", "page_type": "cover", "title": "旧封面", "purpose": "",
         "body": ["副标题"], "blocks": [], "speaker_notes": "", "duration_seconds": 30},
        {"id": "slide_02", "page_type": "concept", "title": "旧正文", "purpose": "",
         "body": ["正文"], "blocks": [], "speaker_notes": "", "duration_seconds": 30},
    ]
    runtime = SimpleNamespace(
        selected_slide_ids=[], baseline_slides=baseline, active_intent="MODIFY",
        source_artifact=SimpleNamespace(id="artifact-v60"), content_policy="edit",
        preferred_template="lessonforge_deck_smart_ai",
    )
    decision = AgentDecision(completed=True, output={"slides": [
        {"id": "S01", "changed_fields": ["title"], "title": "新封面"},
        {"id": "S02", "changed_fields": ["title"], "title": "新正文"},
    ]})

    normalized = _ensure_executable_slide_content(runtime, decision)

    assert [item["id"] for item in normalized.output["slides"]] == ["slide_01", "slide_02"]
    assert len(normalized.output["slides"]) == 2
    assert normalized.output["slides"][0]["body"] == ["副标题"]


def test_smart_ai_absolute_layout_stays_outside_template_rail_and_visual_slot():
    slide = {
        "id": "slide_04", "page_type": "concept", "title": "从液体压强推导浮力",
        "body": ["前置基础", "核心成因", "定量规律"],
        "blocks": [{"kind": "steps", "steps": [{"title": "前置基础", "detail": "p=ρgh"}]}],
    }
    layout = LayoutAgent._layout_slide(
        slide,
        {"visualType": "image", "placement": {"x": 8.0, "y": 1.6, "w": 4.8, "h": 3.6}},
        "lessonforge_deck_smart_ai",
    )
    by_role = {element.get("role"): element for element in layout["elements"]}
    assert by_role["title"]["x"] >= 2.45
    assert by_role["body"]["x"] >= 2.45
    assert by_role["body"]["x"] + by_role["body"]["w"] <= 7.6 + 1e-6
    assert by_role["title"]["x"] + by_role["title"]["w"] <= 12.6


def test_visual_slot_keeps_text_gap_below_title_and_left_of_body():
    # 视觉槽的 y 下限钳制（≥1.7）由 visual-plan 边界（pipeline._ensure_executable_visual_plan
    # → normalize_visual_region）负责；到达 _layout_slide 的 placement 已是规范化坐标，
    # 这里验证确定性版式在规范化槽位下仍与标题/正文保持间距。
    slide = {
        "id": "slide_05", "page_type": "concept", "title": "侧面受力抵消而上下存在深度差",
        "body": ["正方体微观受力示意图", "微观视角：液体分子碰撞物体", "侧面情况：深度相同压力抵消"],
        "blocks": [],
    }
    layout = LayoutAgent._layout_slide(
        slide,
        {"visualType": "image", "placement": {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}},
        "lessonforge_deck_smart_ai",
    )
    region = layout["visual_region"]
    by_role = {element.get("role"): element for element in layout["elements"]}
    assert region["y"] >= 1.7
    assert by_role["title"]["y"] + by_role["title"]["h"] <= region["y"] - 0.3 + 1e-6
    assert by_role["body"]["x"] + by_role["body"]["w"] <= region["x"] - 0.3 + 1e-6


def test_body_items_render_as_separate_spaced_textboxes():
    """左侧正文应逐条独立成框并上下留白，才能响应"文字间隔/太单调"类诉求。"""
    from app.agent.slide_rendering import bind_content_refs, render_coverage

    slide = {
        "id": "slide_03_ki", "page_type": "scenario", "title": "浮力成因解析",
        "purpose": "", "body": ["侧面平衡：前后左右受力对称抵消", "深度压强：下表面更深，液体压强更大"],
        "blocks": [{"kind": "bullets", "items": [
            {"text": "侧面平衡：前后左右受力对称抵消"},
            {"text": "深度压强：下表面更深，液体压强更大"},
        ]}],
        "speaker_notes": "", "duration_seconds": 30,
    }
    layout = LayoutAgent._layout_slide(slide, None, "lessonforge_deck_academic")
    body_elements = [el for el in layout["elements"] if (el.get("content_ref") or "").startswith("body")]
    assert len(body_elements) == 2, "正文条目应逐条渲染为独立文本框"
    assert body_elements[0]["content_ref"] == "body.0"
    assert body_elements[1]["content_ref"] == "body.1"
    assert body_elements[1]["y"] > body_elements[0]["y"] + body_elements[0]["h"], "条目之间应留白"
    assert not any(el.get("text") == "\n".join(slide["body"]) for el in layout["elements"])

    bound, unresolved = bind_content_refs(slide, layout["elements"])
    assert unresolved == []
    coverage = render_coverage({**slide, "render_mode": "absolute", "elements": bound}, baseline=slide)
    assert coverage["missing_refs"] == []
    text_by_ref = {el.get("content_ref"): el.get("text") for el in bound if el.get("content_ref")}
    assert text_by_ref["body.0"] == "侧面平衡：前后左右受力对称抵消"
    assert text_by_ref["body.1"] == "深度压强：下表面更深，液体压强更大"


def test_visual_plan_canonicalizes_slot_and_hardens_image_prompt():
    runtime = SimpleNamespace(
        active_intent="IMAGE_UPDATE",
        content_policy="preserve",
        selected_slide_ids=["slide_05"],
        preferred_template="lessonforge_deck_smart_ai",
        source_artifact=SimpleNamespace(content_json={"slides": [{
            "id": "slide_05", "page_type": "concept", "title": "侧面受力抵消",
            "purpose": "解释压力差", "body": ["上下压力不同"], "visual_suggestion": "正方体受力示意",
        }]}),
        builder=PresentationBuilder("lessonforge_deck_smart_ai"),
        context=SimpleNamespace(user_instruction="为这个页面生成图片内容"),
        expected_visual_requests=[],
    )
    decision = _ensure_executable_visual_plan(runtime, AgentDecision(
        completed=True,
        output={"requests": [{
            "slide_id": "slide_05", "asset_name": "force", "visual_type": "ai_image",
            "prompt": "3D educational force diagram", "purpose": "解释压力差",
            "placement": {"x": 7.4, "y": 1.2, "w": 5.2, "h": 4.8},
        }]},
    ))
    request = VisualPlanArtifact.model_validate(decision.output).requests[0]
    assert request.placement.y == 1.7
    assert request.placement.x == 7.4
    assert "不要在图片内渲染任何中文" in request.prompt


@pytest.mark.asyncio
async def test_locked_smart_ai_layout_under_template_rail_is_blocked(tmp_path):
    source = {
        "id": "slide_04", "page_type": "concept", "title": "从液体压强推导浮力",
        "purpose": "", "body": ["p=ρgh", "F浮=G排"], "blocks": [],
        "speaker_notes": "", "duration_seconds": 60, "render_mode": "absolute",
        "elements": [
            {"id": "E01", "kind": "textbox", "role": "title", "content_ref": "title",
             "text": "从液体压强推导浮力", "x": 0.65, "y": 0.55, "w": 11.9, "h": 0.8},
            {"id": "E02", "kind": "textbox", "role": "body", "content_ref": "body",
             "text": "p=ρgh\nF浮=G排", "x": 0.65, "y": 1.7, "w": 6.4, "h": 2.0},
        ],
    }
    builder = PresentationBuilder("lessonforge_deck_smart_ai").from_ppt_content({
        "theme": "lessonforge_deck_smart_ai", "slides": [source],
    })
    runtime = SimpleNamespace(
        active_intent="LOCAL_REGENERATE", content_policy="preserve",
        selected_slide_ids=["slide_04"], render_coverage={},
        source_artifact=SimpleNamespace(content_json={"slides": [source]}),
    )

    qa = await execute_tool("run_qa", ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime), {})

    assert any(item["rule_id"] == "visual.overlaps_template" for item in qa.output["issues"])


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(tmp_path):
    result = await execute_tool("no_such_tool", _tc(tmp_path), {})
    assert result.ok is False
    assert "未知工具" in result.error


@pytest.mark.asyncio
async def test_editing_tool_creates_element(tmp_path):
    tc = _tc(tmp_path)
    result = await execute_tool("create_slide", tc, {"page_type": "cover", "title": "标题"})
    assert result.ok and result.output["slide_id"]
    slide_id = result.output["slide_id"]
    result = await execute_tool("add_textbox", tc, {"slide_id": slide_id, "text": "内容", "x": 0.7, "y": 1.8, "width": 5, "height": 1})
    assert result.ok and result.output["element_id"]


@pytest.mark.asyncio
async def test_add_image_keeps_browser_asset_metadata(tmp_path):
    tc = _tc(tmp_path)
    slide_id = tc.builder.create_slide("cover", "标题")
    image_path = tmp_path / "image.png"
    Image.new("RGB", (20, 20), "navy").save(image_path)
    result = await execute_tool("add_image", tc, {
        "slide_id": slide_id,
        "file_path": "image.png",
        "x": 6,
        "y": 1,
        "width": 5,
        "height": 4,
        "asset_id": "browser-asset-id",
        "provider": "mock_fallback",
        "degraded": True,
    })
    assert result.ok
    element = tc.builder.get_slide(slide_id)["elements"][-1]
    assert element["kind"] == "image"
    assert element["asset_id"] == "browser-asset-id"
    assert element["asset_path"] == str(image_path)
    assert element["degraded"] is True
    assert tc.builder.get_slide(slide_id)["render_mode"] == "hybrid"


@pytest.mark.asyncio
async def test_ppt_editor_uses_visual_asset_data_path_not_pipeline_json_path(tmp_path):
    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "slide_content":
                return {"data": {"slides": [{"id": "slide_01", "title": "首页"}]}}
            return {"data": {"slides": [{
                "slide_id": "slide_01",
                "visual_region": {"x": 6, "y": 1, "w": 5, "h": 4},
            }]}}

        async def list_all(self):
            return [{
                "artifact_type": "visual_asset",
                "file_path": "assets/visual_asset_slide_01_v1.json",
                "data": {
                    "slide_id": "slide_01",
                    "file_path": "assets/generated-image.png",
                    "asset_id": "browser-asset-id",
                    "provider": "image-provider",
                    "degraded": False,
                },
            }]

    tc = ToolContext(
        artifacts=Artifacts(),
        builder=PresentationBuilder(),
        runtime=SimpleNamespace(mutation_applied=False, selected_slide_ids=["slide_01"]),
        ctx=SimpleNamespace(source_artifact=None),
    )
    decision = await PptEditorAgent().decide(tc)
    image_call = next(call for call in decision.tool_calls if call.tool_name == "add_image")
    assert image_call.input["file_path"] == "assets/generated-image.png"
    assert image_call.input["asset_id"] == "browser-asset-id"


@pytest.mark.asyncio
async def test_ppt_editor_uses_llm_visual_plan_placement_without_layout(tmp_path):
    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "slide_content":
                return {"data": {"slides": [{"id": "slide_01", "title": "首页"}]}}
            if artifact_type == "visual_plan":
                return {"data": {"slides_visual_plan": [{
                    "slide_id": "slide_01",
                    "visual_items": [{"image_id": "hero", "placement": {"x": 5.6, "y": 1.1, "w": 6.2, "h": 3.4}}],
                }]}}
            return None

        async def list_all(self):
            return [{"artifact_type": "visual_asset", "data": {
                "slide_id": "slide_01", "file_path": "assets/hero.png", "asset_id": "hero-id",
            }}]

    tc = ToolContext(
        artifacts=Artifacts(), builder=PresentationBuilder(),
        runtime=SimpleNamespace(mutation_applied=False, selected_slide_ids=["slide_01"]),
        ctx=SimpleNamespace(source_artifact=SimpleNamespace(content_json={"slides": []})),
    )
    decision = await PptEditorAgent().decide(tc)
    image_call = next(call for call in decision.tool_calls if call.tool_name == "add_image")
    assert image_call.input["slide_id"] == "slide_01"
    assert image_call.input["x"] == 5.6
    assert image_call.input["width"] == 6.2


@pytest.mark.asyncio
async def test_image_update_prefers_visual_plan_placement_and_stays_above_caption():
    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "slide_content":
                return {"data": {"slides": [{"id": "slide_01", "title": "首页"}]}}
            if artifact_type == "slide_layout":
                return {"data": {"slides": [{"slide_id": "slide_01", "visual_region": {"x": 7.2, "y": 1.1, "w": 5.5, "h": 5.4}}]}}
            if artifact_type == "visual_plan":
                return {"data": {"slides": [{"id": "slide_01"}], "visual_plans": [{
                    "slide_id": "slide_01", "placement": {"x": 5.65, "y": 1.05, "w": 6.65, "h": 3.45},
                }]}}
            return None

        async def list_all(self):
            return [{"artifact_type": "visual_asset", "data": {
                "slide_id": "slide_01", "file_path": "assets/hero.png", "asset_id": "hero-id",
            }}]

    builder = PresentationBuilder()
    created = builder.create_slide("cover", "首页")
    builder.get_slide(created)["id"] = "slide_01"
    builder.add_textbox("slide_01", "图片说明", 5.8, 4.65, 6.2, 0.45, role="visual_caption")
    tc = ToolContext(
        artifacts=Artifacts(), builder=builder,
        runtime=SimpleNamespace(mutation_applied=False, selected_slide_ids=["slide_01"], active_intent="IMAGE_UPDATE"),
        ctx=SimpleNamespace(source_artifact=None),
    )
    decision = await PptEditorAgent().decide(tc)
    image_call = next(call for call in decision.tool_calls if call.tool_name == "add_image")
    assert image_call.input["x"] == 5.65
    assert image_call.input["height"] == 3.45
    assert image_call.input["y"] + image_call.input["height"] < 4.65


@pytest.mark.asyncio
async def test_media_agent_executes_slides_visual_plan_schema():
    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "visual_plan":
                return {"data": {"slides_visual_plan": [{
                    "slide_id": "slide_01",
                    "visual_items": [{"image_id": "submarine", "prompt": "潜水艇水下受力矢量图"}],
                }]}}
            return {"data": {"slides": [{"id": "slide_01", "title": "浮力"}]}}

    tc = ToolContext(
        artifacts=Artifacts(), runtime=SimpleNamespace(selected_slide_ids=["slide_01"]),
        ctx=SimpleNamespace(template={"palette": {}}, has_tool_result=lambda _: False),
    )
    decision = await MediaAgent().decide(tc)
    assert len(decision.tool_calls) == 1
    assert decision.tool_calls[0].tool_name == "generate_image"
    assert decision.tool_calls[0].input["prompt"] == "潜水艇水下受力矢量图"
    assert decision.tool_calls[0].input["asset_name"] == "submarine"


@pytest.mark.asyncio
async def test_media_agent_prefers_explicit_visual_plan_over_content_slides():
    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "visual_plan":
                return {"data": {
                    "slides": [{"id": "slide_01", "title": "内容页不应变成图片提示词"}],
                    "visual_plans": [{
                        "slide_id": "slide_01", "image_id": "physics_hero",
                        "prompt": "3D submarine buoyancy force diagram", "placement": {"x": 5.6, "y": 1.0, "w": 6.5, "h": 3.4},
                    }],
                }}
            return {"data": {"slides": [{"id": "slide_01", "title": "浮力"}]}}

    tc = ToolContext(
        artifacts=Artifacts(), runtime=SimpleNamespace(selected_slide_ids=["slide_01"]),
        ctx=SimpleNamespace(template={"palette": {}}, has_tool_result=lambda _: False),
    )
    decision = await MediaAgent().decide(tc)
    assert len(decision.tool_calls) == 1
    assert decision.tool_calls[0].input["prompt"] == "3D submarine buoyancy force diagram"
    assert decision.tool_calls[0].input["asset_name"] == "physics_hero"


def test_visual_plan_compiles_full_slide_output_to_canonical_request():
    runtime = SimpleNamespace(
        active_intent="IMAGE_UPDATE",
        selected_slide_ids=["slide_01"],
        source_artifact=SimpleNamespace(content_json={"slides": [{
            "id": "slide_01", "title": "浮力的本质", "purpose": "建立受力模型",
            "visual_suggestion": "潜水艇在水下的浮力与重力矢量",
        }]}),
        builder=PresentationBuilder(),
        context=SimpleNamespace(user_instruction="为第一页生成潜水艇浮力图片"),
        expected_visual_requests=[],
    )
    decision = _ensure_executable_visual_plan(runtime, AgentDecision(
        completed=True,
        output={"slides": [{"id": "slide_01", "title": "模型错误返回的整页内容"}]},
    ))
    parsed = VisualPlanArtifact.model_validate(decision.output)
    assert [item.slide_id for item in parsed.requests] == ["slide_01"]
    assert "潜水艇" in parsed.requests[0].prompt
    assert parsed.requests[0].placement.w > 0


def test_restore_policy_recovers_source_when_content_agent_completes_without_slides():
    source_slide = {
        "id": "slide_03_km", "page_type": "concept", "title": "浮力原理",
        "purpose": "恢复已有内容", "body": ["文字描述仍保存在语义层"],
        "blocks": [], "speaker_notes": "备注", "duration_seconds": 60,
    }
    runtime = SimpleNamespace(
        content_policy="restore", selected_slide_ids=["slide_03_km"],
        source_artifact=SimpleNamespace(content_json={"slides": [source_slide]}),
    )
    decision = _ensure_executable_slide_content(runtime, AgentDecision(completed=True, output={}, summary="完成"))
    assert decision.output["slides"] == [source_slide]


def test_edit_policy_returns_stable_error_for_empty_content_agent_output():
    runtime = SimpleNamespace(
        content_policy="edit", selected_slide_ids=["slide_03_km"],
        source_artifact=SimpleNamespace(content_json={"slides": []}),
    )
    with pytest.raises(PPTAgentError) as caught:
        _ensure_executable_slide_content(runtime, AgentDecision(completed=True, output={}))
    assert caught.value.code == "slide_content_invalid"


def test_edit_policy_sanitizes_dense_block_content_before_pipeline():
    """编辑类 slide_content 必须确定性收敛 blocks 密度（27字→≤25字、去装饰前缀），
    否则 27>25 的边缘超标会让 QA 门禁在修复轮内无法收敛。"""
    source_slide = {
        "id": "slide_03_ki", "page_type": "scenario", "title": "浮力成因",
        "purpose": "", "body": ["压力差产生浮力"], "blocks": [],
        "speaker_notes": "", "duration_seconds": 30,
    }
    runtime = SimpleNamespace(
        content_policy="edit", selected_slide_ids=["slide_03_ki"],
        source_artifact=SimpleNamespace(content_json={"slides": [source_slide]}),
    )
    decision = _ensure_executable_slide_content(runtime, AgentDecision(completed=True, output={
        "slides": [{
            "id": "slide_03_ki", "changed_fields": ["title", "body", "blocks"],
            "title": "浮力成因", "body": ["压力差产生浮力"],
            "blocks": [{"kind": "bullets", "items": [
                {"text": "🔹 本质公式：上下表面压力差形成浮力 F浮=F下-F上"},
            ]}],
        }],
    }))
    block = decision.output["slides"][0]["blocks"][0]
    item = block["items"][0]
    assert len(item["text"]) <= 25
    assert not item["text"].startswith("🔹")


@pytest.mark.asyncio
async def test_media_ignores_aggregate_visual_asset_and_requires_leaf():
    class Artifacts:
        async def latest(self, artifact_type):
            if artifact_type == "visual_plan":
                return {"data": {"requests": [{
                    "slide_id": "slide_01", "asset_name": "hero", "visual_type": "ai_image",
                    "prompt": "潜水艇受力示意", "purpose": "教学", "aspect_ratio": "4:3",
                    "placement": {"x": 6, "y": 1, "w": 5, "h": 4},
                }]}}
            return {"data": {"slides": [{"id": "slide_01", "title": "浮力"}]}}

        async def list_all(self):
            return [{
                "artifact_type": "visual_asset", "name": "default", "producer_tool": "",
                "data": {"assets": [{"slide_id": None, "file_path": "", "asset_id": ""}]},
            }]

    ctx = SimpleNamespace(
        template={"palette": {}}, has_tool_result=lambda name: name == "generate_image",
        tool_results=[],
    )
    runtime = SimpleNamespace(
        selected_slide_ids=["slide_01"], active_intent="IMAGE_UPDATE",
        expected_visual_requests=[], generated_asset_ids=[],
    )
    with pytest.raises(PPTAgentError) as caught:
        await MediaAgent().decide(ToolContext(artifacts=Artifacts(), runtime=runtime, ctx=ctx))
    assert caught.value.code == "image_generation_failed"


@pytest.mark.asyncio
async def test_workspace_read_blocks_path_traversal(tmp_path):
    (tmp_path / "safe.txt").write_text("ok", encoding="utf-8")
    tc = _tc(tmp_path)
    result = await execute_tool("read_workspace_file", tc, {"path": "safe.txt"})
    assert result.ok and result.output["content"] == "ok"
    result = await execute_tool("read_workspace_file", tc, {"path": "../../../../etc/passwd"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_generate_image_placeholder_writes_png(tmp_path):
    tc = _tc(tmp_path)
    result = await execute_tool("generate_image", tc, {
        "prompt": "主体居右留白左侧", "slide_id": "S04", "asset_name": "v", "size": "640x480",
    })
    assert result.ok
    path = Path(tmp_path) / result.output["file_path"]
    assert path.is_file()
    with Image.open(path) as image:
        assert image.size == (640, 480)


@pytest.mark.asyncio
async def test_generate_chart_png_creates_file(tmp_path):
    tc = _tc(tmp_path)
    result = await execute_tool("generate_chart_png", tc, {
        "chart_type": "bar",
        "data": {"categories": ["目标", "现状"], "series": [{"name": "对比", "values": [80, 45]}]},
        "width": 480, "height": 320,
    })
    assert result.ok
    path = Path(tmp_path) / result.output["file_path"]
    assert path.is_file()
    with Image.open(path) as image:
        assert image.size == (480, 320)


@pytest.mark.asyncio
async def test_run_qa_flags_out_of_bounds_element(tmp_path):
    tc = _tc(tmp_path)
    builder = tc.builder
    slide_id = builder.create_slide("concept", "标题", "bullet")
    builder.add_textbox(slide_id, "正常文本", 0.7, 1.8, 5.0, 1.0, style={"size": 18, "color": "text"})
    builder.add_shape(slide_id, "rect", 12.0, 7.0, 2.0, 2.0, fill="primary")  # 越界
    result = await execute_tool("run_qa", tc, {})
    assert result.ok
    issues = result.output["issues"]
    assert any(item["rule_id"] == "geometry.out_of_bounds" for item in issues)


@pytest.mark.asyncio
async def test_absolute_layout_without_source_body_is_blocked(tmp_path):
    source = {
        "id": "slide_04", "page_type": "concept", "title": "浮力推导",
        "purpose": "", "body": ["压力差产生浮力"], "blocks": [],
        "visual_suggestion": "", "speaker_notes": "", "duration_seconds": 60,
    }
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic",
        "slides": [{**source, "render_mode": "absolute", "elements": [{
            "id": "E01", "kind": "textbox", "role": "title", "content_ref": "title",
            "text": "浮力推导", "x": 1, "y": 1, "w": 5, "h": 1,
        }]}],
    })
    runtime = SimpleNamespace(
        active_intent="LOCAL_REGENERATE", content_policy="preserve",
        selected_slide_ids=["slide_04"], render_coverage={},
    )
    tc = ToolContext(
        builder=builder, runtime=runtime,
        ctx=SimpleNamespace(source_artifact=SimpleNamespace(content_json={"slides": [source]})),
    )
    result = await execute_tool("run_qa", tc, {})
    assert any(item["rule_id"] == "layout.incomplete_absolute" for item in result.output["issues"])


@pytest.mark.asyncio
async def test_edit_qa_uses_new_semantic_copy_as_render_coverage_baseline(tmp_path):
    source = {
        "id": "slide_01", "page_type": "cover", "title": "旧标题",
        "purpose": "旧目标", "body": ["旧副标题"], "blocks": [],
        "visual_suggestion": "", "speaker_notes": "", "duration_seconds": 60,
    }
    edited = {
        **source,
        "title": "润色后的标题",
        "purpose": "润色后的目标",
        "body": ["润色后的副标题"],
        "render_mode": "absolute",
        "elements": [
            {"id": "E01", "kind": "textbox", "role": "title", "text": "润色后的标题", "x": 1, "y": 1, "w": 5, "h": 1},
            {"id": "E02", "kind": "textbox", "role": "body", "text": "润色后的副标题", "x": 1, "y": 2, "w": 5, "h": 1},
            {"id": "E03", "kind": "textbox", "role": "purpose", "text": "润色后的目标", "x": 1, "y": 3, "w": 5, "h": 1},
        ],
    }
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic", "slides": [edited],
    })
    runtime = SimpleNamespace(
        active_intent="LOCAL_REGENERATE", content_policy="edit",
        selected_slide_ids=["slide_01"], render_coverage={},
    )
    tc = ToolContext(
        builder=builder, runtime=runtime,
        ctx=SimpleNamespace(source_artifact=SimpleNamespace(content_json={"slides": [source]})),
    )

    result = await execute_tool("run_qa", tc, {})

    assert not any(item["rule_id"] == "layout.incomplete_absolute" for item in result.output["issues"])


@pytest.mark.asyncio
async def test_image_update_qa_requires_image_only_on_selected_slide(tmp_path):
    tc = _tc(tmp_path)
    tc.runtime = SimpleNamespace(active_intent="IMAGE_UPDATE", selected_slide_ids=["slide_01"])
    slide_01 = tc.builder.create_slide("cover", "首页")
    tc.builder.get_slide(slide_01)["id"] = "slide_01"
    slide_02 = tc.builder.create_slide("concept", "旧页")
    tc.builder.get_slide(slide_02)["id"] = "slide_02"
    result = await execute_tool("run_qa", tc, {})
    assert any(item["rule_id"] == "image.missing" and item["slide_id"] == "slide_01" for item in result.output["issues"])
    assert not any(item.get("slide_id") == "slide_02" for item in result.output["issues"])


@pytest.mark.asyncio
async def test_image_update_qa_without_explicit_scope_checks_only_planned_slide(tmp_path):
    class Artifacts:
        async def list_all(self):
            return [{"artifact_type": "visual_plan", "data": {
                "slides_visual_plan": [{"slide_id": "slide_01", "visual_items": [{"image_id": "hero"}]}],
            }}]

        async def create(self, *_args, **_kwargs):
            return {"id": "qa-1"}

    tc = _tc(tmp_path)
    tc.artifacts = Artifacts()
    tc.runtime = SimpleNamespace(active_intent="IMAGE_UPDATE", selected_slide_ids=[])
    slide_01 = tc.builder.create_slide("cover", "首页")
    tc.builder.get_slide(slide_01)["id"] = "slide_01"
    slide_02 = tc.builder.create_slide("concept", "第二页")
    tc.builder.get_slide(slide_02)["id"] = "slide_02"
    result = await execute_tool("run_qa", tc, {})
    missing = [item for item in result.output["issues"] if item["rule_id"] == "image.missing"]
    assert [item["slide_id"] for item in missing] == ["slide_01"]


@pytest.mark.asyncio
async def test_image_update_qa_accepts_relative_production_workspace(tmp_path, monkeypatch):
    """回归：workspace_root 为相对路径时，QA 不得把图片路径重复拼接。"""
    monkeypatch.chdir(tmp_path)
    workspace = Path("storage/generated/course/ppt_pipeline/run")
    image_path = workspace / "assets/submarine.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (120, 90), "navy").save(image_path)

    builder = PresentationBuilder()
    created = builder.create_slide("cover", "首页")
    builder.get_slide(created)["id"] = "slide_01"
    runtime = SimpleNamespace(
        active_intent="IMAGE_UPDATE",
        selected_slide_ids=["slide_01"],
        generated_asset_ids=["asset-current-run"],
        expected_visual_requests=[{"slide_id": "slide_01"}],
        mutation_evidence=[],
        affected_slide_ids=[],
        mutation_applied=False,
        draft_artifact_id=None,
    )
    tc = ToolContext(builder=builder, workspace_root=workspace, runtime=runtime)

    inserted = await execute_tool("add_image", tc, {
        "slide_id": "slide_01",
        "file_path": "assets/submarine.png",
        "x": 7.2,
        "y": 1.1,
        "width": 5.0,
        "height": 4.0,
        "asset_id": "asset-current-run",
        "provider": "openai_compatible:gemini-3.1-flash-image",
        "degraded": False,
    })

    assert inserted.ok
    element = builder.get_slide("slide_01")["elements"][-1]
    assert Path(element["asset_path"]).is_absolute()
    assert Path(element["asset_path"]).is_file()
    assert runtime.mutation_applied is True
    assert builder.get_slide("slide_01")["render_mode"] == "hybrid"

    qa = await execute_tool("run_qa", tc, {})
    assert qa.ok
    assert not any(item["rule_id"] == "image.missing" for item in qa.output["issues"])


@pytest.mark.asyncio
async def test_image_update_qa_blocks_content_overlap_and_wrong_visual_slot(tmp_path):
    image_path = tmp_path / "overlap.png"
    Image.new("RGB", (640, 480), "navy").save(image_path)
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic",
        "slides": [{
            "id": "slide_04", "page_type": "concept", "title": "浮力推导",
            "purpose": "", "body": ["压力差产生浮力"], "blocks": [],
            "speaker_notes": "", "duration_seconds": 60,
            "render_mode": "absolute", "elements": [
                {"id": "E01", "kind": "textbox", "role": "title", "content_ref": "title",
                 "text": "浮力推导", "x": 0.8, "y": 0.6, "w": 6.0, "h": 0.8},
                {"id": "E02", "kind": "textbox", "role": "body", "content_ref": "body",
                 "text": "压力差产生浮力", "x": 0.8, "y": 1.7, "w": 6.2, "h": 3.8},
                {"id": "E03", "kind": "image", "role": "visual", "visual_slot": "wrong_slot",
                 "x": 5.2, "y": 2.0, "w": 4.5, "h": 3.0, "asset_path": str(image_path),
                 "asset_id": "asset-current-run", "degraded": False},
            ],
        }],
    })
    runtime = SimpleNamespace(
        active_intent="IMAGE_UPDATE", content_policy="preserve",
        selected_slide_ids=["slide_04"], generated_asset_ids=["asset-current-run"],
        expected_visual_requests=[{"slide_id": "slide_04", "visual_slot": "primary_visual"}],
        render_coverage={},
    )

    qa = await execute_tool("run_qa", ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime), {})

    rules = {item["rule_id"] for item in qa.output["issues"]}
    assert "visual.overlaps_content" in rules
    assert "visual.slot_missing" in rules


@pytest.mark.asyncio
async def test_template_switch_layout_preserves_existing_image(tmp_path):
    image_path = tmp_path / "existing.png"
    Image.new("RGB", (320, 180), "teal").save(image_path)
    builder = PresentationBuilder("lessonforge_deck_academic").from_ppt_content({
        "theme": "lessonforge_deck_academic",
        "slides": [{
            "id": "slide_01", "page_type": "cover", "title": "浮力",
            "elements": [{
                "id": "E09", "kind": "image", "x": 7.8, "y": 1.3, "w": 4.2, "h": 3.4,
                "z": 9, "style": {}, "role": "visual", "asset_path": str(image_path),
                "asset_id": "existing-asset", "provider": "image-provider", "degraded": False,
            }],
        }],
    })
    builder.apply_template("lessonforge_deck_ai_future")
    runtime = SimpleNamespace(
        active_intent="TEMPLATE_SWITCH", selected_slide_ids=[], mutation_evidence=[],
        affected_slide_ids=[], draft_artifact_id=None, mutation_applied=True,
    )
    tc = ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime)

    result = await execute_tool("layout_slide_batch", tc, {"layouts": [{
        "slide_id": "slide_01", "visual_region": {"x": 7.0, "y": 1.1, "w": 5.2, "h": 3.8},
        "elements": [
            {"kind": "textbox", "role": "title", "text": "浮力", "x": 0.8, "y": 1.2, "w": 5, "h": 1,
             "style": {"size": 34, "color": "primary"}},
            {"kind": "shape", "role": "visual_panel", "x": 6.8, "y": 0.9, "w": 5.6, "h": 4.5,
             "shape_type": "rounded", "fill": "surface", "line": "secondary"},
            {"kind": "textbox", "role": "visual_caption", "text": "潜水艇受力图", "x": 7.1, "y": 4.7, "w": 5, "h": 0.4,
             "style": {"size": 14, "color": "primary"}},
        ],
    }]})

    assert result.ok
    assert result.output["preserved_visual_resources"] == 1
    images = [item for item in builder.get_slide("slide_01")["elements"] if item.get("kind") == "image"]
    assert len(images) == 1
    assert images[0]["asset_id"] == "existing-asset"
    assert images[0]["asset_path"] == str(image_path)
    assert 7.0 <= images[0]["x"] < 12.2
    assert images[0]["y"] + images[0]["h"] < 4.7
    element_ids = [item["id"] for item in builder.get_slide("slide_01")["elements"]]
    assert len(element_ids) == len(set(element_ids))


@pytest.mark.asyncio
async def test_restore_layout_keeps_existing_image_and_semantic_content(tmp_path):
    image_path = tmp_path / "existing.png"
    Image.new("RGB", (320, 180), "teal").save(image_path)
    source = {
        "id": "slide_03_km", "page_type": "concept", "title": "浮力原理",
        "purpose": "恢复布局", "body": ["原文字描述"], "blocks": [],
        "visual_suggestion": "潜水艇受力图", "speaker_notes": "原备注", "duration_seconds": 60,
        "elements": [{
            "id": "E34", "kind": "image", "x": 7.4, "y": 1.4, "w": 5, "h": 4,
            "asset_path": str(image_path), "asset_id": "asset-v34", "role": "visual",
            "visual_slot": "primary_visual", "style": {},
        }],
    }
    builder = PresentationBuilder().from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]})
    runtime = SimpleNamespace(
        active_intent="LOCAL_REGENERATE", content_policy="restore",
        selected_slide_ids=["slide_03_km"], mutation_evidence=[], affected_slide_ids=[],
        draft_artifact_id=None, mutation_applied=False,
    )
    tc = ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime)
    result = await execute_tool("layout_slide_batch", tc, {"layouts": [{
        "slide_id": "slide_03_km", "render_mode": "absolute",
        "visual_region": {"x": 7.2, "y": 1.3, "w": 5.0, "h": 3.8},
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "模型伪造标题", "x": 1, "y": 0.7, "w": 5.8, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body", "text": "模型漏掉原文", "x": 1, "y": 1.8, "w": 5.8, "h": 3.8},
        ],
    }]})
    assert result.ok
    restored = builder.get_slide("slide_03_km")
    assert restored["title"] == "浮力原理"
    assert restored["body"] == ["原文字描述"]
    assert restored["speaker_notes"] == "原备注"
    text_by_ref = {item.get("content_ref"): item.get("text") for item in restored["elements"] if item.get("content_ref")}
    assert text_by_ref == {"title": "浮力原理", "body": "原文字描述"}
    images = [item for item in restored["elements"] if item.get("kind") == "image"]
    assert [item.get("asset_id") for item in images] == ["asset-v34"]


@pytest.mark.asyncio
async def test_modify_layout_keeps_existing_image_for_text_edit(tmp_path):
    """文字润色（MODIFY + edit）重排布局时不得丢掉页面上已有的图片。"""
    image_path = tmp_path / "existing.png"
    Image.new("RGB", (320, 180), "teal").save(image_path)
    source = {
        "id": "slide_01", "page_type": "concept", "title": "浮力原理",
        "purpose": "", "body": ["原文字描述"], "blocks": [],
        "visual_suggestion": "潜水艇受力图", "speaker_notes": "原备注", "duration_seconds": 60,
        "elements": [{
            "id": "E01", "kind": "image", "x": 7.4, "y": 1.4, "w": 5, "h": 4,
            "asset_path": str(image_path), "asset_id": "asset-v1", "role": "visual",
            "visual_slot": "primary_visual", "style": {},
        }],
    }
    builder = PresentationBuilder().from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]})
    runtime = SimpleNamespace(
        active_intent="MODIFY", content_policy="edit",
        selected_slide_ids=["slide_01"], mutation_evidence=[], affected_slide_ids=[],
        draft_artifact_id=None, mutation_applied=False,
    )
    tc = ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime)
    write = await execute_tool("write_slide_batch", tc, {"slides": [{
        "id": "slide_01", "changed_fields": ["title", "body"],
        "title": "润色后的标题", "body": ["润色后的正文"],
    }]})
    assert write.ok
    result = await execute_tool("layout_slide_batch", tc, {"layouts": [{
        "slide_id": "slide_01", "render_mode": "absolute",
        "visual_region": {"x": 7.2, "y": 1.3, "w": 5.0, "h": 3.8},
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "模型伪造标题", "x": 1, "y": 0.7, "w": 5.8, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body", "text": "模型漏掉正文", "x": 1, "y": 1.8, "w": 5.8, "h": 3.8},
        ],
    }]})
    assert result.ok
    assert result.output["preserved_visual_resources"] == 1
    layout_slide = builder.get_slide("slide_01")
    images = [item for item in layout_slide["elements"] if item.get("kind") == "image"]
    assert [item.get("asset_id") for item in images] == ["asset-v1"]
    assert images[0]["asset_path"] == str(image_path)
    assert images[0]["x"] >= 7.0
    text_by_ref = {item.get("content_ref"): item.get("text") for item in layout_slide["elements"] if item.get("content_ref")}
    assert text_by_ref == {"title": "润色后的标题", "body": "润色后的正文"}


@pytest.mark.asyncio
async def test_layout_rejects_unknown_content_ref_before_mutating_slide(tmp_path):
    source = {
        "id": "slide_04", "page_type": "concept", "title": "原标题", "purpose": "",
        "body": ["原正文"], "blocks": [], "visual_suggestion": "", "speaker_notes": "", "duration_seconds": 60,
    }
    builder = PresentationBuilder().from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]})
    before = list(builder.get_slide("slide_04")["elements"])
    runtime = SimpleNamespace(content_policy="preserve", source_artifact=SimpleNamespace(content_json={"slides": [source]}), selected_slide_ids=["slide_04"])
    result = await execute_tool("layout_slide_batch", ToolContext(builder=builder, runtime=runtime), {"layouts": [{
        "slide_id": "slide_04", "render_mode": "absolute", "elements": [{
            "kind": "textbox", "content_ref": "blocks.99.text", "text": "伪造", "x": 1, "y": 1, "w": 5, "h": 1,
        }],
    }]})
    assert result.ok is False
    assert result.error_code == "layout_incomplete"
    assert builder.get_slide("slide_04")["elements"] == before


@pytest.mark.asyncio
async def test_edit_layout_rejects_missing_body_before_mutating_slide(tmp_path):
    source = {
        "id": "slide_01", "page_type": "concept", "title": "浮力原理",
        "purpose": "", "body": ["第一条正文", "第二条正文"], "blocks": [],
        "visual_suggestion": "", "speaker_notes": "", "duration_seconds": 30,
        "render_mode": "absolute", "elements": [{
            "id": "E01", "kind": "textbox", "role": "body", "content_ref": "body",
            "text": "第一条正文\n第二条正文", "x": 2.2, "y": 1.7, "w": 8, "h": 2,
        }],
    }
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic", "slides": [source],
    })
    original_elements = [dict(item) for item in builder.get_slide("slide_01")["elements"]]
    runtime = SimpleNamespace(
        active_intent="MODIFY", content_policy="edit", selected_slide_ids=["slide_01"],
    )
    tc = ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime)

    result = await execute_tool("layout_slide_batch", tc, {"layouts": [{
        "slide_id": "slide_01", "render_mode": "absolute", "elements": [{
            "kind": "textbox", "role": "title", "content_ref": "title",
            "text": "浮力原理", "x": 2.2, "y": 0.55, "w": 8, "h": 0.8,
        }],
    }]})

    assert not result.ok
    assert result.error_code == "layout_incomplete"
    assert result.output["missing_refs"] == ["body.0", "body.1"]
    assert result.output["missing_text"][0]["text"] == "第一条正文"
    assert builder.get_slide("slide_01")["elements"] == original_elements


@pytest.mark.asyncio
async def test_layout_batch_stages_pages_and_partially_applies_safe_candidates(tmp_path):
    source_1 = {
        "id": "slide_01", "page_type": "concept", "title": "第一页",
        "purpose": "", "body": ["可安全排版的正文"], "blocks": [],
        "speaker_notes": "", "duration_seconds": 30, "elements": [],
    }
    source_2 = {
        "id": "slide_02", "page_type": "concept", "title": "第二页",
        "purpose": "", "body": ["必须保留的正文"], "blocks": [],
        "speaker_notes": "", "duration_seconds": 30,
        "render_mode": "absolute", "elements": [{
            "id": "E99", "kind": "textbox", "role": "body", "content_ref": "body",
            "text": "必须保留的正文", "x": 2.2, "y": 1.7, "w": 8.5, "h": 1.0,
        }],
    }
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic", "slides": [source_1, source_2],
    })
    before_2 = deepcopy(builder.get_slide("slide_02"))
    runtime = SimpleNamespace(
        active_intent="LAYOUT_ONLY", content_policy="preserve",
        selected_slide_ids=["slide_01", "slide_02"], baseline_slides=[source_1, source_2],
        affected_slide_ids=[], mutation_evidence=[], mutation_applied=False,
        layout_compile_results=[], result_status="applied", draft_artifact_id=None,
    )

    result = await execute_tool("layout_slide_batch", ToolContext(
        builder=builder, workspace_root=tmp_path, runtime=runtime,
    ), {"layouts": [
        {"slide_id": "slide_01", "render_mode": "absolute", "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "第一页",
             "x": 2.2, "y": 0.6, "w": 9.0, "h": 0.8, "style": {"size": 28}},
            {"kind": "textbox", "role": "body", "content_ref": "body.0", "text": "可安全排版的正文",
             "x": 2.2, "y": 1.7, "w": 9.0, "h": 3.0, "style": {"size": 20}},
        ]},
        {"slide_id": "slide_02", "render_mode": "absolute", "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "第二页",
             "x": 2.2, "y": 0.6, "w": 9.0, "h": 0.8, "style": {"size": 28}},
        ]},
    ]})

    assert result.ok
    assert result.output["slide_ids"] == ["slide_01"]
    assert result.output["preserved_slide_ids"] == ["slide_02"]
    assert builder.get_slide("slide_01")["elements"]
    assert builder.get_slide("slide_02") == before_2
    assert runtime.result_status == "partial"
    assert runtime.mutation_applied is True
    assert next(
        item for item in runtime.layout_compile_results if item["slide_id"] == "slide_02"
    )["status"] == "preserved"


@pytest.mark.asyncio
async def test_slide_content_patch_does_not_erase_unspecified_fields(tmp_path):
    source = {
        "id": "slide_01", "page_type": "concept", "title": "原标题", "purpose": "教学目的",
        "body": ["原正文"], "blocks": [{"kind": "note", "text": "结构化内容"}],
        "visual_suggestion": "原视觉说明", "speaker_notes": "原备注", "duration_seconds": 60,
    }
    builder = PresentationBuilder().from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]})
    runtime = SimpleNamespace(
        active_intent="CONTENT_UPDATE", selected_slide_ids=["slide_01"],
        affected_slide_ids=[], mutation_evidence=[], mutation_applied=False, draft_artifact_id=None,
    )
    result = await execute_tool("write_slide_batch", ToolContext(builder=builder, runtime=runtime), {
        "slides": [{"id": "slide_01", "changed_fields": ["title"], "title": "新标题"}],
    })
    assert result.ok
    updated = builder.get_slide("slide_01")
    assert updated["title"] == "新标题"
    assert updated["body"] == ["原正文"]
    assert updated["blocks"] == [{"kind": "note", "text": "结构化内容"}]
    assert updated["speaker_notes"] == "原备注"


@pytest.mark.asyncio
async def test_identical_slide_content_patch_is_no_change(tmp_path):
    source = {
        "id": "slide_01", "page_type": "concept", "title": "原标题", "purpose": "教学目的",
        "body": ["原正文"], "blocks": [{"kind": "note", "text": "结构化内容"}],
        "speaker_notes": "原备注", "duration_seconds": 60,
    }
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic", "slides": [source],
    })
    runtime = SimpleNamespace(
        active_intent="MODIFY", selected_slide_ids=["slide_01"],
        affected_slide_ids=[], mutation_evidence=[], mutation_applied=False,
        draft_artifact_id=None, result_status="applied",
    )

    result = await execute_tool("write_slide_batch", ToolContext(builder=builder, runtime=runtime), {
        "slides": [{
            "id": "slide_01", "changed_fields": ["title", "body"],
            "title": "原标题", "body": ["原正文"],
        }],
    })

    assert result.ok
    assert result.output["updated"] == 0
    assert result.output["unchanged_slide_ids"] == ["slide_01"]
    assert runtime.affected_slide_ids == []
    assert runtime.mutation_applied is False
    assert runtime.result_status == "no_change"


@pytest.mark.asyncio
async def test_text_only_patch_updates_visible_copy_without_geometry_change(tmp_path):
    from app.agent.slide_rendering import render_coverage, semantic_geometry_hash

    source = {
        "id": "slide_01", "page_type": "concept", "title": "原标题", "purpose": "",
        "body": ["原正文"], "blocks": [], "speaker_notes": "", "duration_seconds": 60,
        "render_mode": "absolute", "elements": [
            {"id": "T1", "kind": "textbox", "role": "title", "content_ref": "title",
             "text": "原标题", "x": 1.0, "y": 0.6, "w": 8.0, "h": 0.8,
             "style": {"size": 28}},
            {"id": "B1", "kind": "textbox", "role": "body", "content_ref": "body.0",
             "text": "原正文", "x": 1.0, "y": 1.8, "w": 8.0, "h": 2.0,
             "style": {"size": 18}},
        ],
    }
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic", "slides": [source],
    })
    before_geometry = semantic_geometry_hash(builder.get_slide("slide_01"))
    runtime = SimpleNamespace(
        active_intent="MODIFY", selected_slide_ids=["slide_01"],
        affected_slide_ids=[], mutation_evidence=[], mutation_applied=False,
        draft_artifact_id=None, result_status="applied",
    )

    result = await execute_tool("write_slide_batch", ToolContext(builder=builder, runtime=runtime), {
        "slides": [{
            "id": "slide_01", "changed_fields": ["title", "body"],
            "title": "润色后的标题", "body": ["润色后的正文"],
        }],
    })

    assert result.ok and result.output["updated"] == 1
    final = builder.get_slide("slide_01")
    assert semantic_geometry_hash(final) == before_geometry
    assert [item["text"] for item in final["elements"]] == ["润色后的标题", "润色后的正文"]
    assert render_coverage(final, baseline=final)["missing_refs"] == []


@pytest.mark.asyncio
async def test_layout_qa_rejects_target_without_render_evidence(tmp_path, monkeypatch):
    from app.renderers.ppt_visual_qa import PPTVisualQARenderer

    source = {
        "id": "slide_01", "page_type": "concept", "title": "标题", "purpose": "",
        "body": ["正文"], "blocks": [], "speaker_notes": "", "duration_seconds": 60,
        "render_mode": "absolute", "elements": [
            {"id": "E1", "kind": "textbox", "role": "title", "content_ref": "title",
             "text": "标题", "x": 1.0, "y": 0.6, "w": 8.0, "h": 0.8,
             "style": {"size": 28}},
            {"id": "E2", "kind": "textbox", "role": "body", "content_ref": "body.0",
             "text": "正文", "x": 1.0, "y": 1.8, "w": 8.0, "h": 3.8,
             "style": {"size": 18}},
        ],
    }
    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic", "slides": [source],
    })
    monkeypatch.setattr(PPTVisualQARenderer, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        PPTVisualQARenderer, "convert_pptx_to_images",
        staticmethod(lambda *_args, **_kwargs: []),
    )
    monkeypatch.setattr(
        PresentationBuilder, "render",
        lambda _self, path: (Path(path).parent.mkdir(parents=True, exist_ok=True), Path(path).touch()),
    )
    runtime = SimpleNamespace(
        active_intent="LAYOUT_ONLY", content_policy="preserve",
        selected_slide_ids=["slide_01"], affected_slide_ids=["slide_01"],
        baseline_slides=[source], source_artifact=SimpleNamespace(content_json={"slides": [source]}),
        layout_engine_params={"quality_mode": "polish_v2", "operations": [{"domain": "layout"}]},
        render_coverage={}, layout_compile_results=[], result_status="applied",
        mutation_applied=True,
    )

    result = await execute_tool(
        "run_qa", ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime), {},
    )

    assert result.ok
    assert result.output["missing_render_slide_ids"] == ["slide_01"]
    assert result.output["qa_level"] == "geometry"
    assert result.output["degraded"] is True
    assert runtime.result_status == "no_change"
    assert any(
        issue["rule_id"] == "layout.candidate_preserved"
        for issue in result.output["issues"]
    )


@pytest.mark.asyncio
async def test_image_geometry_round_trip_only_changes_existing_visual_box(tmp_path):
    from app.agent.layouts.engine import compile_layout
    from app.agent.schemas import PageLayoutSpec

    source = {
        "id": "slide_01", "page_type": "concept", "title": "浮力", "purpose": "",
        "body": ["压力差产生浮力"], "blocks": [], "speaker_notes": "", "duration_seconds": 60,
        "render_mode": "absolute", "elements": [
            {"id": "T1", "kind": "textbox", "role": "title", "content_ref": "title",
             "text": "浮力", "x": 1.0, "y": 0.6, "w": 7.0, "h": 0.8,
             "style": {"size": 28, "color": "primary"}},
            {"id": "B1", "kind": "textbox", "role": "body", "content_ref": "body.0",
             "text": "压力差产生浮力", "x": 1.0, "y": 1.8, "w": 6.5, "h": 3.5,
             "style": {"size": 18, "color": "text"}},
            {"id": "I1", "kind": "image", "role": "visual", "visual_slot": "primary_visual",
             "asset_id": "asset-1", "asset_path": "/tmp/existing.png",
             "crop": {"left": 0.1, "right": 0.0},
             "x": 9.1, "y": 2.1, "w": 2.0, "h": 2.0, "style": {"radius": 8}},
        ],
    }
    directive = {
        "slide_id": "slide_01", "layout_type": "bullet_flow",
        "image_geometry_only": True, "image_scale": 1.10,
        "objectives": [{
            "metric": "image_scale", "direction": "increase",
            "minimum_delta": 0.10, "hard_requirement": True,
        }],
    }
    compiled = compile_layout("lessonforge_deck_academic", source, directive)
    # Exercise the Pydantic artifact boundary that previously dropped asset/crop.
    layout = PageLayoutSpec.model_validate(compiled).model_dump()
    image = next(item for item in layout["elements"] if item["kind"] == "image")
    assert image["asset_id"] == "asset-1"
    assert image["asset_path"] == "/tmp/existing.png"
    assert image["crop"] == {"left": 0.1, "right": 0.0}

    builder = PresentationBuilder().from_ppt_content({
        "theme": "lessonforge_deck_academic", "slides": [source],
    })
    runtime = SimpleNamespace(
        active_intent="LAYOUT_ONLY", content_policy="preserve",
        selected_slide_ids=["slide_01"], baseline_slides=[deepcopy(source)],
        affected_slide_ids=[], mutation_evidence=[], mutation_applied=False,
        layout_compile_results=[{"slide_id": "slide_01", "status": "applied"}],
        layout_engine_params={"image_geometry_only": True}, result_status="applied",
        draft_artifact_id=None,
    )
    result = await execute_tool(
        "layout_slide_batch", ToolContext(builder=builder, workspace_root=tmp_path, runtime=runtime),
        {"layouts": [layout]},
    )

    assert result.ok
    final = builder.get_slide("slide_01")
    assert final["elements"][:2] == source["elements"][:2]
    final_image = final["elements"][2]
    assert {
        key: value for key, value in final_image.items() if key not in {"x", "y", "w", "h"}
    } == {
        key: value for key, value in source["elements"][2].items() if key not in {"x", "y", "w", "h"}
    }
    assert final_image["w"] == pytest.approx(2.2)
    assert final_image["h"] == pytest.approx(2.2)
    assert runtime.affected_slide_ids == ["slide_01"]


@pytest.mark.asyncio
async def test_template_switch_visual_qa_does_not_run_content_qa():
    builder = PresentationBuilder()
    builder.create_slide("cover", "首页")
    tc = ToolContext(
        builder=builder,
        runtime=SimpleNamespace(active_intent="TEMPLATE_SWITCH"),
        ctx=SimpleNamespace(has_tool_result=lambda _name: False),
    )
    decision = await VisualQaAgent().decide(tc)
    tool_names = [call.tool_name for call in decision.tool_calls]
    assert tool_names == ["render_preview", "run_qa"]


@pytest.mark.asyncio
async def test_template_tools_do_not_fall_back_after_profile_replaces_context():
    tc = ToolContext(
        builder=PresentationBuilder("lessonforge_deck_academic"),
        runtime=SimpleNamespace(preferred_template="lessonforge_deck_ai_future"),
        ctx=SimpleNamespace(template={"template_id": "lessonforge_deck_ai_future"}),
    )
    result = await execute_tool("get_template_design", tc, {})
    assert result.ok
    assert result.output["template"]["id"] == "lessonforge_deck_ai_future"
    assert tc.builder.template["id"] == "lessonforge_deck_ai_future"
    assert tc.ctx.template["id"] == "lessonforge_deck_ai_future"


def test_renderer_accepts_null_shape_colors(tmp_path):
    builder = PresentationBuilder("lessonforge_deck_academic")
    slide_id = builder.create_slide("cover", "首页")
    builder.add_shape(slide_id, "rect", 1, 1, 4, 3, fill=None, line=None)
    output = tmp_path / "null-colors.pptx"
    builder.render(output)
    assert output.is_file()
