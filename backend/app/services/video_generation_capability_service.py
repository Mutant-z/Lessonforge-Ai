"""原生有声视频模型能力的统一读取与分辨率校验。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AgentChatSession, CourseProject, ModelConfig
from app.schemas.video import NATIVE_VIDEO_RESOLUTIONS, NativeVideoResolution, resolution_label
from app.services.media_provider_service import MediaProviderError
from app.services.native_audio_video_provider import native_audio_video_provider
from app.services.model_config_service import resolve_model_config
from app.services.video_generation_settings_service import normalize_native_video_resolution


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoGenerationCapabilities:
    provider: str
    model_name: str
    api_mode: str
    resolutions: tuple[NativeVideoResolution, ...]
    duration_seconds: tuple[float, float]
    source: str = "model_configuration"
    available: bool = True
    error_code: str | None = None
    unavailable_reason: str | None = None
    missing_dependencies: tuple[str, ...] = ()
    verification_status: str = "unverified"

    def payload(self) -> dict:
        return {
            "model_name": self.model_name,
            "supported_resolutions": [
                {"value": value, "label": resolution_label(value)} for value in self.resolutions
            ],
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "verification_status": self.verification_status,
            "output_spec": {
                "resolution": self.resolutions[0] if self.resolutions else None,
                "native_audio": True,
            },
        }


class VideoResolutionUnsupported(ValueError):
    def __init__(self, requested: object, capabilities: VideoGenerationCapabilities):
        self.requested = str(requested or "")
        self.capabilities = capabilities
        supported = "、".join(
            f"{value}（{resolution_label(value)}）" for value in capabilities.resolutions
        )
        super().__init__(
            f"当前视频模型 {capabilities.model_name} 不支持 {self.requested}；可用分辨率：{supported}"
        )


async def get_video_generation_capabilities(
    db: AsyncSession, course: CourseProject,
) -> VideoGenerationCapabilities:
    session = await db.scalar(select(AgentChatSession).where(
        AgentChatSession.course_id == course.id,
        AgentChatSession.module_type == "video_generation",
    ))
    config = await resolve_model_config(
        db,
        course.owner_id,
        session.video_model_config_id if session else None,
        "video",
    )
    if config is None:
        # 允许在模型尚未选择时先保存课程偏好；真正报价时仍必须绑定并校验 Provider。
        return VideoGenerationCapabilities(
            provider="unconfigured",
            model_name="unconfigured",
            api_mode="",
            resolutions=("1280x720", "854x480"),
            duration_seconds=(4, 15),
            source="default_native_contract",
            available=False,
            error_code="video_model_config_missing",
            unavailable_reason="请先选择视频模型。",
            missing_dependencies=("video_generation",),
            verification_status="unverified",
        )
    try:
        # 能力展示不应被运行开关挡住，否则前端只能回退到错误的默认分辨率。
        provider = native_audio_video_provider(config, require_enabled=False)
        raw = provider.capabilities()
    except MediaProviderError as exc:
        return VideoGenerationCapabilities(
            provider=config.provider,
            model_name=config.model_name,
            api_mode=config.api_mode,
            resolutions=(),
            duration_seconds=(0, 0),
            available=False,
            error_code=exc.code,
            unavailable_reason=str(exc),
        )
    values = raw.get("resolutions") or [raw.get("resolution")]
    resolutions: list[NativeVideoResolution] = []
    for value in values:
        try:
            canonical = normalize_native_video_resolution(value)
        except ValueError:
            continue
        if canonical not in resolutions:
            resolutions.append(canonical)
    if not resolutions:
        raise ValueError("视频模型未声明可用分辨率")
    duration = raw.get("duration_seconds") or [0, 0]

    try:
        native_audio_video_provider(config)
    except MediaProviderError as exc:
        return VideoGenerationCapabilities(
            provider=config.provider,
            model_name=config.model_name,
            api_mode=config.api_mode,
            resolutions=tuple(resolutions),
            duration_seconds=(float(duration[0]), float(duration[1])),
            available=False,
            error_code=exc.code,
            unavailable_reason=str(exc),
        )

    return VideoGenerationCapabilities(
        provider=config.provider,
        model_name=config.model_name,
        api_mode=config.api_mode,
        resolutions=tuple(resolutions),
        duration_seconds=(float(duration[0]), float(duration[1])),
        verification_status=config.video_capability_status or "unverified",
        unavailable_reason=config.video_capability_error or None,
    )


def validate_video_resolution(
    requested: object, capabilities: VideoGenerationCapabilities,
) -> NativeVideoResolution:
    try:
        resolution = normalize_native_video_resolution(requested)
    except ValueError as exc:
        raise VideoResolutionUnsupported(requested, capabilities) from exc
    if resolution not in capabilities.resolutions:
        raise VideoResolutionUnsupported(resolution, capabilities)
    return resolution
