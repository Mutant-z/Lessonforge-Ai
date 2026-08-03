import json
from typing import Any

from sqlalchemy import select

from app.models.entities import Artifact, CourseTask


TASK_PRIORITY = {
    "lesson_plan": ["task_sheet", "ppt", "exercise", "video_script", "verbatim"],
    "ppt": ["lesson_plan", "task_sheet", "video_script", "verbatim", "exercise"],
    "task_sheet": ["lesson_plan", "ppt", "exercise", "video_script", "verbatim"],
    "exercise": ["lesson_plan", "task_sheet", "ppt", "video_script", "verbatim"],
    "video_script": ["ppt", "lesson_plan", "task_sheet", "verbatim", "exercise"],
    "verbatim": ["video_script", "ppt", "lesson_plan", "task_sheet", "exercise"],
}


def _select_fields(artifact_type: str, content: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "lesson_plan": ("objectives", "key_points", "difficulty_points", "resources", "stages", "homework"),
        "ppt": ("theme", "slides"),
        "task_sheet": ("schema_version", "learning_objectives", "tasks", "record_table", "learning_questions", "self_assessment", "extension"),
        "exercise": ("schema_version", "course_info", "paper_settings", "sections", "items"),
        "video_script": ("schema_version", "course_info", "production_settings", "scenes", "segments"),
        "verbatim": ("speaking_rate", "sections"),
    }.get(artifact_type, tuple(content.keys()))
    return {field: content[field] for field in fields if field in content}


def _compact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 600 else value[:597] + "..."
    if isinstance(value, list):
        limit = 16 if depth < 2 else 8
        items = [_compact(item, depth + 1) for item in value[:limit]]
        if len(value) > limit:
            items.append({"truncated_items": len(value) - limit})
        return items
    if isinstance(value, dict):
        return {str(key): _compact(item, depth + 1) for key, item in value.items()}
    return value


def _bounded(value: dict[str, Any], limit: int) -> dict[str, Any]:
    compacted = _compact(value)
    serialized = json.dumps(compacted, ensure_ascii=False)
    if len(serialized) <= limit:
        return compacted
    return {"truncated": True, "content_excerpt": serialized[: max(0, limit - 80)]}


def _reference_conflicts(value: Any, blueprint: dict[str, Any], path: str = "$") -> list[str]:
    valid = {
        "objective": {item.get("id") for item in blueprint.get("objectives", [])},
        "knowledge_point": {item.get("id") for item in blueprint.get("knowledge_points", [])},
        "stage": {item.get("segment_id") for item in blueprint.get("timeline", [])},
    }
    conflicts: list[str] = []

    def visit(item: Any, current_path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{current_path}.{key}"
                reference_type = None
                if key in {"objective_id", "objective_ids"}:
                    reference_type = "objective"
                elif key in {"knowledge_point_id", "knowledge_point_ids"}:
                    reference_type = "knowledge_point"
                elif key == "stage_id":
                    reference_type = "stage"
                if reference_type:
                    references = child if isinstance(child, list) else [child]
                    for reference in references:
                        if reference and reference not in valid[reference_type]:
                            conflicts.append(f"{child_path} 引用了蓝图中不存在的 {reference}")
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{current_path}[{index}]")

    visit(value, path)
    return conflicts[:20]


async def build_project_knowledge_context(
    db,
    task: CourseTask,
    blueprint: dict[str, Any],
    blueprint_version: int,
    profile_context: dict[str, Any],
    context_window_tokens: int | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Build a bounded, course-isolated snapshot of current sibling artifacts."""
    declared_window = context_window_tokens or 100_000
    total_budget = max(512, min(24_000, int(declared_window * 0.20)))
    blueprint_summary = {
        key: blueprint.get(key)
        for key in ("course_identity", "objectives", "knowledge_points", "timeline", "assessment_plan")
        if key in blueprint
    }
    context: dict[str, Any] = {
        "authority_order": [
            "system_schema_and_locks",
            "approved_blueprint",
            "teacher_instruction",
            "current_target_artifact",
            "sibling_artifacts_advisory",
        ],
        "blueprint": {"version": blueprint_version, "summary": _bounded(blueprint_summary, min(8_000, total_budget // 3))},
        "agent_profile_summary": {
            key: profile_context.get(key)
            for key in (
                "project_background", "project_requirement_summary", "learner_profile",
                "content_scope", "required_source_refs", "material_summaries",
            )
            if profile_context.get(key)
        },
        "hard_dependencies": {},
        "sibling_artifacts": {},
        "conflicts": [],
    }
    tasks = list(await db.scalars(select(CourseTask).where(
        CourseTask.course_id == task.course_id,
    )))
    by_type = {item.task_type: item for item in tasks if item.task_type != task.task_type}
    remaining = max(0, total_budget - len(json.dumps(context, ensure_ascii=False)))
    source_versions: dict[str, int] = {}
    for artifact_type in TASK_PRIORITY.get(task.task_type, list(by_type)):
        sibling = by_type.get(artifact_type)
        if not sibling or not sibling.current_artifact_id or remaining < 256:
            continue
        artifact = await db.scalar(select(Artifact).where(
            Artifact.id == sibling.current_artifact_id,
            Artifact.course_id == task.course_id,
            Artifact.artifact_type == artifact_type,
        ))
        if not artifact:
            continue
        allowance = min(5_000, remaining)
        selected = _bounded(_select_fields(artifact_type, artifact.content_json or {}), allowance)
        entry = {"version": artifact.version, "content": selected}
        target = "hard_dependencies" if artifact_type in (task.dependency_types_json or []) else "sibling_artifacts"
        context[target][artifact_type] = entry
        context["conflicts"].extend(
            f"{artifact_type} V{artifact.version}：{item}"
            for item in _reference_conflicts(selected, blueprint)
        )
        source_versions[artifact_type] = artifact.version
        remaining -= len(json.dumps({artifact_type: entry}, ensure_ascii=False))
    return context, source_versions
