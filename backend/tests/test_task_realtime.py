import asyncio

import pytest

from app.services import course_task_service


@pytest.mark.asyncio
async def test_generation_heartbeat_advances_before_work_completes(monkeypatch):
    updates = []

    async def capture(run_id, phase, progress, phase_status="running", **data):
        updates.append((phase, progress, phase_status, data.get("elapsed_ms", 0)))

    monkeypatch.setattr(course_task_service, "_publish_activity", capture)
    monkeypatch.setattr(course_task_service, "GENERATION_HEARTBEAT_SECONDS", 0.01)

    result, elapsed = await course_task_service._run_with_generation_heartbeat(
        "run-slow",
        asyncio.sleep(0.035, result="complete"),
    )

    assert result == "complete"
    assert elapsed >= 20
    assert [item[1] for item in updates[:3]] == [30, 31, 32]
    assert all(item[0] == "generating" for item in updates)
