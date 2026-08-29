import httpx
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
async def test_settings_accepts_legacy_double_encoded_preferences(client, auth_headers):
    import json

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.entities import ModelConfig, User

    created = await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "旧偏好兼容测试",
        "provider": "mock",
        "base_url": "mock://local",
        "model_name": "legacy-preferences",
        "model_category": "text",
        "model_purpose": "text_chat",
        "is_active": True,
    })
    assert created.status_code == 200, created.text

    async with SessionLocal() as db:
        owner = await db.scalar(select(User).order_by(User.created_at.desc()))
        config = await db.scalar(select(ModelConfig).where(
            ModelConfig.id == created.json()["id"], ModelConfig.owner_id == owner.id,
        ))
        config.preferences_json = json.dumps({
            "default_language": "zh-CN",
            "default_grade_level": "八年级",
            "default_ppt_template": "lessonforge_deck_academic",
        })
        await db.commit()

    loaded = await client.get("/api/v1/settings", headers=auth_headers)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["preferences"]["default_grade_level"] == "八年级"


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
async def test_video_capability_is_normalized_to_protocol_transport(client, auth_headers):
    declared = await client.post(
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
    assert declared.status_code == 200, declared.text
    assert declared.json()["model_purpose"] == "video_generation"
    assert declared.json()["api_mode"] == "protocol_video"
    assert declared.json()["video_capability_status"] == "unverified"

    video = await client.post(
        "/api/v1/settings/models",
        headers=auth_headers,
        json={
            "name": "视频接口配置",
            "provider": "openai_compatible",
            "base_url": "https://media.example/v1",
            "model_name": "gemini-omni-flash-preview",
            "capabilities": ["video_generation", "native_audio_video_generation"],
            "api_mode": "gemini_interactions_video",
            "adapter_config": {"interactions_path": "/v1beta/interactions", "delivery": "uri"},
            "is_active": False,
        },
    )
    assert video.status_code == 200, video.text
    assert video.json()["api_mode"] == "protocol_video"
    assert video.json()["adapter_config"] == {}

    incompatible_update = await client.patch(
        f"/api/v1/settings/models/{video.json()['id']}",
        headers=auth_headers,
        json={"capabilities": ["video_generation", "speech_generation"]},
    )
    assert incompatible_update.status_code == 422
    assert "语音生成" in incompatible_update.json()["detail"]


@pytest.mark.asyncio
async def test_video_connection_test_does_not_require_video_output(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "Seedance-2.0"}]})

    monkeypatch.setattr(
        "app.api.v1.settings.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = await client.post("/api/v1/settings/test-connection", headers=auth_headers, json={
        "provider": "openai_compatible",
        "base_url": "https://gateway.example/v1",
        "model_name": "Seedance-2.0",
        "api_key": "test-key",
        "test_capability": "video_generation",
    })
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["message"] == "连接正常，视频能力将在首次生成时验证。"


@pytest.mark.asyncio
async def test_video_connection_timeout_falls_back_to_gateway_reachability(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            raise httpx.ReadTimeout("model discovery is slow", request=request)
        assert request.url.path == "/v1"
        return httpx.Response(404, json={"detail": "not found"})

    monkeypatch.setattr(
        "app.api.v1.settings.build_async_client",
        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = await client.post("/api/v1/settings/test-connection", headers=auth_headers, json={
        "provider": "openai_compatible",
        "base_url": "https://gateway.example/v1",
        "model_name": "Seedance-2.0",
        "api_key": "test-key",
        "test_capability": "video_generation",
    })
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "网关地址可访问" in response.json()["message"]


@pytest.mark.asyncio
async def test_new_default_video_model_rebinds_existing_course_session(client, auth_headers):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.entities import AgentChatSession, CourseTask

    course_payload = {
        "title": "默认视频模型切换",
        "subject": "测试",
        "grade_level": "八年级",
        "audience": "学生",
        "duration_minutes": 5,
        "scenario": "课堂讲解",
        "course_task": "验证视频模型默认项同步",
    }
    course = await client.post("/api/v1/courses", headers=auth_headers, json=course_payload)
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]
    old_model = await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "旧视频模型",
        "provider": "anthropic",
        "base_url": "https://old.example/v1",
        "model_name": "old-video",
        "model_category": "video",
        "model_purpose": "video_generation",
        "is_active": True,
    })
    assert old_model.status_code == 200, old_model.text
    selected = await client.patch(
        f"/api/v1/courses/{course_id}/tasks/video_generation/model",
        headers=auth_headers,
        json={"video_model_config_id": old_model.json()["id"]},
    )
    assert selected.status_code == 200, selected.text

    async with SessionLocal() as db:
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "video_generation",
        ))
        task.status = "failed"
        task.error_json = {"message": "旧模型失败"}
        await db.commit()

    new_model = await client.post("/api/v1/settings/models", headers=auth_headers, json={
        "name": "新默认视频模型",
        "provider": "openai_compatible",
        "base_url": "https://new.example/v1",
        "model_name": "new-video",
        "model_category": "video",
        "model_purpose": "video_generation",
        "is_active": True,
    })
    assert new_model.status_code == 200, new_model.text

    async with SessionLocal() as db:
        session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course_id,
            AgentChatSession.module_type == "video_generation",
        ))
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "video_generation",
        ))
        assert session.video_model_config_id == new_model.json()["id"]
        assert task.status == "ready_to_generate"
        assert task.error_json is None


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
        "model_name": "gemini-3.7-flash-high", "api_mode": "gemini_interactions_video", "model_category": "video",
        "model_purpose": "video_generation", "adapter_config": {"interactions_path": "/v1beta/interactions", "delivery": "uri"},
        "is_active": True,
    })
    assert video_model.status_code == 200, video_model.text
    assert video_model.json()["api_mode"] == "protocol_video"

    settings = (await client.get("/api/v1/settings", headers=auth_headers)).json()
    assert settings["active_config_id"] == text_model.json()["id"]
    assert settings["active_config_ids"] == {
        "text": text_model.json()["id"],
        "vision": vision_model.json()["id"],
        "video": video_model.json()["id"],
    }

    from app.core.database import SessionLocal
    from app.models.entities import ModelConfig
    from app.services.model_config_service import resolve_model_config

    async with SessionLocal() as db:
        stored_video = await db.get(ModelConfig, video_model.json()["id"])
        resolved_video = await resolve_model_config(
            db,
            stored_video.owner_id,
            text_model.json()["id"],
            "video",
        )
    assert resolved_video.id == video_model.json()["id"]


@pytest.mark.asyncio
async def test_archived_media_config_is_listed_but_cannot_activate(client, auth_headers):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.entities import ModelConfig, User

    async with SessionLocal() as db:
        owner = await db.scalar(select(User).order_by(User.created_at.desc()))
        legacy = ModelConfig(
            owner_id=owner.id,
            name="历史语音配置",
            provider="openai_compatible",
            base_url="https://speech.example/v1",
            model_name="legacy-tts",
            capabilities_json=["speech_generation"],
            api_mode="custom_speech_http",
            model_category="video",
            model_purpose="speech_generation",
            is_archived=True,
            is_active=False,
        )
        db.add(legacy)
        await db.commit()
        legacy_id = legacy.id

    settings = (await client.get("/api/v1/settings", headers=auth_headers)).json()
    archived = next(item for item in settings["configs"] if item["id"] == legacy_id)
    assert archived["is_archived"] is True
    response = await client.post(f"/api/v1/settings/models/{legacy_id}/activate", headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_protocol_video_reconciliation_is_idempotent_and_preserves_secrets(client, auth_headers):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.security import encrypt_secret
    from app.models.entities import ModelConfig, User
    from app.services.model_config_service import reconcile_protocol_video_configs

    await client.get("/api/v1/settings", headers=auth_headers)
    encrypted = encrypt_secret("migration-secret")
    async with SessionLocal() as db:
        owner = await db.scalar(select(User).order_by(User.created_at.desc()))
        db.add(ModelConfig(
            owner_id=owner.id,
            name="通用 3.7",
            provider="openai_compatible",
            base_url="https://gateway.example/v1",
            model_name="gemini-3.7-flash-high",
            encrypted_api_key=encrypted,
            capabilities_json=["text_generation", "structured_output", "video_generation", "native_audio_video_generation"],
            api_mode="openai_chat_video",
            model_category="text",
            model_purpose="text_chat",
            is_active=True,
        ))
        db.add(ModelConfig(
            owner_id=owner.id,
            name="旧豆包",
            provider="volcengine_ark",
            base_url="https://ark.example",
            model_name="doubao-seedance-2.5",
            encrypted_api_key=encrypted,
            capabilities_json=["video_generation", "native_audio_video_generation"],
            api_mode="volcengine_ark_video",
            model_category="video",
            model_purpose="video_generation",
            is_active=True,
        ))
        await db.commit()

        first = await reconcile_protocol_video_configs(db)
        second = await reconcile_protocol_video_configs(db)
        configs = list(await db.scalars(select(ModelConfig).where(ModelConfig.owner_id == owner.id)))

    protocol = [item for item in configs if item.model_purpose == "video_generation" and not item.is_archived]
    legacy = next(item for item in configs if item.name == "旧豆包")
    text_config = next(item for item in configs if item.name == "通用 3.7")
    assert first["created"] == 1
    assert second["created"] == 0
    assert len(protocol) == 1
    assert protocol[0].api_mode == "protocol_video"
    assert protocol[0].encrypted_api_key == encrypted
    assert text_config.api_mode == "text_chat"
    assert "video_generation" not in text_config.capabilities_json
    assert legacy.is_archived is True
    assert legacy.encrypted_api_key == encrypted


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
