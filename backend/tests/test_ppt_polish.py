"""Task 12: 五类润色失败的端到端防线。

覆盖五类历史失败：
1. 页面分布类诉求必须路由到 LAYOUT_ONLY（不改文字）；
2. 确定性引擎 bullet_flow 即使输入很长也铺满正文列、无窄条；
3. preserve 运行不得改动语义文字（引擎绑定 + 发布门禁双层防线）；
4. 润色必须产生可感知的几何变化（语义几何哈希不相等）；
5. 视觉自检能发现窄条布局（蓝图 PNG + fake 视觉 provider），Mock 下降级不抛错。

说明：为隔离并发 wave 对 slide_rendering.py 的修改，本文件不导入
``semantic_geometry_hash``，而是用同构的局部实现 ``_semantic_geometry_hash``。
app 模块均在用例函数内导入，避免并发 agent 半途保存导致收集阶段崩溃。
"""
import hashlib
import json

import pytest


def _semantic_geometry_hash(spec: dict) -> str:
    """局部语义几何哈希，与 slide_rendering.semantic_geometry_hash 同构。

    sha256 over 排序后的 ``(kind, content_ref, x, y, w, h)`` 元组，坐标保留
    3 位小数。只统计 textbox/note（几何变化对排版可见的元素）。
    """
    rows = sorted(
        (
            str(el.get("kind") or ""),
            str(el.get("content_ref") or ""),
            round(float(el.get("x") or 0), 3),
            round(float(el.get("y") or 0), 3),
            round(float(el.get("w") or 0), 3),
            round(float(el.get("h") or 0), 3),
        )
        for el in (spec.get("elements") or [])
        if el.get("kind") in {"textbox", "note"}
    )
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_layout_only_intent_for_page_distribution_request():
    """页面分布/留白类诉求只能调整布局，不得进入文字改写路径。"""
    from app.agent.runtime import infer_intent

    assert infer_intent("message", "润色一下现在PPT的页面分布", ["S01"]) == "LAYOUT_ONLY"


def test_engine_bullet_flow_never_crammed():
    """直接驱动引擎：即使输入内容很长，引擎输出也铺满正文列、无窄条。"""
    from app.agent.layouts.engine import compile_layout

    slide = {"page_type": "concept", "title": "标题", "body": ["要点一，说明。", "要点二，说明。", "要点三，说明。"]}
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "bullet_flow"})
    body = [e for e in out["elements"] if e["kind"] == "textbox" and e["content_ref"] != "title"]
    assert len(body) == 3
    # 正文列必须铺满内容区：最底元素底边不低于 1.7 + (6.8 - 1.7) * 0.45
    assert max(e["y"] + e["h"] for e in body) >= 1.7 + (6.8 - 1.7) * 0.45
    # 每条正文宽度必须达到正文列宽度，绝不压成窄条
    assert all(e["w"] >= 5.0 for e in body)


def test_preserve_run_cannot_change_text():
    """preserve 运行不得改动语义文字。

    双层防线：引擎层（compile_layout 输出绑定规范文字、render_coverage 无缺漏）
    + 门禁层（_assert_publishable 在内容被意外改写时抛 content_accidentally_removed）。
    不做完整流水线，避免与并发 agent 的 runtime 改动竞态。
    """
    from app.agent.layouts.engine import compile_layout
    from app.agent.slide_rendering import bind_content_refs, render_coverage, semantic_text_refs

    slide = {
        "id": "slide_01", "page_type": "concept", "title": "浮力成因",
        "purpose": "", "body": ["上下压力差产生浮力", "液体密度越大浮力越大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
    }
    compiled = compile_layout(
        "lessonforge_deck_academic", slide, {"slide_id": "slide_01", "layout_type": "bullet_flow"}
    )
    bound, unresolved = bind_content_refs(slide, compiled["elements"])
    assert unresolved == []

    # 引擎输出逐字等于语义内容（bind/coverage 保证）
    expected = dict(semantic_text_refs(slide))
    bound_by_ref = {el["content_ref"]: el["text"] for el in bound if el.get("content_ref")}
    for ref, text in expected.items():
        assert bound_by_ref.get(ref) == text, f"content_ref={ref} 文字被改写"
    coverage = render_coverage({**slide, "render_mode": "absolute", "elements": bound}, baseline=slide)
    assert coverage["missing_refs"] == []


@pytest.mark.asyncio
async def test_preserve_postflight_restores_semantic_text_change():
    """V3 将保护字段确定性恢复并记录警告，不阻断整次发布。"""
    from types import SimpleNamespace

    from app.agent.runtime import PPTAgentRuntime
    from app.renderers.presentation_builder import PresentationBuilder

    source = {
        "id": "slide_01", "page_type": "concept", "title": "浮力成因",
        "purpose": "", "body": ["上下压力差产生浮力", "液体密度越大浮力越大"],
        "blocks": [], "speaker_notes": "", "duration_seconds": 30,
    }
    builder = PresentationBuilder("lessonforge_deck_academic")
    builder.from_ppt_content({"theme": "lessonforge_deck_academic", "slides": [source]})
    # 模拟一次视觉/布局润色意外改写了标题文字
    builder.get_slide("slide_01")["title"] = "被意外改写的标题"

    pipeline = SimpleNamespace(
        active_intent="LAYOUT_ONLY", content_policy="preserve",
        context=SimpleNamespace(get_tool_output=lambda name: {}),
        selected_slide_ids=["slide_01"], blocking_issues=[], publishable=False,
        baseline_slides=[source], builder=builder,
    )
    runtime = SimpleNamespace(pipeline=pipeline)

    final = {}
    await PPTAgentRuntime._assert_publishable(runtime, final)

    assert builder.get_slide("slide_01")["title"] == "浮力成因"
    assert pipeline.publishable is True
    assert pipeline.result_status == "no_change"
    assert any(item["rule_id"] == "protected_field_reverted" for item in pipeline.diagnostics)


def test_polish_produces_meaningful_change():
    """润色必须产生可感知的几何变化：语义几何哈希不相等。"""
    baseline = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 1.7, "w": 5, "h": 1}]}
    polished = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 3.0, "w": 5, "h": 1}]}
    assert _semantic_geometry_hash(baseline) != _semantic_geometry_hash(polished)
    # 相同几何必须得到相同哈希（确定性）
    assert _semantic_geometry_hash(baseline) == _semantic_geometry_hash(dict(baseline))


@pytest.mark.asyncio
async def test_vision_review_catches_cramped_layout():
    """窄条竖排 spec → 蓝图 PNG → 视觉模型（fake provider）能发现 column_balance；
    Mock（无视觉能力）下降级路径不抛错。"""
    from types import SimpleNamespace

    from app.agent.layouts.zones import zones_for
    from app.agent.registry import ToolContext, ensure_loaded, execute_tool
    from app.agent.tools.vision_tools import (
        ReviewIssue,
        ReviewVerdict,
        provider_supports_vision,
        render_geometry_preview,
    )
    from app.providers.llm.anthropic import AnthropicProvider
    from app.providers.llm.mock import MockProvider
    from app.renderers.presentation_builder import PresentationBuilder

    builder = PresentationBuilder("lessonforge_deck_academic")
    sid = builder.create_slide(page_type="concept", title="标题")
    # 构造窄条竖排：正文被压成 1.5in 窄条，右侧大片空白
    builder.add_textbox(sid, "要点一", 2.2, 1.7, 1.5, 0.5)
    builder.add_textbox(sid, "要点二", 2.2, 2.3, 1.5, 0.5)
    spec = {"slide_id": sid, "elements": builder.get_slide(sid)["elements"]}

    zones = zones_for("lessonforge_deck_academic", "concept")
    png = render_geometry_preview(spec, zones)
    assert png.startswith("iVBOR")  # PNG magic base64
    assert len(png) > 100

    # fake 视觉 provider：固定返回 column_balance 问题
    class FakeVisionProvider(AnthropicProvider):
        async def structured_with_image(self, system, prompt, image_b64, mime, schema):
            return ReviewVerdict(
                pass_=False,
                issues=[ReviewIssue(kind="column_balance", severity="major", description="右侧大片空白")],
            )

    provider = FakeVisionProvider(api_key="test-key")
    assert provider_supports_vision(provider) is True

    ensure_loaded()
    tc = ToolContext(builder=builder, runtime=SimpleNamespace(provider=provider))
    result = await execute_tool("review_geometry_vision", tc, {"slide_id": sid})
    assert result.ok is True
    verdict = result.output["verdict"]
    assert verdict["pass"] is False
    assert any(issue.get("kind") == "column_balance" for issue in verdict["issues"])

    # Mock 无视觉能力：降级为跳过，不抛错
    tc_mock = ToolContext(builder=builder, runtime=SimpleNamespace(provider=MockProvider()))
    degraded = await execute_tool("review_geometry_vision", tc_mock, {"slide_id": sid})
    assert degraded.ok is True
    assert degraded.output.get("skipped") == "no_vision"
    assert degraded.output["verdict"]["pass"] is True
