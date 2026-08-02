from operator import add
from typing import Annotated, TypedDict


class CourseGraphState(TypedDict, total=False):
    course_id: str
    run_id: str
    thread_id: str
    requirements: dict
    requirement_issues: list[dict]
    material_refs: list[dict]
    blueprint: dict
    blueprint_version: int
    blueprint_approved: bool
    lesson_plan: dict
    ppt: dict
    task_sheet: dict
    exercise: dict
    video_script: dict
    verbatim: dict
    quality_report: dict
    quality_issues: list[dict]
    locked_paths: list[str]
    retry_counts: dict[str, int]
    completed_nodes: Annotated[list[str], add]
    status: str
    error: dict | None
