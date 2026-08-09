"""Serializable LangGraph state for the PPT agent runtime."""
from typing import Any, Literal, TypedDict


PPTIntent = Literal[
    "GENERATE", "MODIFY", "LOCAL_REGENERATE", "GLOBAL_OPTIMIZE",
    "STYLE_CHANGE", "TEMPLATE_SWITCH", "CONTENT_UPDATE", "IMAGE_UPDATE",
    "VISUAL_QA", "EXPORT",
]
ContentPolicy = Literal["preserve", "restore", "edit"]


class PPTAgentState(TypedDict, total=False):
    run_id: str
    course_id: str
    artifact_id: str | None
    user_request: str
    intent: PPTIntent
    trigger_type: str
    course_context: dict[str, Any]
    current_ppt: dict[str, Any]
    teaching_design: dict[str, Any]
    template_id: str
    template_profile: dict[str, Any]
    presentation_plan: dict[str, Any]
    slides: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    selected_slide_ids: list[str]
    affected_slide_ids: list[str]
    draft_artifact_id: str | None
    mutation_applied: bool
    content_policy: ContentPolicy
    baseline_content_hashes: dict[str, str]
    render_coverage: dict[str, dict[str, Any]]
    expected_visual_requests: list[dict[str, Any]]
    generated_asset_ids: list[str]
    mutation_evidence: list[dict[str, Any]]
    publishable: bool
    blocking_issues: list[dict[str, Any]]
    selected_skills: list[str]
    loaded_skills: dict[str, str]
    tool_results: list[dict[str, Any]]
    generated_pptx: str | None
    rendered_slides: dict[str, str]
    qa_results: list[dict[str, Any]]
    repair_round: int
    current_slide: str | None
    current_agent: str
    planned_agents: list[str]
    remaining_agents: list[str]
    completed_agents: list[str]
    next_agent: str | None
    messages: list[dict[str, Any]]
    token_usage: dict[str, Any]
    status: str
    error: dict[str, Any] | None
