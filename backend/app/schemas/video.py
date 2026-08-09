from typing import Literal

from pydantic import BaseModel, Field, model_validator


VideoSceneStatus = Literal["pending", "generating", "ready", "failed"]


class VideoGenerationSettings(BaseModel):
    aspect_ratio: Literal["16:9"] = "16:9"
    resolution: Literal["1920x1080", "1280x720", "640x360"] = "1920x1080"
    subtitle_enabled: bool = True
    voice_style: str = Field(default="natural", min_length=1, max_length=80)
    background_music_enabled: bool = False


class VideoGenerationScene(BaseModel):
    id: str = Field(min_length=1)
    script_scene_id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    visual_prompt: str = Field(min_length=1)
    visual_style: str = Field(default="课程统一视觉", min_length=1)
    narration_text: str = Field(min_length=1)
    subtitle_text: str = Field(default="")
    production_notes: list[str] = Field(default_factory=list)
    status: VideoSceneStatus = "pending"
    video_asset_id: str | None = None
    audio_asset_id: str | None = None
    thumbnail_asset_id: str | None = None
    provider_job_id: str | None = None
    error: dict | None = None

    @model_validator(mode="after")
    def validate_timing(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("视频分镜结束时间必须晚于开始时间")
        if self.status == "ready" and not self.video_asset_id:
            raise ValueError("已完成的视频分镜必须引用视频资源")
        return self


class VideoGenerationOutputs(BaseModel):
    preview_asset_id: str | None = None
    final_asset_id: str | None = None
    subtitle_asset_id: str | None = None
    thumbnail_asset_id: str | None = None
    duration_seconds: float = Field(default=0, ge=0)


class VideoGenerationContent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["hybrid"] = "hybrid"
    production_settings: VideoGenerationSettings = Field(default_factory=VideoGenerationSettings)
    source_versions: dict[str, int] = Field(default_factory=dict)
    scenes: list[VideoGenerationScene] = Field(min_length=1)
    outputs: VideoGenerationOutputs = Field(default_factory=VideoGenerationOutputs)

    @model_validator(mode="after")
    def validate_timeline(self):
        if [scene.sequence for scene in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("视频生成分镜序号必须从 1 连续递增")
        ids = [scene.id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("视频生成分镜 ID 不能重复")
        source_ids = [scene.script_scene_id for scene in self.scenes]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("一个脚本分镜只能映射到一个视频分镜")
        previous_end = self.scenes[0].start_seconds
        for scene in self.scenes:
            if scene.start_seconds < previous_end - 0.01:
                raise ValueError("视频生成分镜不得重叠或倒序")
            previous_end = scene.end_seconds
        if self.outputs.duration_seconds and abs(previous_end - self.outputs.duration_seconds) > 1:
            raise ValueError("视频输出时长必须与分镜时间轴一致")
        return self


class VideoGenerationRunRequest(BaseModel):
    action: Literal["initial", "retry", "recompose", "sync_dependencies"] = "initial"
    resolution: Literal["1920x1080", "1280x720", "640x360"] = "1920x1080"
    voice_style: str = Field(default="natural", min_length=1, max_length=80)
    subtitle_enabled: bool = True
    background_music_enabled: bool = False


class VideoSceneRegenerateRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    visual_prompt: str | None = Field(default=None, max_length=6000)
    visual_style: str | None = Field(default=None, max_length=200)
    narration_text: str | None = Field(default=None, max_length=12000)
    subtitle_text: str | None = Field(default=None, max_length=12000)
    production_notes: list[str] | None = None
    duration_seconds: float | None = Field(default=None, ge=1, le=600)
    regenerate_visual: bool = True
    regenerate_audio: bool = False
    regenerate_subtitle: bool = False
    preserve_locked_content: bool = True

    @model_validator(mode="after")
    def validate_operation(self):
        if not any((self.regenerate_visual, self.regenerate_audio, self.regenerate_subtitle)):
            raise ValueError("至少选择一项需要重新生成的内容")
        return self


def video_generation_markdown(content: VideoGenerationContent) -> str:
    settings = content.production_settings
    lines = [
        "# 微课视频生成",
        "",
        f"- 制作模式：{content.mode}",
        f"- 输出规格：{settings.resolution} · {settings.aspect_ratio}",
        f"- 声音风格：{settings.voice_style}",
        f"- 字幕：{'开启' if settings.subtitle_enabled else '关闭'}",
        f"- 总时长：{content.outputs.duration_seconds:.1f} 秒",
        "",
    ]
    for scene in content.scenes:
        lines.extend([
            f"## {scene.id} · {scene.start_seconds:.1f}s—{scene.end_seconds:.1f}s",
            f"- 脚本分镜：{scene.script_scene_id}",
            f"- 状态：{scene.status}",
            f"- 画面提示词：{scene.visual_prompt}",
            f"- 旁白：{scene.narration_text}",
            f"- 字幕：{scene.subtitle_text}",
            "",
        ])
    return "\n".join(lines)
