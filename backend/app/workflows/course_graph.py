from app.services.ppt_validation_service import PPTXPackageValidator
from app.renderers.ppt_visual_qa import PPTVisualQARenderer
from app.renderers.pptx_renderer import render_pptx
from pathlib import Path
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.generators import generate_structured, make_blueprint, make_exercises, make_lesson_plan, make_ppt, make_task_sheet, make_verbatim, make_video_script
from app.models.entities import CourseProject
from app.schemas.artifact import LessonPlanContent, PPTContent, VideoScriptContent
from app.schemas.blueprint import CourseBlueprintSchema
from app.workflows.state import CourseGraphState


async def lesson_plan_node(state: CourseGraphState):
    bp = CourseBlueprintSchema.model_validate(state["blueprint"])
    value = await generate_structured("Lesson Plan Agent", {"course_id": state["course_id"], "blueprint": state["blueprint"]}, type(make_lesson_plan(bp)), make_lesson_plan(bp))
    return {"lesson_plan": value.model_dump(), "completed_nodes": ["lesson_plan_agent"]}


async def ppt_node(state: CourseGraphState):
    bp = CourseBlueprintSchema.model_validate(state["blueprint"])
    value = await generate_structured("PPT Agent", {"course_id": state["course_id"], "blueprint": state["blueprint"]}, PPTContent, make_ppt(bp))
    return {"ppt": value.model_dump(), "completed_nodes": ["ppt_agent"]}


async def task_sheet_node(state: CourseGraphState):
    bp = CourseBlueprintSchema.model_validate(state["blueprint"])
    mock = make_task_sheet(bp)
    value = await generate_structured("Task Sheet Agent", {"course_id": state["course_id"], "blueprint": state["blueprint"]}, type(mock), mock)
    return {"task_sheet": value.model_dump(), "completed_nodes": ["task_sheet_agent"]}


async def exercise_node(state: CourseGraphState):
    bp = CourseBlueprintSchema.model_validate(state["blueprint"])
    mock = make_exercises(bp)
    value = await generate_structured("Exercise Agent", {"course_id": state["course_id"], "blueprint": state["blueprint"]}, type(mock), mock)
    return {"exercise": value.model_dump(), "completed_nodes": ["exercise_agent"]}


async def video_node(state: CourseGraphState):
    bp = CourseBlueprintSchema.model_validate(state["blueprint"])
    lesson_plan = LessonPlanContent.model_validate(state["lesson_plan"])
    ppt = PPTContent.model_validate(state["ppt"])
    mock = make_video_script(bp, lesson_plan, ppt)
    value = await generate_structured("Video Script Agent", {"course_id": state["course_id"], "blueprint": state["blueprint"], "lesson_plan": state["lesson_plan"], "ppt": state["ppt"]}, VideoScriptContent, mock)
    return {"video_script": value.model_dump(), "completed_nodes": ["video_script_agent"]}


async def verbatim_node(state: CourseGraphState):
    bp, ppt, script = CourseBlueprintSchema.model_validate(state["blueprint"]), PPTContent.model_validate(state["ppt"]), VideoScriptContent.model_validate(state["video_script"])
    mock = make_verbatim(bp, ppt, script)
    value = await generate_structured("Verbatim Agent", {"course_id": state["course_id"], "blueprint": state["blueprint"], "ppt": state["ppt"], "video_script": state["video_script"]}, type(mock), mock)
    return {"verbatim": value.model_dump(), "completed_nodes": ["verbatim_agent"]}


async def qa_node(state: CourseGraphState):
    issues = list(state.get("quality_issues", []))
    if state.get("ppt"):
        try:
            ppt_content = PPTContent.model_validate(state["ppt"]).model_dump()
            temp_dir = Path("/tmp/lessonforge_qa") / str(state.get("course_id", "default"))
            temp_dir.mkdir(parents=True, exist_ok=True)
            pptx_path = temp_dir / "course_deck.pptx"
            render_pptx(title=state.get("requirements", {}).get("title", "PPT"), content=ppt_content, output=pptx_path)
            package_issues = PPTXPackageValidator.validate_pptx(pptx_path)
            for issue in package_issues:
                issues.append({
                    "severity": "critical" if issue.severity == "error" else "warning",
                    "field": "ppt_ooxml_package",
                    "description": f"PPTX 包校验问题 [{issue.component}]: {issue.message}"
                })
            if PPTVisualQARenderer.is_available():
                try:
                    slide_imgs = PPTVisualQARenderer.convert_pptx_to_images(pptx_path, temp_dir / "thumbnails")
                    state["ppt_slide_thumbnails"] = [str(p) for p in slide_imgs]
                except Exception as e:
                    issues.append({
                        "severity": "warning",
                        "field": "ppt_visual_qa",
                        "description": f"Visual QA 缩略图渲染警告: {str(e)}"
                    })
        except Exception as e:
            issues.append({
                "severity": "critical",
                "field": "ppt_render",
                "description": f"PPTX 渲染及校验失败: {str(e)}"
            })

    score = 100 if not any(x.get("severity") == "critical" for x in issues) else 60
    return {
        "quality_report": {"score": score, "summary": "结构化资源已完成设计与包格式审查"},
        "quality_issues": issues,
        "completed_nodes": ["quality_assurance_agent"],
        "status": "teacher_review"
    }


def route_quality(state: CourseGraphState) -> str:
    critical = any(item.get("severity") == "critical" for item in state.get("quality_issues", []))
    attempts = state.get("retry_counts", {}).get("targeted_rework", 0)
    if critical and attempts < 2:
        return "rework"
    if critical:
        return "human"
    return "pass"


async def rework_router_node(state: CourseGraphState):
    counts = dict(state.get("retry_counts", {}))
    counts["targeted_rework"] = counts.get("targeted_rework", 0) + 1
    return {"retry_counts": counts, "quality_issues": [], "completed_nodes": ["targeted_rework_router"], "status": "reworking"}


async def final_review_node(state: CourseGraphState):
    return {"status": "waiting_human", "completed_nodes": ["final_teacher_review"]}


async def supervisor_node(state: CourseGraphState):
    if not state.get("blueprint_approved"):
        return {"status": "waiting_human", "error": {"message": "课程蓝图尚未确认"}, "completed_nodes": ["supervisor_agent"]}
    return {"status": "running", "completed_nodes": ["supervisor_agent"]}


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


def build_course_graph():
    graph = StateGraph(CourseGraphState)
    graph.add_node("supervisor_agent", supervisor_node)
    graph.add_node("lesson_plan_agent", lesson_plan_node)
    graph.add_node("ppt_agent", ppt_node)
    graph.add_node("task_sheet_agent", task_sheet_node)
    graph.add_node("exercise_agent", exercise_node)
    graph.add_node("video_script_agent", video_node)
    graph.add_node("verbatim_agent", verbatim_node)
    graph.add_node("quality_assurance_agent", qa_node)
    graph.add_node("targeted_rework_router", rework_router_node)
    graph.add_node("final_teacher_review", final_review_node)
    graph.add_edge(START, "supervisor_agent")
    graph.add_edge("supervisor_agent", "lesson_plan_agent")
    graph.add_edge("supervisor_agent", "ppt_agent")
    graph.add_edge("supervisor_agent", "task_sheet_agent")
    graph.add_edge("supervisor_agent", "exercise_agent")
    graph.add_edge(["lesson_plan_agent", "ppt_agent"], "video_script_agent")
    graph.add_edge("video_script_agent", "verbatim_agent")
    graph.add_edge(["lesson_plan_agent", "task_sheet_agent", "exercise_agent", "verbatim_agent"], "quality_assurance_agent")
    graph.add_conditional_edges("quality_assurance_agent", route_quality, {"rework": "targeted_rework_router", "human": "final_teacher_review", "pass": "final_teacher_review"})
    graph.add_edge("targeted_rework_router", "quality_assurance_agent")
    graph.add_edge("final_teacher_review", END)
    return graph.compile(checkpointer=MemorySaver())
