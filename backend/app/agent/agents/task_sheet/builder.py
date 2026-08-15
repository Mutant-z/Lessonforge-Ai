"""TaskSheetBuilder：任务单 V3 内存候选稿。"""

from __future__ import annotations

import copy
from typing import Any

from app.schemas.task_sheet import (
    MAX_TASK_SHEET_DEPTH,
    TASK_SHEET_V3,
    TaskSheetContentV3,
    task_sheet_sections_depth,
)


class TaskSheetBuilder:
    def __init__(self, content: dict[str, Any] | None = None):
        self._content: dict[str, Any] = copy.deepcopy(content) if content else {
            "schema_version": TASK_SHEET_V3,
            "course_info": {
                "course_title": "", "subject": "", "grade_level": "",
                "audience": "", "duration_minutes": 0,
            },
            "objective_catalog": [],
            "sections": [],
        }
        self._revision: int = 0

    @property
    def revision(self) -> int:
        return self._revision

    def bump_revision(self) -> int:
        self._revision += 1
        return self._revision

    def to_content(self) -> dict[str, Any]:
        return copy.deepcopy(self._content)

    @property
    def sections(self) -> list[dict[str, Any]]:
        return self._content["sections"]

    @property
    def objective_catalog(self) -> list[dict[str, Any]]:
        return self._content["objective_catalog"]

    def find_section(self, section_id: str) -> dict[str, Any] | None:
        return next((item for item in self.sections if item.get("id") == section_id), None)

    def section_children(self, section_id: str) -> list[dict[str, Any]]:
        return [item for item in self.sections if item.get("parent_id") == section_id]

    def top_level_sections(self) -> list[dict[str, Any]]:
        return sorted(
            [item for item in self.sections if not item.get("parent_id")],
            key=lambda x: int(x.get("order", 0)),
        )

    def all_section_ids(self) -> list[str]:
        return [item.get("id", "") for item in self.sections]

    def all_block_ids(self) -> list[str]:
        return [
            block.get("id", "")
            for section in self.sections
            for block in section.get("blocks", [])
        ]

    def count_sections(self) -> int:
        return len(self.sections)

    # ------------------------------------------------------------------
    # 学习任务定位（方案工具按稳定任务 ID 寻址）
    # ------------------------------------------------------------------

    def find_task(self, task_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """按任务 ID 查找 (task_block, section)。任务即 kind == learning_task 的 Block。"""
        for section in self.sections:
            for block in section.get("blocks", []):
                if block.get("id") == task_id and block.get("kind") == "learning_task":
                    return block, section
        return None, None

    def all_task_ids(self) -> list[str]:
        return [
            block.get("id", "")
            for section in self.sections
            for block in section.get("blocks", [])
            if block.get("kind") == "learning_task"
        ]

    def all_task_blocks(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """返回 [(task_block, section)] 列表，按目录顺序（order 升序）。"""
        ordered = sorted(self.sections, key=lambda x: (int(x.get("order", 0)), x.get("id", "")))
        result: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for section in ordered:
            for block in section.get("blocks", []):
                if block.get("kind") == "learning_task":
                    result.append((block, section))
        return result

    def task_json_path(self, task_id: str) -> str:
        """构造任务的 JSON 路径（用于锁定检查与 QA 定位）。"""
        block, section = self.find_task(task_id)
        if block is None or section is None:
            raise ValueError(f"任务不存在：{task_id}")
        index = next(
            (i for i, b in enumerate(section.get("blocks", [])) if b.get("id") == task_id),
            0,
        )
        return f"$.sections[{section.get('id', '')}].blocks[{index}]"

    def sections_depth(self) -> int:
        return task_sheet_sections_depth([dict(item) for item in self.sections])

    def validate_content(self) -> dict[str, Any]:
        try:
            TaskSheetContentV3.model_validate(self._content)
            return {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    def _check_depth(self, parent_id: str) -> None:
        if not parent_id:
            return
        if self._section_depth(parent_id) >= MAX_TASK_SHEET_DEPTH:
            raise ValueError(f"目录深度不能超过 {MAX_TASK_SHEET_DEPTH} 级")

    def _section_depth(self, section_id: str) -> int:
        depth = 1
        node = self.find_section(section_id)
        while node and node.get("parent_id"):
            node = self.find_section(node.get("parent_id"))
            depth += 1
            if depth > MAX_TASK_SHEET_DEPTH + 1:
                break
        return depth

    def add_section(self, section_id: str, title: str, *, parent_id: str = "", index: int | None = None) -> dict[str, Any]:
        if self.find_section(section_id):
            raise ValueError(f"章节 ID 已存在：{section_id}")
        if parent_id and self.find_section(parent_id) is None:
            raise ValueError(f"父章节不存在：{parent_id}")
        self._check_depth(parent_id)
        siblings = [item for item in self.sections if item.get("parent_id") == parent_id]
        order = len(siblings) if index is None else min(max(0, index), len(siblings))
        self._shift_orders(parent_id, order, 1)
        node = {"id": section_id, "parent_id": parent_id, "order": order,
                "title": title, "purpose": "", "objective_ids": [], "blocks": []}
        self.sections.append(node)
        return copy.deepcopy(node)

    def rename_section(self, section_id: str, title: str) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        node["title"] = title
        return copy.deepcopy(node)

    def update_section_metadata(self, section_id: str, *, purpose: str | None = None,
                                objective_ids: list[str] | None = None) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        if purpose is not None:
            node["purpose"] = purpose
        if objective_ids is not None:
            node["objective_ids"] = list(objective_ids)
        return copy.deepcopy(node)

    def move_section(self, section_id: str, *, target_parent_id: str = "", index: int | None = None) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        if target_parent_id and self.find_section(target_parent_id) is None:
            raise ValueError(f"目标父章节不存在：{target_parent_id}")
        if target_parent_id == section_id:
            raise ValueError("不能把章节移动到自身下面")
        if self._is_descendant(section_id, target_parent_id):
            raise ValueError("不能把章节移动到自己的子章节下")
        self._check_depth(target_parent_id)
        old_parent = node.get("parent_id")
        old_order = int(node.get("order", 0))
        self._remove_section_slot(section_id)
        self._shift_orders(old_parent, old_order + 1, -1)
        siblings = [item for item in self.sections if item.get("parent_id") == target_parent_id]
        new_order = len(siblings) if index is None else min(max(0, index), len(siblings))
        self._shift_orders(target_parent_id, new_order, 1)
        node["parent_id"] = target_parent_id
        node["order"] = new_order
        self.sections.append(node)
        return copy.deepcopy(node)

    def delete_section(self, section_id: str) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        descendants = self._descendants(section_id)
        for desc_id in [section_id, *descendants]:
            self._remove_section_slot(desc_id)
        self._shift_orders(node.get("parent_id"), int(node.get("order", 0)) + 1, -1)
        return copy.deepcopy(node)

    def _is_descendant(self, ancestor_id: str, node_id: str) -> bool:
        return node_id in self._descendants(ancestor_id)

    def _descendants(self, section_id: str) -> list[str]:
        result: list[str] = []
        stack = [section_id]
        while stack:
            current = stack.pop()
            children = [item for item in self.sections if item.get("parent_id") == current]
            for child in children:
                result.append(child.get("id", ""))
                stack.append(child.get("id", ""))
        return result

    def _remove_section_slot(self, section_id: str) -> None:
        self.sections[:] = [item for item in self.sections if item.get("id") != section_id]

    def _shift_orders(self, parent_id: str, from_order: int, delta: int) -> None:
        for item in self.sections:
            if item.get("parent_id") == parent_id and int(item.get("order", 0)) >= from_order:
                item["order"] = max(0, int(item.get("order", 0)) + delta)

    def add_block(self, section_id: str, block: dict[str, Any]) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        if block.get("id") in self.all_block_ids():
            raise ValueError(f"Block ID 已存在：{block.get('id')}")
        node.setdefault("blocks", []).append(copy.deepcopy(block))
        return copy.deepcopy(block)

    def update_block(self, section_id: str, block_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        block = next((b for b in node.get("blocks", []) if b.get("id") == block_id), None)
        if block is None:
            raise ValueError(f"Block 不存在：{block_id}")
        for key, value in patch.items():
            if key in {"kind", "id"}:
                raise ValueError("不允许修改 Block 类型或 ID，请删除后新增")
            block[key] = copy.deepcopy(value)
        return copy.deepcopy(block)

    def move_block(self, section_id: str, block_id: str, target_section_id: str, index: int | None = None) -> dict[str, Any]:
        source = self.find_section(section_id)
        if source is None:
            raise ValueError(f"源章节不存在：{section_id}")
        block = next((b for b in source.get("blocks", []) if b.get("id") == block_id), None)
        if block is None:
            raise ValueError(f"Block 不存在：{block_id}")
        target = self.find_section(target_section_id)
        if target is None:
            raise ValueError(f"目标章节不存在：{target_section_id}")
        source["blocks"] = [b for b in source.get("blocks", []) if b.get("id") != block_id]
        position = len(target.get("blocks", [])) if index is None else min(max(0, index), len(target.get("blocks", [])))
        target.setdefault("blocks", []).insert(position, block)
        return copy.deepcopy(block)

    def delete_block(self, section_id: str, block_id: str) -> dict[str, Any]:
        node = self.find_section(section_id)
        if node is None:
            raise ValueError(f"章节不存在：{section_id}")
        block = next((b for b in node.get("blocks", []) if b.get("id") == block_id), None)
        if block is None:
            raise ValueError(f"Block 不存在：{block_id}")
        node["blocks"] = [b for b in node.get("blocks", []) if b.get("id") != block_id]
        return copy.deepcopy(block)

    def apply_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        def deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
            for key, value in source.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    deep_merge(target[key], value)
                else:
                    target[key] = copy.deepcopy(value)
        deep_merge(self._content, patch)
        return copy.deepcopy(self._content)


def build_initial_builder(
    bp_content: dict[str, Any],
    lesson_plan_raw: dict[str, Any] | None = None,
) -> TaskSheetBuilder:
    from app.schemas.blueprint import CourseBlueprintSchema
    from app.schemas.task_sheet import make_task_sheet_v3

    bp = CourseBlueprintSchema.model_validate(bp_content)
    v3 = make_task_sheet_v3(bp, lesson_plan_raw)
    return TaskSheetBuilder(v3.model_dump())


def upgrade_builder(
    v1_content: dict[str, Any],
    bp_content: dict[str, Any],
    lesson_plan_raw: dict[str, Any] | None = None,
) -> TaskSheetBuilder:
    from app.schemas.blueprint import CourseBlueprintSchema
    from app.schemas.task_sheet import task_sheet_to_v3

    bp = CourseBlueprintSchema.model_validate(bp_content)
    v3 = task_sheet_to_v3(v1_content, bp, lesson_plan_raw)
    return TaskSheetBuilder(v3.model_dump())


def outline_sections_for(content: dict[str, Any]) -> list[dict[str, Any]]:
    from app.schemas.task_sheet import task_sheet_outline_sections

    return task_sheet_outline_sections(content)
