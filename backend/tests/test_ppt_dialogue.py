"""对话单线测试：整轮 PPT pipeline 产出一条「教学 Agent」assistant 消息（agent_message_* 事件流）。

验证：
- 全量 run：恰好一条最终 assistant 消息、执行状态不混入正文、completed 带 sub_agents 明细；
- message 触发：guard 生效，该 run 恰好一条 assistant 消息（无 `_stream_verified_reply` 第二条）；
- emitter 单元：正文按 status_delta 摘要累积、失败路径消息置 failed。
"""
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import AgentMessage, GenerationEvent

from agent_pipeline_helpers import build_runtime, ready_course, wait_for, wait_tasks_terminal

EXPECTED_AGENT_KEYS = (
    "narrative", "template_analysis", "slide_content", "visual_plan",
    "layout", "media", "ppt_editor", "visual_qa",
)


@pytest.mark.asyncio
async def test_full_run_emits_dialogue_message(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="对话 Mock")
    detail = await wait_for(
        client, auth_headers, f"/api/v1/courses/{course_id}/tasks/ppt/pipeline",
        lambda item: item["run"] is not None and item["run"]["status"] == "completed",
    )
    gen_run_id = detail["run"]["generation_run_id"]

    async with SessionLocal() as db:
        messages = list(await db.scalars(select(AgentMessage).where(
            AgentMessage.module_type == "ppt",
            AgentMessage.run_id == gen_run_id,
        ).order_by(AgentMessage.created_at)))
        events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == gen_run_id,
        ).order_by(GenerationEvent.id)))

    assistants = [m for m in messages if m.role == "assistant"]
    assert len(assistants) == 1, "整轮 pipeline 应恰好一条 assistant 对话消息（单线）"
    msg = assistants[0]
    assert msg.status == "completed"
    assert msg.content.startswith("PPT 已生成完成，共 ")
    assert "正在" not in msg.content, "执行状态应保留在 trace，不应混入最终答复"

    types = [ev.event_type for ev in events]
    assert types.index("agent_message_started") < types.index("agent_message_delta") < types.index("agent_message_completed")
    completed_ev = next(ev for ev in events if ev.event_type == "agent_message_completed")
    sub_agents = completed_ev.data_json.get("sub_agents", [])
    keys = {item.get("agent") for item in sub_agents}
    for key in EXPECTED_AGENT_KEYS:
        assert key in keys, f"sub_agents 应包含 {key}"


@pytest.mark.asyncio
async def test_message_trigger_single_assistant_message(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="消息 Mock")
    response = await client.post(
        f"/api/v1/courses/{course_id}/tasks/ppt/messages", headers=auth_headers,
        json={"content": "请把第3页改成对比版式"},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]

    # 等 execute_task_run 完全收尾（任务终态），避免后台协程泄漏到测试结束导致 lifespan 关闭卡住
    await wait_tasks_terminal(client, auth_headers, course_id)

    async with SessionLocal() as db:
        messages = list(await db.scalars(select(AgentMessage).where(
            AgentMessage.module_type == "ppt",
            AgentMessage.run_id == run_id,
        ).order_by(AgentMessage.created_at)))

    roles = [m.role for m in messages]
    assert roles == ["user", "assistant"], "message 触发应有恰好 1 条 user + 1 条 assistant"
    assistant = messages[1]
    assert assistant.status == "completed"
    assert assistant.content, "assistant 正文应为最终回复"


@pytest.mark.asyncio
async def test_emitter_dialogue_accumulates_content(client, auth_headers):
    course_id = await ready_course(client, auth_headers)
    runtime = await build_runtime(course_id, trigger="initial")
    await runtime.emitter.agent_message_started("教学 Agent")
    await runtime.emitter.agent_status_delta("narrative", "正在分析章节结构。")
    await runtime.emitter.agent_status_delta("narrative", "已生成叙事大纲。")
    await runtime.emitter.agent_status_completed("narrative", "叙事完成")
    await runtime.emitter.agent_message_completed(sub_agents=[{"agent": "narrative", "summary": "s", "status": "completed"}])

    async with SessionLocal() as db:
        rows = list(await db.scalars(select(AgentMessage).where(
            AgentMessage.run_id == runtime.generation_run.id,
            AgentMessage.role == "assistant",
        )))
    assert len(rows) == 1
    assert rows[0].status == "completed"
    # 无论节流时机，正文最终等于所有 status 摘要的累积
    assert rows[0].content == "正在分析章节结构。已生成叙事大纲。叙事完成"


@pytest.mark.asyncio
async def test_emitter_failed_marks_message_failed(client, auth_headers):
    course_id = await ready_course(client, auth_headers)
    runtime = await build_runtime(course_id, trigger="initial")
    await runtime.emitter.agent_message_started("教学 Agent")
    await runtime.emitter.agent_status_delta("narrative", "正在分析章节结构。")
    await runtime.emitter.agent_message_failed(message="boom")

    async with SessionLocal() as db:
        rows = list(await db.scalars(select(AgentMessage).where(
            AgentMessage.run_id == runtime.generation_run.id,
            AgentMessage.role == "assistant",
        )))
        failed_events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == runtime.generation_run.id,
            GenerationEvent.event_type == "agent_message_failed",
        )))
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert failed_events, "失败路径应发出 agent_message_failed 事件"
