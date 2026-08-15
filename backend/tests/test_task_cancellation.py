from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import CourseTask, GenerationEvent, GenerationRun
from app.services.course_task_service import ensure_course_tasks


async def test_cancel_orphaned_video_run_persists_terminal_state_and_event(client, auth_headers):
    created = await client.post(
        "/api/v1/courses",
        headers=auth_headers,
        json={
            "title": "视频取消回归",
            "subject": "物理",
            "grade_level": "八年级",
            "audience": "八年级学生",
            "duration_minutes": 10,
            "scenario": "课堂讲解",
            "language": "中文",
        },
    )
    assert created.status_code == 201
    course_id = created.json()["id"]

    async with SessionLocal() as db:
        await ensure_course_tasks(db, course_id)
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "video_generation",
        ))
        run = GenerationRun(
            course_id=course_id,
            course_task_id=task.id,
            thread_id="orphaned-video-run",
            run_type="task",
            status="running",
            progress=28,
        )
        db.add(run)
        await db.flush()
        task.status = "running"
        task.progress = 28
        task.active_run_id = run.id
        await db.commit()
        run_id = run.id

    response = await client.post(
        f"/api/v1/courses/{course_id}/tasks/video_generation/cancel",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    async with SessionLocal() as db:
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "video_generation",
        ))
        run = await db.get(GenerationRun, run_id)
        event = await db.scalar(select(GenerationEvent).where(
            GenerationEvent.run_id == run_id,
            GenerationEvent.event_type == "task_status_changed",
        ).order_by(GenerationEvent.id.desc()))
        assert task.status == "cancelled"
        assert task.active_run_id is None
        assert run.status == "cancelled"
        assert run.finished_at is not None
        assert event.data_json["status"] == "cancelled"
        assert event.data_json["progress"] == 28
