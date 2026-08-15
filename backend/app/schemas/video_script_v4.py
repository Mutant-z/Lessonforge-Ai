"""视频脚本 V4 数据契约（动态章节）。

V3 的分镜目录由固定教学动作（导入/建构/示范/检查/总结）派生；V4 引入由 AI
动态维护的章节大纲：章节数量、标题、顺序与分镜归属不再固定，`pedagogical_role`
只作为单段教学动作分类，不再决定目录标题或固定目录顺序。

兼容约定：
- V3 历史 Artifact 保持只读；首次编辑/同步/重试时通过 ``upgrade_video_script_v4()``
  确定性生成 V4 候选（保留全部分镜 ID、口播、镜头、事实和时间轴），旧 Artifact 不改写。
- 下游（视频生成/报价/逐字稿/导出）在过渡期同时接受 V3/V4：V4 一律经
  ``seedance_video_script_for_generation()`` 投影为扁平 V3 scenes 消费，
  章节变化不强制重新生成媒体。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.artifact import (
    SeedanceCameraBeat,
    SeedanceVideoProductionSettings,
    SeedanceVideoScriptContent,
    VideoScriptCourseInfo,
)

VIDEO_SCRIPT_V4 = "4.0"


class VideoScriptSection(BaseModel):
    """动态章节：由 AI 根据课程内容与教师意图规划，稳定 ID 由 Builder 生成。"""

    id: str = Field(min_length=1, pattern=r"^SEC-[A-Z0-9-]+$")
    sequence: int = Field(gt=0)
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    objective_ids: list[str] = Field(default_factory=list)
    knowledge_point_ids: list[str] = Field(default_factory=list)


class VideoScriptOutline(BaseModel):
    sections: list[VideoScriptSection] = Field(min_length=1)


class SeedanceVideoSceneV4(BaseModel):
    """V4 分镜：V3 全字段 + 所属动态章节（独立模型，避免继承触发校验重建）。"""

    id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    title: str = Field(min_length=1)
    pedagogical_role: Literal["导入", "目标", "情境", "概念讲解", "示范", "练习", "检查点", "总结", "过渡"]
    lesson_stage_id: str = Field(min_length=1)
    objective_ids: list[str] = Field(min_length=1)
    knowledge_point_ids: list[str] = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    continuity_group: str = Field(min_length=1, max_length=120)
    visual_prompt: str = Field(min_length=1, max_length=6000)
    camera_beats: list[SeedanceCameraBeat] = Field(default_factory=list)
    spoken_text: str = Field(min_length=1, max_length=3000)
    required_terms: list[str] = Field(default_factory=list)
    required_numbers: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    voice_direction: str = Field(default="自然、清晰的中文教师讲解", min_length=1, max_length=300)
    sound_design: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    production_notes: list[str] = Field(default_factory=list)
    section_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_v4_scene(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("原生视频片段结束时间必须晚于开始时间")
        duration = self.end_seconds - self.start_seconds
        if duration < 4 or duration > 15:
            raise ValueError("Seedance 原生片段时长必须介于 4–15 秒")
        for beat in self.camera_beats:
            if beat.end_offset_seconds > duration + 0.01:
                raise ValueError("镜头节拍不得超出片段时长")
        return self


class SeedanceVideoScriptContentV4(BaseModel):
    schema_version: Literal["4.0"] = "4.0"
    course_info: VideoScriptCourseInfo
    production_settings: SeedanceVideoProductionSettings
    outline: VideoScriptOutline
    scenes: list[SeedanceVideoSceneV4] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_v4_structure(self):
        """结构门禁：章节归属、时间轴连续、总时长守恒、Seedance 片段窗口。

        - 每个分镜必须且只能属于一个章节，每个章节至少包含一个分镜；
        - 同章分镜必须在时间轴上连续出现，章节顺序与分镜首次出现顺序一致；
        - 分镜时间轴连续，总时长等于制作目标时长，每段满足 4–15 秒。
        """
        if [scene.sequence for scene in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("V4 视频脚本分镜序号必须从 1 连续递增")
        if len({scene.id for scene in self.scenes}) != len(self.scenes):
            raise ValueError("V4 视频脚本分镜 ID 不能重复")
        section_ids = [section.id for section in self.outline.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("V4 章节 ID 不能重复")
        section_set = set(section_ids)
        for scene in self.scenes:
            if scene.section_id not in section_set:
                raise ValueError(f"分镜 {scene.id} 引用了不存在的章节 {scene.section_id}")
            duration = scene.end_seconds - scene.start_seconds
            if duration < 4 or duration > 15:
                raise ValueError(f"Seedance 原生片段 {scene.id} 时长必须介于 4–15 秒")
        # 同章连续 + 章节顺序 == 分镜首次出现顺序
        seen: set[str] = set()
        order: list[str] = []
        last_section: str | None = None
        for scene in self.scenes:
            if scene.section_id != last_section:
                if scene.section_id in seen:
                    raise ValueError(f"同章分镜必须在时间轴上连续出现：{scene.section_id}")
                seen.add(scene.section_id)
                order.append(scene.section_id)
                last_section = scene.section_id
        expected_sequence = {section_id: index + 1 for index, section_id in enumerate(order)}
        for section in self.outline.sections:
            if section.sequence != expected_sequence.get(section.id):
                raise ValueError(
                    f"章节 {section.id} 的序号与其分镜首次出现顺序不一致"
                )
        cursor = 0.0
        for scene in self.scenes:
            if abs(scene.start_seconds - cursor) > 0.11:
                raise ValueError("V4 视频脚本分镜时间轴必须连续")
            cursor = scene.end_seconds
        if abs(cursor - self.production_settings.target_duration_seconds) > 0.11:
            raise ValueError("V4 视频脚本分镜总时长必须与制作目标时长一致")
        return self


def _stage_title(lesson_plan_raw: dict[str, Any] | None, stage_id: str) -> str | None:
    """从教学设计（V1/V2 均可，支持 knowledge 信封）中解析环节标题。"""
    if not lesson_plan_raw:
        return None
    raw = lesson_plan_raw
    if "content" in raw and isinstance(raw.get("content"), dict):
        raw = raw["content"]
    try:
        core = raw.get("pedagogical_core") or raw
        for stage in core.get("stages", []) or []:
            if stage.get("id") == stage_id:
                return stage.get("title")
    except Exception:  # noqa: BLE001  结构非法的教学设计不参与标题解析
        return None
    return None


def upgrade_video_script_v4(
    raw: dict[str, Any],
    lesson_plan_raw: dict[str, Any] | None = None,
) -> SeedanceVideoScriptContentV4:
    """V3 → V4 确定性适配：按连续的 lesson_stage_id 生成初始章节。

    - 保留全部分镜 ID、口播、镜头、事实与时间轴；
    - 章节标题取教学设计真实环节名称，缺失时用环节 ID 兜底；
    - 章节覆盖范围为所属分镜的目标/知识点并集；
    - 不执行内容润色，结构变化本身不强制重新生成媒体。
    """
    if (raw or {}).get("schema_version") == VIDEO_SCRIPT_V4:
        return SeedanceVideoScriptContentV4.model_validate(raw)
    if (raw or {}).get("schema_version") != "3.0":
        raise ValueError("V4 适配器仅接受 V3 或 V4 视频脚本")
    v3 = SeedanceVideoScriptContent.model_validate(raw)
    scenes = [scene.model_dump() for scene in v3.scenes]
    # 按连续 lesson_stage_id 分组（保持时间轴顺序）
    runs: list[list[dict[str, Any]]] = []
    for scene in scenes:
        stage_id = scene["lesson_stage_id"]
        if runs and runs[-1][-1]["lesson_stage_id"] == stage_id:
            runs[-1].append(scene)
        else:
            runs.append([scene])
    sections: list[dict[str, Any]] = []
    for index, group in enumerate(runs, 1):
        stage_id = group[0]["lesson_stage_id"]
        title = _stage_title(lesson_plan_raw, stage_id) or stage_id
        purpose = (
            next(
                (note for note in group[0].get("production_notes", []) if note),
                f"围绕「{title}」组织教学叙事",
            )
        )
        objective_ids = list(dict.fromkeys(
            obj_id for scene in group for obj_id in scene.get("objective_ids", [])
        ))
        knowledge_point_ids = list(dict.fromkeys(
            kp_id for scene in group for kp_id in scene.get("knowledge_point_ids", [])
        ))
        section_id = f"SEC-{index:02d}"
        sections.append({
            "id": section_id, "sequence": index, "title": title,
            "purpose": purpose, "objective_ids": objective_ids,
            "knowledge_point_ids": knowledge_point_ids,
        })
        for scene in group:
            scene["section_id"] = section_id
    return SeedanceVideoScriptContentV4.model_validate({
        "schema_version": VIDEO_SCRIPT_V4,
        "course_info": v3.course_info.model_dump(),
        "production_settings": v3.production_settings.model_dump(),
        "outline": {"sections": sections},
        "scenes": scenes,
    })


def seedance_video_script_for_generation(raw: dict[str, Any]) -> SeedanceVideoScriptContent:
    """V3/V4 统一投影：V4 去掉 outline 与 section_id，返回扁平 V3 脚本供下游消费。"""
    if (raw or {}).get("schema_version") == VIDEO_SCRIPT_V4:
        v4 = SeedanceVideoScriptContentV4.model_validate(raw)
        scenes = [
            scene.model_dump(exclude={"section_id"})
            for scene in v4.scenes
        ]
        return SeedanceVideoScriptContent.model_validate({
            "schema_version": "3.0",
            "course_info": v4.course_info.model_dump(),
            "production_settings": v4.production_settings.model_dump(),
            "scenes": scenes,
        })
    return SeedanceVideoScriptContent.model_validate(raw)


def video_script_v4_to_markdown(content: SeedanceVideoScriptContentV4 | dict[str, Any]) -> str:
    """V4 Markdown：按动态章节分组渲染分镜，不出现预设目录。"""
    if isinstance(content, SeedanceVideoScriptContentV4):
        content = content.model_dump()
    info = content.get("course_info") or {}
    settings = content.get("production_settings") or {}
    outline = content.get("outline") or {}
    sections = {item["id"]: item for item in outline.get("sections", [])}
    lines = [
        "# 微课视频脚本 V4（动态章节）", "",
        f"**课程：** {info.get('course_title')}",
        f"**学科 / 年级：** {info.get('subject')} / {info.get('grade_level') or info.get('audience')}",
        "**制作方式：** Doubao-Seedance-2.5 原生有声分段生成",
        f"**目标时长：** {settings.get('target_duration_seconds')} 秒",
        f"**片段范围：** {settings.get('min_clip_seconds')}–{settings.get('max_clip_seconds')} 秒",
        f"**章节数：** {len(sections)}", "",
    ]
    for scene in content.get("scenes", []):
        section = sections.get(scene.get("section_id")) or {}
        lines += [
            f"## {scene.get('id')} · {scene.get('start_seconds', 0):.1f}s—{scene.get('end_seconds', 0):.1f}s · {scene.get('pedagogical_role')}",
            f"- 所属章节：{section.get('sequence', '')} · {section.get('title', scene.get('section_id'))}",
            f"- 连续性分组：{scene.get('continuity_group')}",
            f"- 目标 / 知识点：{'、'.join(scene.get('objective_ids', []))} / {'、'.join(scene.get('knowledge_point_ids', []))}",
            f"- 画面：{scene.get('visual_prompt')}",
            f"- 原生口播：{scene.get('spoken_text')}",
            f"- 声音指导：{scene.get('voice_direction')}",
            f"- 必须保留：{'、'.join((scene.get('required_terms') or []) + (scene.get('required_numbers') or [])) or '无'}",
            f"- 禁止项：{'；'.join(scene.get('negative_constraints', [])) or '无'}",
            "",
        ]
    return "\n".join(lines)
