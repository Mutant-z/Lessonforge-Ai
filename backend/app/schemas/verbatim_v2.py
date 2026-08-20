"""教师逐字稿 V2 数据契约（数值时间轴 + 教学动作 + 确定性时长）。

与 V1 的差异：
- ``start_seconds/end_seconds`` 为权威数值时间轴（对齐视频脚本 scene_id），
  展示用时间字符串由程序派生，不再存储字符串 ``time_range``。
- 文档级 ``speaking_rate_cps`` 为默认语速；``word_count`` 与
  ``estimated_duration_seconds`` 由后端确定性计算（required_text 字数 / 语速 +
  停顿秒数），不接受模型伪造。
- 每个章节（section）稳定 id + scene_id + 可选 slide_ids；必讲/补充/语气/重音/
  互动提示/停顿秒数分离，便于按维度返修。
- ``source_versions`` 记录上游视频脚本版本，用于跨版本兼容与 no_change 判定。

兼容约定：
- 历史 V1 Artifact 原样保留；首次由新 Agent 修改时通过 ``upgrade_verbatim_v2()``
  在运行期生成 V2 候选，旧 Artifact 不改写。
- ``verbatim_sections_for()`` 是 V1/V2 统一章节投影入口（前端预览/导出/质量校验复用）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.artifact import PedagogicalActionType

VERBATIM_V2 = "2.0"
VERBATIM_V1 = "1.0"

DEFAULT_SPEAKING_RATE_CPS = 4.0   # 默认语速：4.0 字/秒 = 240 字/分
MIN_SECTION_SECONDS = 3.0
TIMELINE_TOLERANCE = 0.11


def verbatim_word_count(text: str) -> int:
    """逐字稿字数：中文按字符计数（不含首尾空白）。"""
    return len((text or "").strip())


def verbatim_speech_seconds(text: str, speaking_rate_cps: float) -> float:
    """按语速估算口播秒数。"""
    return round(verbatim_word_count(text) / max(1.0, speaking_rate_cps), 2)


def verbatim_section_seconds(text: str, speaking_rate_cps: float, pause_seconds: float) -> float:
    """整段预估口播秒数 = 口播字数/语速 + 停顿秒数（下限 MIN_SECTION_SECONDS）。"""
    return round(max(MIN_SECTION_SECONDS, verbatim_speech_seconds(text, speaking_rate_cps) + pause_seconds), 2)


def format_clock(seconds: float) -> str:
    """把秒数格式化为 00:00 展示字符串（仅供前端展示，不参与持久化）。"""
    value = max(0, int(round(seconds)))
    return f"{value // 60:02d}:{value % 60:02d}"


# ---------------------------------------------------------------------------
# 文档级事实
# ---------------------------------------------------------------------------


class VerbatimCourseInfo(BaseModel):
    course_title: str = Field(min_length=1)
    subject: str = ""
    grade_level: str = ""
    audience: str = ""
    duration_seconds: float = Field(gt=0)


class VerbatimSectionV2(BaseModel):
    """逐字稿章节：与视频脚本场景对齐，使用数值时间轴。"""

    id: str = Field(min_length=1, pattern=r"^VB-[A-Z0-9-]+$")
    scene_id: str = Field(min_length=1, description="关联的视频脚本场景 ID")
    slide_ids: list[str] = Field(default_factory=list, description="可选关联 PPT 页面 ID（不参与生成约束）")
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    pedagogical_action: PedagogicalActionType = "scenario_connect"
    delivery_tone: str = Field(default="自然、清晰、符合学习者水平", min_length=0, max_length=300)
    required_text: str = Field(min_length=1, max_length=3000, description="必讲口播台词")
    optional_text: str = Field(default="", max_length=1500, description="时间允许时的补充/举例旁白")
    key_emphasis: list[str] = Field(default_factory=list, description="需要重音强调的术语/数字")
    interaction: str = Field(default="", max_length=500, description="互动或思考提示")
    pause_seconds: float = Field(default=0.0, ge=0, le=30, description="口播后的停顿秒数")
    word_count: int = Field(default=0, ge=0, description="由后端确定性计算：required_text 字数")
    estimated_duration_seconds: float = Field(default=0, ge=0, description="由后端确定性计算：字数/语速+停顿")

    @model_validator(mode="after")
    def validate_section(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError(f"逐字稿章节 {self.id} 结束时间必须晚于开始时间")
        duration = self.end_seconds - self.start_seconds
        if self.pause_seconds > duration:
            raise ValueError(f"逐字稿章节 {self.id} 停顿秒数不能超过该段时长")
        # 确定性派生：展示时间字符串由程序计算，不接受模型伪造。
        return self

    @property
    def time_range(self) -> str:
        return f"{format_clock(self.start_seconds)}—{format_clock(self.end_seconds)}"

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 2)


class VerbatimContentV2(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    course_info: VerbatimCourseInfo
    speaking_rate_cps: float = Field(default=DEFAULT_SPEAKING_RATE_CPS, ge=1.0, le=12.0)
    source_versions: dict[str, int] = Field(default_factory=dict, description="上游产物版本（如 video_script）")
    sections: list[VerbatimSectionV2] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_document(self):
        section_ids = [section.id for section in self.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("逐字稿章节 ID 不能重复")
        scene_ids = [section.scene_id for section in self.sections]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("逐字稿章节必须一对一映射到不同视频脚本场景")
        # 时间轴必须按 start 升序连续，总时长与 course_info 一致。
        if abs(self.sections[0].start_seconds) > TIMELINE_TOLERANCE:
            raise ValueError("逐字稿时间轴必须从 0 秒开始")
        cursor = 0.0
        for section in self.sections:
            if section.start_seconds < cursor - TIMELINE_TOLERANCE:
                raise ValueError("逐字稿章节时间不得重叠或倒序")
            if section.start_seconds - cursor > 1.0:
                raise ValueError("逐字稿章节之间不得出现超过 1 秒的空档")
            cursor = section.end_seconds
        if abs(cursor - self.course_info.duration_seconds) > TIMELINE_TOLERANCE:
            raise ValueError("逐字稿总时长必须与课程视频时长一致")
        # 确定性重算：word_count / estimated_duration 一律按 required_text + 语速 + 停顿计算。
        for section in self.sections:
            computed_count = verbatim_word_count(section.required_text)
            computed_duration = verbatim_section_seconds(section.required_text, self.speaking_rate_cps, section.pause_seconds)
            section.word_count = computed_count
            section.estimated_duration_seconds = computed_duration
        return self


# ---------------------------------------------------------------------------
# V1 / V2 统一投影
# ---------------------------------------------------------------------------


def verbatim_sections_for(content: dict[str, Any] | None) -> list[dict[str, Any]]:
    """V1/V2 逐字稿统一章节投影：返回带 scene_id/start_seconds/end_seconds 的 dict 列表。

    - V2：直接返回 sections（含数值时间轴与派生 time_range）。
    - V1：从 time_range 字符串解析数值时间轴（容错失败则用 0）。
    """
    if not content:
        return []
    if content.get("schema_version") == VERBATIM_V2:
        sections = []
        for section in content.get("sections", []):
            item = dict(section)
            start = _parse_clock(item.get("start_seconds"))
            end = _parse_clock(item.get("end_seconds"))
            item["start_seconds"] = start
            item["end_seconds"] = max(start, end)
            item["time_range"] = item.get("time_range") or f"{format_clock(start)}—{format_clock(end)}"
            sections.append(item)
        return sections
    # V1：sections 使用字符串 time_range（如 00:00—00:15）。
    sections = []
    for index, section in enumerate(content.get("sections", [])):
        item = dict(section)
        start, end = _parse_v1_time_range(item.get("time_range", ""))
        item["start_seconds"] = start
        item["end_seconds"] = max(start, end)
        item["scene_id"] = item.get("scene_id") or f"SCENE-{index + 1:02d}"
        sections.append(item)
    return sections


def _parse_clock(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_v1_time_range(time_range: str) -> tuple[float, float]:
    """把 V1 的 00:00—00:15 解析为 (start, end) 秒；失败返回 (0, 0)。"""
    parts = [
        part.strip()
        for part in str(time_range or "").replace("~", "—").replace("-", "—").split("—")
    ]
    if len(parts) != 2:
        return 0.0, 0.0
    try:
        def _to_seconds(text: str) -> float:
            minutes, seconds = text.split(":")
            return int(minutes) * 60 + float(seconds)
        return _to_seconds(parts[0]), _to_seconds(parts[1])
    except (ValueError, IndexError):
        return 0.0, 0.0


# ---------------------------------------------------------------------------
# V1 → V2 确定性适配器
# ---------------------------------------------------------------------------


def _pedagogical_action_from_role(role: str) -> str:
    return {
        "导入": "hook", "目标": "objective_guide", "情境": "scenario_connect",
        "概念讲解": "metaphor_explain", "示范": "step_demonstration",
        "检查点": "check_in", "总结": "summary_recap",
    }.get(role, "scenario_connect")


def _coerce_speaking_rate(content: dict[str, Any]) -> float:
    """兼容 V1 的文字语速（如 standard/slow/fast）与 V2 数值语速。"""
    raw = content.get("speaking_rate_cps")
    if raw is None:
        raw = content.get("speaking_rate")
    if isinstance(raw, str):
        presets = {"slow": 3.0, "standard": DEFAULT_SPEAKING_RATE_CPS, "normal": DEFAULT_SPEAKING_RATE_CPS, "fast": 5.0}
        value = presets.get(raw.strip().lower(), raw.strip())
    else:
        value = raw
    try:
        rate = float(value or DEFAULT_SPEAKING_RATE_CPS)
    except (TypeError, ValueError):
        rate = DEFAULT_SPEAKING_RATE_CPS
    return max(1.0, min(12.0, rate))


def _canonical_legacy_section_id(raw_id: Any, index: int) -> str:
    """将旧版 seg_01/segment-01 等展示 ID 迁移为 V2 稳定章节 ID。"""
    raw = str(raw_id or "").strip()
    if raw.upper().startswith("VB-") and raw[3:]:
        suffix = raw[3:].upper().replace("_", "-")
        if suffix.replace("-", "").isalnum():
            return f"VB-{suffix}"
    import re
    match = re.search(r"(\d+)", raw)
    if match:
        return f"VB-{int(match.group(1)):02d}"
    return f"VB-{index + 1:02d}"


def upgrade_verbatim_v2(
    v1_content: dict[str, Any],
    video_script_raw: dict[str, Any] | None = None,
    course_info_override: dict[str, Any] | None = None,
) -> VerbatimContentV2:
    """V1/历史混合结构 → V2 适配；保留旧 Artifact，不修改历史版本。

    数值时间轴优先取视频脚本场景的真实 start/end；缺失时解析 V1 的 time_range。
    旧版 seg_01 等展示 ID、文字语速和缺失 course_info 均在此处归一化。
    """
    v1_content = dict(v1_content or {})
    if v1_content.get("schema_version") == VERBATIM_V2:
        # 合法 V2 原样保留；历史数据偶尔带了错误的 schema_version，失败时继续走兼容迁移。
        try:
            return VerbatimContentV2.model_validate(v1_content)
        except Exception:  # noqa: BLE001
            pass
    scenes: dict[str, dict[str, Any]] = {}
    if video_script_raw:
        for scene in video_script_raw.get("scenes", []) or []:
            scenes[str(scene.get("id", ""))] = scene
    course_info = course_info_override or v1_content.get("course_info") or {}
    try:
        duration_seconds = float(course_info.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        duration_seconds = 0.0
    speaking_rate = _coerce_speaking_rate(v1_content)
    sections: list[VerbatimSectionV2] = []
    for index, section in enumerate((v1_content.get("sections") or [])):
        section = dict(section or {})
        scene = scenes.get(str(section.get("scene_id") or ""), {})
        if scene:
            start = float(scene.get("start_seconds", 0) or 0)
            end = float(scene.get("end_seconds", 0) or 0)
        else:
            start, end = _parse_v1_time_range(section.get("time_range", ""))
        if end <= start:
            end = start + MIN_SECTION_SECONDS
        required_text = str(section.get("required_text") or "")
        try:
            pause = float(section.get("pause_seconds") or 0)
        except (TypeError, ValueError):
            pause = 0.0
        pause = max(0.0, min(pause, end - start))
        sections.append(VerbatimSectionV2(
            id=_canonical_legacy_section_id(section.get("id"), index),
            scene_id=str(section.get("scene_id") or f"SCENE-{index + 1:02d}"),
            slide_ids=list(section.get("slide_ids") or []),
            start_seconds=start,
            end_seconds=end,
            pedagogical_action=section.get("pedagogical_action") or _pedagogical_action_from_role(scene.get("pedagogical_role", "")),
            delivery_tone=str(section.get("delivery_tone") or ""),
            required_text=required_text,
            optional_text=str(section.get("optional_text") or ""),
            key_emphasis=list(section.get("key_emphasis") or section.get("required_terms") or []),
            interaction=str(section.get("interaction") or ""),
            pause_seconds=pause,
            word_count=verbatim_word_count(required_text),
            estimated_duration_seconds=verbatim_section_seconds(required_text, speaking_rate, pause),
        ))
    # 历史版本有时只写了文档总时长，章节时间轴却存在空档或未延伸到末尾。
    # 迁移时修复时间轴连续性，避免兼容层把旧数据直接送入 V2 门禁而失败。
    if sections:
        cursor = 0.0
        for section in sections:
            duration = max(MIN_SECTION_SECONDS, section.end_seconds - section.start_seconds)
            section.start_seconds = round(max(0.0, cursor), 2)
            section.end_seconds = round(section.start_seconds + duration, 2)
            cursor = section.end_seconds
        if duration_seconds <= 0:
            duration_seconds = cursor
        elif abs(cursor - duration_seconds) > TIMELINE_TOLERANCE:
            # 保留已有段落时长；将最后一段延伸/收束到文档总时长。
            if duration_seconds > cursor:
                sections[-1].end_seconds = round(duration_seconds, 2)
            else:
                duration_seconds = cursor
    elif duration_seconds <= 0:
        duration_seconds = 0
    return VerbatimContentV2.model_validate({
        "schema_version": VERBATIM_V2,
        "course_info": {
            "course_title": course_info.get("course_title") or "未命名课程",
            "subject": course_info.get("subject", ""),
            "grade_level": course_info.get("grade_level", ""),
            "audience": course_info.get("audience", ""),
            "duration_seconds": duration_seconds,
        },
        "speaking_rate_cps": speaking_rate,
        "source_versions": dict(v1_content.get("source_versions") or {}),
        "sections": [section.model_dump() for section in sections],
    })


def make_seedance_verbatim_v2(
    bp: Any,
    script: Any,
) -> VerbatimContentV2:
    """蓝图 + 视频脚本驱动的确定性首稿（Mock / 兜底路径）。

    每个视频脚本场景映射为一个逐字稿章节；scene 的数值时间轴即章节时间轴。
    """
    if hasattr(script, "model_dump"):
        script_data = script.model_dump()
    else:
        script_data = dict(script or {})
    scenes = script_data.get("scenes", []) or []
    info = script_data.get("course_info") or {}
    speaking_rate = float(script_data.get("speaking_rate_cps") or DEFAULT_SPEAKING_RATE_CPS)
    total_duration = float(info.get("duration_seconds") or 0)
    if total_duration <= 0 and scenes:
        total_duration = max(float(scene.get("end_seconds", 0)) for scene in scenes)
    sections: list[VerbatimSectionV2] = []
    for index, scene in enumerate(scenes):
        required_text = str(scene.get("spoken_text") or "")
        required_terms = list(scene.get("required_terms") or [])
        required_numbers = list(scene.get("required_numbers") or [])
        interaction = next(
            (note for note in scene.get("production_notes") or [] if "提问" in str(note) or "互动" in str(note)),
            "邀请学生用一句话概括当前要点。",
        )
        start = float(scene.get("start_seconds", 0))
        end = float(scene.get("end_seconds", 0))
        if end <= start:
            end = start + MIN_SECTION_SECONDS
        pause = round(max(0.0, float(scene.get("end_seconds", end)) - end - verbatim_speech_seconds(required_text, speaking_rate)), 2)
        pause = max(0.0, min(3.0, pause))
        sections.append(VerbatimSectionV2(
            id=f"VB-{index + 1:02d}",
            scene_id=str(scene.get("id") or f"SCENE-{index + 1:02d}"),
            slide_ids=[],
            start_seconds=start,
            end_seconds=end,
            pedagogical_action=_pedagogical_action_from_role(str(scene.get("pedagogical_role", ""))),
            delivery_tone=str(scene.get("voice_direction") or "自然、清晰、符合学习者水平"),
            required_text=required_text,
            optional_text=f"如果时间允许，可以结合{info.get('audience') or '学生'}熟悉的情境补充说明这一段要点。",
            key_emphasis=[*required_terms, *required_numbers],
            interaction=interaction,
            pause_seconds=pause,
            word_count=verbatim_word_count(required_text),
            estimated_duration_seconds=verbatim_section_seconds(required_text, speaking_rate, pause),
        ))
    return VerbatimContentV2.model_validate({
        "schema_version": VERBATIM_V2,
        "course_info": {
            "course_title": info.get("course_title") or (bp.course_identity.title if bp and hasattr(bp, "course_identity") else "未命名课程"),
            "subject": info.get("subject", ""),
            "grade_level": info.get("grade_level", ""),
            "audience": info.get("audience", ""),
            "duration_seconds": total_duration,
        },
        "speaking_rate_cps": speaking_rate,
        "source_versions": {},
        "sections": [section.model_dump() for section in sections],
    })


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def verbatim_v2_to_markdown(content: VerbatimContentV2 | dict[str, Any]) -> str:
    """从 V2 数值时间轴生成 Markdown（前端预览与导出共用）。"""
    if isinstance(content, VerbatimContentV2):
        content = content.model_dump()
    info = content.get("course_info") or {}
    rate = float(content.get("speaking_rate_cps") or DEFAULT_SPEAKING_RATE_CPS)
    lines = [
        "# 教师逐字稿 V2", "",
        f"**课程：** {info.get('course_title')} · **学科/年级：** {info.get('subject')} / "
        f"{info.get('grade_level') or info.get('audience')}",
        f"**总时长：** {format_clock(float(info.get('duration_seconds', 0)))} · **默认语速：** {rate} 字/秒",
        "",
    ]
    for section in content.get("sections", []):
        required_text = str(section.get("required_text") or "")
        estimated = float(section.get("estimated_duration_seconds") or 0)
        duration = max(0.0, float(section.get("end_seconds", 0)) - float(section.get("start_seconds", 0)))
        lines += [
            f"## {section.get('id')} · {format_clock(float(section.get('start_seconds', 0)))}—{format_clock(float(section.get('end_seconds', 0)))}",
            f"- 关联场景：{section.get('scene_id')} · 教学动作：{section.get('pedagogical_action')}",
            f"- 语气：{section.get('delivery_tone') or '—'} · 重音：{'、'.join(section.get('key_emphasis', [])) or '—'}",
            f"- 口播时长：{estimated:.1f}s / 段落时长：{duration:.1f}s · 停顿：{float(section.get('pause_seconds', 0)):.1f}s",
            f"- 必讲：{required_text}",
        ]
        if section.get("optional_text"):
            lines.append(f"- 补充（时间允许时）：{section.get('optional_text')}")
        if section.get("interaction"):
            lines.append(f"- 互动提示：{section.get('interaction')}")
        lines.append("")
    return "\n".join(lines)
