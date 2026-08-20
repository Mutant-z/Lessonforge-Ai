"""视频脚本 Agent 的课程级视频生成设置工具。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ToolResult
from app.schemas.video import NativeVideoResolution
from app.core.database import SessionLocal
from app.services.video_generation_capability_service import (
    VideoResolutionUnsupported,
    get_video_generation_capabilities,
    validate_video_resolution,
)
from app.services.video_generation_settings_service import (
    VideoGenerationSettingsPatch,
    preferred_video_resolution,
)


class SetVideoGenerationResolutionInput(BaseModel):
    preferred_resolution: NativeVideoResolution | None = None
    requested_resolution: str = ""
    reason: str = ""


class SetVideoGenerationResolutionOutput(BaseModel):
    status: Literal["settings_staged", "settings_unchanged"]
    preferred_resolution: NativeVideoResolution
    previous_resolution: NativeVideoResolution | None = None
    changed: bool
    persistence: Literal["staged"] = "staged"


async def _set_video_generation_resolution(
    tc: ToolContext, inp: SetVideoGenerationResolutionInput,
) -> ToolResult:
    runtime = tc.runtime
    course = tc.course
    if runtime is None or course is None:
        return ToolResult(
            ok=False, error="缺少视频生成设置运行上下文", error_code="settings_context_missing", retryable=False,
        )
    requested = inp.preferred_resolution or inp.requested_resolution
    try:
        async with SessionLocal() as db:
            capabilities = await get_video_generation_capabilities(db, course)
        resolution = validate_video_resolution(requested, capabilities)
    except VideoResolutionUnsupported as exc:
        return ToolResult(
            ok=False,
            error=str(exc),
            error_code="video_resolution_unsupported",
            retryable=False,
            output={
                "requested": str(requested),
                "supported": list(exc.capabilities.resolutions),
                "provider": exc.capabilities.provider,
                "model_name": exc.capabilities.model_name,
                "capabilities": exc.capabilities.payload(),
            },
        )
    except ValueError as exc:
        return ToolResult(
            ok=False, error=str(exc), error_code="video_provider_capability_stale", retryable=True,
        )
    previous = preferred_video_resolution(course)
    changed = previous != resolution
    runtime.pending_video_settings = VideoGenerationSettingsPatch(preferred_resolution=resolution)
    output = {
        "status": "settings_staged" if changed else "settings_unchanged",
        "preferred_resolution": resolution,
        "previous_resolution": previous,
        "changed": changed,
        "persistence": "staged",
        "capabilities": capabilities.payload(),
    }
    return ToolResult(ok=True, output=output)


def _register_project_settings_tools() -> None:
    register_tool(Tool(
        "vs_set_video_generation_resolution",
        "暂存课程级视频生成分辨率设置。只能使用当前原生视频契约支持的 1280x720 或 854x480；不要修改视频脚本候选稿。",
        SetVideoGenerationResolutionInput,
        _set_video_generation_resolution,
        output_schema=SetVideoGenerationResolutionOutput,
        idempotent=True,
    ))
