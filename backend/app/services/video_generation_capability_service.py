"""原生有声视频模型能力的统一读取与分辨率校验。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AgentChatSession, CourseProject, ModelConfig
from app.schemas.video import NATIVE_VIDEO_RESOLUTIONS, NativeVideoResolution, resolution_label
from app.services.native_audio_video_provider import native_audio_video_provider
from app.services.video_generation_settings_service import normalize_native_video_resolution


@dataclass(frozen=True)
class VideoGenerationCapabilities:
    provider: str
    model_name: str
    api_mode: str
    resolutions: tuple[NativeVideoResolution, ...]
    duration_seconds: tuple[float, float]
    source: str = "model_configuration"

    def payload(self) -> dict:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "api_mode": self.api_mode,
            "supported_resolutions": [
                {"value": value, "label": resolution_label(value)} for value in self.resolutions
            ],
            "duration_seconds": list(self.duration_seconds),
            "source": self.source,
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
    config = await db.get(ModelConfig, session.video_model_config_id) if session and session.video_model_config_id else None
    if config is None:
        # 允许在模型尚未选择时先保存课程偏好；真正报价时仍必须绑定并校验 Provider。
        return VideoGenerationCapabilities(
            provider="unconfigured",
            model_name="unconfigured",
            api_mode="",
            resolutions=("1280x720", "854x480"),
            duration_seconds=(4, 15),
            source="default_native_contract",
        )
    provider = native_audio_video_provider(config)
    try:
        raw = provider.capabilities()
    except Exception as exc:  # noqa: BLE001  Provider 未配置或探测失败
        raise ValueError(
            f"{config.model_name} 视频功能尚未启用；请先完成本地网关能力探测或配置 API 账号"
        ) from exc
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
    return VideoGenerationCapabilities(
        provider=config.provider,
        model_name=config.model_name,
        api_mode=config.api_mode,
        resolutions=tuple(resolutions),
        duration_seconds=(float(duration[0]), float(duration[1])),
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
