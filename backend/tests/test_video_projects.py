from __future__ import annotations

import pytest
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_pipeline_helpers import ready_course
from app.api.v1 import video_projects as video_projects_api
from app.core.database import SessionLocal
from app.models.entities import CourseProject, CourseTask, GenerationRun, VideoGenerationQuote, VideoSceneJob
from app.schemas.video import VideoGenerationQuoteResponse
from app.services.course_task_service import _refresh_course_status


@pytest.mark.asyncio
async def test_video_center_lists_owned_projects_and_workspace(client, auth_headers):
    course_id = await ready_course(client, auth_headers, title="视频中心聚合测试")

    listing = await client.get("/api/v1/video-projects", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    item = next(row for row in listing.json()["items"] if row["course"]["id"] == course_id)
    assert item["course"]["title"] == "视频中心聚合测试"
    assert item["status"] == "ready"
    assert item["script"]["version"] >= 1

    workspace = await client.get(f"/api/v1/video-projects/{course_id}", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["task"]["task_type"] == "video_generation"
    assert workspace.json()["summary"]["memory_revision"] >= 1


@pytest.mark.asyncio
async def test_video_agent_consult_reads_memory_without_creating_billable_work(client, auth_headers):
    course_id = await ready_course(client, auth_headers, title="视频 Agent 咨询测试")

    response = await client.post(
        f"/api/v1/video-projects/{course_id}/agent/messages",
        headers=auth_headers,
        json={"content": "请说明当前视频状态", "client_message_id": "consult-1"},
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["outcome"] == "consult"
    assert payload["pending_action"] is None
    assert payload["memory_revision"] >= 1

    async with SessionLocal() as db:
        run = await db.get(GenerationRun, payload["run_id"])
        quote_count = await db.scalar(select(VideoGenerationQuote).where(
            VideoGenerationQuote.course_id == course_id,
        ).with_only_columns(VideoGenerationQuote.id).limit(1))
        job_count = await db.scalar(select(VideoSceneJob).where(
            VideoSceneJob.course_id == course_id,
        ).with_only_columns(VideoSceneJob.id).limit(1))
    assert run and run.status == "completed"
    assert run.memory_revision == payload["memory_revision"]
    assert run.context_hash
    assert quote_count is None
    assert job_count is None


@pytest.mark.asyncio
async def test_video_failure_does_not_change_course_delivery_status(client, auth_headers):
    course_id = await ready_course(client, auth_headers, title="视频状态解耦测试")
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course_id)))
        for task in tasks:
            task.status = "approved" if task.task_type != "video_generation" else "failed"
        await _refresh_course_status(db, course)
        await db.commit()
        assert course.status == "completed"


@pytest.mark.asyncio
async def test_video_agent_requires_single_confirmation_before_generation(client, auth_headers, monkeypatch):
    course_id = await ready_course(client, auth_headers, title="视频 Agent 确认测试")

    async def fake_quote(db, task, owner_id, request):
        return VideoGenerationQuoteResponse(
            quote_id="quote-confirm-once", expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            script_version=1, model_config_id="video-model", model_name="测试视频模型",
            resolution="1280x720", scene_count=2, reusable_scene_count=0,
            duration_seconds=20, estimated_tokens=200, estimated_cost_fen=40,
            maximum_cost_fen=40, scenes=[],
        )

    async def fake_generation(db, task, request):
        run = GenerationRun(
            course_id=task.course_id, course_task_id=task.id, thread_id=str(uuid4()),
            run_type="task", trigger_type=request.action, status="queued",
        )
        db.add(run)
        await db.flush()
        task.active_run_id = run.id
        task.status = "queued"
        return run

    monkeypatch.setattr(video_projects_api, "create_video_generation_quote", fake_quote)
    monkeypatch.setattr(video_projects_api, "create_seedance_video_run", fake_generation)
    monkeypatch.setattr(video_projects_api, "start_task_run", lambda _run_id: None)

    planned = await client.post(
        f"/api/v1/video-projects/{course_id}/agent/messages", headers=auth_headers,
        json={"content": "帮我生成视频"},
    )
    assert planned.status_code == 202, planned.text
    pending = planned.json()["pending_action"]
    assert planned.json()["outcome"] == "needs_confirmation"
    assert pending["quote"]["maximum_cost_fen"] == 40
    async with SessionLocal() as db:
        assert await db.scalar(select(VideoSceneJob.id).where(VideoSceneJob.course_id == course_id)) is None

    confirmed = await client.post(
        f"/api/v1/video-projects/{course_id}/agent/actions/{pending['request_id']}",
        headers=auth_headers, json={"choice": "confirm"},
    )
    assert confirmed.status_code == 202, confirmed.text
    duplicate = await client.post(
        f"/api/v1/video-projects/{course_id}/agent/actions/{pending['request_id']}",
        headers=auth_headers, json={"choice": "confirm"},
    )
    assert duplicate.status_code == 409
