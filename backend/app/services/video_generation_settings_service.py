"""课程级视频生成偏好：唯一读取、校验、持久化与历史修复入口。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import CourseProject, GenerationEvent, GenerationRun
from app.schemas.video import NATIVE_VIDEO_RESOLUTIONS, NativeVideoResolution

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoGenerationSettingsPatch:
    preferred_resolution: NativeVideoResolution


@dataclass(frozen=True)
class VideoGenerationSettingsUpdate:
    previous_resolution: NativeVideoResolution | None
    resolution: NativeVideoResolution
    changed: bool


def normalize_native_video_resolution(value: object) -> NativeVideoResolution:
    resolution = str(value or "").strip().lower()
    if resolution not in NATIVE_VIDEO_RESOLUTIONS:
        raise ValueError(f"不支持的视频分辨率：{value}")
    return cast(NativeVideoResolution, resolution)


def preferred_video_resolution(course: CourseProject) -> NativeVideoResolution | None:
    value = ((course.settings_json or {}).get("video_generation") or {}).get("preferred_resolution")
    try:
        return normalize_native_video_resolution(value) if value else None
    except ValueError:
        return None


def effective_video_resolution(
    course: CourseProject,
    supported: Iterable[object],
    fallback: object = "1280x720",
) -> NativeVideoResolution:
    supported_values = {
        str(item or "").strip().lower()
        for item in supported
        if str(item or "").strip().lower() in NATIVE_VIDEO_RESOLUTIONS
    }
    preferred = preferred_video_resolution(course)
    if preferred and preferred in supported_values:
        return preferred
    try:
        default = normalize_native_video_resolution(fallback)
    except ValueError:
        default = "1280x720"
    if default in supported_values or not supported_values:
        return default
    return next(item for item in NATIVE_VIDEO_RESOLUTIONS if item in supported_values)


async def apply_video_generation_settings(
    db: AsyncSession,
    course: CourseProject,
    patch: VideoGenerationSettingsPatch,
) -> VideoGenerationSettingsUpdate:
    """在调用方事务中不可变地更新 JSON；不 commit、不发事件。"""
    resolution = normalize_native_video_resolution(patch.preferred_resolution)
    previous = preferred_video_resolution(course)
    changed = previous != resolution
    if changed:
        settings = dict(course.settings_json or {})
        video_generation = dict(settings.get("video_generation") or {})
        video_generation["preferred_resolution"] = resolution
        settings["video_generation"] = video_generation
        course.settings_json = settings
        await db.flush()
    return VideoGenerationSettingsUpdate(
        previous_resolution=previous,
        resolution=resolution,
        changed=changed,
    )


def _event_payload(event: GenerationEvent) -> dict:
    data = dict(event.data_json or {})
    return dict(data.get("payload") or {})


def _comparable_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def reconcile_video_generation_preferences(db: AsyncSession) -> dict[str, int]:
    """回放每门课程最新的已完成设置事件，修复旧版本产生的假成功。"""
    events = list(await db.scalars(
        select(GenerationEvent)
        .join(GenerationRun, GenerationRun.id == GenerationEvent.run_id)
        .where(
            GenerationEvent.event_type == "video_generation.setting.updated",
            GenerationRun.status == "completed",
        )
        .order_by(GenerationEvent.id.desc())
    ))
    latest_by_course: dict[str, GenerationEvent] = {}
    ignored = 0
    for event in events:
        data = dict(event.data_json or {})
        course_id = str(data.get("course_id") or "")
        try:
            normalize_native_video_resolution(_event_payload(event).get("resolution"))
        except ValueError:
            ignored += 1
            continue
        if not course_id or course_id in latest_by_course:
            ignored += 1
            continue
        latest_by_course[course_id] = event

    repaired = unchanged = errors = 0
    for course_id, event in latest_by_course.items():
        try:
            async with db.begin_nested():
                course = await db.get(CourseProject, course_id)
                if course is None:
                    ignored += 1
                    continue
                resolution = normalize_native_video_resolution(_event_payload(event).get("resolution"))
                current = preferred_video_resolution(course)
                # 后续人工或新版本写入比旧事件更新时，不用历史事件覆盖。
                if current == resolution or _comparable_datetime(course.updated_at) > _comparable_datetime(event.created_at):
                    unchanged += 1
                    continue
                await apply_video_generation_settings(
                    db, course, VideoGenerationSettingsPatch(preferred_resolution=resolution)
                )
                repaired += 1
        except Exception:
            errors += 1
            logger.exception("Failed to reconcile video generation preference", extra={"course_id": course_id})
    await db.commit()
    report = {
        "scanned": len(latest_by_course),
        "repaired": repaired,
        "unchanged": unchanged,
        "ignored": ignored,
        "errors": errors,
    }
    logger.info("Video generation preference reconciliation finished", extra=report)
    return report
