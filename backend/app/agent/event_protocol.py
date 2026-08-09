"""Canonical PPT agent event protocol and legacy compatibility mapping."""
from datetime import datetime, timezone
from typing import Any


LEGACY_EVENT_TYPES = {
    "pipeline_started": "run.started", "pipeline_completed": "run.completed",
    "pipeline_failed": "run.failed", "agent_started": "agent.started",
    "agent_status_delta": "agent.progress", "agent_completed": "agent.completed",
    "tool_call_started": "tool.started", "tool_call_delta": "tool.progress",
    "tool_call_completed": "tool.completed", "artifact_started": "artifact.created",
    "artifact_patch": "artifact.updated", "artifact_created": "artifact.created",
    "qa_issue_found": "qa.issue", "qa_completed": "qa.completed",
    "revision_started": "repair.started", "revision_completed": "repair.completed",
    "task_paused": "run.paused", "task_resumed": "run.resumed",
}


def canonical_event(*, event_id: int, event_type: str, data: dict[str, Any], created_at=None) -> dict[str, Any]:
    canonical_type = LEGACY_EVENT_TYPES.get(event_type, event_type)
    agent_key = data.get("agent_key") or data.get("agent_type") or ""
    slide_id = data.get("slide_id") or (data.get("issue") or {}).get("slide_id") or ""
    known = {"agent", "message", "progress", "artifact", "slide", "payload"}
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {
        key: value for key, value in data.items()
        if key not in known and key not in {"course_id", "run_id", "pipeline_run_id", "task_id", "task_type", "sequence", "timestamp"}
    }
    return {
        "event_id": event_id, "sequence": event_id, "run_id": str(data.get("run_id") or ""),
        "timestamp": data.get("timestamp") or (created_at.isoformat() if created_at else datetime.now(timezone.utc).isoformat()),
        "type": canonical_type,
        "agent": data.get("agent") or ({"id": agent_key, "name": data.get("agent_label") or agent_key} if agent_key else {}),
        "message": data.get("message") or data.get("summary") or data.get("text") or "",
        "progress": data.get("progress") if isinstance(data.get("progress"), dict) else ({"current": data.get("progress")} if data.get("progress") is not None else {}),
        "artifact": data.get("artifact") or ({"artifact_id": data.get("artifact_id"), "type": data.get("artifact_type")} if data.get("artifact_id") else {}),
        "slide": data.get("slide") or ({"slide_id": slide_id, "page": data.get("slide_index")} if slide_id else {}),
        "payload": payload, "legacy_type": event_type if canonical_type != event_type else None,
    }
