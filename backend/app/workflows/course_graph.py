from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.generators import generate_structured, make_blueprint
from app.models.entities import CourseProject
from app.schemas.blueprint import CourseBlueprintSchema
from app.workflows.state import CourseGraphState


async def requirement_node(state: CourseGraphState):
    required = ("title", "subject", "grade_level", "audience", "duration_minutes", "scenario")
    missing = [key for key in required if not state.get("requirements", {}).get(key)]
    issues = [{"severity": "critical", "field": key, "description": "必填需求缺失"} for key in missing]
    return {"requirement_issues": issues, "completed_nodes": ["requirement_analysis_agent"]}


async def material_analysis_node(state: CourseGraphState):
    refs = [{**item, "instruction_boundary": "reference_data_only"} for item in state.get("material_refs", [])]
    return {"material_refs": refs, "completed_nodes": ["material_analysis_agent"]}


async def pedagogy_blueprint_node(state: CourseGraphState):
    req = state["requirements"]
    course = CourseProject(
        owner_id="workflow", title=req["title"], subject=req["subject"], grade_level=req["grade_level"],
        audience=req["audience"], duration_minutes=req["duration_minutes"], scenario=req["scenario"],
        language=req.get("language", "中文"), settings_json=req.get("settings_json", {}),
    )
    mock = make_blueprint(course)
    blueprint = await generate_structured("Pedagogy Blueprint Agent", {"course_id": state["course_id"], "requirements": req, "material_refs": state.get("material_refs", [])}, CourseBlueprintSchema, mock)
    blueprint.source_refs = [x.get("id", "") for x in state.get("material_refs", []) if x.get("id")]
    return {"blueprint": blueprint.model_dump(), "completed_nodes": ["pedagogy_blueprint_agent"], "status": "waiting_human"}


def build_blueprint_graph():
    graph = StateGraph(CourseGraphState)
    graph.add_node("requirement_analysis_agent", requirement_node)
    graph.add_node("material_analysis_agent", material_analysis_node)
    graph.add_node("pedagogy_blueprint_agent", pedagogy_blueprint_node)
    graph.add_edge(START, "requirement_analysis_agent")
    graph.add_edge("requirement_analysis_agent", "material_analysis_agent")
    graph.add_edge("material_analysis_agent", "pedagogy_blueprint_agent")
    graph.add_edge("pedagogy_blueprint_agent", END)
    return graph.compile(checkpointer=MemorySaver())
