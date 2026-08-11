from pydantic import BaseModel

from app.agent.event_protocol import canonical_event
from app.agent.registry import Tool
from app.agent.pipeline import normalize_handoff
from types import SimpleNamespace

import pytest

from app.agent.runtime import INTENT_AGENTS, PPTAgentRuntime, infer_content_policy, infer_intent, normalize_agent_plan
from app.agent.schemas import AgentDecision, PPTAgentError, ToolResult
from app.agent.skills.registry import SkillRegistry
from app.renderers.presentation_builder import PresentationBuilder
from app.services.ppt_template_analysis_service import analyze_template


def test_intent_routes_are_scoped():
    assert infer_intent("initial") == "GENERATE"
    assert infer_intent("message", "请切换模板") == "TEMPLATE_SWITCH"
    assert infer_intent("message", "这页太密", ["S03"]) == "LAYOUT_ONLY"
    assert len(INTENT_AGENTS["VISUAL_QA"]) < len(INTENT_AGENTS["GENERATE"])


def test_modify_plan_rejects_revision_as_primary_writer_and_injects_dependencies():
    assert normalize_agent_plan("MODIFY", ["revision", "layout"]) == [
        "slide_content", "layout", "ppt_editor", "visual_qa",
    ]


def test_image_update_plan_and_handoff_capability_are_normalized():
    assert normalize_agent_plan("IMAGE_UPDATE", ["media", "ppt_editor"]) == [
        "visual_plan", "layout", "media", "ppt_editor", "visual_qa",
    ]
    assert normalize_handoff("image_generation") == "media"
    assert normalize_handoff("image-agent") == "media"
    assert normalize_handoff("invented_agent") is None


@pytest.mark.parametrize("instruction", [
    "为第四页生成一张教学配图",
    "替换第四页的受力示意图",
    "为当前页增加一幅插画",
])
def test_visual_synonyms_route_to_locked_image_update(instruction):
    intent = infer_intent("message", instruction, ["slide_04"])
    assert intent == "IMAGE_UPDATE"
    assert infer_content_policy(intent, instruction) == "preserve"


def test_template_switch_plan_cannot_route_to_content_or_media_agents():
    assert normalize_agent_plan("TEMPLATE_SWITCH", ["slide_content", "media", "revision"]) == [
        "template_analysis", "layout", "ppt_editor", "visual_qa",
    ]


def test_missing_text_request_restores_layout_without_rewriting_content():
    assert infer_content_policy("LOCAL_REGENERATE", "第四页文字描述不见了，请恢复原文字") == "restore"
    assert normalize_agent_plan("LOCAL_REGENERATE", ["slide_content", "revision"], "restore") == [
        "layout", "ppt_editor", "visual_qa",
    ]


def test_restore_route_wins_even_when_request_mentions_the_image_regression():
    instruction = "第四页插入图片后文字描述不见了，请恢复原文字"
    intent = infer_intent("message", instruction, ["slide_04"])
    policy = infer_content_policy(intent, instruction)
    assert intent == "LOCAL_REGENERATE"
    assert policy == "restore"
    assert normalize_agent_plan("IMAGE_UPDATE", INTENT_AGENTS["IMAGE_UPDATE"], policy) == [
        "layout", "ppt_editor", "visual_qa",
    ]


@pytest.mark.parametrize("instruction", [
    "第四页文字消失了，请恢复",
    "第四页文本不见了",
    "请恢复第四页文字内容",
])
def test_restore_route_recognizes_common_missing_text_phrasings(instruction):
    intent = infer_intent("message", instruction, ["slide_04"])
    assert intent == "LOCAL_REGENERATE"
    assert infer_content_policy(intent, instruction) == "restore"


def test_negated_rewrite_does_not_override_restore_policy():
    instruction = "第四页文字显示不完整，请恢复原文字布局；保留当前配图，不改写任何教学内容。"
    intent = infer_intent("message", instruction, ["slide_03_km"])
    policy = infer_content_policy(intent, instruction)
    assert intent == "LOCAL_REGENERATE"
    assert policy == "restore"
    assert normalize_agent_plan(intent, INTENT_AGENTS[intent], policy) == [
        "layout", "ppt_editor", "visual_qa",
    ]


def test_explicit_positive_rewrite_still_uses_edit_policy():
    instruction = "恢复原文字后改写第二段，使表达更简洁"
    intent = infer_intent("message", instruction, ["slide_03_km"])
    assert infer_content_policy(intent, instruction) == "edit"


def test_template_switch_publish_gate_rejects_lost_visual_resource():
    source = {
        "theme": "lessonforge_deck_academic",
        "slides": [{
            "id": "slide_01", "page_type": "cover", "title": "浮力", "body": [],
            "elements": [{
                "id": "E01", "kind": "image", "x": 7, "y": 1, "w": 5, "h": 4,
                "asset_id": "asset-1", "asset_path": "/tmp/source.png", "role": "visual",
            }],
        }],
    }
    builder = PresentationBuilder().from_ppt_content(source)
    builder.apply_template("lessonforge_deck_ai_future")
    builder.get_slide("slide_01")["elements"] = []
    pipeline = SimpleNamespace(
        source_artifact=SimpleNamespace(content_json=source), builder=builder,
        preferred_template="lessonforge_deck_ai_future", mutation_applied=True,
        publishable=False,
    )
    with pytest.raises(PPTAgentError) as caught:
        PPTAgentRuntime._assert_template_switch_integrity(SimpleNamespace(pipeline=pipeline), {})
    assert caught.value.code == "template_switch_visual_lost"


@pytest.mark.asyncio
async def test_content_edit_publish_gate_rejects_blocking_visual_qa():
    pipeline = SimpleNamespace(
        active_intent="LOCAL_REGENERATE",
        content_policy="edit",
        context=SimpleNamespace(get_tool_output=lambda name: {
            "issues": [{
                "severity": "critical",
                "slide_id": "slide_01",
                "rule_id": "layout.incomplete_absolute",
                "message": "绝对布局未覆盖页面必要文字",
            }],
        } if name == "run_qa" else {}),
        selected_slide_ids=["slide_01"],
        blocking_issues=[],
        publishable=False,
    )
    runtime = SimpleNamespace(pipeline=pipeline)

    with pytest.raises(PPTAgentError) as caught:
        await PPTAgentRuntime._assert_publishable(runtime, {})

    assert caught.value.code == "layout_incomplete"
    assert pipeline.publishable is False


@pytest.mark.asyncio
async def test_edit_layout_cannot_reintroduce_text_from_previous_revision():
    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _ensure_executable_layout
    from app.agent.slide_rendering import bind_content_refs, render_coverage
    from app.agent.tools.qa_tools import _text_height_inches

    old_slide = {
        "id": "slide_01", "page_type": "cover", "title": "旧标题",
        "purpose": "旧目标", "body": ["旧副标题"], "blocks": [],
        "speaker_notes": "", "duration_seconds": 60,
    }
    edited_slide = {
        **old_slide,
        "title": "润色后的标题",
        "purpose": "润色后的目标",
        "body": ["润色后的副标题", "润色后的核心问题"],
    }

    class Artifacts:
        async def latest(self, artifact_type):
            return {"data": {"slides": [edited_slide]}} if artifact_type == "slide_content" else None

    runtime = SimpleNamespace(
        selected_slide_ids=["slide_01"], content_policy="edit",
        baseline_slides=[old_slide], artifacts=Artifacts(), emitter=None,
        preferred_template="lessonforge_deck_academic", expected_visual_requests=[],
    )
    stale_layout = AgentDecision(completed=True, output={"slides": [{
        "slide_id": "slide_01", "layout_type": "cover", "designRationale": "保留旧布局",
        "render_mode": "absolute",
        "elements": [
            {"kind": "textbox", "role": "title", "text": "旧标题", "x": 2.2, "y": 1.2, "w": 4, "h": 1},
            {"kind": "textbox", "role": "body", "text": "旧副标题", "x": 2.2, "y": 2.5, "w": 4, "h": 1},
        ],
    }]})

    normalized = await _ensure_executable_layout(runtime, LAYOUT_AGENT, stale_layout)
    elements = normalized.output["slides"][0]["elements"]
    bound, unresolved = bind_content_refs(edited_slide, elements)

    assert unresolved == []
    assert "润色后的副标题" in "\n".join(item.get("text", "") for item in bound)
    assert render_coverage(
        {**edited_slide, "render_mode": "absolute", "elements": bound},
        baseline=edited_slide,
    )["missing_refs"] == []
    semantic_text = [item for item in bound if item.get("content_ref")]
    assert all(float(item["x"]) >= 2.2 for item in semantic_text)
    body_element = next(item for item in semantic_text if item.get("content_ref") == "body")
    assert float(body_element["h"]) >= 1.65
    body_style = body_element.get("style") or {}
    assert _text_height_inches(
        body_element.get("text", ""), float(body_element["w"]), float(body_style.get("size") or 18),
    ) <= float(body_element["h"]) * 1.15


@pytest.mark.asyncio
async def test_edit_layout_reserves_visual_slot_for_preserved_image():
    """文字润色页已有待保留图片时，LLM 布局即使缺失 visual_region 也必须补齐视觉槽，
    并把正文收窄到视觉槽左侧，避免保留图片与正文重叠触发 QA 拦截。"""
    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _ensure_executable_layout

    source = {
        "id": "slide_03_ki", "page_type": "scenario", "title": "侧面受力抵消",
        "purpose": "", "body": ["原正文"], "blocks": [],
        "speaker_notes": "", "duration_seconds": 30,
        "elements": [{
            "id": "E450", "kind": "image", "x": 7.5, "y": 1.8, "w": 4.8, "h": 3.6,
            "asset_id": "asset-1", "asset_path": "/tmp/img.png", "role": "visual",
            "visual_slot": "primary_visual", "style": {},
        }],
    }
    edited_slide = {**source, "title": "润色后的标题", "body": ["润色后的正文"]}

    class Artifacts:
        async def latest(self, artifact_type):
            return {"data": {"slides": [edited_slide]}} if artifact_type == "slide_content" else None

    runtime = SimpleNamespace(
        selected_slide_ids=["slide_03_ki"], content_policy="edit",
        active_intent="MODIFY", baseline_slides=[source], artifacts=Artifacts(),
        emitter=None, preferred_template="lessonforge_deck_academic",
        expected_visual_requests=[],
        builder=PresentationBuilder().from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]}),
    )
    stale_layout = AgentDecision(completed=True, output={"slides": [{
        "slide_id": "slide_03_ki", "layout_type": "title_and_body",
        "designRationale": "全宽正文且未预留视觉区", "render_mode": "absolute",
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "润色后的标题",
             "x": 2.45, "y": 0.55, "w": 10.1, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body", "text": "润色后的正文",
             "x": 2.45, "y": 1.7, "w": 10.1, "h": 3.2},
        ],
    }]})

    normalized = await _ensure_executable_layout(runtime, LAYOUT_AGENT, stale_layout)
    layout = normalized.output["slides"][0]
    assert layout.get("visual_region"), "待保留图片所在页必须预留视觉槽"
    body = next(el for el in layout["elements"] if str(el.get("content_ref") or "").startswith("body"))
    visual_right = float(layout["visual_region"]["x"])
    assert float(body["x"]) + float(body["w"]) <= visual_right - 0.1, "正文不得延伸到视觉槽下方"


@pytest.mark.asyncio
async def test_edit_layout_expands_aggregate_body_into_spaced_items():
    """LLM 布局即使只给出单个 content_ref=body 聚合文本框，也必须拆成逐条、
    带留白的独立文本框，才能让"文字间隔/太单调"类润色产生可见变化。"""
    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _ensure_executable_layout
    from app.agent.slide_rendering import bind_content_refs, render_coverage

    source = {
        "id": "slide_03_ki", "page_type": "scenario", "title": "浮力成因解析",
        "purpose": "", "body": ["侧面平衡：前后左右受力对称抵消", "深度压强：下表面更深，液体压强更大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
        "elements": [{
            "id": "E450", "kind": "image", "x": 7.5, "y": 1.8, "w": 4.8, "h": 3.6,
            "asset_id": "asset-1", "asset_path": "/tmp/img.png", "role": "visual",
            "visual_slot": "primary_visual", "style": {},
        }],
    }
    edited_slide = {**source, "title": "润色后的标题", "body": ["润色条目一", "润色条目二", "润色条目三"]}

    class Artifacts:
        async def latest(self, artifact_type):
            return {"data": {"slides": [edited_slide]}} if artifact_type == "slide_content" else None

    runtime = SimpleNamespace(
        selected_slide_ids=["slide_03_ki"], content_policy="edit",
        active_intent="MODIFY", baseline_slides=[source], artifacts=Artifacts(),
        emitter=None, preferred_template="lessonforge_deck_academic",
        expected_visual_requests=[],
        builder=PresentationBuilder().from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]}),
    )
    single_body_layout = AgentDecision(completed=True, output={"slides": [{
        "slide_id": "slide_03_ki", "layout_type": "left_text_right_visual",
        "designRationale": "单行聚合正文", "render_mode": "absolute",
        "visual_region": {"x": 7.4, "y": 1.7, "w": 5.0, "h": 4.0},
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "润色后的标题",
             "x": 2.45, "y": 0.55, "w": 10.1, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body", "text": "聚合正文",
             "x": 2.45, "y": 1.7, "w": 4.6, "h": 3.0},
        ],
    }]})

    normalized = await _ensure_executable_layout(runtime, LAYOUT_AGENT, single_body_layout)
    elements = normalized.output["slides"][0]["elements"]
    body_refs = [el for el in elements if str(el.get("content_ref") or "").startswith("body")]
    assert [el["content_ref"] for el in body_refs] == ["body.0", "body.1", "body.2"]
    assert body_refs[1]["y"] > body_refs[0]["y"] + body_refs[0]["h"], "条目之间应留白"
    assert not any(el.get("content_ref") == "body" for el in elements), "聚合正文框应被拆散"

    bound, unresolved = bind_content_refs(edited_slide, elements)
    assert unresolved == []
    assert render_coverage(
        {**edited_slide, "render_mode": "absolute", "elements": bound},
        baseline=edited_slide,
    )["missing_refs"] == []
    text_by_ref = {el.get("content_ref"): el.get("text") for el in bound if el.get("content_ref")}
    assert text_by_ref["body.0"] == "润色条目一"
    assert text_by_ref["body.1"] == "润色条目二"
    assert text_by_ref["body.2"] == "润色条目三"


@pytest.mark.asyncio
async def test_llm_layout_with_own_phrasing_is_preserved_and_bound_to_canonical_text():
    """LLM 布局用自己的措辞写文字时，不能因文本不匹配就退回朴素竖排。

    先绑定权威文字再校验：只要 content_ref 正确，LLM 精心设计的双栏版式
    必须被保留，且渲染文字用规范内容。
    """
    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _ensure_executable_layout
    from app.agent.slide_rendering import bind_content_refs, render_coverage

    source = {
        "id": "slide_03_km", "page_type": "concept", "title": "浮力成因拆解",
        "purpose": "", "body": ["上下压力差产生浮力", "液体密度越大浮力越大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
    }

    class Artifacts:
        async def latest(self, artifact_type):
            return None

    runtime = SimpleNamespace(
        selected_slide_ids=["slide_03_km"], content_policy="preserve",
        active_intent="LAYOUT_ONLY", baseline_slides=[source], artifacts=Artifacts(),
        emitter=None, preferred_template="lessonforge_deck_academic",
        expected_visual_requests=[], builder=None,
    )
    two_column = AgentDecision(completed=True, output={"slides": [{
        "slide_id": "slide_03_km", "layout_type": "split", "designRationale": "左右双栏对比",
        "render_mode": "absolute",
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "任意标题措辞",
             "x": 2.2, "y": 0.55, "w": 10.3, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body.0", "text": "模型自己写的左栏话术",
             "x": 2.2, "y": 1.7, "w": 4.5, "h": 0.6},
            {"kind": "textbox", "role": "body", "content_ref": "body.1", "text": "模型自己写的右栏话术",
             "x": 7.0, "y": 1.7, "w": 4.5, "h": 0.6},
        ],
    }]})

    normalized = await _ensure_executable_layout(runtime, LAYOUT_AGENT, two_column)
    layout = normalized.output["slides"][0]
    body = [el for el in layout["elements"] if str(el.get("content_ref") or "").startswith("body")]
    assert len(body) == 2
    xs = {round(float(el["x"]), 1) for el in body}
    assert xs == {2.2, 7.0}, "LLM 双栏布局必须被保留，不得退回竖排"
    assert body[0]["y"] == 1.7 and body[1]["y"] == 1.7

    bound, unresolved = bind_content_refs(source, layout["elements"])
    assert unresolved == []
    text_by_ref = {el.get("content_ref"): el.get("text") for el in bound if el.get("content_ref")}
    assert text_by_ref["body.0"] == "上下压力差产生浮力"
    assert text_by_ref["body.1"] == "液体密度越大浮力越大"
    assert text_by_ref["title"] == "浮力成因拆解"
    assert render_coverage(
        {**source, "render_mode": "absolute", "elements": bound},
        baseline=source,
    )["missing_refs"] == []


@pytest.mark.asyncio
async def test_partial_llm_layout_completes_missing_slides_deterministically():
    """LLM 整本修订时只返回前几页布局，缺失页必须用确定性版式补齐，
    而不是沿用旧元素导致内容覆盖门禁失败。"""
    from app.agent.agents.layout import LAYOUT_AGENT
    from app.agent.pipeline import _ensure_executable_layout
    from app.agent.slide_rendering import bind_content_refs, render_coverage

    source = [
        {"id": "slide_01", "page_type": "cover", "title": "浮力", "purpose": "创设情境",
         "body": ["副标题"], "blocks": [], "speaker_notes": "", "duration_seconds": 30,
         "elements": []},
        {"id": "slide_02", "page_type": "concept", "title": "浮力成因", "purpose": "",
         "body": ["上下压力差产生浮力", "液体密度越大浮力越大"], "blocks": [],
         "speaker_notes": "", "duration_seconds": 30, "elements": []},
    ]

    class Artifacts:
        async def latest(self, artifact_type):
            return None

    runtime = SimpleNamespace(
        selected_slide_ids=[], content_policy="preserve",
        active_intent="LAYOUT_ONLY", baseline_slides=source, artifacts=Artifacts(),
        emitter=None, preferred_template="lessonforge_deck_academic",
        expected_visual_requests=[], builder=None,
    )
    # LLM 只返回第一页的合法布局，漏掉第二页
    partial = AgentDecision(completed=True, output={"slides": [{
        "slide_id": "slide_01", "layout_type": "cover", "designRationale": "封面",
        "render_mode": "absolute",
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "浮力",
             "x": 2.95, "y": 1.15, "w": 4.4, "h": 1.4},
            {"kind": "textbox", "role": "body", "content_ref": "body", "text": "副标题",
             "x": 2.95, "y": 2.85, "w": 4.4, "h": 0.8},
        ],
    }]})

    normalized = await _ensure_executable_layout(runtime, LAYOUT_AGENT, partial)
    slide_ids = {item["slide_id"] for item in normalized.output["slides"]}
    assert slide_ids == {"slide_01", "slide_02"}, "缺失页必须被补齐"
    for item in normalized.output["slides"]:
        slide = next(s for s in source if s["id"] == item["slide_id"])
        bound, unresolved = bind_content_refs(slide, item["elements"])
        assert unresolved == []
        assert render_coverage(
            {**slide, "render_mode": "absolute", "elements": bound},
            baseline=slide,
        )["missing_refs"] == [], item["slide_id"]


def test_skill_registry_discovers_without_loading():
    registry = SkillRegistry()
    found = registry.discover(["layout-design", "visual-qa"])
    assert {item.name for item in found} == {"ppt-layout-design", "ppt-visual-qa"}
    assert not registry.is_loaded("ppt-layout-design")
    body = registry.load("ppt-layout-design")
    assert "PPT Layout Design" in body
    assert registry.is_loaded("ppt-layout-design")


def test_template_analysis_reads_real_pptx():
    academic_hash, academic = analyze_template("lessonforge_deck_academic")
    ai_hash, ai = analyze_template("lessonforge_deck_ai_future")
    assert academic_hash != ai_hash
    assert academic["masters"] >= 1 and academic["layouts"]
    assert academic["design_context_only"] is True
    assert academic["layout_patterns"] != ai["layout_patterns"]


def test_legacy_event_is_normalized():
    event = canonical_event(
        event_id=12, event_type="artifact_patch",
        data={"run_id": "r1", "artifact_id": "a1", "slide_id": "S03", "summary": "更新页面"},
    )
    assert event["type"] == "artifact.updated"
    assert event["sequence"] == 12
    assert event["slide"]["slide_id"] == "S03"


class EmptyInput(BaseModel):
    pass


def test_tool_schema_exposes_runtime_policy():
    async def handler(_tc, _payload):
        return ToolResult(ok=True, output={"done": True})

    schema = Tool("agentic_policy_test_tool", "test", EmptyInput, handler,
                  timeout_seconds=3, max_retries=2, idempotent=True).schema_dict()
    assert schema["timeout_seconds"] == 3
    assert schema["retry_policy"] == {"max_retries": 2}
    assert schema["idempotent"] is True


@pytest.mark.parametrize("instruction", [
    "润色一下现在PPT的页面分布",
    "调整第3页的排版和留白",
    "这一页太挤了，重新排一下",
    "让正文条目之间间隔再大一点",
    "本页内容堆在左上角，重新分布一下",
])
def test_layout_only_phrasings_route_to_layout_intent_and_preserve_content(instruction):
    intent = infer_intent("message", instruction, ["S03"])
    assert intent == "LAYOUT_ONLY"
    assert infer_content_policy(intent, instruction) == "preserve"
    assert normalize_agent_plan(intent, INTENT_AGENTS[intent], "preserve") == [
        "layout", "ppt_editor", "visual_qa",
    ]


@pytest.mark.parametrize("instruction", [
    "润色第三页的文字表达",
    "把正文改写得更口语化",
])
def test_text_polish_phrasings_remain_edits(instruction):
    intent = infer_intent("message", instruction, ["S03"])
    assert intent in {"LOCAL_REGENERATE", "MODIFY"}
    assert infer_content_policy(intent, instruction) == "edit"


def test_layout_only_plan_never_runs_content_or_media_agents():
    assert normalize_agent_plan("LAYOUT_ONLY", INTENT_AGENTS["LAYOUT_ONLY"]) == [
        "layout", "ppt_editor", "visual_qa",
    ]
    assert "slide_content" not in INTENT_AGENTS["LAYOUT_ONLY"]
    assert "media" not in INTENT_AGENTS["LAYOUT_ONLY"]


def test_canonicalize_spatial_layout_redistributes_crammed_body():
    from app.agent.agents.layout import canonicalize_spatial_layout

    slide = {
        "id": "slide_01", "page_type": "concept", "title": "浮力成因",
        "purpose": "", "body": ["上下压力差产生浮力", "液体密度越大浮力越大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
    }
    # 模拟 LLM 把正文全部压进左上角小区域：既没有纵向铺满、也没有横向展开
    crammed = {
        "slide_id": "slide_01", "layout_type": "title_and_body",
        "render_mode": "absolute", "visual_region": {"x": 7.4, "y": 1.7, "w": 5.0, "h": 4.0},
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "浮力成因",
             "x": 2.45, "y": 0.55, "w": 1.5, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body.0", "text": "上下压力差产生浮力",
             "x": 2.45, "y": 0.9, "w": 1.5, "h": 0.5},
            {"kind": "textbox", "role": "body", "content_ref": "body.1", "text": "液体密度越大浮力越大",
             "x": 2.45, "y": 1.5, "w": 1.5, "h": 0.5},
        ],
    }
    normalized = canonicalize_spatial_layout("lessonforge_deck_academic", slide, crammed)
    from app.agent.agents.layout import MARGIN_Y, MIN_BODY_VERTICAL_USAGE, SAFE_CONTENT_BOTTOM

    body = [el for el in normalized["elements"] if str(el.get("content_ref") or "").startswith("body")]
    assert len(body) == 2
    assert body[0]["y"] >= MARGIN_Y
    span = (body[-1]["y"] + body[-1]["h"]) - body[0]["y"]
    assert span >= (SAFE_CONTENT_BOTTOM - MARGIN_Y) * MIN_BODY_VERTICAL_USAGE, "正文列必须铺满内容区"
    assert body[1]["y"] > body[0]["y"] + body[0]["h"], "条目之间应留白"
    # 语义文字必须逐字保留
    assert body[0]["text"] == "上下压力差产生浮力"
    assert body[1]["text"] == "液体密度越大浮力越大"


def test_canonicalize_spatial_layout_keeps_multi_column_layout():
    """双栏/横向卡片等真正利用横向空间的版式不能被重排压成竖排。"""
    from app.agent.agents.layout import canonicalize_spatial_layout

    slide = {
        "id": "slide_01", "page_type": "concept", "title": "浮力成因",
        "purpose": "", "body": ["上下压力差产生浮力", "液体密度越大浮力越大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
    }
    two_column = {
        "slide_id": "slide_01", "layout_type": "split", "render_mode": "absolute",
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "浮力成因",
             "x": 2.2, "y": 0.55, "w": 10.3, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body.0", "text": "上下压力差产生浮力",
             "x": 2.2, "y": 1.7, "w": 4.5, "h": 0.6},
            {"kind": "textbox", "role": "body", "content_ref": "body.1", "text": "液体密度越大浮力越大",
             "x": 7.0, "y": 1.7, "w": 4.5, "h": 0.6},
        ],
    }
    normalized = canonicalize_spatial_layout("lessonforge_deck_academic", slide, two_column)
    body = [el for el in normalized["elements"] if str(el.get("content_ref") or "").startswith("body")]
    assert len(body) == 2
    xs = {round(float(el["x"]), 1) for el in body}
    assert len(xs) == 2, "双栏布局必须保留两个不同列位置"
    assert body[0]["y"] == 1.7 and body[1]["y"] == 1.7, "双栏布局不得改成竖排错位"


def test_canonicalize_spatial_layout_keeps_well_distributed_layout():
    from app.agent.agents.layout import canonicalize_spatial_layout

    slide = {
        "id": "slide_01", "page_type": "concept", "title": "浮力成因",
        "purpose": "", "body": ["上下压力差产生浮力", "液体密度越大浮力越大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
    }
    distributed = {
        "slide_id": "slide_01", "layout_type": "title_and_body",
        "render_mode": "absolute",
        "elements": [
            {"kind": "textbox", "role": "title", "content_ref": "title", "text": "浮力成因",
             "x": 2.2, "y": 0.55, "w": 10.3, "h": 0.8},
            {"kind": "textbox", "role": "body", "content_ref": "body.0", "text": "上下压力差产生浮力",
             "x": 2.2, "y": 1.7, "w": 10.3, "h": 1.5},
            {"kind": "textbox", "role": "body", "content_ref": "body.1", "text": "液体密度越大浮力越大",
             "x": 2.2, "y": 3.5, "w": 10.3, "h": 1.5},
        ],
    }
    normalized = canonicalize_spatial_layout("lessonforge_deck_academic", slide, distributed)
    body = [el for el in normalized["elements"] if str(el.get("content_ref") or "").startswith("body")]
    assert len(body) == 2
    assert body[0]["y"] == 1.7
    assert body[1]["y"] == 3.5


def test_knowledge_block_not_truncated_for_layout():
    """knowledge 块必须整体注入，typography/ppt_skills 不能被 6000 字符截断丢。"""
    import json
    from pathlib import Path

    from app.agent.context import ContextState

    knowledge_path = Path(__file__).resolve().parents[2] / "templates/ppt_design/knowledge.json"
    ctx = ContextState()
    ctx.knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    prompt = ctx.to_prompt("layout")
    assert "typography" in prompt
    assert "ppt_skills" in prompt or "cover_patterns" in prompt


# ---- Task 7: 结构化意图提取（LLM；Mock/失败由关键词 infer_intent 兜底） ----
from app.agent.intents import extract_polish_intent  # noqa: E402


@pytest.mark.asyncio
async def test_extract_polish_intent_falls_back_on_mock():
    from app.providers.llm.mock import MockProvider

    runtime = SimpleNamespace(provider=MockProvider())
    assert await extract_polish_intent(runtime) is None


# ---- Task 10: 收敛性修复（几何类规则确定性收敛 + 单调性门禁） ----
from app.agent.runtime import DETERMINISTIC_RULES  # noqa: E402
from app.agent.slide_rendering import semantic_geometry_hash  # noqa: E402


def test_geometry_rules_are_deterministic():
    assert "geometry.overlap" in DETERMINISTIC_RULES
    assert "geometry.text_overflow" in DETERMINISTIC_RULES
    assert "layout.cluster_cramming" in DETERMINISTIC_RULES
    assert "layout.column_balance" in DETERMINISTIC_RULES


def test_semantic_geometry_hash_detects_monotony():
    a = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 1.7, "w": 5, "h": 1}]}
    b = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 1.7, "w": 5, "h": 1}]}
    c = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 3.0, "w": 5, "h": 1}]}
    assert semantic_geometry_hash(a) == semantic_geometry_hash(b)
    assert semantic_geometry_hash(a) != semantic_geometry_hash(c)
