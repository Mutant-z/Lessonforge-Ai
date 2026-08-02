import asyncio

import pytest


async def wait_for_project(client, headers, course_id, predicate, attempts=200):
    payload = None
    for _ in range(attempts):
        response = await client.get(f"/api/v1/courses/{course_id}/project", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        if predicate(payload):
            return payload
        await asyncio.sleep(0.02)
    return payload


@pytest.mark.asyncio
async def test_intent_confirmation_creates_and_runs_six_independent_tasks(client, auth_headers):
    await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "项目 Mock",
            "provider": "mock",
            "base_url": "mock://project",
            "model_name": "mock-project",
            "timeout_seconds": 30,
            "is_active": True,
        },
    )
    session = (await client.post("/api/v1/course-intakes", headers=auth_headers)).json()
    sent = await client.post(
        f"/api/v1/course-intakes/{session['id']}/messages",
        headers=auth_headers,
        json={
            "content": "为八年级学生制作一节10分钟的《阿基米德原理》物理微课，用于课堂讲解，重点解释浮力来源并完成基础判断。",
            "expected_revision": 0,
        },
    )
    assert sent.status_code == 202
    ready = None
    for _ in range(100):
        ready = (await client.get(f"/api/v1/course-intakes/{session['id']}", headers=auth_headers)).json()
        if ready["status"] == "ready":
            break
        await asyncio.sleep(0.02)
    confirmed = await client.post(
        f"/api/v1/course-intakes/{session['id']}/confirm",
        headers=auth_headers,
        json={"expected_revision": ready["current_revision"], "idempotency_key": f"project-{session['id']}"},
    )
    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()["project_status"] == "planning"
    assert len(confirmed.json()["tasks"]) == 6
    course_id = confirmed.json()["course_id"]

    project = await wait_for_project(
        client,
        auth_headers,
        course_id,
        lambda item: all(task["status"] == "review" for task in item["tasks"]),
    )
    assert project["planning"]["status"] == "ready", project
    assert [task["task_type"] for task in project["tasks"]] == [
        "lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim",
    ]
    assert all(task["current_artifact"] for task in project["tasks"])
    assert project["quality"]["score"] is not None

    repeated = await client.post(
        f"/api/v1/course-intakes/{session['id']}/confirm",
        headers=auth_headers,
        json={"expected_revision": ready["current_revision"], "idempotency_key": f"project-{session['id']}"},
    )
    assert repeated.status_code == 202
    assert len(repeated.json()["tasks"]) == 6


@pytest.mark.asyncio
async def test_task_message_creates_version_and_marks_dependents_stale(client, auth_headers):
    course = (await client.post(
        "/api/v1/courses",
        headers=auth_headers,
        json={
            "title": "平行线性质",
            "subject": "数学",
            "grade_level": "七年级",
            "audience": "已学习基本几何概念的学生",
            "duration_minutes": 12,
            "scenario": "课堂讲解",
            "course_task": "解释平行线性质并完成基础判断",
        },
    )).json()
    blueprint = (await client.post(f"/api/v1/courses/{course['id']}/blueprint/generate", headers=auth_headers)).json()
    await client.post(f"/api/v1/blueprints/{blueprint['id']}/approve", headers=auth_headers)
    await client.get(f"/api/v1/courses/{course['id']}/project", headers=auth_headers)
    from app.services.course_task_service import schedule_ready_tasks
    await schedule_ready_tasks(course["id"])

    project = await wait_for_project(
        client,
        auth_headers,
        course["id"],
        lambda item: all(task["status"] == "review" for task in item["tasks"]),
    )
    assert all(task["status"] == "review" for task in project["tasks"]), project
    sent = await client.post(
        f"/api/v1/courses/{course['id']}/tasks/ppt/messages",
        headers=auth_headers,
        json={"content": "将核心概念页压缩为三个要点"},
    )
    assert sent.status_code == 202, sent.text
    concurrent = await client.post(
        f"/api/v1/courses/{course['id']}/tasks/ppt/messages",
        headers=auth_headers,
        json={"content": "同时再改一次"},
    )
    assert concurrent.status_code == 409

    project = await wait_for_project(
        client,
        auth_headers,
        course["id"],
        lambda item: next(task for task in item["tasks"] if task["task_type"] == "ppt")["current_artifact"]["version"] == 2,
    )
    statuses = {task["task_type"]: task["status"] for task in project["tasks"]}
    assert statuses["ppt"] == "review"
    assert statuses["video_script"] == "stale"
    assert statuses["verbatim"] == "stale"

    synced = await client.post(
        f"/api/v1/courses/{course['id']}/tasks/video_script/runs",
        headers=auth_headers,
        json={"action": "sync_dependencies"},
    )
    assert synced.status_code == 202
    project = await wait_for_project(
        client,
        auth_headers,
        course["id"],
        lambda item: next(task for task in item["tasks"] if task["task_type"] == "video_script")["current_artifact"]["version"] == 2,
    )
    assert next(task for task in project["tasks"] if task["task_type"] == "verbatim")["status"] == "stale"
