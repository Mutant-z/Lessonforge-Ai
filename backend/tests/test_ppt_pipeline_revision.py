"""PPT 流水线修订测试：消息触发创建新版本、锁定路径保留、修订事件。"""
import asyncio

import pytest

from agent_pipeline_helpers import ready_course, wait_for, wait_tasks_terminal
from app.services.ppt_pipeline_service import _resolve_message_slide_ids


@pytest.mark.parametrize(("instruction", "expected"), [
    ("为第一页生成一张图片并插入", ["slide_01"]),
    ("修改第一页面", ["slide_01"]),
    ("润色第十二页", ["slide_12"]),
    ("调整首张幻灯片", ["slide_01"]),
    ("[目标页面:slide_03,slide_05] 修改", ["slide_03", "slide_05"]),
])
def test_resolve_message_slide_ids_supports_chinese_page_numbers(instruction, expected):
    slides = [{"id": f"slide_{index:02d}"} for index in range(1, 16)]
    assert _resolve_message_slide_ids(instruction, slides) == expected


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
