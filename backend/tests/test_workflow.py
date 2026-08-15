import pytest

from app.core.database import create_schema
from app.models.entities import CourseProject
from app.schemas.blueprint import CourseBlueprintSchema
from app.workflows.course_graph import build_blueprint_graph


@pytest.mark.asyncio
async def test_blueprint_graph_generates_blueprint():
    await create_schema()
    course = CourseProject(owner_id="u", title="Python 异步编程", subject="计算机", grade_level="高校", audience="具备 Python 基础的学生", duration_minutes=20, scenario="课堂讲解", language="中文", settings_json={})
    graph = build_blueprint_graph()
    result = await graph.ainvoke(
        {
            "course_id": "c", "run_id": "r", "thread_id": "t",
            "requirements": {"title": course.title, "subject": course.subject, "grade_level": course.grade_level, "audience": course.audience, "duration_minutes": course.duration_minutes, "scenario": course.scenario, "language": course.language, "settings_json": course.settings_json},
            "material_refs": [], "completed_nodes": [], "status": "running",
        },
        config={"configurable": {"thread_id": "t"}},
    )
    blueprint = CourseBlueprintSchema.model_validate(result["blueprint"])
    assert blueprint.course_identity.title == "Python 异步编程"
    assert len(blueprint.timeline) == 3
    assert result["completed_nodes"] == ["requirement_analysis_agent", "material_analysis_agent", "pedagogy_blueprint_agent"]
    assert result["status"] == "waiting_human"
    assert result["requirement_issues"] == []
