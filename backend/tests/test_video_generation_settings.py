from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import CourseProject, GenerationEvent, GenerationRun
from app.services.video_generation_settings_service import (
    VideoGenerationSettingsPatch,
    apply_video_generation_settings,
    preferred_video_resolution,
    reconcile_video_generation_preferences,
)


@pytest.fixture
async def settings_course(client, auth_headers):
    from agent_pipeline_helpers import ready_course

    return await ready_course(client, auth_headers, title="视频分辨率设置事务课程")


@pytest.mark.asyncio
async def test_existing_nested_resolution_is_persisted_immutably(settings_course):
    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        first = await apply_video_generation_settings(
            db, course, VideoGenerationSettingsPatch(preferred_resolution="854x480")
        )
        await db.commit()
        assert first.changed

    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        original_settings = course.settings_json
        update = await apply_video_generation_settings(
            db, course, VideoGenerationSettingsPatch(preferred_resolution="1280x720")
        )
        assert course.settings_json is not original_settings
        await db.commit()
        assert update.previous_resolution == "854x480"
        assert update.resolution == "1280x720"
        assert update.changed

    async with SessionLocal() as db:
        persisted = await db.get(CourseProject, settings_course)
        assert preferred_video_resolution(persisted) == "1280x720"


@pytest.mark.asyncio
async def test_repeated_resolution_is_successful_no_change(settings_course):
    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        await apply_video_generation_settings(
            db, course, VideoGenerationSettingsPatch(preferred_resolution="1280x720")
        )
        await db.commit()

    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        update = await apply_video_generation_settings(
            db, course, VideoGenerationSettingsPatch(preferred_resolution="1280x720")
        )
        assert not update.changed
        assert course not in db.sync_session.dirty


@pytest.mark.asyncio
async def test_reconciliation_replays_latest_completed_setting_event(settings_course):
    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        await apply_video_generation_settings(
            db, course, VideoGenerationSettingsPatch(preferred_resolution="854x480")
        )
        await db.commit()
        run = GenerationRun(
            course_id=settings_course,
            thread_id=f"resolution-repair-{settings_course}",
            run_type="task",
            trigger_type="message",
            status="completed",
        )
        db.add(run)
        await db.flush()
        db.add(GenerationEvent(
            run_id=run.id,
            event_type="video_generation.setting.updated",
            data_json={
                "course_id": settings_course,
                "payload": {"resolution": "1280x720"},
            },
        ))
        await db.commit()

    async with SessionLocal() as db:
        report = await reconcile_video_generation_preferences(db)
        assert report["repaired"] >= 1

    async with SessionLocal() as db:
        repaired = await db.get(CourseProject, settings_course)
        assert preferred_video_resolution(repaired) == "1280x720"
        latest = await db.scalar(select(GenerationEvent).where(
            GenerationEvent.run_id == run.id,
        ))
        assert latest is not None

    async with SessionLocal() as db:
        second = await reconcile_video_generation_preferences(db)
        assert second["repaired"] == 0


@pytest.mark.asyncio
async def test_video_script_setting_run_commits_before_success_event(
    client, auth_headers, settings_course,
):
    from agent_pipeline_helpers import wait_tasks_terminal

    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        await apply_video_generation_settings(
            db, course, VideoGenerationSettingsPatch(preferred_resolution="854x480")
        )
        await db.commit()

    response = await client.post(
        f"/api/v1/courses/{settings_course}/tasks/video_script/messages",
        headers=auth_headers,
        json={"content": "把分辨率调成720"},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    await wait_tasks_terminal(client, auth_headers, settings_course)

    task_response = await client.get(
        f"/api/v1/courses/{settings_course}/tasks/video_script",
        headers=auth_headers,
    )
    assert task_response.status_code == 200
    assert task_response.json()["preferred_video_resolution"] == "1280x720"

    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        assert preferred_video_resolution(course) == "1280x720"
        events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == run_id,
        ).order_by(GenerationEvent.id)))
    setting_event = next(event for event in events if event.event_type == "video_generation.setting.updated")
    assert setting_event.data_json["payload"] == {
        "resolution": "1280x720",
        "previous_resolution": "854x480",
        "changed": True,
    }
    assert next(
        event.id for event in events if event.event_type == "video_generation.setting.updated"
    ) < next(event.id for event in events if event.event_type == "agent_message_completed")


@pytest.mark.asyncio
async def test_setting_commit_failure_emits_no_false_success(
    client, auth_headers, settings_course, monkeypatch,
):
    from agent_pipeline_helpers import wait_tasks_terminal
    from app.services import course_task_service

    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        await apply_video_generation_settings(
            db, course, VideoGenerationSettingsPatch(preferred_resolution="854x480")
        )
        await db.commit()

    async def fail_setting_write(*_args, **_kwargs):
        raise RuntimeError("simulated settings commit failure")

    monkeypatch.setattr(course_task_service, "apply_video_generation_settings", fail_setting_write)
    response = await client.post(
        f"/api/v1/courses/{settings_course}/tasks/video_script/messages",
        headers=auth_headers,
        json={"content": "把分辨率调成720"},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    await wait_tasks_terminal(client, auth_headers, settings_course)

    async with SessionLocal() as db:
        course = await db.get(CourseProject, settings_course)
        assert preferred_video_resolution(course) == "854x480"
        events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == run_id,
        )))
    assert not any(event.event_type == "video_generation.setting.updated" for event in events)
    assert not any(event.event_type == "agent_message_completed" for event in events)
    assert any(event.event_type == "agent_message_failed" for event in events)
