import pytest


def _tiny_png() -> bytes:
    from io import BytesIO
    from PIL import Image
    output = BytesIO()
    Image.new("RGB", (12, 8), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_auth_and_course_crud(client, auth_headers):
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 200
    payload = {"title": "一次函数", "subject": "初中数学", "grade_level": "八年级", "audience": "已掌握变量概念的学生", "duration_minutes": 12, "scenario": "课堂讲解", "course_task": "解释函数关系并完成基础判断"}
    created = await client.post("/api/v1/courses", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    course_id = created.json()["id"]
    listed = await client.get("/api/v1/courses", headers=auth_headers)
    assert listed.json()["total"] >= 1
    updated = await client.patch(f"/api/v1/courses/{course_id}", headers=auth_headers, json={"title": "一次函数的图像"})
    assert updated.json()["title"] == "一次函数的图像"


@pytest.mark.asyncio
async def test_course_permission_isolation(client, auth_headers):
    payload = {"title": "权限课程", "subject": "测试", "grade_level": "测试", "audience": "测试学习者", "duration_minutes": 5, "scenario": "课堂讲解", "course_task": "验证隔离"}
    course_id = (await client.post("/api/v1/courses", headers=auth_headers, json=payload)).json()["id"]
    import uuid
    name = f"other_{uuid.uuid4().hex[:8]}"
    await client.post("/api/v1/auth/register", json={"username": name, "password": "strong-password"})
    token = (await client.post("/api/v1/auth/login", data={"username": name, "password": "strong-password"})).json()["access_token"]
    response = await client.get(f"/api/v1/courses/{course_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_model_key_is_never_returned(client, auth_headers):
    secret = "sk-private-model-key"
    saved = await client.patch("/api/v1/settings", headers=auth_headers, json={"provider": "openai_compatible", "base_url": "https://example.invalid/v1", "model_name": "example-model", "api_key": secret, "timeout_seconds": 60})
    assert saved.status_code == 200 and secret not in saved.text
    loaded = await client.get("/api/v1/settings", headers=auth_headers)
    assert loaded.json()["api_key_configured"] is True
    assert secret not in loaded.text


@pytest.mark.asyncio
async def test_model_capabilities_defaults_and_updates(client, auth_headers):
    created = await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "能力测试模型",
            "provider": "mock",
            "base_url": "mock://local",
            "model_name": "mock-capability",
            "timeout_seconds": 30,
            "is_active": True,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["context_window_tokens"] == 1_000_000
    assert created.json()["supports_multimodal"] is False

    updated = await client.patch(
        f"/api/v1/settings/models/{created.json()['id']}",
        headers=auth_headers,
        json={"context_window_tokens": 128_000, "supports_multimodal": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["context_window_tokens"] == 128_000
    assert updated.json()["supports_multimodal"] is True

    invalid = await client.patch(
        f"/api/v1/settings/models/{created.json()['id']}",
        headers=auth_headers,
        json={"context_window_tokens": 0},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_model_selection_rejects_another_users_config(client, auth_headers):
    config = (await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "私有模型", "provider": "mock", "base_url": "mock://local",
            "model_name": "private-mock", "timeout_seconds": 30,
        },
    )).json()

    import uuid
    username = f"model_other_{uuid.uuid4().hex[:8]}"
    await client.post("/api/v1/auth/register", json={"username": username, "password": "strong-password"})
    token = (await client.post(
        "/api/v1/auth/login", data={"username": username, "password": "strong-password"}
    )).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/course-intakes",
        headers=other_headers,
        json={"model_config_id": config["id"]},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_image_connection_test_calls_image_transport(client, auth_headers, monkeypatch):
    created = await client.post(
        "/api/v1/settings/models", headers=auth_headers, json={
            "name": "图片连通性模型",
            "provider": "openai_compatible",
            "base_url": "https://images.example/v1",
            "model_name": "image-model",
            "timeout_seconds": 30,
            "capabilities": ["image_generation"],
            "api_mode": "custom_image_http",
            "adapter_config": {"endpoint_path": "/render", "response_base64_path": "image"},
            "is_active": False,
        },
    )
    assert created.status_code == 200, created.text
    calls = []

    async def fake_generate(config, prompt, size):
        calls.append((config.api_mode, config.adapter_config_json, prompt, size))
        return _tiny_png(), "image/png"

    monkeypatch.setattr("app.services.exercise_visual_service.generate_image", fake_generate)
    tested = await client.post("/api/v1/settings/test-connection", headers=auth_headers, json={
        "config_id": created.json()["id"],
        "test_capability": "image_generation",
    })
    assert tested.status_code == 200, tested.text
    assert tested.json()["success"] is True
    assert tested.json()["mime_type"] == "image/png"
    assert calls[0][0] == "custom_image_http"
    assert calls[0][1]["endpoint_path"] == "/render"
