from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.models.entities import ModelConfig
from app.schemas.video import (
    SeedanceNativeScene,
    SeedanceNativeSettings,
    SeedanceVideoGenerationContent,
    VideoGenerationQuoteRequest,
)
from app.services.seedance_video_generation_service import _fact_qa, _request_hash
from app.services import seedance_provider_service


def native_scene(**overrides):
    value = {
        "id": "VG-01",
        "script_scene_id": "SV-01",
        "sequence": 1,
        "start_seconds": 0,
        "end_seconds": 10,
        "continuity_group": "lab-a",
        "visual_prompt": "教师在实验台前演示量筒读数",
        "spoken_text": "量筒读数是二十毫升，视线要与液面最低处相平。",
        "voice_direction": "自然清晰",
        "required_terms": ["量筒", "液面最低处"],
        "required_numbers": ["二十毫升"],
        "required_facts": ["视线要与液面最低处相平"],
    }
    value.update(overrides)
    return SeedanceNativeScene.model_validate(value)


def model_config():
    return ModelConfig(
        id="model-1",
        owner_id="owner-1",
        name="Seedance 2.5",
        provider="volcengine_ark",
        base_url="https://ark.example.com/api/v3",
        model_name="account-authorized-seedance-2-5-id",
        timeout_seconds=30,
        api_mode="volcengine_ark_video",
        capabilities_json=["video_generation", "native_audio_video_generation"],
        adapter_config_json={"model_family": "doubao-seedance-2.5", "tokens_per_second_720p": 1000, "price_per_million_tokens_cny": 1},
    )


def test_v3_generation_rejects_ppt_source_version():
    with pytest.raises(ValidationError, match="只能记录 video_script"):
        SeedanceVideoGenerationContent(
            production_settings=SeedanceNativeSettings(
                model_config_id="model-1", model_name="Seedance 2.5",
                quote_id="quote-1", approved_max_cost_fen=10,
            ),
            source_versions={"video_script": 3, "ppt": 2},
            scenes=[native_scene()],
        )


def test_request_hash_covers_native_audio_edit_fields():
    config = model_config()
    original = native_scene()
    assert _request_hash(original, config, "1280x720") != _request_hash(
        native_scene(spoken_text="量筒读数是三十毫升。"), config, "1280x720",
    )
    assert _request_hash(original, config, "1280x720") != _request_hash(
        native_scene(end_seconds=12), config, "1280x720",
    )
    assert _request_hash(original, config, "1280x720") != _request_hash(
        original, config, "1280x720", "教师动作更克制",
    )


def test_fact_qa_requires_terms_numbers_and_conclusion():
    scene = native_scene()
    assert _fact_qa(scene, scene.spoken_text)["status"] == "passed"
    failed = _fact_qa(scene, "教师演示了实验，并提醒大家认真观察。")
    assert failed["status"] == "failed"
    assert failed["missing_terms"]
    assert failed["missing_numbers"]


def test_scene_quote_accepts_exact_edit_snapshot():
    quote = VideoGenerationQuoteRequest(
        target_scene_id="SV-01",
        instruction="保留实验室环境",
        visual_prompt="教师近景演示量筒",
        spoken_text="量筒读数是二十毫升。",
        voice_direction="自然清晰",
        duration_seconds=9,
        include_dependents=True,
    )
    assert quote.resolution == "1280x720"
    assert quote.duration_seconds == 9
    assert quote.include_dependents is True


def test_adapter_blocks_unmarked_or_legacy_model_family():
    config = model_config()
    config.adapter_config_json = {**config.adapter_config_json, "model_family": "doubao-seedance-2.0"}
    with pytest.raises(Exception, match="2.5"):
        seedance_provider_service.ArkSeedanceAdapter(config).validate_capabilities()


@pytest.mark.asyncio
async def test_adapter_can_probe_account_native_audio_capabilities(monkeypatch):
    def handler(request: httpx.Request):
        assert request.method == "GET"
        assert request.url.path.endswith("/models/account-authorized-seedance-2-5-id")
        return httpx.Response(200, json={
            "model": "account-authorized-seedance-2-5-id",
            "capabilities": {
                "native_audio": True,
                "resolutions": ["720p", "1080p"],
                "min_duration_seconds": 4,
                "max_duration_seconds": 15,
            },
        })

    def client_factory(*args, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(seedance_provider_service, "build_async_client", client_factory)
    config = model_config()
    config.adapter_config_json = {
        **config.adapter_config_json,
        "capability_probe_endpoint_path": "/models/{model}",
    }
    result = await seedance_provider_service.ArkSeedanceAdapter(config).probe_capabilities()
    assert result["source"] == "provider_capability_probe"
    assert result["native_audio"] is True


def test_v3_runtime_has_no_forbidden_generation_imports():
    source = (Path(__file__).resolve().parents[1] / "app/services/seedance_video_generation_service.py").read_text()
    for forbidden in (
        "PPTContent", "ppt_render", "generate_image", "generate_speech", "local_tts",
    ):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_seedance_contract_forces_native_audio_and_resume_only_polls(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.method == "POST":
            payload = __import__("json").loads(request.content)
            assert payload["generate_audio"] is True
            assert payload["resolution"] == "720p"
            assert payload["ratio"] == "16:9"
            assert request.headers["x-idempotency-key"] == "stable-key"
            return httpx.Response(200, json={"id": "provider-job-1"})
        return httpx.Response(200, json={
            "status": "completed",
            "content": {"video_url": "https://media.example.com/result.mp4"},
            "usage": {"total_tokens": 10000},
        })

    def client_factory(*args, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def safe_download(*args, **kwargs):
        return b"native-video-with-audio", "video/mp4"

    monkeypatch.setattr(seedance_provider_service, "build_async_client", client_factory)
    monkeypatch.setattr(seedance_provider_service, "_safe_remote_media", safe_download)
    config = model_config()
    created = await seedance_provider_service.generate_seedance_video(
        config,
        prompt="教学片段",
        duration_seconds=10,
        resolution="1280x720",
        idempotency_key="stable-key",
    )
    assert created.provider_job_id == "provider-job-1"
    post_count = sum(request.method == "POST" for request in requests)
    resumed = await seedance_provider_service.resume_seedance_video(
        config, provider_job_id="provider-job-1",
    )
    assert resumed.provider_job_id == "provider-job-1"
    assert sum(request.method == "POST" for request in requests) == post_count
