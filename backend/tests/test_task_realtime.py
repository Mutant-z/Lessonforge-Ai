import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

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


@pytest.mark.asyncio
async def test_task_event_retries_sqlite_lock_without_failing_generation(monkeypatch):
    class LockedSession:
        attempts = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, model, identifier):
            if model is course_task_service.GenerationRun:
                return SimpleNamespace(id=identifier, course_id="course-1", course_task_id="task-1", status="running")
            return SimpleNamespace(id="task-1", task_type="lesson_plan", status="running", progress=30)

        def add(self, _item):
            return None

        async def commit(self):
            self.attempts += 1
            if self.attempts < 3:
                raise OperationalError("commit", {}, Exception("database is locked"))

    session = LockedSession()
    monkeypatch.setattr(course_task_service, "SessionLocal", lambda: session)

    await course_task_service._publish_task_event("run-1", "task_activity_updated", progress=31)

    assert session.attempts == 3
