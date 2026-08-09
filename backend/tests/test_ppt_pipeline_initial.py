"""PPT 多 Agent 流水线初始生成集成测试：pipeline 表行、事件流、最终 Artifact。"""
import asyncio

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import ArtifactAsset, GenerationEvent, PipelineArtifact, PipelineEvent, PipelineRun, PipelineToolCall
from app.schemas.artifact import PPTContent

from agent_pipeline_helpers import ready_course, wait_for, wait_tasks_terminal


@pytest.mark.asyncio
async def test_pipeline_initial_run_populates_tables_and_events(client, auth_headers):
    course_id = await ready_course(client, auth_headers)
    # ready_course 已让全部任务（含 ppt 流水线）达到终态
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt_task = next(task for task in project["tasks"] if task["task_type"] == "ppt")
    assert ppt_task["status"] == "review"

    # pipeline 运行 + 产物图 + 工具调用 + 事件
    detail = await wait_for(client, auth_headers, f"/api/v1/courses/{course_id}/tasks/ppt/pipeline",
                            lambda item: item["run"] is not None and item["run"]["status"] == "completed")
    assert detail["run"]["status"] == "completed"
    run_id = detail["run"]["generation_run_id"]
    artifact_types = {item["artifact_type"] for item in detail["artifacts"]}
    assert {"presentation_narrative", "design_system", "slide_content", "slide_layout",
            "visual_plan", "visual_asset", "visual_qa"} <= artifact_types, artifact_types
    assert len(detail["tool_calls"]) >= 20
    assert len(detail["events"]) >= 20

    # 最终 PPT Artifact 合法
    ppt_artifact = await wait_for(client, auth_headers, f"/api/v1/courses/{course_id}/artifacts",
                                  lambda item: any(x["artifact_type"] == "ppt" for x in item))
    ppt = next(x for x in ppt_artifact if x["artifact_type"] == "ppt")
    content = PPTContent.model_validate(ppt["content_json"])
    assert len(content.slides) >= 10
    image_elements = [
        element
        for slide in ppt["content_json"]["slides"]
        for element in (slide.get("elements") or [])
        if element.get("kind") == "image"
    ]
    assert image_elements, "生成的视觉资产必须绑定为可渲染的页面 image 元素"
    assert image_elements[0].get("asset_id"), "页面图片必须携带浏览器可读取的 ArtifactAsset ID"
    asset_response = await client.get(
        f"/api/v1/artifact-assets/{image_elements[0]['asset_id']}", headers=auth_headers,
    )
    assert asset_response.status_code == 200
    assert asset_response.headers["content-type"].startswith("image/")
    async with SessionLocal() as db:
        bound_asset = await db.get(ArtifactAsset, image_elements[0]["asset_id"])
        assert bound_asset is not None and bound_asset.artifact_id == ppt["id"]

    # SSE 事件类型
    async with SessionLocal() as db:
        events = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == run_id,
        ).order_by(GenerationEvent.id)))
        event_types = [event.event_type for event in events]
        for expected in ("agent_started", "agent_completed", "tool_call_started",
                         "tool_call_completed", "artifact_created", "asset_generated", "qa_completed"):
            assert expected in event_types, event_types
        ids = [event.id for event in events]
        assert ids == sorted(ids)
        assert len(ids) == len(set(ids))

    # pipeline 明细表
    async with SessionLocal() as db:
        pipeline_run = await db.scalar(select(PipelineRun).where(PipelineRun.generation_run_id == run_id))
        assert pipeline_run is not None and pipeline_run.status == "completed"
        artifact_count = await db.scalar(select(func.count(PipelineArtifact.id)).where(PipelineArtifact.pipeline_run_id == pipeline_run.id))
        tool_count = await db.scalar(select(func.count(PipelineToolCall.id)).where(PipelineToolCall.pipeline_run_id == pipeline_run.id))
        event_count = await db.scalar(select(func.count(PipelineEvent.id)).where(PipelineEvent.pipeline_run_id == pipeline_run.id))
        assert artifact_count >= 10
        assert tool_count >= 20
        assert event_count >= 20
