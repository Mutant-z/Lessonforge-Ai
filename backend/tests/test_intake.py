import asyncio

import pytest

from app.providers.llm.base import LLMProviderError
from app.services import intake_service


async def wait_for_intake(client, headers, session_id: str, terminal=("ready", "collecting", "failed")):
    state = None
    for _ in range(100):
        state = (await client.get(f"/api/v1/course-intakes/{session_id}", headers=headers)).json()
        if state["status"] in terminal and not state.get("active_turn_id"):
            return state
        await asyncio.sleep(0.02)
    return state


@pytest.mark.asyncio
async def test_conversational_intake_confirm_is_idempotent(client, auth_headers):
    created = await client.post("/api/v1/course-intakes", headers=auth_headers)
    assert created.status_code == 201
    session = created.json()

    sent = await client.post(
        f"/api/v1/course-intakes/{session['id']}/messages",
        headers=auth_headers,
        json={
            "content": "为高一学生制作一节15分钟的《牛顿第二定律》物理微课，用于课堂讲解，重点解释F=ma并结合电梯案例。",
            "expected_revision": 0,
        },
    )
    assert sent.status_code == 202
    turn_id = sent.json()["turn_id"]
    state = await wait_for_intake(client, auth_headers, session["id"])
    assert state["status"] == "ready", state
    assert state["draft"]["title"] == "牛顿第二定律"
    assert state["draft"]["duration_minutes"] == 15
    assert not state["missing_fields"]

    token = await client.post(f"/api/v1/course-intakes/turns/{turn_id}/stream-token", headers=auth_headers)
    events = await client.get(f"/api/v1/course-intakes/turns/{turn_id}/events?token={token.json()['token']}")
    assert "event: draft_updated" in events.text
    assert "event: assistant_delta" in events.text

    patched = await client.patch(
        f"/api/v1/course-intakes/{session['id']}/draft",
        headers=auth_headers,
        json={"field": "grade_level", "value": "高二", "expected_revision": state["current_revision"]},
    )
    assert patched.status_code == 200
    revised = patched.json()
    stale = await client.patch(
        f"/api/v1/course-intakes/{session['id']}/draft",
        headers=auth_headers,
        json={"field": "grade_level", "value": "高三", "expected_revision": state["current_revision"]},
    )
    assert stale.status_code == 409

    confirmation = {"expected_revision": revised["current_revision"], "idempotency_key": f"intake-{session['id']}"}
    confirmed = await client.post(f"/api/v1/course-intakes/{session['id']}/confirm", headers=auth_headers, json=confirmation)
    assert confirmed.status_code == 202, confirmed.text
    repeated = await client.post(f"/api/v1/course-intakes/{session['id']}/confirm", headers=auth_headers, json=confirmation)
    assert repeated.status_code == 202
    assert repeated.json()["course_id"] == confirmed.json()["course_id"]
    assert repeated.json()["run_id"] == confirmed.json()["run_id"]


@pytest.mark.asyncio
async def test_intake_detects_blocking_scope_and_material_conflicts(client, auth_headers):
    session = (await client.post("/api/v1/course-intakes", headers=auth_headers)).json()
    sent = await client.post(
        f"/api/v1/course-intakes/{session['id']}/messages",
        headers=auth_headers,
        json={
            "content": "为八年级学生制作5分钟《勾股定理》数学微课，覆盖整章全部知识点，并且完全依据教材，重点掌握基础判断。",
            "expected_revision": 0,
        },
    )
    assert sent.status_code == 202
    state = await wait_for_intake(client, auth_headers, session["id"])
    assert state["status"] == "collecting"
    blocking = [item for item in state["conflicts"] if item["severity"] == "blocking"]
    assert {item["field"] for item in blocking} == {"duration_minutes", "materials"}
    confirm = await client.post(
        f"/api/v1/course-intakes/{session['id']}/confirm",
        headers=auth_headers,
        json={"expected_revision": state["current_revision"], "idempotency_key": "intake-test-key-0002"},
    )
    assert confirm.status_code == 409


@pytest.mark.asyncio
async def test_intake_model_selection_persists_and_is_inherited(client, auth_headers):
    first = (await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "默认 Mock",
            "provider": "mock",
            "base_url": "mock://local",
            "model_name": "mock-default",
            "timeout_seconds": 30,
            "is_active": True,
        },
    )).json()
    second = (await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "会话 Mock",
            "provider": "mock",
            "base_url": "mock://local",
            "model_name": "mock-session",
            "timeout_seconds": 30,
            "is_active": False,
        },
    )).json()

    created = await client.post("/api/v1/course-intakes", headers=auth_headers, json={})
    assert created.json()["model_config_id"] == first["id"]
    session_id = created.json()["id"]
    switched = await client.patch(
        f"/api/v1/course-intakes/{session_id}/model",
        headers=auth_headers,
        json={"model_config_id": second["id"]},
    )
    assert switched.status_code == 200
    assert switched.json()["model_config_id"] == second["id"]

    sent = await client.post(
        f"/api/v1/course-intakes/{session_id}/messages",
        headers=auth_headers,
        json={
            "content": "为高一学生制作一节15分钟的《牛顿第二定律》物理微课，用于课堂讲解，重点解释F=ma。",
            "expected_revision": 0,
        },
    )
    assert sent.status_code == 202
    state = await wait_for_intake(client, auth_headers, session_id)
    confirmed = await client.post(
        f"/api/v1/course-intakes/{session_id}/confirm",
        headers=auth_headers,
        json={
            "expected_revision": state["current_revision"],
            "idempotency_key": f"model-inherit-{session_id}",
        },
    )
    assert confirmed.status_code == 202, confirmed.text
    course = await client.get(
        f"/api/v1/courses/{confirmed.json()['course_id']}", headers=auth_headers
    )
    assert course.json()["model_config_id"] == second["id"]


@pytest.mark.asyncio
async def test_failed_intake_turn_is_safe_and_retry_does_not_duplicate_user_message(
    client,
    auth_headers,
    monkeypatch,
):
    attempts = 0

    async def flaky_analysis(provider, current, messages, material_summaries):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise LLMProviderError(
                "upstream_empty_response",
                "模型服务返回了空响应，请检查 Base URL、模型名称或网关兼容性。",
            )
        return intake_service.deterministic_analysis(current, messages, bool(material_summaries))

    monkeypatch.setattr(intake_service, "analyze_requirements", flaky_analysis)
    session = (await client.post("/api/v1/course-intakes", headers=auth_headers)).json()
    sent = await client.post(
        f"/api/v1/course-intakes/{session['id']}/messages",
        headers=auth_headers,
        json={
            "content": "为高一学生制作一节15分钟的《牛顿第二定律》物理微课，用于课堂讲解，重点解释F=ma。",
            "expected_revision": 0,
        },
    )
    failed_turn_id = sent.json()["turn_id"]
    failed = await wait_for_intake(client, auth_headers, session["id"])

    assert failed["status"] == "collecting"
    assert failed["last_failure"] == {
        "turn_id": failed_turn_id,
        "code": "upstream_empty_response",
        "message": "模型服务返回了空响应，请检查 Base URL、模型名称或网关兼容性。",
        "retryable": True,
    }
    token = await client.post(
        f"/api/v1/course-intakes/turns/{failed_turn_id}/stream-token",
        headers=auth_headers,
    )
    events = await client.get(
        f"/api/v1/course-intakes/turns/{failed_turn_id}/events?token={token.json()['token']}"
    )
    assert '"code": "upstream_empty_response"' in events.text
    assert "Expecting value" not in events.text

    retried = await client.post(
        f"/api/v1/course-intakes/turns/{failed_turn_id}/retry",
        headers=auth_headers,
    )
    assert retried.status_code == 202
    recovered = await wait_for_intake(client, auth_headers, session["id"])
    assert recovered["status"] == "ready"
    assert recovered["last_failure"] is None
    messages = (await client.get(
        f"/api/v1/course-intakes/{session['id']}/messages",
        headers=auth_headers,
    )).json()
    assert len([message for message in messages if message["role"] == "user"]) == 1

    stale_retry = await client.post(
        f"/api/v1/course-intakes/turns/{failed_turn_id}/retry",
        headers=auth_headers,
    )
    assert stale_retry.status_code == 409
