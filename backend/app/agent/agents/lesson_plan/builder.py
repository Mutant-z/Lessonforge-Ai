"""LessonPlanBuilder：内存候选稿。

编辑工具只修改内存中的候选稿，不直接写正式 Artifact。候选稿最终经
finalizer 校验后发布为新版本；未通过门禁时保留原版。

结构：V2 content dict 的内存可变副本（course_info + pedagogical_core + outline）。
章节树 CRUD 维护大纲；锁定路径检查在工具层完成（builder 只做纯数据操作）。
"""

from __future__ import annotations

import copy
from typing import Any

from app.schemas.lesson_plan import LessonPlanContentV2, lesson_plan_outline_sections


class LessonPlanBuilder:
    def __init__(self, content: dict[str, Any] | None = None):
        self._content: dict[str, Any] = copy.deepcopy(content) if content else {
            "schema_version": "2.0",
            "course_info": {},
            "pedagogical_core": {
                "objectives": [], "knowledge_points": [], "key_points": [],
                "difficulty_points": [], "methods": [], "resources": [],
                "stages": [], "assessment_plan": [], "homework": "",
                "board_design": "", "reflection": "课后由教师填写教学反思。",
            },
            "outline": {"sections": []},
        }

    # ------------------------------------------------------------------
    # 只读
    # ------------------------------------------------------------------

    def to_content(self) -> dict[str, Any]:
        return copy.deepcopy(self._content)

    def replace_content(self, content: dict[str, Any]) -> None:
        """Atomically replace the candidate after external guards validate a clone."""
        self._content = copy.deepcopy(content)

    @property
    def outline(self) -> list[dict[str, Any]]:
        return self._content["outline"]["sections"]

    @property
    def core(self) -> dict[str, Any]:
        return self._content["pedagogical_core"]

    def find_section(self, section_id: str) -> dict[str, Any] | None:
        """按 ID 在大纲树中查找章节（含子孙）。"""
        def visit(sections: list[dict[str, Any]]) -> dict[str, Any] | None:
            for section in sections:
                if section.get("id") == section_id:
                    return section
                found = visit(section.get("children") or [])
                if found is not None:
                    return found
            return None
        return visit(self.outline)

    def all_section_ids(self) -> list[str]:
        result: list[str] = []

        def visit(sections: list[dict[str, Any]]) -> None:
            for section in sections:
                result.append(section.get("id", ""))
                visit(section.get("children") or [])
        visit(self.outline)
        return result

    def count_sections(self) -> int:
        return len(self.all_section_ids())

    def validate_content(self) -> dict[str, Any]:
        """返回 (ok, error) 风格结果供工具使用。"""
        try:
            LessonPlanContentV2.model_validate(self._content)
            return {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    # ------------------------------------------------------------------
    # 大纲结构编辑
    # ------------------------------------------------------------------

    def _locate_parent(self, parent_id: str) -> list[dict[str, Any]] | None:
        if parent_id in {"", "$", "root"}:
            return self.outline
        parent = self.find_section(parent_id)
        return (parent.get("children") if parent else None)

    def add_section(self, section_id: str, title: str, *, parent_id: str = "", index: int | None = None) -> dict[str, Any]:
        """在 parent_id 下插入章节；返回新章节副本。"""
        if self.find_section(section_id):
            raise ValueError(f"章节 ID 已存在：{section_id}")
        siblings = self._locate_parent(parent_id)
        if siblings is None:
            raise ValueError(f"父章节不存在：{parent_id}")
        node = {"id": section_id, "title": title, "summary": "", "coverage_refs": [], "blocks": [], "children": []}
        position = len(siblings) if index is None else min(max(0, index), len(siblings))
        siblings.insert(position, node)
        return copy.deepcopy(node)

    def move_section(self, section_id: str, *, target_parent_id: str = "", index: int | None = None) -> dict[str, Any]:
        """移动章节到新父节点下；返回被移动章节副本。"""
        node = self._detach_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        if target_parent_id != "" and self.find_section(target_parent_id) is None:
            raise ValueError(f"目标父章节不存在：{target_parent_id}")
        siblings = self._locate_parent(target_parent_id)
        if siblings is None:
            raise ValueError(f"目标父章节不存在：{target_parent_id}")
        position = len(siblings) if index is None else min(max(0, index), len(siblings))
        siblings.insert(position, node)
        return copy.deepcopy(node)

    def rename_section(self, section_id: str, title: str) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        node["title"] = title
        return copy.deepcopy(node)

    def merge_sections(self, section_ids: list[str], new_title: str) -> dict[str, Any]:
        """合并多个同级章节为一个（保留各自内容块），新章节取代第一个位置。"""
        if len(section_ids) < 2:
            raise ValueError("合并至少需要两个章节")
        nodes = [self.find_section(section_id) for section_id in section_ids]
        if any(node is None for node in nodes):
            raise ValueError("合并目标章节不存在")
        first_parent = self._locate_parent("")
        first_index = next(
            (index for index, item in enumerate(first_parent) if item.get("id") == section_ids[0]), None,
        )
        merged: dict[str, Any] = {
            "id": section_ids[0],
            "title": new_title,
            "summary": "；".join(node["summary"] for node in nodes if node and node.get("summary"))[:200],
            "coverage_refs": sorted({
                ref for node in nodes if node
                for ref in node.get("coverage_refs") or []
            }),
            "blocks": [block for node in nodes if node for block in node.get("blocks") or []],
            "children": [child for node in nodes if node for child in node.get("children") or []],
        }
        for section_id in section_ids[1:]:
            self._detach_section(section_id)
        first_parent = self._locate_parent("")
        if first_index is not None and first_index < len(first_parent):
            first_parent[first_index] = merged
        else:
            first_parent.append(merged)
        return copy.deepcopy(merged)

    def delete_section(self, section_id: str) -> dict[str, Any]:
        node = self._detach_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        return copy.deepcopy(node)

    def _detach_section(self, section_id: str) -> dict[str, Any] | None:
        def visit(sections: list[dict[str, Any]]) -> dict[str, Any] | None:
            for index, section in enumerate(sections):
                if section.get("id") == section_id:
                    return sections.pop(index)
                found = visit(section.get("children") or [])
                if found is not None:
                    return found
            return None
        return visit(self.outline)

    def set_outline(self, sections: list[dict[str, Any]]) -> None:
        self._content["outline"]["sections"] = sections

    # ------------------------------------------------------------------
    # 内容编辑
    # ------------------------------------------------------------------

    def write_section(self, section_id: str, *, blocks: list[dict[str, Any]] | None = None,
                      summary: str | None = None, coverage_refs: list[str] | None = None,
                      title: str | None = None) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        if blocks is not None:
            node["blocks"] = blocks
        if summary is not None:
            node["summary"] = summary
        if coverage_refs is not None:
            node["coverage_refs"] = coverage_refs
        if title is not None:
            node["title"] = title
        return copy.deepcopy(node)

    def update_core(self, patch: dict[str, Any]) -> dict[str, Any]:
        """更新稳定内核字段（objectives/stages/... 整体替换或指定键）。"""
        for key, value in patch.items():
            if key in self.core:
                self.core[key] = copy.deepcopy(value)
        return copy.deepcopy(self.core)

    def apply_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        """深层合并补丁（覆盖内容与内核）。"""
        def deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
            for key, value in source.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    deep_merge(target[key], value)
                else:
                    target[key] = copy.deepcopy(value)
        deep_merge(self._content, patch)
        return copy.deepcopy(self._content)


def build_initial_builder(bp_content: dict[str, Any]) -> LessonPlanBuilder:
    """蓝图驱动初始化：把已批准蓝图投影为 V2 候选稿（确定性）。"""
    from app.schemas.blueprint import CourseBlueprintSchema
    from app.schemas.lesson_plan import make_lesson_plan_v2

    bp = CourseBlueprintSchema.model_validate(bp_content)
    v2 = make_lesson_plan_v2(bp)
    return LessonPlanBuilder(v2.model_dump())


def upgrade_builder(v1_content: dict[str, Any], bp_content: dict[str, Any]) -> LessonPlanBuilder:
    """V1 → V2 确定性适配（首次修改/同步时使用），不改写旧 Artifact。"""
    from app.schemas.blueprint import CourseBlueprintSchema
    from app.schemas.lesson_plan import upgrade_lesson_plan_v2

    bp = CourseBlueprintSchema.model_validate(bp_content)
    v2 = upgrade_lesson_plan_v2(v1_content, bp)
    return LessonPlanBuilder(v2.model_dump())


def outline_sections_for(content: dict[str, Any]) -> list[dict[str, Any]]:
    """对外统一的大纲树投影（V2 或 V1 默认目录），供前端与工具读取。"""
    return lesson_plan_outline_sections(content)
