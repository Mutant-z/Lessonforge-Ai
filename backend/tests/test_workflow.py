import pytest

from app.agents.generators import make_blueprint
from app.models.entities import CourseProject
from app.workflows.course_graph import build_course_graph, route_quality


@pytest.mark.asyncio
async def test_langgraph_generates_six_resources():
    course = CourseProject(owner_id="u", title="Python 异步编程", subject="计算机", grade_level="高校", audience="具备 Python 基础的学生", duration_minutes=20, scenario="课堂讲解", language="中文", settings_json={})
    bp = make_blueprint(course)
    graph = build_course_graph()
    result = await graph.ainvoke({"course_id": "c", "run_id": "r", "thread_id": "t", "blueprint": bp.model_dump(), "blueprint_version": 1, "blueprint_approved": True, "completed_nodes": [], "locked_paths": [], "retry_counts": {}, "status": "running"}, config={"configurable": {"thread_id": "t"}})
    for key in ("lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim", "quality_report"):
        assert key in result
    assert len(result["completed_nodes"]) == 9


def test_qa_rework_route_is_bounded():
    issue = [{"severity": "critical"}]
    assert route_quality({"quality_issues": issue, "retry_counts": {}}) == "rework"
    assert route_quality({"quality_issues": issue, "retry_counts": {"targeted_rework": 2}}) == "human"
