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
