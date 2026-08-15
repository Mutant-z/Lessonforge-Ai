"""共享项目记忆架构测试。

验证：六类内容 Agent 并行启动（不依赖彼此产物）；缺少教学设计/视频脚本时
video_script / verbatim 仍可生成基础版本；Artifact 保存推进记忆 revision 并
写入索引；一个 Agent 修改不创建其他 Agent Run；视频生成仍按运行输入契约
（V3/V4 脚本）执行，不阻塞其他 Agent；GenerationRun 记录上下文快照；新 SSE
事件可达；记忆严格按 course_id 隔离。
"""
import asyncio

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    Artifact,
    CourseTask,
    GenerationEvent,
    GenerationRun,
    ProjectMemoryItem,
    ProjectMemoryRevision,
)
from app.services.course_task_service import CONTENT_TASK_TYPES, schedule_ready_tasks
from app.services.project_knowledge_service import _artifact_keywords


def test_memory_backfill_accepts_legacy_string_keywords():
    """V1 lesson plans store objectives as strings, unlike the V2 object shape."""
    keywords = _artifact_keywords(
        "lesson_plan",
        {"objectives": ["理解浮力来源"], "stages": ["课堂导入"]},
    )
    assert keywords == ["lesson_plan", "理解浮力来源", "课堂导入"]


async def wait_for_project(client, headers, course_id, predicate, attempts=240):
    payload = None
    for _ in range(attempts):
        response = await client.get(f"/api/v1/courses/{course_id}/project", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        if predicate(payload):
            return payload
        await asyncio.sleep(0.02)
    return payload


async def _confirmed_course(client, auth_headers) -> str:
    """从 intake 确认创建一门课程（蓝图自动批准 + Agent 初始化）。"""
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
        json={"expected_revision": ready["current_revision"], "idempotency_key": f"memory-{session['id']}"},
    )
    assert confirmed.status_code == 202, confirmed.text
    return confirmed.json()["course_id"]


@pytest.mark.asyncio
async def test_six_content_agents_parallel_generation_and_memory_writes(client, auth_headers):
    course_id = await _confirmed_course(client, auth_headers)
    project = await wait_for_project(
        client, auth_headers, course_id,
        lambda item: all(
            task["current_artifact"] is not None
            and task["status"] == "review"
            for task in item["tasks"]
            if task["task_type"] in CONTENT_TASK_TYPES
        ),
    )
    # 六类内容 Agent 全部生成完成（并行启动，无需等待彼此产物）。
    content = {task["task_type"]: task for task in project["tasks"] if task["task_type"] in CONTENT_TASK_TYPES}
    assert set(content) == CONTENT_TASK_TYPES
    # 视频生成仍受运行输入契约约束：脚本确认前保持 waiting_dependency。
    video_task = next(task for task in project["tasks"] if task["task_type"] == "video_generation")
    assert video_task["status"] in {"waiting_dependency", "ready_to_generate"}
    # 每个内容 Agent 都携带可选参考来源与记忆版本字段。
    sample = content["video_script"]
    assert "optional_reference_types" in sample and "available_sources" in sample
    assert sample["optional_reference_types"] == ["lesson_plan"]

    async with SessionLocal() as db:
        revisions = list(await db.scalars(select(ProjectMemoryRevision).where(
            ProjectMemoryRevision.course_id == course_id,
        ).order_by(ProjectMemoryRevision.revision)))
        assert revisions, "必须存在记忆版本流水"
        revisions_by_number = [r.revision for r in revisions]
        assert revisions_by_number == sorted(revisions_by_number), "记忆版本必须单调递增"
        artifacts = list(await db.scalars(select(Artifact).where(
            Artifact.course_id == course_id,
            Artifact.artifact_type.in_(tuple(CONTENT_TASK_TYPES)),
        )))
        assert len(artifacts) >= len(CONTENT_TASK_TYPES)
        for artifact in artifacts:
            assert artifact.memory_revision_created > 0, "Artifact 必须记录创建时读取的记忆版本"
        items = list(await db.scalars(select(ProjectMemoryItem).where(
            ProjectMemoryItem.course_id == course_id,
            ProjectMemoryItem.source_type == "artifact",
        )))
        assert len(items) >= len(CONTENT_TASK_TYPES), "Artifact 必须写入项目记忆索引"
        # GenerationRun 记录上下文快照（context_hash / context_manifest）。
        runs = list(await db.scalars(select(GenerationRun).where(
            GenerationRun.course_id == course_id,
            GenerationRun.run_type == "task",
        )))
        assert runs, "内容 Agent 必须创建 GenerationRun"
        assert any(run.context_hash for run in runs), "Run 必须记录 context_hash"
        manifest_run = next((run for run in runs if run.context_manifest_json), runs[0])
        assert manifest_run.memory_revision > 0
        assert "available_sources" in manifest_run.context_manifest_json
        # 事件可达：artifact.published / project_memory.updated / context.snapshot_created。
        events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == manifest_run.id,
        )))
        event_types = {event.event_type for event in events}
        assert "artifact.published" in event_types
        assert "project_memory.updated" in event_types
        assert "context.snapshot_created" in event_types
        memory_events = [e for e in events if e.event_type == "project_memory.updated"]
        assert all((e.data_json or {}).get("memory_revision", 0) > 0 for e in memory_events)


@pytest.mark.asyncio
async def test_memory_revision_bumps_on_revision_and_isolation(client, auth_headers):
    course_id = await _confirmed_course(client, auth_headers)
    project = await wait_for_project(
        client, auth_headers, course_id,
        lambda item: all(
            task["current_artifact"] is not None
            for task in item["tasks"]
            if task["task_type"] in CONTENT_TASK_TYPES
        ),
    )
    async with SessionLocal() as db:
        before = await db.scalar(select(func.max(ProjectMemoryRevision.revision)).where(
            ProjectMemoryRevision.course_id == course_id,
        ))

    # 教师在线编辑（确定性创建新版本，走 register_artifact_version 记忆钩子）。
    lesson = next(
        task["current_artifact"] for task in project["tasks"] if task["task_type"] == "lesson_plan"
    )
    revised = dict(lesson["content_json"])
    if revised.get("schema_version") == "2.0":
        core = dict(revised.get("pedagogical_core") or {})
        core["board_design"] = f"{core.get('board_design', '')}（补充板书要点）"
        revised["pedagogical_core"] = core
    else:
        revised["content_analysis"] = f"{revised.get('content_analysis', '')} · 补充内容分析"
    updated = await client.patch(
        f"/api/v1/artifacts/{lesson['id']}",
        headers=auth_headers,
        json={"content_json": revised, "content_markdown": lesson["content_markdown"], "change_summary": "教师在线编辑"},
    )
    assert updated.status_code == 201, updated.text

    project = await wait_for_project(
        client, auth_headers, course_id,
        lambda item: next(
            task for task in item["tasks"] if task["task_type"] == "lesson_plan"
        )["current_artifact"]["version"] == 2,
    )
    async with SessionLocal() as db:
        after = await db.scalar(select(func.max(ProjectMemoryRevision.revision)).where(
            ProjectMemoryRevision.course_id == course_id,
        ))
        # 教学设计新版本 → 记忆版本必须推进。
        assert int(after) > int(before), "Agent 修改后项目记忆版本必须推进"
        # 一个 Agent 修改后，其他 Agent 不被标记 stale、不自动创建 Run。
        tasks = list(await db.scalars(select(CourseTask).where(CourseTask.course_id == course_id)))
        stale_tasks = [task for task in tasks if task.status == "stale" and task.task_type != "lesson_plan"]
        assert not stale_tasks, "其他 Agent 不应因教学设计修改而被标记 stale"
        lesson_items = list(await db.scalars(select(ProjectMemoryItem).where(
            ProjectMemoryItem.course_id == course_id,
            ProjectMemoryItem.artifact_type == "lesson_plan",
        )))
        assert any(item.source_version == 2 for item in lesson_items), "教学设计 V2 必须进入项目记忆索引"


@pytest.mark.asyncio
async def test_video_script_and_verbatim_generate_without_upstreams(client, auth_headers):
    """共享记忆：无教学设计时 video_script 可用蓝图生成；无脚本时 verbatim 可生成基础版。

    直接构造只有蓝图的课程任务，手动调度所有内容 Agent（Mock 环境，快速验证兜底路径）。
    """
    from app.agents.generators import make_lesson_plan
    from app.core.database import SessionLocal as DB
    from app.models.entities import CourseBlueprint, CourseProject, CourseTask as CT
    from app.schemas.blueprint import CourseBlueprintSchema

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
    await schedule_ready_tasks(course["id"])

    project = await wait_for_project(
        client, auth_headers, course["id"],
        lambda item: all(
            task["current_artifact"] is not None
            for task in item["tasks"]
            if task["task_type"] in CONTENT_TASK_TYPES
        ),
    )
    script_artifact = next(
        task["current_artifact"] for task in project["tasks"] if task["task_type"] == "video_script"
    )
    assert script_artifact, "缺少教学设计时视频脚本仍可生成"
    assert script_artifact["content_json"]["schema_version"] == "3.0"
    verbatim_artifact = next(
        task["current_artifact"] for task in project["tasks"] if task["task_type"] == "verbatim"
    )
    assert verbatim_artifact, "缺少视频脚本时逐字稿仍可生成基础版本"
    assert verbatim_artifact["content_json"]["schema_version"] == "2.0"
    # 任务字段：视频脚本的可选参考只包含教学设计（不阻塞）。
    script_task = next(task for task in project["tasks"] if task["task_type"] == "video_script")
    assert script_task["optional_reference_types"] == ["lesson_plan"]


@pytest.mark.asyncio
async def test_video_generation_input_contract_not_blocking(client, auth_headers):
    """视频生成仍要求 V3/V4 脚本（运行输入契约），但缺失时不阻塞其他 Agent 生成。"""
    course_id = await _confirmed_course(client, auth_headers)
    project = await wait_for_project(
        client, auth_headers, course_id,
        lambda item: all(
            task["current_artifact"] is not None
            for task in item["tasks"]
            if task["task_type"] in CONTENT_TASK_TYPES
        ),
    )
    video_task = next(task for task in project["tasks"] if task["task_type"] == "video_generation")
    # 其他内容 Agent 全部生成完成，只有视频生成还停留在输入契约等待。
    assert video_task["status"] == "waiting_dependency"
    assert video_task["required_input_contract"] == {"video_script": "执行前必须存在 Seedance V3/V4 视频脚本"}
    assert not video_task["current_artifact"]
    # 确认视频脚本后，视频生成进入 ready_to_generate。
    approved = await client.post(
        f"/api/v1/courses/{course_id}/tasks/video_script/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    project = await wait_for_project(
        client, auth_headers, course_id,
        lambda item: next(
            task for task in item["tasks"] if task["task_type"] == "video_generation"
        )["status"] == "ready_to_generate",
    )
    assert next(task for task in project["tasks"] if task["task_type"] == "video_generation")["status"] == "ready_to_generate"


@pytest.mark.asyncio
async def test_memory_api_endpoints(client, auth_headers):
    course_id = await _confirmed_course(client, auth_headers)
    await wait_for_project(
        client, auth_headers, course_id,
        lambda item: all(
            task["current_artifact"] is not None
            for task in item["tasks"]
            if task["task_type"] in CONTENT_TASK_TYPES
        ),
    )
    memory = (await client.get(f"/api/v1/courses/{course_id}/memory", headers=auth_headers)).json()
    assert memory["revision"] > 0
    assert memory["item_count"] > 0
    assert set(memory["items"]) >= {"requirement", "blueprint", "artifact"}
    # 任意一个 artifact 条目可以单独读取。
    artifact_items = memory["items"].get("artifact", [])
    assert artifact_items
    item = (await client.get(
        f"/api/v1/courses/{course_id}/memory/items/{artifact_items[0]['id']}",
        headers=auth_headers,
    )).json()
    assert item["source_type"] == "artifact"
    # 搜索：按摘要关键词检索。
    search = (await client.get(
        f"/api/v1/courses/{course_id}/memory/search",
        params={"q": "阿基米德"},
        headers=auth_headers,
    )).json()
    assert isinstance(search["items"], list)
    # 上下文清单：video_script 的可选参考与记忆版本。
    context = (await client.get(
        f"/api/v1/courses/{course_id}/memory/context",
        params={"task_type": "video_script"},
        headers=auth_headers,
    )).json()
    assert context["memory_revision"] == memory["revision"]
    assert "available_sources" in context
    assert "missing_optional_sources" in context
