"""QA + 修订闭环测试：几何检查、修订 Agent 路由、修订环有界。"""
import pytest
from sqlalchemy import select

from app.agent.tools.qa_tools import run_geometry_qa
from app.core.database import SessionLocal
from app.models.entities import PipelineEvent
from app.renderers.presentation_builder import PresentationBuilder

from agent_pipeline_helpers import build_runtime, ready_course, wait_for


def test_geometry_qa_flags_out_of_bounds_and_text_overflow():
    builder = PresentationBuilder("lessonforge_deck_academic")
    slide_id = builder.create_slide("concept", "标题", "bullet")
    builder.add_textbox(slide_id, "正文", 0.7, 1.8, 5.0, 1.0, style={"size": 18, "color": "text"})
    builder.add_shape(slide_id, "rect", 12.0, 7.0, 2.0, 2.0, fill="primary")  # 越界
    builder.add_textbox(slide_id, "超长文本" * 40, 0.7, 4.0, 1.0, 0.3, style={"size": 18, "color": "text"})  # 溢出
    issues = run_geometry_qa(builder.geometry_report())
    rules = {issue["rule_id"] for issue in issues}
    assert "geometry.out_of_bounds" in rules
    assert "geometry.text_overflow" in rules
    overflow = next(issue for issue in issues if issue["rule_id"] == "geometry.text_overflow")
    assert overflow["target_agent"] == "slide_content"


@pytest.mark.asyncio
async def test_revision_agent_routes_issues_to_target(client, auth_headers):
    from app.agent.agents.revision import REVISION_AGENT
    course_id = await ready_course(client, auth_headers, model_name="QA Mock")
    runtime = await build_runtime(course_id)
    await runtime.artifacts.create("visual_qa", "default", {
        "score": 60, "issues": [
            {"severity": "major", "slide_id": "S03", "rule_id": "geometry.text_overflow",
             "message": "第3页文本溢出", "target_agent": "slide_content"},
            {"severity": "critical", "slide_id": "S04", "rule_id": "geometry.out_of_bounds",
             "message": "第4页元素越界", "target_agent": "layout"},
        ],
    }, producer_agent="visual_qa", producer_tool="run_qa")
    decision = await REVISION_AGENT.decide(runtime.tool_context)
    assert decision.completed
    target_agents = decision.output["target_agents"]
    assert "slide_content" in target_agents
    assert "layout" in target_agents


@pytest.mark.asyncio
async def test_revision_loop_is_bounded_and_emits_revision_events(client, auth_headers, monkeypatch):
    from app.agent.pipeline import build_plan, run_revision_loop
    from app.schemas.artifact import PPTContent
    course_id = await ready_course(client, auth_headers, model_name="修订 Mock")
    runtime = await build_runtime(course_id)

    # 让 run_qa 始终追加一个越界问题 → 触发修订环（验证有界 + 路由）
    from app.agent.tools import qa_tools

    async def buggy_run_qa(tc, payload):
        result = await qa_tools._run_qa(tc, payload)
        result.output["issues"].append({
            "severity": "major", "slide_id": "S99", "rule_id": "geometry.out_of_bounds",
            "message": "模拟越界", "target_agent": "layout",
        })
        result.output["severity_counts"]["major"] = result.output["severity_counts"].get("major", 0) + 1
        result.output["score"] = max(0, result.output["score"] - 8)
        return result

    monkeypatch.setattr(qa_tools, "_run_qa", buggy_run_qa)
    plan = build_plan(runtime, "initial")
    await run_revision_loop(runtime, plan)

    async with SessionLocal() as db:
        from app.models.entities import PipelineEvent
        from sqlalchemy import select
        rows = list(await db.scalars(select(PipelineEvent).where(
            PipelineEvent.pipeline_run_id == runtime.pipeline_run.id,
        ).order_by(PipelineEvent.sequence)))
    types = [row.event_type for row in rows]
    assert "revision_started" in types
    assert "revision_completed" in types
    # 有界：revision_started 次数 ≤ max_revision_rounds
    started = sum(1 for t in types if t == "revision_started")
    assert started <= runtime.pipeline_run.max_revision_rounds

    # 最终内容仍是合法 PPTContent
    from app.agent.pipeline import finalize_content
    content = finalize_content(runtime)
    PPTContent.model_validate(content)


def test_geometry_qa_flags_crammed_layout_with_blank_space():
    """把全部文字堆在左上角、其余大面积空白的布局必须被空间利用率规则拦截。"""
    builder = PresentationBuilder("lessonforge_deck_academic")
    slide_id = builder.create_slide("concept", "挤成一团", "bullet")
    # 5 条正文全部叠在左上角小区域（纵向跨度 0.9in，远小于内容列 45%）
    for index in range(5):
        builder.add_textbox(slide_id, f"短条目{index}", 0.7, 0.5 + index * 0.18, 2.0, 0.18,
                            style={"size": 18, "color": "text"})
    issues = run_geometry_qa(builder.geometry_report())
    rules = {issue["rule_id"] for issue in issues}
    assert "layout.vertical_underuse" in rules
    assert "layout.cluster_cramming" in rules
    assert "layout.blank_region" in rules
    for issue in issues:
        if issue["rule_id"] in {"layout.vertical_underuse", "layout.cluster_cramming", "layout.blank_region"}:
            assert issue["severity"] == "major"
            assert issue["target_agent"] == "layout"


def test_geometry_qa_does_not_flag_well_distributed_layout():
    builder = PresentationBuilder("lessonforge_deck_academic")
    slide_id = builder.create_slide("concept", "正常排版", "bullet")
    builder.add_textbox(slide_id, "标题", 0.7, 0.55, 11.5, 0.8, style={"size": 28, "color": "primary"})
    for index in range(5):
        builder.add_textbox(slide_id, f"正文条目{index}展开", 0.7, 1.7 + index * 1.0, 11.5, 0.8,
                            style={"size": 18, "color": "text"})
    issues = run_geometry_qa(builder.geometry_report())
    rules = {issue["rule_id"] for issue in issues}
    assert "layout.vertical_underuse" not in rules
    assert "layout.cluster_cramming" not in rules
    assert "layout.blank_region" not in rules


def _el(slide_id, kind="textbox", x=0, y=0, w=2, h=1, text="标题", size=18, content_ref=""):
    return {"slide_id": slide_id, "kind": kind, "element_id": f"{slide_id}-{kind}-{x}", "x": x, "y": y, "w": w, "h": h,
            "text": text, "style": {"size": size}, "content_ref": content_ref}


def test_title_off_rail_flags():
    report = [_el("S1", y=2.0, text="标题", content_ref="title")]  # 标题落进正文区
    issues = run_geometry_qa(report)
    assert any(i["rule_id"] == "geometry.title_in_rail" for i in issues)


def test_narrow_column_but_tall_flags_column_balance():
    # 左侧细条占满高度（span_h 达标）→ 旧规则放行，新 column_balance 必须抓
    report = [
        _el("S1", x=0.65, y=1.7, w=2.0, h=1.0, text="第一条正文内容要点说明。", content_ref="body.0"),
        _el("S1", x=0.65, y=3.0, w=2.0, h=1.0, text="第二条正文内容要点说明。", content_ref="body.1"),
        _el("S1", x=0.65, y=4.3, w=2.0, h=1.0, text="第三条正文内容要点说明。", content_ref="body.2"),
    ]
    issues = run_geometry_qa(report)
    assert any(i["rule_id"] == "layout.column_balance" for i in issues)


def test_sparse_two_textboxes_still_checked():
    # 标题 + 单条正文（2 个元素）也查空间分布
    report = [_el("S1", x=0.65, y=0.55, w=8, h=0.8, text="标题", size=28),
              _el("S1", x=0.65, y=1.7, w=1.5, h=0.6, text="短", content_ref="body.0")]
    issues = run_geometry_qa(report)
    assert any(i["rule_id"] == "layout.cluster_cramming" for i in issues)


def test_title_in_rail_exempts_cover_and_flags_content():
    # 封面标题按 hero 设计位于 y≈2.05，不适用标题轨规则 → 豁免
    cover = [
        {"slide_id": "S1", "element_id": "cover-title", "kind": "textbox", "page_type": "cover",
         "x": 2.2, "y": 2.05, "w": 8.0, "h": 1.6, "text": "课程封面", "style": {"size": 40}, "content_ref": "title"},
    ]
    assert not any(i["rule_id"] == "geometry.title_in_rail" for i in run_geometry_qa(cover))
    # 内容页标题落在正文区 y=2.0 → 必须触发
    content = [
        {"slide_id": "S2", "element_id": "content-title", "kind": "textbox", "page_type": "concept",
         "x": 2.2, "y": 2.0, "w": 8.0, "h": 0.8, "text": "标题", "style": {"size": 28}, "content_ref": "title"},
    ]
    issues = run_geometry_qa(content)
    assert any(i["rule_id"] == "geometry.title_in_rail" for i in issues)
