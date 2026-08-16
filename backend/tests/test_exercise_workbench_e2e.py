"""验证 exercise message 端点 → exercise agentic pipeline 全链路（Mock provider）。

Mock 下修订为确定性 no_change（不修改内容 → 不创建新版本），与 task_sheet 行为一致；
本测试重点验证：端点可走通、pipeline 事件产生、任务终态合法。
"""
import pytest
from tests.agent_pipeline_helpers import wait_for


@pytest.mark.asyncio
async def test_exercise_message_run_flows_through_agentic_pipeline(client, auth_headers):
    await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "Exercise E2E Mock", "provider": "mock", "base_url": "mock://e2e",
        "model_name": "exercise-e2e-mock", "timeout_seconds": 30, "is_active": True,
    })
    course = (await client.post("/api/v1/courses", headers=auth_headers, json={
        "title": "课后练习端到端", "subject": "物理", "grade_level": "八年级",
        "audience": "初二", "duration_minutes": 10, "scenario": "课堂讲解",
        "course_task": "理解并应用核心概念",
    })).json()
    blueprint = (await client.post(f"/api/v1/courses/{course['id']}/blueprint/generate", headers=auth_headers)).json()
    await client.post(f"/api/v1/blueprints/{blueprint['id']}/approve", headers=auth_headers)
    await wait_for(client, auth_headers, f"/api/v1/courses/{course['id']}/project",
                   lambda item: item["agent_initialization"]["status"] == "ready")

    # exercise 首次生成（initial）→ V2 合法结构
    project = await wait_for(client, auth_headers, f"/api/v1/courses/{course['id']}/project",
                             lambda item: next(
                                 (t for t in item["tasks"] if t["task_type"] == "exercise"), {}
                             ).get("current_artifact") is not None,
                             attempts=600)
    exercise = next(t for t in project["tasks"] if t["task_type"] == "exercise")
    assert exercise["current_artifact"]["content_json"]["schema_version"] == "2.0"
    assert exercise["current_artifact"]["content_json"]["paper_settings"]["total_score"] == 100

    # exercise message 修订（带分区作用域元数据）
    resp = await client.post(f"/api/v1/courses/{course['id']}/tasks/exercise/messages", headers=auth_headers, json={
        "content": "把基础巩固的题目难度下调",
        "selected_section_ids": ["basic_consolidation"],
        "mode": "content",
    })
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]

    # 等待任务终态（review / failed 均结束本轮；修订结果 no_change 时 version 不变）
    project = await wait_for(client, auth_headers, f"/api/v1/courses/{course['id']}/project",
                             lambda item: next(
                                 (t for t in item["tasks"] if t["task_type"] == "exercise"), {}
                             ).get("status") in {"review", "stale", "failed", "cancelled"},
                             attempts=600)
    exercise = next(t for t in project["tasks"] if t["task_type"] == "exercise")
    assert exercise["status"] != "failed", exercise.get("error")

    # pipeline 详情可读（前端 ExerciseWorkbench.loadDetail 依赖）
    detail = await client.get(f"/api/v1/courses/{course['id']}/tasks/exercise/pipeline", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload.get("run") is not None
    assert payload["run"].get("generation_run_id") == run_id
    assert payload.get("events") is not None

    # 运行详情中包含 exercise pipeline 事件（agent 流式渲染依赖）
    event_types = {item.get("event_type") for item in payload.get("events", [])}
    assert event_types & {"agent_started", "intent.resolved", "pipeline_completed"}, event_types
    # Mock 下角色走确定性 decide 不产生工具调用（空集符合预期）；若产生则必须是 exercise_* 工具。
    tool_calls = payload.get("tool_calls") or []
    tool_names = {item.get("tool_name") for item in tool_calls if isinstance(item, dict)}
    if tool_names:
        assert all(name.startswith("exercise_") or name.startswith("get_") or name.startswith("read_")
                   or name.startswith("list_") or name.startswith("search_") for name in tool_names), tool_names
