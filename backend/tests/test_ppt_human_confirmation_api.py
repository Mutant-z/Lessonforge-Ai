"""API contract tests for the V2 human-confirmation continuation flow."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    AgentMessage,
    Artifact,
    GenerationRun,
    PipelineRun,
    PPTHumanRequest,
)
from app.agent.runtime import PPTAgentRuntime
from agent_pipeline_helpers import build_runtime, ready_course


def _resolved_command(slide_id: str) -> dict:
    return {
        "raw_text": "把第 2 页的文字放大，但界面选中了第 3 页",
        "turn_relation": "new",
        "scope": {
            "target_slide_ids": [slide_id],
            "reference_slide_ids": [],
            "source": "explicit_selection",
        },
        "operations": [{
            "domain": "typography",
            "action": "resize",
            "object_targets": ["body"],
            "strength": "subtle",
            "hard_requirement": True,
            "execution_order": 20,
        }],
        "objectives": [{
            "metric": "font_size",
            "direction": "increase",
            "minimum_delta": 0.05,
            "priority": 100,
            "hard_requirement": True,
            "source": "explicit",
        }],
        "preservation": {
            "semantic_text": True,
            "images_and_assets": True,
            "notes": True,
            "duration": True,
            "theme": True,
            "page_count": True,
            "slide_order": True,
            "template_chrome": True,
        },
        "confidence": 0.69,
        "ambiguities": ["scope.selection_text_conflict"],
        "needs_confirmation": True,
        "summary": "将修改第 3 页的字号；执行前需要确认。",
    }


async def _seed_human_request(course_id: str, slide_id: str, *, request_type: str = "polish_intent_confirmation"):
    runtime = await build_runtime(course_id, trigger="message")
    command = _resolved_command(slide_id)
    async with SessionLocal() as db:
        generation = await db.get(GenerationRun, runtime.generation_run.id)
        pipeline = await db.get(PipelineRun, runtime.pipeline_run.id)
        generation.status = "completed"
        pipeline.status = "completed"
        pipeline.plan_json = {
            "result_status": "needs_confirmation",
            "resolved_polish_command": command,
        }
        message = AgentMessage(
            course_id=course_id,
            task_id=runtime.task.id,
            run_id=generation.id,
            module_type="ppt",
            role="user",
            content=command["raw_text"],
            metadata_json={
                "target_slide_ids": [slide_id],
                "selected_slide_ids": [slide_id],
                "modality": "layout",
                "polish_options": {"strength": "subtle"},
            },
            status="completed",
        )
        db.add(message)
        options = (
            [
                {"id": "candidate-a", "candidate_id": "steps_horizontal:2", "label": "方案 A",
                 "candidate": {"selected_candidate_id": "steps_horizontal:2", "slide_id": slide_id}},
                {"id": "candidate-b", "candidate_id": "bullet_flow:3", "label": "方案 B",
                 "candidate": {"selected_candidate_id": "bullet_flow:3", "slide_id": slide_id}},
                {"id": "reject", "label": "保留原版"},
            ]
            if "candidate" in request_type
            else [
                {"id": "confirm", "label": "按此范围执行"},
                {"id": "edit", "label": "重新指定范围或要求"},
            ]
        )
        human = PPTHumanRequest(
            pipeline_run_id=pipeline.id,
            request_type=request_type,
            prompt=command["summary"],
            options_json=options,
            response_json={"resolved_command": command},
        )
        db.add(human)
        await db.commit()
        await db.refresh(human)
    return runtime.generation_run.id, human.id


@pytest.mark.asyncio
async def test_candidate_choice_is_bound_to_continuation_metadata(
    client, auth_headers, monkeypatch,
):
    course_id = await ready_course(client, auth_headers, model_name="Human Candidate Continue Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    slide_id = ppt["current_artifact"]["content_json"]["slides"][1]["id"]
    source_run_id, request_id = await _seed_human_request(
        course_id, slide_id, request_type="layout_candidate_selection",
    )
    started: list[str] = []
    monkeypatch.setattr("app.api.v1.ppt_agent.start_task_run", started.append)

    invalid = await client.post(
        f"/api/v1/ppt-agent/runs/{source_run_id}/human-response",
        headers=auth_headers,
        json={
            "request_id": request_id,
            "choice": "candidate-a",
            "data": {"candidate_id": "unlisted:99"},
        },
    )
    assert invalid.status_code == 422
    async with SessionLocal() as db:
        assert (await db.get(PPTHumanRequest, request_id)).status == "pending"

    response = await client.post(
        f"/api/v1/ppt-agent/runs/{source_run_id}/human-response",
        headers=auth_headers,
        json={
            "request_id": request_id,
            "choice": "candidate-b",
            "data": {"candidate_id": "bullet_flow:3"},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["selected_candidate_id"] == "bullet_flow:3"
    assert payload["resolution"] == "continued"
    assert payload["result_status"] == "queued"
    assert payload["target_slide_ids"] == [slide_id]
    assert payload["confirmation_token"]
    assert started == [payload["continuation_run_id"]]
    async with SessionLocal() as db:
        human = await db.get(PPTHumanRequest, request_id)
        continuation = await db.get(GenerationRun, payload["continuation_run_id"])
        message = await db.get(AgentMessage, payload["message_id"])
        source_pipeline = await db.scalar(select(PipelineRun).where(
            PipelineRun.generation_run_id == source_run_id,
        ))
    assert human.status == "resolved"
    assert human.response_json["resolved_command"]["scope"]["target_slide_ids"] == [slide_id]
    assert continuation.trigger_type == "message"
    assert message.run_id == continuation.id
    assert "第 2 页" not in message.content
    assert message.metadata_json["target_slide_ids"] == [slide_id]
    assert message.metadata_json["polish_options"]["confirmation_token"] == payload["confirmation_token"]
    assert message.metadata_json["human_confirmation"]["request_id"] == request_id
    assert message.metadata_json["selected_candidate_id"] == "bullet_flow:3"
    assert message.metadata_json["human_confirmation"]["choice"] == "candidate-b"
    assert message.metadata_json["confirmed_resolved_command"]["objectives"][0]["metric"] == "font_size"
    assert message.metadata_json["confirmed_resolved_command"]["needs_confirmation"] is False
    assert message.metadata_json["confirmed_resolved_command"]["ambiguities"] == []
    assert source_pipeline.plan_json["human_resolution"]["continuation_run_id"] == continuation.id
    metadata = dict(message.metadata_json)
    validated = await PPTAgentRuntime(
        SimpleNamespace(generation_run=continuation),
    )._validated_confirmed_command(metadata)
    assert validated.scope.target_slide_ids == [slide_id]
    assert validated.needs_confirmation is False
    assert metadata["validated_selected_candidate"]["selected_candidate_id"] == "bullet_flow:3"


@pytest.mark.asyncio
async def test_reject_confirmation_is_no_change_and_creates_no_version_or_run(
    client, auth_headers, monkeypatch,
):
    course_id = await ready_course(client, auth_headers, model_name="Human Reject Noop Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    slide_id = ppt["current_artifact"]["content_json"]["slides"][0]["id"]
    source_run_id, request_id = await _seed_human_request(course_id, slide_id)
    monkeypatch.setattr(
        "app.api.v1.ppt_agent.start_task_run",
        lambda _run_id: pytest.fail("拒绝确认不得启动新 Run"),
    )
    async with SessionLocal() as db:
        run_count_before = await db.scalar(select(func.count(GenerationRun.id)))
        artifact_count_before = await db.scalar(select(func.count(Artifact.id)))

    response = await client.post(
        f"/api/v1/ppt-agent/runs/{source_run_id}/human-response",
        headers=auth_headers,
        json={"request_id": request_id, "choice": "edit", "data": {}},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "request_id": request_id,
        "status": "resolved",
        "resolution": "rejected",
        "result_status": "no_change",
        "continuation_run_id": None,
    }
    async with SessionLocal() as db:
        human = await db.get(PPTHumanRequest, request_id)
        pipeline = await db.scalar(select(PipelineRun).where(
            PipelineRun.generation_run_id == source_run_id,
        ))
        run_count_after = await db.scalar(select(func.count(GenerationRun.id)))
        artifact_count_after = await db.scalar(select(func.count(Artifact.id)))
    assert human.status == "resolved"
    assert human.response_json["resolution"] == "rejected"
    assert pipeline.plan_json["result_status"] == "no_change"
    assert run_count_after == run_count_before
    assert artifact_count_after == artifact_count_before


@pytest.mark.asyncio
async def test_close_layout_candidates_create_pending_human_request(
    client, auth_headers, monkeypatch,
):
    course_id = await ready_course(client, auth_headers, model_name="Candidate Gate Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    slide = ppt["current_artifact"]["content_json"]["slides"][0]
    slide_id = slide["id"]
    runtime = await build_runtime(course_id, trigger="message")
    runtime.selected_slide_ids = [slide_id]
    runtime.baseline_slides = list(ppt["current_artifact"]["content_json"]["slides"])
    runtime.resolved_polish_command = {
        **_resolved_command(slide_id),
        "confidence": 1.0, "ambiguities": [], "needs_confirmation": False,
    }
    base_elements = list(slide.get("elements") or []) or [
        {"kind": "textbox", "role": "title", "content_ref": "title",
         "text": slide.get("title") or "标题", "x": 1.0, "y": 0.6, "w": 8.0, "h": 0.8,
         "style": {"size": 28}},
    ]
    runtime.layout_compile_results = [{
        "slide_id": slide_id, "status": "applied",
        "requires_candidate_confirmation": True, "candidate_score_gap": 2.4,
        "requested_style": {}, "requested_objectives": [],
        "baseline_metrics": {"quality_score": 70},
        "final_metrics": {"quality_score": 80},
        "candidate_rankings": [
            {"rank": 1, "candidate_id": "bullet_flow:1", "layout_type": "bullet_flow",
             "style": {}, "quality_score": 80, "quality_delta": 10,
             "objective_results": [], "elements": base_elements},
            {"rank": 2, "candidate_id": "split_two_column:1", "layout_type": "split_two_column",
             "style": {}, "quality_score": 78, "quality_delta": 8,
             "objective_results": [], "elements": base_elements},
        ],
    }]
    preview = runtime.workspace_root / "qa" / "candidate.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"candidate-preview")
    monkeypatch.setattr(
        PPTAgentRuntime, "_render_candidate_preview",
        lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=str(preview)),
    )

    created = await PPTAgentRuntime(runtime)._request_candidate_confirmation_if_needed()

    assert created is True
    async with SessionLocal() as db:
        request = await db.scalar(select(PPTHumanRequest).where(
            PPTHumanRequest.pipeline_run_id == runtime.pipeline_run.id,
            PPTHumanRequest.request_type == "layout_candidate_selection",
        ))
    assert request is not None
    assert request.status == "pending"
    assert [item["id"] for item in request.options_json] == [
        "candidate-a", "candidate-b", "reject",
    ]
    assert request.options_json[0]["candidate_id"] == "bullet_flow:1"
    assert request.options_json[0]["candidate"]["elements"] == base_elements
    assert request.options_json[0]["preview_url"] == (
        f"/api/v1/ppt-agent/runs/{runtime.generation_run.id}"
        f"/candidate-previews/{request.id}/candidate-a"
    )
    assert runtime.candidate_request_id == request.id
    assert runtime.candidate_options[0]["preview_url"] == request.options_json[0]["preview_url"]
    assert "candidate" not in runtime.candidate_options[0]
    assert request.options_json[0]["page_number"] == 1
    assert request.options_json[0]["display_label"].startswith("第 1 页")

    unauthenticated = await client.get(request.options_json[0]["preview_url"])
    assert unauthenticated.status_code == 401
    response = await client.get(
        request.options_json[0]["preview_url"], headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.content == b"candidate-preview"


@pytest.mark.asyncio
async def test_layout_candidate_confirmation_requires_two_rendered_previews(
    client, auth_headers, monkeypatch,
):
    course_id = await ready_course(client, auth_headers, model_name="Preview Failure Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    slide = ppt["current_artifact"]["content_json"]["slides"][0]
    slide_id = slide["id"]
    runtime = await build_runtime(course_id, trigger="message")
    runtime.selected_slide_ids = [slide_id]
    runtime.baseline_slides = list(ppt["current_artifact"]["content_json"]["slides"])
    runtime.layout_compile_results = [{
        "slide_id": slide_id, "status": "applied",
        "requires_candidate_confirmation": True, "candidate_score_gap": 1.0,
        "requested_style": {}, "requested_objectives": [],
        "baseline_metrics": {"quality_score": 85},
        "final_metrics": {"quality_score": 89},
        "candidate_rankings": [
            {"rank": 1, "candidate_id": "bullet_flow:1", "layout_type": "bullet_flow",
             "style": {}, "quality_score": 89, "quality_delta": 4,
             "objective_results": [], "publishable": True,
             "elements": list(slide.get("elements") or [])},
            {"rank": 2, "candidate_id": "split_two_column:1", "layout_type": "split_two_column",
             "style": {}, "quality_score": 88.7, "quality_delta": 3.7,
             "objective_results": [], "publishable": True,
             "elements": list(slide.get("elements") or [])},
        ],
    }]
    monkeypatch.setattr(
        PPTAgentRuntime, "_render_candidate_preview",
        lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=""),
    )

    created = await PPTAgentRuntime(runtime)._request_candidate_confirmation_if_needed()

    assert created is False
    assert runtime.result_status == "no_change"
    page = runtime.layout_compile_results[0]
    assert page["status"] == "preserved"
    assert page["rejection_code"] == "render_unavailable"
    async with SessionLocal() as db:
        request = await db.scalar(select(PPTHumanRequest).where(
            PPTHumanRequest.pipeline_run_id == runtime.pipeline_run.id,
            PPTHumanRequest.request_type == "layout_candidate_selection",
        ))
    assert request is None


@pytest.mark.asyncio
async def test_single_preview_eligible_candidate_can_be_confirmed(
    client, auth_headers, monkeypatch,
):
    course_id = await ready_course(client, auth_headers, model_name="Single Preview Mock")
    project = (await client.get(f"/api/v1/courses/{course_id}/project", headers=auth_headers)).json()
    ppt = next(item for item in project["tasks"] if item["task_type"] == "ppt")
    slides = list(ppt["current_artifact"]["content_json"]["slides"])
    slide = slides[0]
    runtime = await build_runtime(course_id, trigger="message")
    runtime.selected_slide_ids = [slide["id"]]
    runtime.baseline_slides = slides
    runtime.layout_compile_results = [{
        "slide_id": slide["id"], "status": "applied",
        "requires_candidate_confirmation": True,
        "requested_style": {}, "requested_objectives": [],
        "baseline_metrics": {"quality_score": 85},
        "final_metrics": {"quality_score": 87.4},
        "candidate_rankings": [{
            "rank": 1, "candidate_id": "bullet_flow:1", "layout_type": "bullet_flow",
            "style": {}, "quality_score": 87.4, "quality_delta": 2.4,
            "objective_results": [], "preview_eligible": True,
            "elements": list(slide.get("elements") or []),
        }],
    }]
    preview = runtime.workspace_root / "qa" / "single-candidate.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"candidate-preview")
    monkeypatch.setattr(
        PPTAgentRuntime, "_render_candidate_preview",
        lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=str(preview)),
    )

    created = await PPTAgentRuntime(runtime)._request_candidate_confirmation_if_needed()

    assert created is True
    async with SessionLocal() as db:
        request = await db.scalar(select(PPTHumanRequest).where(
            PPTHumanRequest.pipeline_run_id == runtime.pipeline_run.id,
            PPTHumanRequest.request_type == "layout_candidate_selection",
        ))
    assert request is not None
    assert [item["id"] for item in request.options_json] == ["candidate-a", "reject"]
    assert request.options_json[0]["preview_url"]
