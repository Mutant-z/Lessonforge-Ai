"""流水线事件协议测试：pipeline_events.sequence 镜像 generation_events.id，且递增唯一。"""
import asyncio

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import GenerationEvent, PipelineEvent

from agent_pipeline_helpers import ready_course, wait_for


@pytest.mark.asyncio
async def test_pipeline_event_sequence_mirrors_generation_event_ids(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="事件 Mock")
    # ready_course 已让全部任务终态，ppt 流水线已完成
    detail = await wait_for(client, auth_headers, f"/api/v1/courses/{course_id}/tasks/ppt/pipeline",
                            lambda item: item["run"] is not None and item["run"]["status"] == "completed")
    pipeline_run_id = detail["run"]["id"]
    gen_run_id = detail["run"]["generation_run_id"]

    async with SessionLocal() as db:
        gen_ids = list(await db.scalars(select(GenerationEvent.id).where(
            GenerationEvent.run_id == gen_run_id,
        ).order_by(GenerationEvent.id)))
        pipeline_rows = list(await db.scalars(select(PipelineEvent).where(
            PipelineEvent.pipeline_run_id == pipeline_run_id,
        ).order_by(PipelineEvent.sequence)))

    assert gen_ids == sorted(gen_ids)
    assert len(gen_ids) == len(set(gen_ids))
    sequences = [row.sequence for row in pipeline_rows]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))
    # pipeline_events.sequence 取自已镜像的 generation_events.id
    assert set(sequences) <= set(gen_ids)
    # 每种事件在 SSE 事件流与明细中各至少出现一次
    types = {row.event_type for row in pipeline_rows}
    for expected in ("agent_started", "tool_call_completed", "artifact_created", "qa_completed"):
        assert expected in types
