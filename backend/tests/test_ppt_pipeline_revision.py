"""PPT 流水线修订测试：消息触发创建新版本、锁定路径保留、修订事件。"""
import asyncio

import pytest

from agent_pipeline_helpers import ready_course, wait_for, wait_tasks_terminal


@pytest.mark.asyncio
async def test_pipeline_message_preserves_locked_paths(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="修订路径 Mock")
    # ready_course 已让全部任务终态，ppt 为 v1 review
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt = next(t for t in project["tasks"] if t["task_type"] == "ppt")
    artifact = ppt["current_artifact"]
    assert artifact["version"] == 1

    # 锁定第一页标题
    locked_title = artifact["content_json"]["slides"][0]["title"]
    lock = await client.post(f"/api/v1/artifacts/{artifact['id']}/lock", headers=auth_headers,
                             json={"json_path": "$.slides.S01.title"})
    assert lock.status_code == 200

    sent = await client.post(f"/api/v1/courses/{course_id}/tasks/ppt/messages", headers=auth_headers,
                             json={"content": "请把第一页标题改写为更有吸引力的表述"})
    assert sent.status_code == 202, sent.text

    project = await wait_for(client, auth_headers, f"/api/v1/courses/{course_id}/project",
                             lambda item: next(t for t in item["tasks"] if t["task_type"] == "ppt")["current_artifact"]["version"] == 2)
    v2 = next(t for t in project["tasks"] if t["task_type"] == "ppt")["current_artifact"]
    # 锁定路径保留原值
    assert v2["content_json"]["slides"][0]["title"] == locked_title
    # 修订事件已发出
    detail = await wait_for(client, auth_headers, f"/api/v1/courses/{course_id}/tasks/ppt/pipeline",
                            lambda item: item["run"] is not None and item["run"]["status"] == "completed")
    types = {event["event_type"] for event in detail["events"]}
    assert "revision_started" in types
    assert "revision_completed" in types
    await wait_tasks_terminal(client, auth_headers, course_id)
