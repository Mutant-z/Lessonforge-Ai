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
    # 多模态状态现在由 vision_chat 用途派生，不能再通过旧布尔字段把文本模型伪装成视觉模型。
    assert updated.json()["supports_multimodal"] is False

    invalid = await client.patch(
        f"/api/v1/settings/models/{created.json()['id']}",
        headers=auth_headers,
        json={"context_window_tokens": 0},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_media_capabilities_require_matching_transport(client, auth_headers):
    mismatched = await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "错误的视频能力配置",
            "provider": "openai_compatible",
            "base_url": "https://media.example/v1",
            "model_name": "chat-only-model",
            "capabilities": ["text_generation", "video_generation"],
            "api_mode": "text_chat",
            "is_active": False,
        },
    )
    assert mismatched.status_code == 422
    assert "不支持已勾选的能力：视频生成" in mismatched.json()["detail"]

    video = await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "视频接口配置",
            "provider": "openai_compatible",
            "base_url": "https://media.example/v1",
            "model_name": "video-model",
            "capabilities": ["video_generation"],
            "api_mode": "custom_video_async_http",
            "adapter_config": {"endpoint_path": "/videos/generations"},
            "is_active": False,
        },
    )
    assert video.status_code == 200, video.text

    incompatible_update = await client.patch(
        f"/api/v1/settings/models/{video.json()['id']}",
        headers=auth_headers,
        json={"capabilities": ["video_generation", "speech_generation"]},
    )
    assert incompatible_update.status_code == 422
    assert "语音生成" in incompatible_update.json()["detail"]


@pytest.mark.asyncio
async def test_text_vision_and_video_have_independent_defaults(client, auth_headers):
    text_model = await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "默认文本", "provider": "openai_compatible", "base_url": "https://chat.example/v1",
        "model_name": "chat", "api_mode": "text_chat", "model_category": "text",
        "model_purpose": "text_chat", "is_active": True,
    })
    assert text_model.status_code == 200, text_model.text
    vision_model = await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "默认视觉", "provider": "openai_compatible", "base_url": "https://vision.example/v1",
        "model_name": "vision", "api_mode": "text_chat", "model_category": "vision",
        "model_purpose": "vision_chat", "is_active": True,
    })
    assert vision_model.status_code == 200, vision_model.text
    assert vision_model.json()["capabilities"] == ["text_generation", "structured_output", "vision_review"]
    video_model = await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "默认视频", "provider": "openai_compatible", "base_url": "https://video.example/v1",
        "model_name": "video", "api_mode": "custom_video_async_http", "model_category": "video",
        "model_purpose": "video_generation", "adapter_config": {"endpoint_path": "/videos/generations"},
        "is_active": True,
    })
    assert video_model.status_code == 200, video_model.text

    settings = (await client.get("/api/v1/settings", headers=auth_headers)).json()
    assert settings["active_config_id"] == text_model.json()["id"]
    assert settings["active_config_ids"] == {
        "text": text_model.json()["id"],
        "vision": vision_model.json()["id"],
        "video": video_model.json()["id"],
    }


@pytest.mark.asyncio
async def test_duplicate_model_keeps_encrypted_key_without_exposing_secret(client, auth_headers):
    secret = "sk-duplicate-private-key"
    source = await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "文本端点", "provider": "openai_compatible", "base_url": "https://chat.example/v1",
        "model_name": "multimodal", "api_key": secret, "model_category": "text",
        "model_purpose": "text_chat", "api_mode": "text_chat", "is_active": False,
    })
    duplicated = await client.post(
        f"/api/v1/settings/models/{source.json()['id']}/duplicate", headers=auth_headers,
        json={"model_category": "vision", "model_purpose": "vision_chat"},
    )
    assert duplicated.status_code == 200, duplicated.text
    assert duplicated.json()["model_category"] == "vision"
    assert duplicated.json()["api_key_configured"] is True
    assert secret not in duplicated.text


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
