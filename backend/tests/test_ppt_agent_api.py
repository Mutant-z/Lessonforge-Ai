from copy import deepcopy

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.agent.runtime import PPTAgentRuntime
from app.agent.slide_rendering import semantic_content_hash
from app.models.entities import AgentChatSession, AgentMessage, Artifact, GenerationEvent, GenerationRun, PipelineRun, PPTAgentInstruction
from app.agent.tools.asset_tools import _resolve_image_config
from app.renderers.presentation_builder import PresentationBuilder
from agent_pipeline_helpers import build_runtime, ready_course, wait_for


@pytest.mark.asyncio
async def test_queued_instruction_is_persisted_as_visible_user_message(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="Instruction Queue Mock")
    runtime = await build_runtime(course_id, trigger="initial")

    response = await client.post(
        f"/api/v1/ppt-agent/runs/{runtime.generation_run.id}/instructions",
        headers=auth_headers,
        json={"content": "调整当前页配色", "selected_slide_ids": ["S02"]},
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["message"]["content"] == "调整当前页配色"
    assert payload["message"]["run_id"] == runtime.generation_run.id

    async with SessionLocal() as db:
        message = await db.scalar(select(AgentMessage).where(AgentMessage.id == payload["message_id"]))
    assert message is not None
    assert message.role == "user"
    assert message.status == "completed"

    # 非紧急指令也必须重新规划受影响 Agent，不能因旧计划已完成而直接结束。
    await PPTAgentRuntime(runtime, persistent_checkpoints=False).run()
    async with SessionLocal() as db:
        instruction = await db.get(PPTAgentInstruction, payload["instruction_id"])
    assert instruction.disposition == "merged"
    decision_agents = {item.get("agent") for item in runtime.context.decisions}
    assert {"slide_content", "layout", "ppt_editor"}.issubset(decision_agents)


@pytest.mark.asyncio
async def test_pipeline_detail_repairs_terminal_generation_with_stale_running_pipeline(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="Stale Runtime Mock")
    runtime = await build_runtime(course_id, trigger="initial")
    async with SessionLocal() as db:
        generation = await db.get(GenerationRun, runtime.generation_run.id)
        pipeline = await db.get(PipelineRun, runtime.pipeline_run.id)
        generation.status = "failed"
        generation.error_json = {"code": "upstream_timeout", "message": "模型超时"}
        pipeline.status = "running"
        await db.commit()

    response = await client.get(f"/api/v1/courses/{course_id}/tasks/ppt/pipeline", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "failed"
    async with SessionLocal() as db:
        pipeline = await db.get(PipelineRun, runtime.pipeline_run.id)
        assert pipeline.status == "failed"
        assert pipeline.error_json["code"] == "upstream_timeout"


@pytest.mark.asyncio
async def test_run_centric_api_and_slide_revisions(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="Run API Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt_task = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    artifact = ppt_task["current_artifact"]

    slides = await client.get(f"/api/v1/ppt-agent/artifacts/{artifact['id']}/slides", headers=auth_headers)
    assert slides.status_code == 200, slides.text
    slide_payload = slides.json()
    assert slide_payload["revision"] == artifact["version"]
    assert len(slide_payload["slides"]) == len(artifact["content_json"]["slides"])

    detail = (await client.get(f"/api/v1/courses/{course_id}/tasks/ppt/pipeline", headers=auth_headers)).json()
    run_id = detail["run"]["generation_run_id"]
    run = await client.get(f"/api/v1/ppt-agent/runs/{run_id}", headers=auth_headers)
    assert run.status_code == 200
    assert run.json()["status"] == "completed"

    created = await client.post("/api/v1/ppt-agent/runs", headers=auth_headers, json={
        "course_id": course_id,
        "instruction": "润色一下当前页",
        "selected_slide_ids": [artifact["content_json"]["slides"][1]["id"]],
    })
    assert created.status_code == 202, created.text
    assert created.json()["message_id"]
    updated = await wait_for(
        client, auth_headers, f"/api/v1/courses/{course_id}/project",
        lambda item: next(t for t in item["tasks"] if t["task_type"] == "ppt")["current_artifact"]["version"] == artifact["version"] + 1,
    )
    v2 = next(t for t in updated["tasks"] if t["task_type"] == "ppt")["current_artifact"]
    before = artifact["content_json"]["slides"]
    after = v2["content_json"]["slides"]
    assert after[1]["title"].endswith("（润色版）")
    assert [(item["id"], item["title"], item.get("body")) for item in after[2:]] == [
        (item["id"], item["title"], item.get("body")) for item in before[2:]
    ]
    async with SessionLocal() as db:
        patches = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == created.json()["run_id"],
            GenerationEvent.event_type == "artifact_patch",
        ).order_by(GenerationEvent.id)))
    assert len(patches) >= 2, "目标页应至少产生内容和布局两次增量 patch"
    assert {item["path"] for event in patches for item in event.data_json["patch"]} == {"/slides/1"}
    v2_slides = (await client.get(f"/api/v1/ppt-agent/artifacts/{v2['id']}/slides", headers=auth_headers)).json()["slides"]
    history = await client.get(f"/api/v1/ppt-agent/slides/{v2_slides[0]['id']}/revisions", headers=auth_headers)
    assert history.status_code == 200
    assert len(history.json()["revisions"]) >= 2


@pytest.mark.asyncio
async def test_template_switch_preserves_pages_content_and_existing_image(client, auth_headers, tmp_path):
    from PIL import Image

    course_id = await ready_course(client, auth_headers, model_name="Template Switch Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    task = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    official = task["current_artifact"]
    image_path = tmp_path / "existing-visual.png"
    Image.new("RGB", (640, 420), "teal").save(image_path)

    async with SessionLocal() as db:
        artifact = await db.get(Artifact, official["id"])
        content = dict(artifact.content_json)
        slides = [dict(item) for item in content["slides"]]
        first = dict(slides[0])
        first["elements"] = [*(first.get("elements") or []), {
            "id": "E90", "kind": "image", "x": 7.2, "y": 1.3, "w": 5.0, "h": 4.1,
            "z": 90, "style": {}, "role": "visual", "asset_path": str(image_path),
            "asset_id": "existing-template-asset", "provider": "test", "degraded": False,
        }]
        slides[0] = first
        content["slides"] = slides
        artifact.content_json = content
        await db.commit()
    before = content

    created = await client.post(
        f"/api/v1/ppt-agent/artifacts/{official['id']}/template-switch",
        headers=auth_headers,
        json={"template_id": "lessonforge_deck_ai_future", "selected_slide_ids": []},
    )
    assert created.status_code == 202, created.text
    updated = await wait_for(
        client, auth_headers, f"/api/v1/courses/{course_id}/project",
        lambda item: next(t for t in item["tasks"] if t["task_type"] == "ppt")["current_artifact"]["version"] == official["version"] + 1,
    )
    switched = next(item for item in updated["tasks"] if item["task_type"] == "ppt")["current_artifact"]
    after = switched["content_json"]
    assert after["theme"] == "lessonforge_deck_ai_future"
    assert [item["id"] for item in after["slides"]] == [item["id"] for item in before["slides"]]
    for source, target in zip(before["slides"], after["slides"]):
        assert (target["title"], target.get("body"), target.get("speaker_notes")) == (
            source["title"], source.get("body"), source.get("speaker_notes"),
        )
    images = [item for item in after["slides"][0].get("elements") or [] if item.get("kind") == "image"]
    assert any(item.get("asset_id") == "existing-template-asset" for item in images)


@pytest.mark.asyncio
async def test_explicit_image_update_without_image_model_does_not_publish(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="Strict Image Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    task = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    official = task["current_artifact"]
    slide_id = official["content_json"]["slides"][0]["id"]

    created = await client.post("/api/v1/ppt-agent/runs", headers=auth_headers, json={
        "course_id": course_id,
        "instruction": "为第一页生成一张潜水艇浮力示意图片并插入 PPT",
        "selected_slide_ids": [slide_id],
    })
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]
    await wait_for(
        client, auth_headers, f"/api/v1/courses/{course_id}/project",
        lambda item: next(task for task in item["tasks"] if task["task_type"] == "ppt")["status"] in {"failed", "review"},
    )
    terminal_response = await client.get(f"/api/v1/ppt-agent/runs/{run_id}", headers=auth_headers)
    assert terminal_response.status_code == 200, terminal_response.text
    terminal = terminal_response.json()
    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "image_model_required"

    refreshed = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    current = next(item for item in refreshed["tasks"] if item["task_type"] == "ppt")["current_artifact"]
    assert current["id"] == official["id"]
    assert current["version"] == official["version"]


@pytest.mark.asyncio
async def test_unique_image_model_is_auto_bound_to_ppt_session(client, auth_headers):
    course_id = await ready_course(client, auth_headers, model_name="Auto Image Bind Mock")
    image_config = (await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "唯一图片模型",
        "provider": "openai_compatible",
        "base_url": "https://images.example/v1",
        "model_name": "image-model",
        "timeout_seconds": 30,
        "capabilities": ["image_generation"],
        "api_mode": "openai_images",
        "is_active": False,
    })).json()
    runtime = await build_runtime(course_id, trigger="message")
    resolved = await _resolve_image_config(runtime.tool_context)
    assert resolved is not None and resolved.id == image_config["id"]
    async with SessionLocal() as db:
        session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course_id,
            AgentChatSession.module_type == "ppt",
        ))
    assert session is not None
    assert session.image_model_config_id == image_config["id"]


@pytest.mark.asyncio
async def test_strict_image_runtime_records_real_asset_and_add_image_evidence(client, auth_headers, monkeypatch):
    from io import BytesIO
    from PIL import Image

    course_id = await ready_course(client, auth_headers, model_name="Strict Image Success Mock")
    await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "测试图片模型", "provider": "openai_compatible",
        "base_url": "https://images.example/v1", "model_name": "image-model",
        "timeout_seconds": 30, "capabilities": ["image_generation"],
        "api_mode": "openai_images", "is_active": False,
    })
    buffer = BytesIO()
    Image.new("RGB", (1024, 768), "navy").save(buffer, format="PNG")

    async def fake_generate(_config, _prompt, _size):
        return buffer.getvalue(), "image/png"

    monkeypatch.setattr("app.services.exercise_visual_service.generate_image", fake_generate)
    runtime = await build_runtime(course_id, trigger="message")
    async with SessionLocal() as db:
        source = await db.scalar(select(Artifact).where(
            Artifact.course_id == course_id, Artifact.artifact_type == "ppt",
        ).order_by(Artifact.version.desc()))
    runtime.source_artifact = source
    runtime.context.source_artifact = source
    runtime.context.user_instruction = "为目标页生成一张教学图片并插入 PPT"
    before = deepcopy(source.content_json)
    runtime.builder = PresentationBuilder(source.content_json.get("theme")).from_ppt_content(source.content_json)
    runtime.tool_context.builder = runtime.builder
    candidates = [
        slide for slide in source.content_json["slides"]
        if any(element.get("role") in {"visual_panel", "visual", "image"} for element in slide.get("elements") or [])
    ]
    target = candidates[0] if candidates else source.content_json["slides"][1]
    try:
        await PPTAgentRuntime(runtime, persistent_checkpoints=False).run(selected_slide_ids=[target["id"]])
    except Exception as exc:
        pytest.fail(f"strict image runtime failed: {getattr(exc, 'details', {})}")
    assert runtime.publishable is True
    assert runtime.generated_asset_ids
    assert any(
        item["kind"] == "image" and item["slide_id"] == target["id"] and item["asset_id"] in runtime.generated_asset_ids
        for item in runtime.mutation_evidence
    )
    after = runtime.builder.to_ppt_content()
    before_by_id = {item["id"]: item for item in before["slides"]}
    after_by_id = {item["id"]: item for item in after["slides"]}
    assert list(after_by_id) == list(before_by_id)
    assert semantic_content_hash(after_by_id[target["id"]]) == semantic_content_hash(before_by_id[target["id"]])
    stable_fields = (
        "page_type", "title", "purpose", "body", "blocks", "layout",
        "visual_suggestion", "speaker_notes", "duration_seconds", "script_segment_ids", "elements",
    )
    list_fields = {"body", "blocks", "script_segment_ids", "elements"}
    for slide_id, original in before_by_id.items():
        if slide_id != target["id"]:
            assert {field: after_by_id[slide_id].get(field, [] if field in list_fields else "") for field in stable_fields} == {
                field: original.get(field, [] if field in list_fields else "") for field in stable_fields
            }

    async with SessionLocal() as db:
        patches = list(await db.scalars(select(GenerationEvent).where(
            GenerationEvent.run_id == runtime.generation_run.id,
            GenerationEvent.event_type == "artifact_patch",
        ).order_by(GenerationEvent.id)))
    target_index = next(index for index, item in enumerate(before["slides"]) if item["id"] == target["id"])
    target_patches = [
        operation for event in patches for operation in event.data_json.get("patch", [])
        if operation.get("path") == f"/slides/{target_index}"
    ]
    assert len(target_patches) == 1
    patched_slide = target_patches[0]["value"]
    assert patched_slide["title"] == target["title"]
    assert patched_slide.get("body") == target.get("body")
    assert any(item.get("kind") == "image" for item in patched_slide.get("elements") or [])
