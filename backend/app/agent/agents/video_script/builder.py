"""VideoScriptBuilder：视频脚本 V4 内存候选稿。

编辑工具只修改内存中的候选稿，不直接写正式 Artifact。候选稿最终经
finalizer 校验后发布为新版本；未通过门禁时保留原版。

结构：V4 content dict 的内存可变副本（course_info + production_settings +
outline.sections + 扁平 scenes）。核心不变量（与 V4 schema 门禁一致）：
- 每个分镜必须且只能属于一个章节，每个章节至少包含一个分镜；
- 同章分镜必须在时间轴上连续出现，章节顺序与分镜首次出现顺序一致；
- 分镜时间轴连续，总时长等于制作目标时长，每段满足 4–15 秒；
- 新 ID 由 Builder 生成（章节 SEC-xx、分镜 VS-xx），移动/重排只更新 sequence，
  禁止 LLM 自行编造或批量改号。

锁定路径检查在工具层完成（builder 只做纯数据操作）。
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.schemas.video_script_v4 import (
    VIDEO_SCRIPT_V4,
    SeedanceVideoScriptContentV4,
    upgrade_video_script_v4,
)

MIN_SCENE_SECONDS = 4.0
MAX_SCENE_SECONDS = 15.0
CHARS_PER_SECOND = 4.0  # 口播语速基准（字/秒），用于时间重平衡的默认时长估计


class VideoScriptBuilder:
    def __init__(self, content: dict[str, Any] | None = None):
        self._content: dict[str, Any] = copy.deepcopy(content) if content else {
            "schema_version": VIDEO_SCRIPT_V4,
            "course_info": {
                "course_title": "", "subject": "", "grade_level": "",
                "audience": "", "duration_seconds": 0,
            },
            "production_settings": {
                "mode": "seedance_native", "aspect_ratio": "16:9",
                "target_duration_seconds": 0, "target_clip_seconds": 12,
                "min_clip_seconds": 8, "max_clip_seconds": 15,
                "global_visual_style": "统一、清晰、适龄的现代教学影像",
                "global_voice_direction": "自然、清晰、可信赖的中文教师声音",
            },
            "outline": {"sections": []},
            "scenes": [],
        }
        self._revision: int = 0
        existing_ids = [
            str(item.get("id") or "")
            for item in [*self._content.get("outline", {}).get("sections", []), *self._content.get("scenes", [])]
        ]
        self._id_counter = max(
            (int(match.group(1)) for value in existing_ids if (match := re.search(r"-(\d+)$", value))),
            default=0,
        )

    # ------------------------------------------------------------------
    # 草稿修订（供工具返回修订号 / 前端 patch 冲突检测）
    # ------------------------------------------------------------------

    @property
    def revision(self) -> int:
        return self._revision

    def bump_revision(self) -> int:
        self._revision += 1
        return self._revision

    def _next_id(self, prefix: str) -> str:
        self._id_counter += 1
        return f"{prefix}{self._id_counter:02d}"

    # ------------------------------------------------------------------
    # 只读
    # ------------------------------------------------------------------

    def to_content(self) -> dict[str, Any]:
        return copy.deepcopy(self._content)

    def restore(self, content: dict[str, Any], revision: int | None = None) -> None:
        """原子工具失败时恢复候选稿，不留下半应用状态。"""
        self._content = copy.deepcopy(content)
        if revision is not None:
            self._revision = revision

    def replace_content(self, content: dict[str, Any], *, validate: bool = False) -> None:
        if validate:
            SeedanceVideoScriptContentV4.model_validate(content)
        self._content = copy.deepcopy(content)

    def update_production_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "aspect_ratio", "target_duration_seconds", "target_clip_seconds",
            "min_clip_seconds", "max_clip_seconds", "global_visual_style",
            "global_voice_direction",
        }
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(f"不支持的制作参数：{', '.join(sorted(unknown))}")
        self._content["production_settings"].update(copy.deepcopy(patch))
        if "target_duration_seconds" in patch and self.scenes:
            self.rebalance_timeline()
        return copy.deepcopy(self._content["production_settings"])

    def configure_renderer_limit(self, max_scene_seconds: float) -> None:
        """设置当前渲染器片段上限；不在准备阶段静默改写时间轴。"""
        limit = min(MAX_SCENE_SECONDS, max(MIN_SCENE_SECONDS, float(max_scene_seconds)))
        self._content["production_settings"]["max_clip_seconds"] = limit
        self._content["production_settings"]["target_clip_seconds"] = min(
            float(self._content["production_settings"].get("target_clip_seconds") or limit), limit,
        )

    def to_v3_flat(self) -> dict[str, Any]:
        """V4 → 扁平 V3 投影（用于与正式源版本比较 no_change / 下游 diff）。"""
        from app.schemas.video_script_v4 import seedance_video_script_for_generation

        return seedance_video_script_for_generation(self._content).model_dump()

    @property
    def sections(self) -> list[dict[str, Any]]:
        return self._content["outline"]["sections"]

    @property
    def scenes(self) -> list[dict[str, Any]]:
        return self._content["scenes"]

    @property
    def target_duration_seconds(self) -> float:
        return float(self._content["production_settings"].get("target_duration_seconds") or 0)

    def find_section(self, section_id: str) -> dict[str, Any] | None:
        return next((item for item in self.sections if item.get("id") == section_id), None)

    def find_scene(self, scene_id: str) -> dict[str, Any] | None:
        return next((item for item in self.scenes if item.get("id") == scene_id), None)

    def section_scenes(self, section_id: str) -> list[dict[str, Any]]:
        return [item for item in self.scenes if item.get("section_id") == section_id]

    def all_section_ids(self) -> list[str]:
        return [item.get("id", "") for item in self.sections]

    def all_scene_ids(self) -> list[str]:
        return [item.get("id", "") for item in self.scenes]

    def count_sections(self) -> int:
        return len(self.sections)

    def count_scenes(self) -> int:
        return len(self.scenes)

    def validate_content(self) -> dict[str, Any]:
        """返回 {ok, error} 供工具使用。"""
        try:
            SeedanceVideoScriptContentV4.model_validate(self._content)
            return {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    # ------------------------------------------------------------------
    # 章节编辑
    # ------------------------------------------------------------------

    def add_section(self, title: str, *, purpose: str = "", objective_ids: list[str] | None = None,
                    knowledge_point_ids: list[str] | None = None) -> dict[str, Any]:
        section_id = self._next_id("SEC-")
        node = {
            "id": section_id, "sequence": len(self.sections) + 1, "title": title,
            "purpose": purpose or title, "objective_ids": list(objective_ids or []),
            "knowledge_point_ids": list(knowledge_point_ids or []),
        }
        self.sections.append(node)
        return copy.deepcopy(node)

    def rename_section(self, section_id: str, title: str) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        node["title"] = title
        return copy.deepcopy(node)

    def update_section_metadata(self, section_id: str, *, purpose: str | None = None,
                                objective_ids: list[str] | None = None,
                                knowledge_point_ids: list[str] | None = None) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        if purpose is not None:
            node["purpose"] = purpose
        if objective_ids is not None:
            node["objective_ids"] = list(objective_ids)
        if knowledge_point_ids is not None:
            node["knowledge_point_ids"] = list(knowledge_point_ids)
        return copy.deepcopy(node)

    def move_section(self, section_id: str, *, to_sequence: int) -> dict[str, Any]:
        """移动章节：只更新 sequence（重排），分镜在时间轴上的归属不变。"""
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        sections = sorted(self.sections, key=lambda item: int(item.get("sequence", 0)))
        index = next(i for i, item in enumerate(sections) if item.get("id") == section_id)
        sections.pop(index)
        target = min(max(1, to_sequence), len(sections) + 1)
        sections.insert(target - 1, node)
        for new_index, item in enumerate(sections, 1):
            item["sequence"] = new_index
        return copy.deepcopy(node)

    def merge_sections(self, target_id: str, absorbed_id: str) -> dict[str, Any]:
        """把 absorbed 章节合并进 target 章节（分镜全部归属 target，章节删除）。"""
        target = self.find_section(target_id)
        absorbed = self.find_section(absorbed_id)
        if target is None or absorbed is None:
            raise ValueError("合并章节不存在")
        if target_id == absorbed_id:
            raise ValueError("不能把章节合并到自身")
        for scene in self.scenes:
            if scene.get("section_id") == absorbed_id:
                scene["section_id"] = target_id
        target["objective_ids"] = list(dict.fromkeys([
            *target.get("objective_ids", []), *absorbed.get("objective_ids", []),
        ]))
        target["knowledge_point_ids"] = list(dict.fromkeys([
            *target.get("knowledge_point_ids", []), *absorbed.get("knowledge_point_ids", []),
        ]))
        self.sections[:] = [item for item in self.sections if item.get("id") != absorbed_id]
        self._renumber_sections()
        self._ensure_contiguous_sections()
        return copy.deepcopy(target)

    def delete_section(self, section_id: str, *, move_scenes_to: str | None = None) -> dict[str, Any]:
        """删除章节：分镜必须迁移到其他章节（或由工具按用户指令显式删除分镜）。"""
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        scenes = self.section_scenes(section_id)
        if scenes and not move_scenes_to:
            raise ValueError("删除非空章节必须指定 move_scenes_to，或先删除该章节全部分镜")
        if move_scenes_to:
            target = self.find_section(move_scenes_to)
            if target is None:
                raise ValueError(f"目标章节不存在：{move_scenes_to}")
            for scene in scenes:
                scene["section_id"] = move_scenes_to
        self.sections[:] = [item for item in self.sections if item.get("id") != section_id]
        self._renumber_sections()
        self._ensure_contiguous_sections()
        return copy.deepcopy(node)

    def _renumber_sections(self) -> None:
        ordered = self._section_first_appearance_order()
        for index, section_id in enumerate(ordered, 1):
            node = self.find_section(section_id)
            if node is not None:
                node["sequence"] = index

    def _section_first_appearance_order(self) -> list[str]:
        order: list[str] = []
        seen: set[str] = set()
        for scene in self.scenes:
            section_id = scene.get("section_id", "")
            if section_id and section_id not in seen:
                seen.add(section_id)
                order.append(section_id)
        order.extend(item.get("id", "") for item in self.sections if item.get("id") not in seen)
        return order

    def _ensure_contiguous_sections(self) -> None:
        """重排分镜数组，使同章分镜连续（以各章节首次出现顺序为准），并重排时间偏移。"""
        order: list[str] = []
        seen: set[str] = set()
        for scene in self.scenes:
            section_id = scene.get("section_id", "")
            if section_id and section_id not in seen:
                seen.add(section_id)
                order.append(section_id)
        for section in self.sections:
            if section.get("id") not in seen:
                order.append(section.get("id", ""))
                seen.add(section.get("id", ""))
        grouped: dict[str, list[dict[str, Any]]] = {sid: [] for sid in order}
        for scene in self.scenes:
            sid = scene.get("section_id", "")
            grouped.setdefault(sid, []).append(scene)
        self._content["scenes"] = [scene for sid in order for scene in grouped.get(sid, [])]
        # 结构重排会改变分镜在时间轴上的先后，各分镜时长保持不变，只重排偏移保证连续。
        self._rewrite_timeline_offsets()

    def _clip_cues_to_duration(self, scene: dict[str, Any]) -> None:
        """时长缩小后裁剪镜头节拍等相对时间提示，避免超出片段时长。"""
        duration = float(scene.get("end_seconds", 0)) - float(scene.get("start_seconds", 0))
        beats = [beat for beat in scene.get("camera_beats", []) if float(beat.get("end_offset_seconds", 0)) <= duration + 0.01]
        scene["camera_beats"] = beats

    def _rewrite_timeline_offsets(self) -> None:
        """保持各分镜时长不变，仅按新顺序重排时间轴偏移（结构移动/归属调整后调用）。"""
        target = self.target_duration_seconds
        cursor = 0.0
        count = len(self.scenes)
        for index, scene in enumerate(self.scenes):
            duration = float(scene.get("end_seconds", 0)) - float(scene.get("start_seconds", 0))
            if duration <= 0:
                duration = MIN_SCENE_SECONDS
            if index == count - 1 and count > 1:
                duration = max(MIN_SCENE_SECONDS, target - cursor)
            scene["start_seconds"] = round(cursor, 3)
            scene["end_seconds"] = round(cursor + duration, 3)
            cursor += duration
            self._clip_cues_to_duration(scene)
        self._content["production_settings"]["target_duration_seconds"] = round(target, 3)
        self._content["course_info"]["duration_seconds"] = round(target, 3)

    # ------------------------------------------------------------------
    # 分镜编辑
    # ------------------------------------------------------------------

    _SCENE_EDITABLE_FIELDS = {
        "title", "pedagogical_role", "lesson_stage_id", "section_id",
        "objective_ids", "knowledge_point_ids", "continuity_group",
        "visual_prompt", "camera_beats", "spoken_text", "required_terms",
        "required_numbers", "required_facts", "voice_direction", "sound_design",
        "negative_constraints", "production_notes",
    }
    _SCENE_PROTECTED_FIELDS = {"id", "sequence"}

    def _validate_scene_patch(self, patch: dict[str, Any]) -> None:
        # 受保护字段一律拒绝，其余 V4 schema 不存在的字段（V3 遗留如 learning_purpose、
        # 或 LLM 编造的字段）静默忽略，避免一次无关字段让整批分镜操作失败。
        for protected in self._SCENE_PROTECTED_FIELDS:
            if protected in patch:
                raise ValueError(f"不允许修改分镜 {protected}")
        unknown = set(patch) - self._SCENE_EDITABLE_FIELDS - {"duration_seconds", "start_seconds", "end_seconds"}
        for key in unknown:
            patch.pop(key)
        if patch.get("section_id") and self.find_section(patch["section_id"]) is None:
            raise ValueError(f"目标章节不存在：{patch['section_id']}")

    def add_scene(self, section_id: str, scene: dict[str, Any]) -> dict[str, Any]:
        """在章节末尾新增分镜；时间轴由 recalc_timeline 重算。"""
        if self.find_section(section_id) is None:
            raise ValueError(f"章节不存在：{section_id}")
        scene_id = self._next_id("VS-")
        base = {
            "id": scene_id, "sequence": self.count_scenes() + 1, "title": "",
            "pedagogical_role": "概念讲解", "lesson_stage_id": "", "section_id": section_id,
            "objective_ids": [], "knowledge_point_ids": [], "start_seconds": 0.0,
            "end_seconds": 0.0, "continuity_group": f"stage-{section_id}",
            "visual_prompt": "", "camera_beats": [], "spoken_text": "",
            "required_terms": [], "required_numbers": [], "required_facts": [],
            "voice_direction": "自然、清晰、可信赖的中文教师讲解", "sound_design": [],
            "negative_constraints": ["禁止 PPT、幻灯片、信息图和软件界面", "禁止水印、乱码和大段可读文字", "禁止改变教学事实"],
            "production_notes": [],
        }
        base.update(copy.deepcopy(scene))
        self._validate_scene_patch({key: value for key, value in base.items() if key != "id" and key not in {"sequence"}})
        base["id"] = scene_id
        base.pop("start_seconds", None)
        base.pop("end_seconds", None)
        self.scenes.append(base)
        self._renumber_scenes()
        self.recalc_timeline()
        return copy.deepcopy(base)

    def update_scene(self, scene_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        node = self.find_scene(scene_id)
        if node is None:
            raise ValueError(f"分镜不存在：{scene_id}")
        self._validate_scene_patch(patch)
        duration_patch = None
        if "duration_seconds" in patch:
            duration_patch = float(patch.pop("duration_seconds"))
            if not MIN_SCENE_SECONDS <= duration_patch <= MAX_SCENE_SECONDS:
                raise ValueError("分镜时长必须介于 4–15 秒")
        for key, value in patch.items():
            node[key] = copy.deepcopy(value)
        if "spoken_text" in patch:
            # 与 rewrite_spoken_text 保持一致：事实基准只保留仍出现在新口播中的条目，
            # 避免精简口播后残留整句旧事实导致 QA 误判。
            node["required_facts"] = [
                text for text in node.get("required_facts", []) if text in node.get("spoken_text", "")
            ]
        if patch.get("section_id") and patch["section_id"] != node.get("section_id"):
            self._ensure_contiguous_sections()
        if duration_patch is not None:
            self.recalc_timeline(fixed_durations={scene_id: duration_patch})
        return copy.deepcopy(node)

    def move_scene(self, scene_id: str, section_id: str, *, index: int | None = None) -> dict[str, Any]:
        """移动分镜到目标章节；同章连续约束由数组重排保证。"""
        node = self.find_scene(scene_id)
        if node is None:
            raise ValueError(f"分镜不存在：{scene_id}")
        if self.find_section(section_id) is None:
            raise ValueError(f"目标章节不存在：{section_id}")
        self.scenes.remove(node)
        node["section_id"] = section_id
        if index is None:
            # 放到目标章节分镜块末尾（保持同章连续）
            insert_at = len(self.scenes)
            for pos, scene in enumerate(self.scenes):
                if scene.get("section_id") == section_id and pos + 1 < len(self.scenes) and self.scenes[pos + 1].get("section_id") != section_id:
                    insert_at = pos + 1
                    break
            else:
                insert_at = len(self.scenes)
            self.scenes.insert(insert_at, node)
        else:
            block = self.section_scenes(section_id)
            if block:
                block_end = self.scenes.index(block[-1]) + 1
            else:
                block_end = len(self.scenes)
            target = min(max(0, index), len(block))
            insert_at = block_end - len(block) + target
            self.scenes.insert(insert_at, node)
        self._renumber_scenes()
        self._renumber_sections()
        self._ensure_contiguous_sections()
        return copy.deepcopy(node)

    def split_scene(self, scene_id: str, *, split_at_seconds: float,
                    new_title: str = "", new_spoken_text: str = "") -> dict[str, Any]:
        """在 split_at_seconds 处拆分分镜；两段都必须满足完整语句与 4–15 秒。"""
        node = self.find_scene(scene_id)
        if node is None:
            raise ValueError(f"分镜不存在：{scene_id}")
        duration = float(node.get("end_seconds", 0)) - float(node.get("start_seconds", 0))
        if not 2 * MIN_SCENE_SECONDS <= duration <= 2 * MAX_SCENE_SECONDS:
            raise ValueError(f"该分镜时长 {duration:.1f} 秒无法拆分为两个合法片段（各 4–15 秒）")
        if not MIN_SCENE_SECONDS <= split_at_seconds <= duration - MIN_SCENE_SECONDS:
            raise ValueError(f"拆分点 {split_at_seconds:.1f} 秒必须使两段都位于 4–15 秒之间")
        spoken = node.get("spoken_text") or ""
        cut_index = 0
        for index, char in enumerate(spoken):
            if char in "。！？" and index + 1 <= int((split_at_seconds / duration) * len(spoken)) + 1:
                cut_index = index + 1
        if cut_index == 0 or cut_index >= len(spoken):
            raise ValueError("拆分点未落在完整句边界，请调整拆分点")
        spoken_a, spoken_b = spoken[:cut_index].strip(), spoken[cut_index:].strip()
        if not spoken_a or not spoken_b:
            raise ValueError("拆分后的两个片段都必须有完整口播")
        new_node = copy.deepcopy(node)
        new_node["id"] = self._next_id("VS-")
        new_node["sequence"] = node.get("sequence", 0) + 1
        node["spoken_text"] = spoken_a
        new_node["spoken_text"] = new_spoken_text.strip() or spoken_b
        new_node["title"] = new_title.strip() or f"{node.get('title', '')} · 续"
        new_node["required_facts"] = [text for text in node.get("required_facts", []) if text in new_node["spoken_text"]]
        node["required_facts"] = [text for text in node.get("required_facts", []) if text in node["spoken_text"]]
        self.scenes.insert(self.scenes.index(node) + 1, new_node)
        self._renumber_scenes()
        self.recalc_timeline()
        return copy.deepcopy(new_node)

    def merge_scenes(self, scene_ids: list[str], *, title: str = "", spoken_text: str = "") -> dict[str, Any]:
        """合并多个同章连续分镜为一个（口播拼接，时长重新分配）。"""
        if len(scene_ids) < 2:
            raise ValueError("至少需要两个分镜才能合并")
        nodes = [self.find_scene(scene_id) for scene_id in scene_ids]
        if any(node is None for node in nodes):
            raise ValueError("合并分镜中存在不存在的 ID")
        merged = nodes[0]
        section_ids = {node.get("section_id") for node in nodes}
        if len(section_ids) != 1:
            raise ValueError("只能合并同一章节内的连续分镜")
        index = self.scenes.index(merged)
        segment = self.scenes[index:index + len(nodes)]
        if [item.get("id") for item in segment] != scene_ids:
            raise ValueError("合并分镜必须在时间轴上连续")
        total_duration = sum(float(node.get("end_seconds", 0)) - float(node.get("start_seconds", 0)) for node in nodes)
        if not MIN_SCENE_SECONDS <= total_duration <= MAX_SCENE_SECONDS:
            raise ValueError(f"合并后时长 {total_duration:.1f} 秒超出 4–15 秒窗口")
        spoken_parts = [str(node.get("spoken_text", "")).strip() for node in nodes]
        merged["spoken_text"] = spoken_text.strip() or "".join(part for part in spoken_parts if part)
        if title:
            merged["title"] = title
        merged["required_terms"] = list(dict.fromkeys(
            term for node in nodes for term in node.get("required_terms", [])
        ))
        merged["required_numbers"] = list(dict.fromkeys(
            value for node in nodes for value in node.get("required_numbers", [])
        ))
        merged["required_facts"] = list(dict.fromkeys(
            fact for node in nodes for fact in node.get("required_facts", [])
        ))
        merged["objective_ids"] = list(dict.fromkeys(
            obj for node in nodes for obj in node.get("objective_ids", [])
        ))
        merged["knowledge_point_ids"] = list(dict.fromkeys(
            kp for node in nodes for kp in node.get("knowledge_point_ids", [])
        ))
        for extra in nodes[1:]:
            self.scenes.remove(extra)
        self._renumber_scenes()
        self.recalc_timeline()
        return copy.deepcopy(merged)

    def delete_scene(self, scene_id: str) -> dict[str, Any]:
        node = self.find_scene(scene_id)
        if node is None:
            raise ValueError(f"分镜不存在：{scene_id}")
        self.scenes.remove(node)
        self._renumber_scenes()
        self.recalc_timeline()
        return copy.deepcopy(node)

    def rewrite_spoken_text(self, scene_id: str, spoken_text: str) -> dict[str, Any]:
        node = self.find_scene(scene_id)
        if node is None:
            raise ValueError(f"分镜不存在：{scene_id}")
        spoken_text = spoken_text.strip()
        if not spoken_text:
            raise ValueError("口播不能为空")
        node["spoken_text"] = spoken_text
        node["required_facts"] = [text for text in node.get("required_facts", []) if text in spoken_text]
        return copy.deepcopy(node)

    def update_visual_direction(self, scene_id: str, visual_prompt: str | None = None,
                                camera_beats: list[dict[str, Any]] | None = None,
                                voice_direction: str | None = None,
                                sound_design: list[str] | None = None) -> dict[str, Any]:
        node = self.find_scene(scene_id)
        if node is None:
            raise ValueError(f"分镜不存在：{scene_id}")
        if visual_prompt is not None:
            if not visual_prompt.strip():
                raise ValueError("画面提示词不能为空")
            node["visual_prompt"] = visual_prompt.strip()
        if camera_beats is not None:
            node["camera_beats"] = copy.deepcopy(camera_beats)
        if voice_direction is not None:
            if not voice_direction.strip():
                raise ValueError("声音指导不能为空")
            node["voice_direction"] = voice_direction.strip()
        if sound_design is not None:
            node["sound_design"] = [str(item).strip() for item in sound_design if str(item).strip()]
        return copy.deepcopy(node)

    def update_continuity(self, scene_id: str, continuity_group: str) -> dict[str, Any]:
        node = self.find_scene(scene_id)
        if node is None:
            raise ValueError(f"分镜不存在：{scene_id}")
        if not continuity_group.strip():
            raise ValueError("连续性分组不能为空")
        node["continuity_group"] = continuity_group.strip()
        return copy.deepcopy(node)

    # ------------------------------------------------------------------
    # 时间轴
    # ------------------------------------------------------------------

    def _renumber_scenes(self) -> None:
        for index, scene in enumerate(self.scenes, 1):
            scene["sequence"] = index

    def recalc_timeline(self, fixed_durations: dict[str, float] | None = None) -> None:
        """按口播长度重算分镜时间轴：连续、总时长守恒、每段 4–15 秒。

        - fixed_durations：教师显式指定的分镜时长（保持不变）；
        - 其余分镜按口播字数估计时长，做有界比例分配（4–15 秒窗口内把目标总时长
          分配到各镜），再重排偏移；末镜吸收微小舍入残差；
        - 结构性保护：当渲染器单镜上限使全部镜头无法达到目标总时长时
          （例如 50 镜 × 10 秒上限 < 600 秒目标），把目标时长收敛到实际可达的
          合计值，保证“总时长守恒 + 每段 4–max 秒”两个不变量始终成立，
          避免末镜吸收巨大残差导致结构非法。
        """
        target = self.target_duration_seconds
        fixed = {key: float(value) for key, value in (fixed_durations or {}).items()}
        weights: dict[str, float] = {}
        for scene in self.scenes:
            scene_id = scene.get("id", "")
            if scene_id in fixed:
                weights[scene_id] = fixed[scene_id]
                continue
            chars = len((scene.get("spoken_text") or "").strip())
            weights[scene_id] = max(MIN_SCENE_SECONDS, min(self.max_scene_seconds, chars / CHARS_PER_SECOND + 1.0))
        durations = self._allocate_bounded(weights, fixed, target)
        # 单镜上限导致目标时长不可达时，收敛目标到实际分配合计，保证结构合法。
        feasible_total = sum(durations.values())
        if abs(feasible_total - target) > 0.11 and self.scenes:
            target = round(max(feasible_total, MIN_SCENE_SECONDS * len(self.scenes)), 3)
            self._content["production_settings"]["target_duration_seconds"] = target
            self._content["course_info"]["duration_seconds"] = target
        cursor = 0.0
        count = len(self.scenes)
        for index, scene in enumerate(self.scenes):
            duration = durations[scene.get("id", "")]
            if index == count - 1 and count > 1:
                duration = min(self.max_scene_seconds, max(MIN_SCENE_SECONDS, target - cursor))
            scene["start_seconds"] = round(cursor, 3)
            scene["end_seconds"] = round(cursor + duration, 3)
            cursor += duration
            self._clip_cues_to_duration(scene)
        self._content["production_settings"]["target_duration_seconds"] = round(target, 3)
        self._content["course_info"]["duration_seconds"] = round(target, 3)

    def _allocate_bounded(
        self,
        weights: dict[str, float],
        fixed: dict[str, float],
        target: float,
    ) -> dict[str, float]:
        """有界比例分配：总时长 = target，每镜 ∈ [4, 15]，指定时长不变。

        迭代调整：按比例缩放后夹取到窗口，把盈余/缺口在未触及边界的场景间
        再次按比例分配，直到收敛或没有可调整项（此时允许轻微偏差，由 QA 门禁拦截）。
        """
        max_seconds = self.max_scene_seconds
        result: dict[str, float] = {}
        for scene_id, weight in weights.items():
            if scene_id in fixed:
                result[scene_id] = min(max_seconds, max(MIN_SCENE_SECONDS, weight))
            else:
                result[scene_id] = min(max_seconds, max(MIN_SCENE_SECONDS, weight))
        ids = [scene_id for scene_id in weights]
        for _ in range(40):
            total = sum(result.values())
            if abs(total - target) < 0.01:
                break
            diff = target - total
            adjustable = [
                scene_id for scene_id in ids
                if scene_id not in fixed
                and not (diff > 0 and result[scene_id] >= max_seconds - 1e-6)
                and not (diff < 0 and result[scene_id] <= MIN_SCENE_SECONDS + 1e-6)
            ]
            if not adjustable:
                break
            adjust_total = sum(result[scene_id] for scene_id in adjustable) or 1.0
            for scene_id in adjustable:
                result[scene_id] = min(
                    max_seconds,
                    max(MIN_SCENE_SECONDS, result[scene_id] * (1 + diff / adjust_total)),
                )
        return result

    @property
    def max_scene_seconds(self) -> float:
        return min(
            MAX_SCENE_SECONDS,
            max(MIN_SCENE_SECONDS, float(self._content["production_settings"].get("max_clip_seconds") or MAX_SCENE_SECONDS)),
        )

    def rebalance_timeline(self, durations: dict[str, float] | None = None) -> dict[str, Any]:
        """时间重平衡：优先保留锁定分镜与教师指定时长，其余按口播比例重算。"""
        self.recalc_timeline(fixed_durations=durations or {})
        return {
            "target_duration_seconds": self.target_duration_seconds,
            "scenes": [
                {"id": scene.get("id"), "start_seconds": scene.get("start_seconds"),
                 "end_seconds": scene.get("end_seconds"),
                 "duration_seconds": round(float(scene.get("end_seconds", 0)) - float(scene.get("start_seconds", 0)), 3)}
                for scene in self.scenes
            ],
        }

    # ------------------------------------------------------------------
    # 差异
    # ------------------------------------------------------------------

    def diff(self, source_content: dict[str, Any] | None) -> dict[str, Any]:
        """候选稿 vs 正式源版本的结构差异（章节 / 分镜级，ID 感知）。"""
        if not source_content:
            return {"is_new": True, "note": "首次生成，无源版本可对比"}
        if source_content.get("schema_version") != VIDEO_SCRIPT_V4:
            return {"is_new": True, "note": "源版本为 V3/V2，本轮将生成首个 V4 版本", "migration_required": True}
        source_sections = {str(item.get("id")): item for item in source_content.get("outline", {}).get("sections", [])}
        source_scenes = {str(item.get("id")): item for item in source_content.get("scenes", [])}
        candidate_sections = {item.get("id"): item for item in self.sections}
        candidate_scenes = {item.get("id"): item for item in self.scenes}
        added_sections = sorted(set(candidate_sections) - set(source_sections))
        removed_sections = sorted(set(source_sections) - set(candidate_sections))
        changed_sections = sorted(
            section_id for section_id in set(source_sections) & set(candidate_sections)
            if source_sections[section_id] != candidate_sections[section_id]
        )
        added_scenes = sorted(set(candidate_scenes) - set(source_scenes))
        removed_scenes = sorted(set(source_scenes) - set(candidate_scenes))
        changed_scenes = sorted(
            scene_id for scene_id in set(source_scenes) & set(candidate_scenes)
            if source_scenes[scene_id] != candidate_scenes[scene_id]
        )
        return {
            "added_sections": added_sections, "removed_sections": removed_sections,
            "changed_sections": changed_sections, "added_scenes": added_scenes,
            "removed_scenes": removed_scenes, "changed_scenes": changed_scenes,
            "changed": bool(added_sections or removed_sections or changed_sections
                            or added_scenes or removed_scenes or changed_scenes),
        }


def build_initial_builder(
    bp_content: dict[str, Any],
    lesson_plan_raw: dict[str, Any] | None = None,
) -> VideoScriptBuilder:
    """蓝图驱动初始化：确定性 V4 候选稿。

    章节由教学设计的真实环节生成（连续 lesson_stage_id 分组），分镜沿用
    V3 确定性 mock 的时间轴与口播，最后重排为动态章节结构。
    """
    from app.agents.generators import make_seedance_video_script
    from app.schemas.blueprint import CourseBlueprintSchema
    from app.schemas.artifact import LessonPlanContent

    bp = CourseBlueprintSchema.model_validate(bp_content)
    lesson_plan = _to_v1_lesson_plan(lesson_plan_raw)
    if lesson_plan is None or not lesson_plan.stages:
        from app.agents.generators import make_lesson_plan

        lesson_plan = make_lesson_plan(bp)
    v3 = make_seedance_video_script(bp, lesson_plan)
    v4 = upgrade_video_script_v4(v3.model_dump(), lesson_plan_raw)
    return VideoScriptBuilder(v4.model_dump())


def build_empty_builder(bp_content: dict[str, Any]) -> VideoScriptBuilder:
    """真实 LLM 首次生成的最小骨架；不预填章节、分镜或模板化口播。"""
    from app.schemas.blueprint import CourseBlueprintSchema

    bp = CourseBlueprintSchema.model_validate(bp_content)
    identity = bp.course_identity
    duration_seconds = max(4, int(float(identity.duration_minutes or 0) * 60))
    return VideoScriptBuilder({
        "schema_version": VIDEO_SCRIPT_V4,
        "course_info": {
            "course_title": identity.title,
            "subject": identity.subject,
            "grade_level": identity.grade_level,
            "audience": identity.audience,
            "duration_seconds": duration_seconds,
        },
        "production_settings": {
            "mode": "seedance_native", "aspect_ratio": "16:9",
            "target_duration_seconds": duration_seconds,
            "target_clip_seconds": 12, "min_clip_seconds": 4, "max_clip_seconds": 15,
            "global_visual_style": "统一、清晰、适龄的现代教学影像",
            "global_voice_direction": "自然、清晰、可信赖的中文教师声音",
        },
        "outline": {"sections": []},
        "scenes": [],
    })


def _to_v1_lesson_plan(lesson_plan_raw: dict[str, Any] | None):
    """容错解析教学设计为 V1 LessonPlanContent。

    输入可能是：V1 原始结构、V2（schema_version 2.0）、或知识上下文的稳定内核
    投影（lesson_plan_core：objectives 为 {id, statement, evidence} 字典列表、
    stages 为内核形状）。统一投影为 V1，供确定性 mock 生成器消费。
    """
    if not lesson_plan_raw:
        return None
    from app.schemas.artifact import LessonPlanContent, LessonStage

    raw = lesson_plan_raw
    if "content" in raw and isinstance(raw.get("content"), dict):
        raw = raw["content"]
    # V2 → V1 投影
    if raw.get("schema_version") == "2.0":
        from app.schemas.lesson_plan import lesson_plan_v1_from_any

        try:
            return lesson_plan_v1_from_any(raw)
        except Exception:  # noqa: BLE001
            return None
    try:
        return LessonPlanContent.model_validate(raw)
    except Exception:  # noqa: BLE001
        pass
    # 稳定内核投影形状：objectives 是字典列表、stages 是内核形状
    try:
        objectives = [
            str(item.get("statement") or item.get("behavior") or item.get("id") or "")
            for item in raw.get("objectives", []) if isinstance(item, dict)
        ]
        stages = [
            LessonStage(
                id=item.get("id", ""), title=item.get("title", ""),
                duration_minutes=float(item.get("duration_minutes", 1)),
                teacher_activity=item.get("teacher_activity", ""),
                learner_activity=item.get("learner_activity", ""),
                design_intent=item.get("design_intent", ""),
                assessment=item.get("assessment", ""),
            )
            for item in raw.get("stages", []) if isinstance(item, dict)
        ]
        if not stages:
            return None
        return LessonPlanContent(
            content_analysis=raw.get("content_analysis", ""),
            learner_analysis=raw.get("learner_analysis", ""),
            objectives=objectives,
            key_points=[str(item) for item in raw.get("key_points", [])],
            difficulty_points=[str(item) for item in raw.get("difficulty_points", [])],
            methods=[str(item) for item in raw.get("methods", [])],
            resources=[str(item) for item in raw.get("resources", [])],
            stages=stages,
            board_design=raw.get("board_design", ""),
            homework=raw.get("homework", ""),
        )
    except Exception:  # noqa: BLE001
        return None


def upgrade_builder(
    source_content: dict[str, Any],
    bp_content: dict[str, Any] | None = None,
    lesson_plan_raw: dict[str, Any] | None = None,
) -> VideoScriptBuilder:
    """V3 → V4 确定性适配（首次修改/同步时使用），不改写旧 Artifact。"""
    if (source_content or {}).get("schema_version") == VIDEO_SCRIPT_V4:
        return VideoScriptBuilder(source_content)
    v4 = upgrade_video_script_v4(source_content, lesson_plan_raw)
    return VideoScriptBuilder(v4.model_dump())
