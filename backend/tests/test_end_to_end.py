import asyncio

import pytest


@pytest.mark.asyncio
async def test_full_api_generation_and_export(client, auth_headers):
    course_model = (await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "课程默认模型", "provider": "mock", "base_url": "mock://local",
            "model_name": "mock-course", "timeout_seconds": 30, "is_active": True,
        },
    )).json()
    module_model = (await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "模块修订模型", "provider": "mock", "base_url": "mock://local",
            "model_name": "mock-module", "timeout_seconds": 30, "is_active": False,
        },
    )).json()
    course = (await client.post(
        "/api/v1/courses",
        headers=auth_headers,
        json={"title": "勾股定理", "subject": "初中数学", "grade_level": "八年级", "audience": "已学习三角形基础的学生", "duration_minutes": 10, "scenario": "课堂讲解", "course_task": "解释勾股定理并完成基础判断", "model_config_id": course_model["id"]},
    )).json()
    blueprint = await client.post(f"/api/v1/courses/{course['id']}/blueprint/generate", headers=auth_headers)
    assert blueprint.status_code == 201, blueprint.text
    approved = await client.post(f"/api/v1/blueprints/{blueprint.json()['id']}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    project_response = await client.get(f"/api/v1/courses/{course['id']}/project", headers=auth_headers)
    assert project_response.status_code == 200, project_response.text
    from app.services.course_task_service import schedule_ready_tasks
    await schedule_ready_tasks(course["id"])
    for _ in range(200):
        project = (await client.get(f"/api/v1/courses/{course['id']}/project", headers=auth_headers)).json()
        if all(task["status"] in {"review", "approved", "stale", "failed", "ready_to_generate"} for task in project["tasks"]):
            break
        await asyncio.sleep(0.02)
    assert all(task["status"] in {"review", "approved", "stale", "ready_to_generate"} for task in project["tasks"]), project
    assert project["quality"]["score"] is not None, project
    artifacts = await client.get(f"/api/v1/courses/{course['id']}/artifacts", headers=auth_headers)
    assert {"lesson_plan", "ppt", "task_sheet", "exercise", "video_script", "verbatim", "quality_report", "citation_report"} <= {x["artifact_type"] for x in artifacts.json()}
    assert next(x for x in artifacts.json() if x["artifact_type"] == "ppt")["model_name"] == "mock-course"
    switched = await client.patch(
        f"/api/v1/courses/{course['id']}/modules/ppt/chat/model",
        headers=auth_headers,
        json={"model_config_id": module_model["id"]},
    )
    assert switched.status_code == 200
    chat = await client.post(f"/api/v1/courses/{course['id']}/modules/ppt/chat/send", headers=auth_headers, json={"instruction": "第 3 页压缩为三个要点", "path": "slides.S03", "preserve_locked_content": True})
    assert chat.status_code == 201 and chat.json()["artifact"]["version"] == 2
    assert chat.json()["artifact"]["model_name"] == "mock-module"
    locked = await client.post(
        f"/api/v1/artifacts/{chat.json()['artifact']['id']}/lock",
        headers=auth_headers,
        json={"json_path": "$"},
    )
    assert locked.status_code == 200
    blocked = await client.post(
        f"/api/v1/courses/{course['id']}/modules/ppt/chat/send",
        headers=auth_headers,
        json={"instruction": "覆盖已锁定产物", "path": "", "preserve_locked_content": True},
    )
    assert blocked.status_code == 409
    versions = await client.get(
        f"/api/v1/artifacts/{chat.json()['artifact']['id']}/versions", headers=auth_headers
    )
    assert [item["version"] for item in versions.json()] == [2, 1]
    history = await client.get(f"/api/v1/courses/{course['id']}/modules/ppt/chat/history", headers=auth_headers)
    assert [x["role"] for x in history.json()["messages"]] == ["user", "assistant"]
    assert history.json()["model_config_id"] == module_model["id"]
    deleted = await client.delete(
        f"/api/v1/settings/models/{module_model['id']}", headers=auth_headers
    )
    assert deleted.status_code == 200
    fallback = await client.get(
        f"/api/v1/courses/{course['id']}/modules/ppt/chat/history", headers=auth_headers
    )
    assert fallback.json()["model_config_id"] == course_model["id"]
    exported = await client.post(f"/api/v1/courses/{course['id']}/exports", headers=auth_headers)
    assert exported.status_code == 201, exported.text
    assert exported.json()["checksum"] and exported.json()["manifest"]["blueprint_version"] == 1
