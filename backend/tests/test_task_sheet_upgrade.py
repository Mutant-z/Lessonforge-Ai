import asyncio
import json

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Artifact, CourseBlueprint, CourseTask, PromptTemplate
from app.services.course_task_service import schedule_ready_tasks
from app.services.project_knowledge_service import build_project_knowledge_context


async def _wait_for_project(client, headers, course_id, predicate, attempts=240):
    payload = None
    for _ in range(attempts):
        response = await client.get(f"/api/v1/courses/{course_id}/project", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        if predicate(payload):
            return payload
        await asyncio.sleep(0.02)
    raise AssertionError(payload)


async def _generated_course(client, headers, title, marker):
    course = (await client.post(
        "/api/v1/courses",
        headers=headers,
        json={
            "title": title,
            "subject": "物理",
            "grade_level": "八年级",
            "audience": f"{marker} 学生",
            "duration_minutes": 10,
            "scenario": "课堂讲解",
            "course_task": f"{marker} 解释核心概念并完成观察记录",
        },
    )).json()
    blueprint = (await client.post(
        f"/api/v1/courses/{course['id']}/blueprint/generate",
        headers=headers,
    )).json()
    approved = await client.post(f"/api/v1/blueprints/{blueprint['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    await client.get(f"/api/v1/courses/{course['id']}/project", headers=headers)
    await schedule_ready_tasks(course["id"])
    project = await _wait_for_project(
        client, headers, course["id"],
        lambda item: all(
            task["status"] == ("ready_to_generate" if task["task_type"] == "video_generation" else "review")
            for task in item["tasks"]
        ),
    )
    return course, project


def _task(project, task_type):
    return next(item for item in project["tasks"] if item["task_type"] == task_type)


@pytest.mark.asyncio
async def test_knowledge_snapshot_is_course_isolated_and_soft_versions_propagate(client, auth_headers):
    course_a, project_a = await _generated_course(client, auth_headers, "浮力课程 A", "COURSE_A_ONLY")
    course_b, project_b = await _generated_course(client, auth_headers, "浮力课程 B", "COURSE_B_ONLY")

    for project, marker in ((project_a, "COURSE_A_ONLY"), (project_b, "COURSE_B_ONLY")):
        lesson = _task(project, "lesson_plan")["current_artifact"]
        revised = dict(lesson["content_json"])
        revised["content_analysis"] = f"{marker} · {revised['content_analysis']}"
        response = await client.patch(
            f"/api/v1/artifacts/{lesson['id']}", headers=auth_headers,
            json={"content_json": revised, "content_markdown": lesson["content_markdown"], "change_summary": marker},
        )
        assert response.status_code == 201, response.text

    exercise_a = _task(project_a, "exercise")["current_artifact"]
    exercise_payload = json.loads(json.dumps(exercise_a["content_json"], ensure_ascii=False))
    exercise_payload["sections"][0]["blocks"][0]["objective_ids"] = ["OBJ-NOT-IN-BLUEPRINT"]
    exercise_updated = await client.patch(
        f"/api/v1/artifacts/{exercise_a['id']}", headers=auth_headers,
        json={"content_json": exercise_payload, "content_markdown": exercise_a["content_markdown"], "change_summary": "构造冲突引用"},
    )
    assert exercise_updated.status_code == 422, exercise_updated.text
    async with SessionLocal() as db:
        exercise_task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_a["id"], CourseTask.task_type == "exercise",
        ))
        invalid_exercise = Artifact(
            course_id=course_a["id"], artifact_type="exercise", version=exercise_a["version"] + 1,
            blueprint_version=exercise_a["blueprint_version"], content_json=exercise_payload,
            content_markdown=exercise_a["content_markdown"], model_name="test-conflict",
            prompt_version="v2", change_summary="构造知识快照冲突",
            source_versions_json={}, agent_profile_id=exercise_task.current_agent_profile_id,
        )
        db.add(invalid_exercise)
        await db.flush()
        exercise_task.current_artifact_id = invalid_exercise.id
        await db.commit()

    async with SessionLocal() as db:
        task_a = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_a["id"], CourseTask.task_type == "task_sheet",
        ))
        blueprint_a = await db.scalar(select(CourseBlueprint).where(
            CourseBlueprint.course_id == course_a["id"], CourseBlueprint.status == "approved",
        ))
        context, versions = await build_project_knowledge_context(
            db, task_a, blueprint_a.content_json, blueprint_a.version, {}, 120_000,
        )
    serialized = json.dumps(context, ensure_ascii=False)
    assert "COURSE_A_ONLY" in serialized
    assert "COURSE_B_ONLY" not in serialized
    assert versions["lesson_plan"] == 2
    assert versions["exercise"] == 2
    assert "task_sheet" not in versions
    assert "OBJ-NOT-IN-BLUEPRINT" in "\n".join(context["conflicts"])
    # 上下文包含 15 页 PPT slides，阈值按该规模放宽（仍是防失控的软上限）
    assert len(serialized) <= 28_000

    refreshed_a = (await client.get(f"/api/v1/courses/{course_a['id']}/project", headers=auth_headers)).json()
    assert _task(refreshed_a, "task_sheet")["status"] == "review"
    lesson_v2 = _task(refreshed_a, "lesson_plan")["current_artifact"]
    lesson_payload = dict(lesson_v2["content_json"])
    lesson_payload["content_analysis"] = "COURSE_A_ONLY_LATEST"
    updated = await client.patch(
        f"/api/v1/artifacts/{lesson_v2['id']}", headers=auth_headers,
        json={"content_json": lesson_payload, "content_markdown": lesson_v2["content_markdown"], "change_summary": "教学设计更新"},
    )
    assert updated.status_code == 201, updated.text
    after_lesson_update = (await client.get(f"/api/v1/courses/{course_a['id']}/project", headers=auth_headers)).json()
    assert _task(after_lesson_update, "task_sheet")["status"] == "review"

    task_sheet_before = _task(after_lesson_update, "task_sheet")["current_artifact"]
    sent = await client.post(
        f"/api/v1/courses/{course_a['id']}/tasks/task_sheet/messages",
        headers=auth_headers,
        json={"content": "结合最新教学设计优化完成标准"},
    )
    assert sent.status_code == 202, sent.text
    revised_project = await _wait_for_project(
        client, auth_headers, course_a["id"],
        lambda item: _task(item, "task_sheet")["current_artifact"]["version"] == task_sheet_before["version"] + 1,
    )
    revised_sheet = _task(revised_project, "task_sheet")["current_artifact"]
    assert revised_sheet["source_versions_json"]["lesson_plan"] == 3
    assert revised_sheet["content_json"]["schema_version"] == "2.0"

    synced = await client.post(
        f"/api/v1/courses/{course_a['id']}/tasks/task_sheet/runs",
        headers=auth_headers,
        json={"action": "sync_context"},
    )
    assert synced.status_code == 202, synced.text
    synced_project = await _wait_for_project(
        client, auth_headers, course_a["id"],
        lambda item: _task(item, "task_sheet")["current_artifact"]["version"] == revised_sheet["version"] + 1,
    )
    synced_sheet = _task(synced_project, "task_sheet")["current_artifact"]
    assert synced_sheet["source_versions_json"]["lesson_plan"] == 3
    assert synced_sheet["content_json"] == revised_sheet["content_json"]


@pytest.mark.asyncio
async def test_legacy_task_sheet_is_immutable_and_chat_revision_upgrades_to_v2(client, auth_headers):
    course, project = await _generated_course(client, auth_headers, "旧版兼容课程", "LEGACY_ONLY")
    current = _task(project, "task_sheet")["current_artifact"]
    legacy_content = {
        "title": "旧版学习任务单",
        "items": [{"id": "OLD-01", "instruction": "记录观察结果", "completion_standard": "完成记录"}],
    }
    async with SessionLocal() as db:
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course["id"], CourseTask.task_type == "task_sheet",
        ))
        legacy = Artifact(
            course_id=course["id"], artifact_type="task_sheet", version=current["version"] + 1,
            blueprint_version=current["blueprint_version"], content_json=legacy_content,
            content_markdown="# 旧版学习任务单\n\n- 记录观察结果",
            model_name="legacy", prompt_version="v1", change_summary="历史 V1 数据",
            source_versions_json={}, agent_profile_id=task.current_agent_profile_id,
        )
        db.add(legacy)
        await db.flush()
        legacy_id = legacy.id
        task.current_artifact_id = legacy.id
        task.status = "review"
        await db.commit()

    visible = await client.get(f"/api/v1/artifacts/{legacy_id}", headers=auth_headers)
    assert visible.status_code == 200
    assert visible.json()["content_json"] == legacy_content

    sent = await client.post(
        f"/api/v1/courses/{course['id']}/tasks/task_sheet/messages",
        headers=auth_headers,
        json={"content": "把旧版升级为可打印的学生版结构化任务单"},
    )
    assert sent.status_code == 202, sent.text
    upgraded_project = await _wait_for_project(
        client, auth_headers, course["id"],
        lambda item: _task(item, "task_sheet")["current_artifact"]["version"] == current["version"] + 2,
    )
    upgraded = _task(upgraded_project, "task_sheet")["current_artifact"]
    assert upgraded["content_json"]["schema_version"] == "2.0"
    assert upgraded["prompt_version"] == "v2"
    still_legacy = await client.get(f"/api/v1/artifacts/{legacy_id}", headers=auth_headers)
    assert still_legacy.json()["content_json"] == legacy_content

    async with SessionLocal() as db:
        templates = list(await db.scalars(select(PromptTemplate).where(
            PromptTemplate.agent_type == "task_sheet_agent",
        )))
    assert {item.version for item in templates} >= {"v1", "v2"}
    assert [item.version for item in templates if item.is_active] == ["v2"]

    edited = upgraded["content_json"]
    edited["extension"] = ["完成一次家庭观察记录"]
    patched = await client.patch(
        f"/api/v1/artifacts/{upgraded['id']}", headers=auth_headers,
        json={"content_json": edited, "content_markdown": "SHOULD_NOT_SURVIVE", "change_summary": "结构化编辑"},
    )
    assert patched.status_code == 201, patched.text
    assert "SHOULD_NOT_SURVIVE" not in patched.json()["content_markdown"]
    assert "完成一次家庭观察记录" in patched.json()["content_markdown"]
