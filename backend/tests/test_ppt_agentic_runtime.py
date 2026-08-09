from pydantic import BaseModel

from app.agent.event_protocol import canonical_event
from app.agent.registry import Tool
from app.agent.pipeline import normalize_handoff
from types import SimpleNamespace

import pytest

from app.agent.runtime import INTENT_AGENTS, PPTAgentRuntime, infer_content_policy, infer_intent, normalize_agent_plan
from app.agent.schemas import PPTAgentError, ToolResult
from app.agent.skills.registry import SkillRegistry
from app.renderers.presentation_builder import PresentationBuilder
from app.services.ppt_template_analysis_service import analyze_template


def test_intent_routes_are_scoped():
    assert infer_intent("initial") == "GENERATE"
    assert infer_intent("message", "请切换模板") == "TEMPLATE_SWITCH"
    assert infer_intent("message", "这页太密", ["S03"]) == "LOCAL_REGENERATE"
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
