"""VerbatimBuilder：教师逐字稿 V2 内存候选稿。

编辑工具只修改内存候选稿，绝不直接写正式 Artifact。候选稿经 finalizer 校验后
发布为新版本；未通过门禁时保留原版。

约定：
- V2 content dict 的内存可变副本（course_info + speaking_rate_cps +
  source_versions + 扁平 sections）。
- 时间轴、字数、口播时长一律确定性计算：``word_count = len(required_text)``、
  ``estimated_duration = word_count / speaking_rate + pause_seconds``。
- 章节与视频脚本场景一对一（scene_id 唯一）；结构调整（新增/移动/删除章节）
  会重算时间轴以保持连续，并在结构非法时抛出可修复错误。
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.schemas.verbatim_v2 import (
    VERBATIM_V2,
    DEFAULT_SPEAKING_RATE_CPS,
    MIN_SECTION_SECONDS,
    VerbatimContentV2,
    verbatim_section_seconds,
    verbatim_v2_to_markdown,
)


class VerbatimBuilder:
    def __init__(self, content: dict[str, Any] | None = None):
        self._content: dict[str, Any] = copy.deepcopy(content) if content else {
            "schema_version": VERBATIM_V2,
            "course_info": {
                "course_title": "", "subject": "", "grade_level": "",
                "audience": "", "duration_seconds": 0,
            },
            "speaking_rate_cps": DEFAULT_SPEAKING_RATE_CPS,
            "source_versions": {},
            "sections": [],
        }
        self._revision: int = 0

    # ------------------------------------------------------------------
    # 草稿修订（供工具返回修订号 / 前端 patch 冲突检测）
    # ------------------------------------------------------------------

    @property
    def revision(self) -> int:
        return self._revision

    def bump_revision(self) -> int:
        self._revision += 1
        return self._revision

    # ------------------------------------------------------------------
    # 只读
    # ------------------------------------------------------------------

    def to_content(self) -> dict[str, Any]:
        return copy.deepcopy(self._content)

    @property
    def sections(self) -> list[dict[str, Any]]:
        return self._content["sections"]

    @property
    def speaking_rate_cps(self) -> float:
        return float(self._content.get("speaking_rate_cps") or DEFAULT_SPEAKING_RATE_CPS)

    def canonical_section_id(self, raw_id: str | Any) -> str | None:
        """智能解析并归一化章节标识符（支持 seg_01, scene_01, VB-01, 序号等）。"""
        if not raw_id:
            return None
        raw = str(raw_id).strip()
        # 1. 直接匹配 id (如 VB-01)
        for item in self.sections:
            if item.get("id") == raw or str(item.get("id", "")).lower() == raw.lower():
                return item.get("id")
        # 2. 匹配关联场景 scene_id (如 scene_01 / SCENE-01)
        for item in self.sections:
            sid = str(item.get("scene_id", ""))
            if sid == raw or sid.lower() == raw.lower() or sid.replace("-", "_").lower() == raw.replace("-", "_").lower():
                return item.get("id")
        # 3. 匹配 seg_XX / segment_XX / 纯数字序号
        match = re.search(r"(\d+)", raw)
        if match:
            num = int(match.group(1))
            target_vb = f"VB-{num:02d}"
            for item in self.sections:
                if item.get("id") == target_vb:
                    return item.get("id")
            if 1 <= num <= len(self.sections):
                return self.sections[num - 1].get("id")
        return None

    def find_section(self, section_id: str) -> dict[str, Any] | None:
        canonical = self.canonical_section_id(section_id)
        if not canonical:
            return None
        return next((item for item in self.sections if item.get("id") == canonical), None)

    def _require_section(self, section_id: str) -> dict[str, Any]:
        section = self.find_section(section_id)
        if section is None:
            raise ValueError(f"章节不存在：{section_id}")
        return section

    def find_section_by_scene(self, scene_id: str) -> dict[str, Any] | None:
        canonical = self.canonical_section_id(scene_id)
        if canonical:
            return next((item for item in self.sections if item.get("id") == canonical), None)
        return next((item for item in self.sections if item.get("scene_id") == scene_id), None)

    def all_section_ids(self) -> list[str]:
        return [item.get("id", "") for item in self.sections]

    def scene_id_set(self) -> set[str]:
        return {item.get("scene_id", "") for item in self.sections}

    def count_sections(self) -> int:
        return len(self.sections)

    def total_duration(self) -> float:
        return round(max((item.get("end_seconds", 0) for item in self.sections), default=0.0), 2)

    def _recompute_section(self, section: dict[str, Any]) -> None:
        """按 required_text + 语速 + 停顿确定性重算字数与口播时长。"""
        text = str(section.get("required_text") or "")
        rate = self.speaking_rate_cps
        pause = float(section.get("pause_seconds") or 0)
        section["word_count"] = len(text.strip())
        section["estimated_duration_seconds"] = verbatim_section_seconds(text, rate, pause)

    def _recompute_course_duration(self) -> None:
        self._content["course_info"]["duration_seconds"] = self.total_duration()

    # ------------------------------------------------------------------
    # 文档元数据（课程名称是课程项目的投影，不是正文）
    # ------------------------------------------------------------------

    def update_course_title(self, title: str) -> str:
        title = str(title).strip()
        if not title:
            raise ValueError("课程名称不能为空")
        if len(title) > 200:
            raise ValueError("课程名称不能超过 200 个字符")
        self._content.setdefault("course_info", {})["course_title"] = title
        return title

    # ------------------------------------------------------------------
    # 内容编辑（verbatim_director / timing_engine 主路径）
    # ------------------------------------------------------------------

    def update_required_text(self, section_id: str, text: str) -> dict[str, Any]:
        section = self._require_section(section_id)
        text = str(text).strip()
        if not text:
            raise ValueError("必讲口播 required_text 不能为空")
        section["required_text"] = text
        self._recompute_section(section)
        return copy.deepcopy(section)

    def update_optional_text(self, section_id: str, text: str) -> dict[str, Any]:
        section = self._require_section(section_id)
        section["optional_text"] = str(text).strip()
        return copy.deepcopy(section)

    def update_tone(self, section_id: str, tone: str) -> dict[str, Any]:
        section = self._require_section(section_id)
        tone = str(tone).strip()
        if not tone:
            raise ValueError("表达语气 delivery_tone 不能为空")
        section["delivery_tone"] = tone
        return copy.deepcopy(section)

    def update_emphasis(self, section_id: str, terms: list[str]) -> dict[str, Any]:
        section = self._require_section(section_id)
        section["key_emphasis"] = [str(item).strip() for item in terms if str(item).strip()]
        return copy.deepcopy(section)

    def update_interaction(self, section_id: str, interaction: str) -> dict[str, Any]:
        section = self._require_section(section_id)
        section["interaction"] = str(interaction).strip()
        return copy.deepcopy(section)

    def update_pause(self, section_id: str, pause_seconds: float) -> dict[str, Any]:
        section = self._require_section(section_id)
        pause = round(float(pause_seconds), 2)
        duration = float(section.get("end_seconds", 0)) - float(section.get("start_seconds", 0))
        if pause < 0:
            raise ValueError("停顿秒数不能为负")
        if pause > duration:
            raise ValueError(f"停顿秒数不能超过该段时长 {duration:.1f}s")
        section["pause_seconds"] = pause
        self._recompute_section(section)
        return copy.deepcopy(section)

    def batch_style(self, *, tone: str | None = None, emphasis: list[str] | None = None,
                    pause_seconds: float | None = None) -> list[str]:
        """批量风格润色：对全部章节统一语气/重音/停顿（不改动必讲事实与数字）。"""
        changed: list[str] = []
        for section in self.sections:
            if tone:
                section["delivery_tone"] = str(tone).strip()
            if emphasis is not None:
                merged = list(dict.fromkeys([*(section.get("key_emphasis") or []), *[str(t).strip() for t in emphasis if str(t).strip()]]))
                section["key_emphasis"] = merged
            if pause_seconds is not None:
                duration = float(section.get("end_seconds", 0)) - float(section.get("start_seconds", 0))
                section["pause_seconds"] = round(min(max(0.0, float(pause_seconds)), max(0.0, duration)), 2)
                self._recompute_section(section)
            changed.append(section.get("id", ""))
        return changed

    def rebalance_timing(self, speaking_rate_cps: float | None = None) -> dict[str, Any]:
        """按语速与场景时长重算停顿，使「口播 + 停顿」贴合每段时长（≤ 该段时长）。

        若某段口播本身超出时长（无法通过停顿压缩），保留该段口播并让停顿为 0，
        交由 QA 门禁报告超长问题。返回调整后的章节 id 列表。
        """
        if speaking_rate_cps is not None:
            rate = round(float(speaking_rate_cps), 2)
            if not 1.0 <= rate <= 12.0:
                raise ValueError("语速必须在 1.0–12.0 字/秒之间")
            self._content["speaking_rate_cps"] = rate
        rate = self.speaking_rate_cps
        changed: list[str] = []
        for section in self.sections:
            duration = float(section.get("end_seconds", 0)) - float(section.get("start_seconds", 0))
            speech = float(section.get("word_count", 0)) / max(1.0, rate)
            new_pause = round(max(0.0, min(3.0, duration - speech)), 2)
            if abs(new_pause - float(section.get("pause_seconds") or 0)) > 0.01:
                section["pause_seconds"] = new_pause
                self._recompute_section(section)
                changed.append(section.get("id", ""))
        self._recompute_course_duration()
        return {"changed_section_ids": changed, "speaking_rate_cps": rate}

    def set_speaking_rate(self, rate: float) -> None:
        rate = round(float(rate), 2)
        if not 1.0 <= rate <= 12.0:
            raise ValueError("语速必须在 1.0–12.0 字/秒之间")
        self._content["speaking_rate_cps"] = rate
        for section in self.sections:
            self._recompute_section(section)

    # ------------------------------------------------------------------
    # 结构调整（新增/移动/删除章节；会重算时间轴）
    # ------------------------------------------------------------------

    def _require_section(self, section_id: str) -> dict[str, Any]:
        section = self.find_section(section_id)
        if section is None:
            raise ValueError(f"章节不存在：{section_id}")
        return section

    def add_section(self, section_id: str, scene_id: str, required_text: str, *,
                    delivery_tone: str = "", pedagogical_action: str = "scenario_connect",
                    start_seconds: float | None = None, end_seconds: float | None = None) -> dict[str, Any]:
        """追加一个章节到末尾（scene_id 必须唯一）。时长未指定时按口播推算。"""
        if self.find_section(section_id):
            raise ValueError(f"章节 ID 已存在：{section_id}")
        if self.find_section_by_scene(scene_id):
            raise ValueError(f"场景 {scene_id} 已被其他章节占用")
        text = str(required_text).strip()
        if not text:
            raise ValueError("必讲口播 required_text 不能为空")
        speech = len(text) / max(1.0, self.speaking_rate_cps)
        start = self.total_duration() if start_seconds is None else float(start_seconds)
        end = (start + max(MIN_SECTION_SECONDS, round(speech, 2))) if end_seconds is None else float(end_seconds)
        if end <= start:
            raise ValueError("章节结束时间必须晚于开始时间")
        node = {
            "id": section_id, "scene_id": scene_id, "slide_ids": [],
            "start_seconds": round(start, 2), "end_seconds": round(end, 2),
            "pedagogical_action": pedagogical_action,
            "delivery_tone": delivery_tone or "自然、清晰、符合学习者水平",
            "required_text": text, "optional_text": "", "key_emphasis": [],
            "interaction": "", "pause_seconds": 0.0,
            "word_count": len(text),
            "estimated_duration_seconds": verbatim_section_seconds(text, self.speaking_rate_cps, 0),
        }
        self.sections.append(node)
        self._recompute_course_duration()
        return copy.deepcopy(node)

    def delete_section(self, section_id: str) -> dict[str, Any]:
        """删除章节并把后续章节前移保持时间轴连续；更新课程总时长。"""
        node = self._require_section(section_id)
        removed_duration = float(node.get("end_seconds", 0)) - float(node.get("start_seconds", 0))
        removed_start = float(node.get("start_seconds", 0))
        self.sections[:] = [item for item in self.sections if item.get("id") != section_id]
        for item in self.sections:
            start = float(item.get("start_seconds", 0))
            if start > removed_start:
                item["start_seconds"] = round(start - removed_duration, 2)
                item["end_seconds"] = round(float(item.get("end_seconds", 0)) - removed_duration, 2)
        self._recompute_course_duration()
        return copy.deepcopy(node)

    def move_section(self, section_id: str, target_scene_id: str) -> dict[str, Any]:
        """把章节移动到指定场景对应的时间槽（与另一个章节交换 scene 归属与时间）。

        用于「把这段口播移到另一段视频画面」类指令；保留两边 required_text。
        """
        node = self._require_section(section_id)
        target = next((item for item in self.sections if item.get("scene_id") == target_scene_id), None)
        if target is None:
            raise ValueError(f"目标场景不存在：{target_scene_id}")
        if target.get("id") == section_id:
            raise ValueError("目标场景与当前章节一致，无需移动")
        # 交换时间槽与 scene 归属，保留各自口播内容。
        node_start, node_end = node.get("start_seconds"), node.get("end_seconds")
        node["start_seconds"], node["end_seconds"] = target.get("start_seconds"), target.get("end_seconds")
        target["start_seconds"], target["end_seconds"] = node_start, node_end
        return copy.deepcopy(node)

    def validate_content(self) -> dict[str, Any]:
        """返回 {ok, error} 供工具使用。"""
        try:
            VerbatimContentV2.model_validate(self._content)
            return {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    def to_markdown(self) -> str:
        return verbatim_v2_to_markdown(self._content)


def _blueprint_basic_script(bp_content: dict[str, Any]) -> dict[str, Any]:
    """共享项目记忆：无视频脚本时从蓝图 timeline 生成基础场景结构。

    逐字稿不再强制等待视频脚本；缺失时基于蓝图生成基础候选稿，脚本存在后
    可按需读取并更新。
    """
    timeline = (bp_content or {}).get("timeline", []) or []
    identity = (bp_content or {}).get("course_identity", {}) or {}
    total = float(identity.get("duration_minutes", 0) or 0) * 60
    scenes = []
    for index, segment in enumerate(timeline):
        start = float(segment.get("start_minute", 0) or 0) * 60
        end = float(segment.get("end_minute", 0) or 0) * 60
        if end <= start:
            end = start + max(10.0, total / max(1, len(timeline)))
        scenes.append({
            "id": f"SV-{index + 1:02d}",
            "sequence": index + 1,
            "title": segment.get("name", ""),
            "lesson_stage_id": segment.get("segment_id", ""),
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "spoken_text": f"同学们好，接下来我们进入「{segment.get('name', '')}」环节。{segment.get('purpose', '')}",
            "pedagogical_role": "概念讲解",
            "voice_direction": "自然、清晰、可信赖的中文教师讲解",
            "required_terms": [],
            "required_numbers": [],
            "required_facts": [segment.get("purpose", "")],
            "production_notes": [segment.get("teacher_action", "")],
        })
    return {
        "schema_version": "3.0",
        "course_info": {
            "course_title": identity.get("title", ""),
            "subject": identity.get("subject", ""),
            "grade_level": identity.get("grade_level", ""),
            "audience": identity.get("audience", ""),
            "duration_seconds": round(total) or max(1, round(max((s["end_seconds"] for s in scenes), default=60))),
        },
        "scenes": scenes,
    }


def build_initial_builder(
    bp_content: dict[str, Any],
    video_script_raw: dict[str, Any] | None,
) -> VerbatimBuilder:
    """蓝图 + 视频脚本驱动初始化：投影为 V2 候选稿（确定性）。

    共享项目记忆：视频脚本缺失或为空时，用蓝图 timeline 生成基础场景结构兜底，
    不阻塞逐字稿生成。
    """
    from app.schemas.verbatim_v2 import make_seedance_verbatim_v2

    script = video_script_raw or {}
    if not script.get("scenes"):
        script = _blueprint_basic_script(bp_content)
    v2 = make_seedance_verbatim_v2(bp_content, script)
    return VerbatimBuilder(v2.model_dump())


def upgrade_builder(
    v1_content: dict[str, Any],
    video_script_raw: dict[str, Any] | None,
) -> VerbatimBuilder:
    """V1 → V2 确定性适配（首次修改/同步时使用），不改写旧 Artifact。"""
    from app.schemas.verbatim_v2 import upgrade_verbatim_v2

    v2 = upgrade_verbatim_v2(v1_content, video_script_raw or {})
    return VerbatimBuilder(v2.model_dump())
