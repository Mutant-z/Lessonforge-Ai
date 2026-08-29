from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


VideoSceneStatus = Literal["pending", "generating", "ready", "failed"]
VideoVisualMode = Literal["hybrid_director", "ppt_only", "ai_visual_first"]

# 原生有声视频支持的分辨率与其 Provider 规格标记。
NativeVideoResolution = Literal["1280x720", "854x480"]
NATIVE_VIDEO_RESOLUTIONS: tuple[NativeVideoResolution, ...] = ("1280x720", "854x480")
RESOLUTION_LABELS: dict[str, str] = {"1280x720": "720p", "854x480": "480p"}


def resolution_label(resolution: str) -> str:
    return RESOLUTION_LABELS.get(resolution, resolution)


class VideoShot(BaseModel):
    id: str = Field(min_length=1)
    start_offset_seconds: float = Field(ge=0)
    end_offset_seconds: float = Field(gt=0)
    source_type: Literal["ppt", "ppt_asset", "ai_image", "ai_video"] = "ppt"
    asset_id: str | None = None
    motion: Literal["static", "slow_zoom_in", "slow_zoom_out", "pan_left", "pan_right", "focus"] = "slow_zoom_in"
    focus_box: list[float] | None = Field(default=None, min_length=4, max_length=4)
    prompt: str = ""
    fallback_reason: str = ""

    @model_validator(mode="after")
    def validate_shot_timing(self):
        if self.end_offset_seconds <= self.start_offset_seconds:
            raise ValueError("镜头结束时间必须晚于开始时间")
        return self


class VideoGenerationSettings(BaseModel):
    aspect_ratio: Literal["16:9"] = "16:9"
    resolution: Literal["1920x1080", "1280x720", "640x360"] = "1920x1080"
    subtitle_enabled: bool = True
    voice_style: str = Field(default="natural", min_length=1, max_length=80)
    background_music_enabled: bool = False
    visual_mode: VideoVisualMode = "ai_visual_first"


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
    source_slide_id: str = ""
    pedagogical_role: str = ""
    animation_cues: list[dict] = Field(default_factory=list)
    speaking_rate_cps: float = Field(default=4.0, gt=0)
    visual_source: Literal["ppt", "ppt_asset", "ai_image", "ai_video"] = "ppt"
    shots: list[VideoShot] = Field(default_factory=list)
    generation_warnings: list[str] = Field(default_factory=list)
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
    schema_version: Literal["2.0"] = "2.0"
    mode: Literal["hybrid"] = "hybrid"
    production_settings: VideoGenerationSettings = Field(default_factory=VideoGenerationSettings)
    source_versions: dict[str, int] = Field(default_factory=dict)
    scenes: list[VideoGenerationScene] = Field(min_length=1)
    outputs: VideoGenerationOutputs = Field(default_factory=VideoGenerationOutputs)
    generation_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_v1(cls, value):
        if isinstance(value, dict) and value.get("schema_version") == "1.0":
            upgraded = dict(value)
            upgraded["schema_version"] = "2.0"
            upgraded.setdefault("generation_warnings", ["该视频由 V1 产物兼容升级，重新生成后可获得脚本导演镜头"])
            return upgraded
        return value

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
    visual_mode: VideoVisualMode = "ai_visual_first"


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
    visual_source: Literal["auto", "ppt", "ai_image"] = "auto"

    @model_validator(mode="after")
    def validate_operation(self):
        if not any((self.regenerate_visual, self.regenerate_audio, self.regenerate_subtitle)):
            raise ValueError("至少选择一项需要重新生成的内容")
        return self


NativeVideoSceneStatus = Literal["pending", "generating", "ready", "failed", "qa_failed"]


class SeedanceNativeSettings(BaseModel):
    aspect_ratio: Literal["16:9"] = "16:9"
    resolution: NativeVideoResolution = "1280x720"
    subtitle_enabled: bool = True
    native_audio: Literal[True] = True
    continuity_policy: Literal["grouped"] = "grouped"
    model_config_id: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    quote_id: str = Field(min_length=1)
    approved_max_cost_fen: int = Field(ge=0)
    provider: str | None = None
    api_mode: str | None = None
    interaction_ids: list[str] = Field(default_factory=list)


class SeedanceNativeScene(BaseModel):
    id: str = Field(min_length=1)
    script_scene_id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    continuity_group: str = Field(min_length=1)
    visual_prompt: str = Field(min_length=1)
    spoken_text: str = Field(min_length=1)
    voice_direction: str = Field(min_length=1)
    sound_design: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)
    required_numbers: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    request_hash: str = ""
    provider_job_id: str = ""
    reference_scene_ids: list[str] = Field(default_factory=list)
    status: NativeVideoSceneStatus = "pending"
    video_asset_id: str | None = None
    thumbnail_asset_id: str | None = None
    actual_transcript: str = ""
    subtitle_segments: list[dict] = Field(default_factory=list)
    qa: dict = Field(default_factory=dict)
    usage: dict = Field(default_factory=dict)
    estimated_tokens: int = Field(default=0, ge=0)
    actual_tokens: int = Field(default=0, ge=0)
    estimated_cost_fen: int = Field(default=0, ge=0)
    actual_cost_fen: int = Field(default=0, ge=0)
    error: dict | None = None

    @model_validator(mode="after")
    def validate_native_timing(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("视频片段结束时间必须晚于开始时间")
        if self.status == "ready" and not self.video_asset_id:
            raise ValueError("已完成片段必须引用视频资源")
        return self


class SeedanceVideoGenerationContent(BaseModel):
    schema_version: Literal["3.0"] = "3.0"
    mode: Literal["seedance_native"] = "seedance_native"
    production_settings: SeedanceNativeSettings
    source_versions: dict[str, int]
    scenes: list[SeedanceNativeScene] = Field(min_length=1)
    outputs: VideoGenerationOutputs = Field(default_factory=VideoGenerationOutputs)
    cost_summary: dict = Field(default_factory=dict)
    audio_qa: dict = Field(default_factory=dict)
    generation_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_native_content(self):
        if set(self.source_versions) != {"video_script"}:
            raise ValueError("Seedance V3 只能记录 video_script 来源版本")
        if [scene.sequence for scene in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("视频片段序号必须连续")
        return self


class VideoGenerationQuoteRequest(BaseModel):
    resolution: Literal["1280x720", "854x480"] | None = None
    subtitle_enabled: bool = True
    continuity_policy: Literal["grouped"] = "grouped"
    target_scene_id: str | None = None
    include_dependents: bool = False
    instruction: str = Field(default="", max_length=4000)
    visual_prompt: str | None = Field(default=None, max_length=6000)
    spoken_text: str | None = Field(default=None, max_length=3000)
    voice_direction: str | None = Field(default=None, max_length=300)
    duration_seconds: float | None = Field(default=None, ge=3, le=15)


class VideoGenerationQuoteResponse(BaseModel):
    quote_id: str
    expires_at: datetime
    script_version: int
    model_config_id: str
    model_name: str
    provider: str = ""
    api_mode: str = ""
    resolution: str
    scene_count: int
    reusable_scene_count: int
    duration_seconds: float
    estimated_tokens: int
    estimated_cost_fen: int
    maximum_cost_fen: int
    currency: Literal["CNY"] = "CNY"
    scenes: list[dict]


class SeedanceVideoGenerationRunRequest(BaseModel):
    action: Literal["initial", "retry", "recompose", "sync_dependencies"] = "initial"
    quote_id: str | None = None
    approved_max_cost_fen: int | None = Field(default=None, ge=0)
    subtitle_enabled: bool = True


class SeedanceSceneRegenerateRequest(BaseModel):
    quote_id: str | None = None
    approved_max_cost_fen: int | None = Field(default=None, ge=0)
    instruction: str = Field(min_length=1, max_length=4000)
    visual_prompt: str | None = Field(default=None, max_length=6000)
    spoken_text: str | None = Field(default=None, max_length=3000)
    voice_direction: str | None = Field(default=None, max_length=300)
    duration_seconds: float | None = Field(default=None, ge=3, le=15)
    include_dependents: bool = False


class VideoGenerationMetricsResponse(BaseModel):
    scene_attempt_count: int = 0
    completed_attempt_count: int = 0
    generation_success_rate: float = 0
    retried_scene_count: int = 0
    scene_retry_rate: float = 0
    actual_cost_fen: int = 0
    estimated_cost_fen: int = 0
    estimate_actual_deviation_rate: float = 0
    billable_duration_seconds: float = 0
    average_cost_fen_per_minute: float = 0
    qa_checked_attempt_count: int = 0
    qa_failed_attempt_count: int = 0
    asr_fact_failure_rate: float = 0
    quoted_scene_count: int = 0
    reusable_scene_count: int = 0
    cache_reuse_rate: float = 0


def seedance_video_generation_markdown(content: SeedanceVideoGenerationContent) -> str:
    lines = [
        "# Seedance 原生有声微课视频", "",
        f"- 模型：{content.production_settings.model_name}",
        f"- 输出：{content.production_settings.resolution} · 16:9",
        f"- 原生音频：是",
        f"- 总时长：{content.outputs.duration_seconds:.1f} 秒",
        f"- 实际费用：¥{content.cost_summary.get('actual_cost_fen', 0) / 100:.2f}", "",
    ]
    for scene in content.scenes:
        lines += [
            f"## {scene.id} · {scene.start_seconds:.1f}s—{scene.end_seconds:.1f}s",
            f"- 状态：{scene.status}",
            f"- 连续性分组：{scene.continuity_group}",
            f"- 画面提示词：{scene.visual_prompt}",
            f"- 计划口播：{scene.spoken_text}",
            f"- 实际口播：{scene.actual_transcript or '待识别'}",
            f"- 教学事实 QA：{scene.qa.get('status', 'pending')}",
            f"- 片段费用：¥{scene.actual_cost_fen / 100:.2f}", "",
        ]
    return "\n".join(lines)


def video_generation_markdown(content: VideoGenerationContent) -> str:
    settings = content.production_settings
    lines = [
        "# 微课视频生成",
        "",
        f"- 制作模式：{content.mode}",
        f"- 输出规格：{settings.resolution} · {settings.aspect_ratio}",
        f"- 声音风格：{settings.voice_style}",
        f"- 画面模式：{settings.visual_mode}",
        f"- 字幕：{'开启' if settings.subtitle_enabled else '关闭'}",
        f"- 总时长：{content.outputs.duration_seconds:.1f} 秒",
        "",
    ]
    for scene in content.scenes:
        lines.extend([
            f"## {scene.id} · {scene.start_seconds:.1f}s—{scene.end_seconds:.1f}s",
            f"- 脚本分镜：{scene.script_scene_id}",
            f"- 状态：{scene.status}",
            f"- 画面来源：{scene.visual_source}",
            f"- 画面提示词：{scene.visual_prompt}",
            f"- 旁白：{scene.narration_text}",
            f"- 字幕：{scene.subtitle_text}",
            "",
        ])
    return "\n".join(lines)
