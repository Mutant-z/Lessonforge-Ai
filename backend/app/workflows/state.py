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
    completed_nodes: Annotated[list[str], add]
    status: str
