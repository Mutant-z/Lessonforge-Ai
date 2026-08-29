from __future__ import annotations

import pytest
from sqlalchemy import select

from agent_pipeline_helpers import ready_course
from app.api.v1 import video_generation as video_generation_api
from app.core.database import SessionLocal
from app.core.security import encrypt_secret
from app.models.entities import AgentChatSession, Artifact, CourseProject, CourseTask, ModelConfig, VideoSceneJob
from app.schemas.artifact import (
    SeedanceVideoProductionSettings,
    SeedanceVideoScene,
    SeedanceVideoScriptContent,
    VideoScriptCourseInfo,
)
from app.schemas.video import SeedanceVideoGenerationRunRequest, VideoGenerationQuoteRequest
from app.services.media_provider_service import MediaProviderError
from app.services.seedance_video_generation_service import create_seedance_video_run, create_video_generation_quote
from app.services.video_generation_capability_service import get_video_generation_capabilities


def _protocol_video_config(owner_id: str) -> ModelConfig:
    return ModelConfig(
        owner_id=owner_id,
        name="通用协议视频测试",
        provider="openai_compatible",
        base_url="http://127.0.0.1:8045",
        model_name="gemini-3.7-flash-high",
        timeout_seconds=10,
        capabilities_json=["video_generation", "native_audio_video_generation"],
        api_mode="protocol_video",
        adapter_config_json={},
        model_category="video",
        model_purpose="video_generation",
    )


def _gemini_transcription_config(owner_id: str) -> ModelConfig:
    return ModelConfig(
        owner_id=owner_id,
        name="Gemini 3.7 Audio Test",
        provider="anthropic",
        base_url="http://127.0.0.1:8045",
        model_name="gemini-3.7-flash-high",
        encrypted_api_key=encrypt_secret("test-key"),
        timeout_seconds=10,
        capabilities_json=["text_generation", "structured_output"],
        api_mode="text_chat",
        adapter_config_json={},
        model_category="text",
        model_purpose="text_chat",
    )


def _script_50_scenes() -> dict:
    scenes = []
    for index in range(50):
        scenes.append(SeedanceVideoScene(
            id=f"SV-{index + 1:02d}",
            sequence=index + 1,
            title=f"分镜 {index + 1}",
            pedagogical_role="概念讲解",
            lesson_stage_id="stage-1",
            objective_ids=["objective-1"],
            knowledge_point_ids=["knowledge-1"],
            start_seconds=index * 10,
            end_seconds=(index + 1) * 10,
            continuity_group="lesson",
            visual_prompt="教师在真实课堂中清晰讲解知识点。",
            spoken_text="这是经过确认的教学讲解内容。",
        ))
    return SeedanceVideoScriptContent(
        course_info=VideoScriptCourseInfo(
            course_title="报价测试课程",
            subject="物理",
            grade_level="八年级",
            audience="八年级学生",
            duration_seconds=500,
        ),
        production_settings=SeedanceVideoProductionSettings(
            target_duration_seconds=500,
            target_clip_seconds=10,
            min_clip_seconds=8,
            max_clip_seconds=10,
        ),
        scenes=scenes,
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_media_provider_error_is_structured_http_response(client, auth_headers, monkeypatch):
    course_id = await ready_course(client, auth_headers, title="视频错误契约测试")

    async def unavailable(*_args, **_kwargs):
        raise MediaProviderError(
            "Gemini Interactions 视频功能尚未启用",
            retryable=False,
            code="video_interactions_endpoint_unavailable",
        )

    monkeypatch.setattr(video_generation_api, "create_video_generation_quote", unavailable)
    response = await client.post(
        f"/api/v1/courses/{course_id}/tasks/video_generation/quotes",
        headers={**auth_headers, "X-Request-ID": "quote-request-id"},
        json={"resolution": "1280x720"},
    )

    assert response.status_code == 503
    assert response.headers["X-Request-ID"] == "quote-request-id"
    assert response.json() == {
        "detail": "Gemini Interactions 视频功能尚未启用",
        "error_code": "video_interactions_endpoint_unavailable",
        "retryable": False,
        "request_id": "quote-request-id",
    }


@pytest.mark.asyncio
async def test_unknown_quote_error_is_logged_and_response_stays_safe(
    client, auth_headers, monkeypatch, caplog,
):
    course_id = await ready_course(client, auth_headers, title="视频未知异常日志测试")

    async def fail(*_args, **_kwargs):
        raise RuntimeError("internal-sensitive-cause")

    monkeypatch.setattr(video_generation_api, "create_video_generation_quote", fail)
    response = await client.post(
        f"/api/v1/courses/{course_id}/tasks/video_generation/quotes",
        headers={**auth_headers, "X-Request-ID": "unknown-quote-request"},
        json={"resolution": "1280x720"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "服务器处理请求失败",
        "request_id": "unknown-quote-request",
    }
    assert "internal-sensitive-cause" not in response.text
    assert "unknown-quote-request" in caplog.text
    assert "tasks/video_generation/quotes" in caplog.text
    assert "internal-sensitive-cause" in caplog.text


@pytest.mark.asyncio
async def test_preflight_does_not_require_audio_transcription(client, auth_headers):
    course_id = await ready_course(client, auth_headers, title="视频预检测试")
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        config = _protocol_video_config(course.owner_id)
        db.add(config)
        await db.flush()
        session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course_id,
            AgentChatSession.module_type == "video_generation",
        ))
        if session is None:
            session = AgentChatSession(course_id=course_id, module_type="video_generation")
            db.add(session)
        session.video_model_config_id = config.id
        await db.commit()

    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        ready = await get_video_generation_capabilities(db, course)
    assert ready.available
    assert ready.verification_status == "unverified"


@pytest.mark.asyncio
async def test_unverified_protocol_model_quotes_fifty_ten_second_scenes(client, auth_headers):
    course_id = await ready_course(client, auth_headers, title="视频报价成功测试")
    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        video = _protocol_video_config(course.owner_id)
        db.add(video)
        await db.flush()
        session = await db.scalar(select(AgentChatSession).where(
            AgentChatSession.course_id == course_id,
            AgentChatSession.module_type == "video_generation",
        ))
        if session is None:
            session = AgentChatSession(course_id=course_id, module_type="video_generation")
            db.add(session)
        session.video_model_config_id = video.id
        latest_version = await db.scalar(select(Artifact.version).where(
            Artifact.course_id == course_id,
            Artifact.artifact_type == "video_script",
        ).order_by(Artifact.version.desc())) or 0
        db.add(Artifact(
            course_id=course_id,
            artifact_type="video_script",
            version=latest_version + 1,
            blueprint_version=course.current_blueprint_version,
            content_json=_script_50_scenes(),
            content_markdown="# 视频脚本",
            status="draft",
        ))
        await db.commit()

    async with SessionLocal() as db:
        course = await db.get(CourseProject, course_id)
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "video_generation",
        ))
        quote = await create_video_generation_quote(
            db,
            task,
            course.owner_id,
            VideoGenerationQuoteRequest(resolution="1280x720"),
        )
    assert quote.scene_count == 50
    assert quote.duration_seconds == 500
    assert quote.resolution == "1280x720"

    async with SessionLocal() as db:
        task = await db.scalar(select(CourseTask).where(
            CourseTask.course_id == course_id,
            CourseTask.task_type == "video_generation",
        ))
        run = await create_seedance_video_run(
            db,
            task,
            SeedanceVideoGenerationRunRequest(action="initial"),
        )
        await db.commit()
        control = await db.scalar(select(VideoSceneJob).where(
            VideoSceneJob.generation_run_id == run.id,
            VideoSceneJob.scene_id == "__run__",
        ))
    assert control.input_json["quote"]
    assert control.input_json["quote_id"]
