"""ExerciseBuilder：课后练习 V2 内存候选稿。

结构与 ExerciseContent schema 一一对应；工具通过稳定题目 ID 寻址（顶层
question block 或 question_group 的 sub_questions）。所有修改作用于内存
候选稿，绝不直接改写正式 Artifact；最终由 finalizer 的发布门禁校验。
"""

from __future__ import annotations

import copy
from typing import Any

from app.schemas.artifact import ExerciseContent

EXERCISE_SCHEMA_VERSION = "2.0"

#: 三区固定 ID 顺序（schema 强制）
SECTION_ORDER = ["basic_consolidation", "understanding_application", "transfer_challenge"]


def _empty_content() -> dict[str, Any]:
    return {
        "schema_version": EXERCISE_SCHEMA_VERSION,
        "course_info": {
            "course_title": "", "subject": "", "grade_level": "",
            "audience": "", "duration_minutes": 0,
        },
        "paper_settings": {
            "title": "", "student_instructions": [],
            "total_score": 100, "estimated_minutes": 10.0, "answer_requirements": "",
        },
        "sections": [],
        "review_summary": {
            "rules_status": "pending", "text_review_status": "pending",
            "visual_review_status": "not_required", "needs_teacher_attention": False,
            "notes": [],
        },
    }


def _iter_questions(content: dict[str, Any]):
    """按稳定 ID 遍历全部计分题：产出 (question_block, section, group_block | None)。"""
    for section in content.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("kind") == "question":
                yield block, section, None
            elif block.get("kind") == "question_group":
                for question in block.get("sub_questions", []):
                    yield question, section, block


class ExerciseBuilder:
    def __init__(self, content: dict[str, Any] | None = None):
        self._content: dict[str, Any] = copy.deepcopy(content) if content else _empty_content()
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
    def paper_settings(self) -> dict[str, Any]:
        return self._content["paper_settings"]

    def find_section(self, section_id: str) -> dict[str, Any] | None:
        return next((item for item in self.sections if item.get("id") == section_id), None)

    def all_question_ids(self) -> list[str]:
        return [item[0].get("id", "") for item in _iter_questions(self._content)]

    def question_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for question, _, _ in _iter_questions(self._content):
            question_type = str(question.get("question_type") or "")
            counts[question_type] = counts.get(question_type, 0) + 1
        return counts

    def question_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "id": question.get("id"),
                "question_type": question.get("question_type"),
                "score": question.get("score"),
                "correct_option_ids": list((question.get("answer_key") or {}).get("correct_option_ids") or []),
                "section_id": section.get("id"),
                "group_id": group.get("id") if group else None,
            }
            for question, section, group in _iter_questions(self._content)
        ]

    def replace_content(self, content: dict[str, Any], *, revision: int | None = None) -> None:
        """Atomically replace the in-memory candidate after external validation."""
        self._content = copy.deepcopy(content)
        self._revision = self._revision + 1 if revision is None else revision

    def all_stimulus_ids(self) -> list[str]:
        result: list[str] = []
        for section in self.sections:
            for block in section.get("blocks", []):
                if block.get("kind") == "question_group":
                    result.extend(stimulus.get("id", "") for stimulus in block.get("stimuli", []))
        return result

    def find_question(self, question_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        """按题目 ID 查找 (question_block, section, group_block | None)。"""
        for question, section, group in _iter_questions(self._content):
            if question.get("id") == question_id:
                return question, section, group
        return None, None, None

    def question_json_path(self, question_id: str) -> str:
        question, section, group = self.find_question(question_id)
        if question is None or section is None:
            raise ValueError(f"题目不存在：{question_id}")
        section_index = next(
            (i for i, item in enumerate(self.sections) if item.get("id") == section.get("id")),
            0,
        )
        if group is None:
            block_index = next(
                (i for i, block in enumerate(section.get("blocks", [])) if block.get("id") == question_id),
                0,
            )
            return f"$.sections[{section_index}].blocks[{block_index}]"
        group_index = next(
            (i for i, block in enumerate(section.get("blocks", [])) if block.get("id") == group.get("id")),
            0,
        )
        sub_index = next(
            (i for i, item in enumerate(group.get("sub_questions", [])) if item.get("id") == question_id),
            0,
        )
        return f"$.sections[{section_index}].blocks[{group_index}].sub_questions[{sub_index}]"

    def _block_owner(self, block_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """按 block ID（question 或 question_group）定位 (block, section)。"""
        for section in self.sections:
            for block in section.get("blocks", []):
                if block.get("id") == block_id:
                    return block, section
        return None, None

    # ------------------------------------------------------------------
    # 结构操作
    # ------------------------------------------------------------------

    def add_block(self, section_id: str, block: dict[str, Any]) -> dict[str, Any]:
        """添加或覆盖一个题目/题组块。

        幂等 upsert 语义：ID 已存在时用新内容**原地覆盖**该块（保留原 ID 与位置），
        而不是改名或报错。这样 LLM 无论重复 add 多少次，ID 都保持稳定，
        后续 update 用同一 ID 永远能找到——避免"add 成功后 update 找不到"的
        状态失同步（LLM 不追踪改名后的 ID 是已反复出现的真实失败模式）。
        """
        section = self.find_section(section_id)
        if section is None:
            raise ValueError(f"分区不存在：{section_id}")
        block_id = block.get("id", "q")
        # 目标分区内已有同名块：原地覆盖。
        for index, existing in enumerate(section.get("blocks", [])):
            if existing.get("id") == block_id:
                section["blocks"][index] = copy.deepcopy(block)
                return copy.deepcopy(block)
        # 同名块在其他分区：从原位置移除，然后在目标分区新增（ID 收敛到本次 add 的分区）。
        for other in self.sections:
            other["blocks"] = [b for b in other.get("blocks", []) if b.get("id") != block_id]
            for group in other.get("blocks", []):
                if group.get("kind") == "question_group":
                    group["sub_questions"] = [
                        q for q in group.get("sub_questions", []) if q.get("id") != block_id
                    ]
        # 目标分区内题组子题里的同名块同样清理，避免全卷出现重复 ID。
        for group in section.get("blocks", []):
            if group.get("kind") == "question_group":
                group["sub_questions"] = [
                    q for q in group.get("sub_questions", []) if q.get("id") != block_id
                ]
        section.setdefault("blocks", []).append(copy.deepcopy(block))
        return copy.deepcopy(block)

    def update_block(self, block_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        block, section, _ = self.find_question(block_id)
        if block is None:
            block, section = self._block_owner(block_id)
        if block is None:
            raise ValueError(f"题目/题组不存在：{block_id}")
        for key, value in patch.items():
            if key in {"kind", "id"}:
                raise ValueError("不允许修改题目类型或 ID，请删除后新增")
            block[key] = copy.deepcopy(value)
        return copy.deepcopy(block)

    def delete_block(self, block_id: str) -> dict[str, Any]:
        for section in self.sections:
            for index, block in enumerate(section.get("blocks", [])):
                if block.get("id") == block_id:
                    removed = section["blocks"].pop(index)
                    return copy.deepcopy(removed)
                if block.get("kind") == "question_group":
                    for sub_index, question in enumerate(block.get("sub_questions", [])):
                        if question.get("id") == block_id:
                            removed = block["sub_questions"].pop(sub_index)
                            return copy.deepcopy(removed)
        raise ValueError(f"题目/题组不存在：{block_id}")

    def move_question(self, question_id: str, destination_section_id: str) -> dict[str, Any]:
        """Move a top-level question intact and make section scores follow content."""
        question, source_section, group = self.find_question(question_id)
        destination = self.find_section(destination_section_id)
        if question is None or source_section is None:
            raise ValueError(f"题目不存在：{question_id}")
        if destination is None:
            raise ValueError(f"分区不存在：{destination_section_id}")
        if group is not None:
            raise ValueError("题组子题不能脱离共享材料单独移动，请移动或拆分整个题组")
        source_section_id = str(source_section.get("id") or "")
        if source_section_id == destination_section_id:
            return {
                "question_id": question_id,
                "source_section_id": source_section_id,
                "destination_section_id": destination_section_id,
                "moved": False,
            }
        preserved = copy.deepcopy(question)
        source_section["blocks"] = [
            block for block in source_section.get("blocks", []) if block.get("id") != question_id
        ]
        destination.setdefault("blocks", []).append(preserved)
        for section in self.sections:
            section["score"] = sum(
                int(item.get("score") or 0)
                for item, owner, _ in _iter_questions(self._content)
                if owner is section
            )
        return {
            "question_id": question_id,
            "source_section_id": source_section_id,
            "destination_section_id": destination_section_id,
            "moved": True,
        }

    def update_section_score(self, section_id: str, score: int) -> dict[str, Any]:
        section = self.find_section(section_id)
        if section is None:
            raise ValueError(f"分区不存在：{section_id}")
        if not isinstance(score, int) or score <= 0:
            raise ValueError("分区分值必须是正整数")
        section["score"] = score
        return copy.deepcopy(section)

    def update_section_title(self, section_id: str, title: str) -> dict[str, Any]:
        section = self.find_section(section_id)
        if section is None:
            raise ValueError(f"分区不存在：{section_id}")
        section["title"] = title
        return copy.deepcopy(section)

    def update_paper_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        for key, value in patch.items():
            if key in {"schema_version", "total_score"}:
                raise ValueError("不允许直接修改 schema_version 或 total_score，请调整各分区与题目分值")
            self._content["paper_settings"][key] = copy.deepcopy(value)
        return copy.deepcopy(self._content["paper_settings"])

    def update_review_summary(self, patch: dict[str, Any]) -> dict[str, Any]:
        for key, value in patch.items():
            self._content["review_summary"][key] = copy.deepcopy(value)
        return copy.deepcopy(self._content["review_summary"])

    def update_stimulus(self, stimulus_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        for section in self.sections:
            for block in section.get("blocks", []):
                if block.get("kind") != "question_group":
                    continue
                for stimulus in block.get("stimuli", []):
                    if stimulus.get("id") == stimulus_id:
                        for key, value in patch.items():
                            if key in {"kind", "id"}:
                                raise ValueError("不允许修改材料类型或 ID，请删除后新增")
                            stimulus[key] = copy.deepcopy(value)
                        return copy.deepcopy(stimulus)
        raise ValueError(f"材料不存在：{stimulus_id}")

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def validate_content(self) -> dict[str, Any]:
        try:
            ExerciseContent.model_validate(self._content)
            return {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    def to_validated_content(self) -> dict[str, Any]:
        """结构校验通过后返回规范化 dict；非法抛 ValueError（由调用方降级保留原版）。"""
        model = ExerciseContent.model_validate(self._content)
        return model.model_dump()


def build_initial_builder(
    bp_content: dict[str, Any],
    task_sheet_raw: dict[str, Any] | None = None,
) -> ExerciseBuilder:
    """首稿：以蓝图驱动的确定性示例（make_exercises）为种子，LLM 角色在此基础上精修。"""
    from app.agents.generators import make_exercises
    from app.schemas.blueprint import CourseBlueprintSchema

    bp = CourseBlueprintSchema.model_validate(bp_content)
    example = make_exercises(bp)
    return ExerciseBuilder(example.model_dump())


def upgrade_builder(
    source_content: dict[str, Any],
    bp_content: dict[str, Any],
    task_sheet_raw: dict[str, Any] | None = None,
) -> ExerciseBuilder:
    """修订：V2 源内容原样加载为候选稿；V1 或结构非法时重建为确定性种子。"""
    if source_content.get("schema_version") == EXERCISE_SCHEMA_VERSION:
        try:
            ExerciseContent.model_validate(source_content)
            return ExerciseBuilder(source_content)
        except Exception:  # noqa: BLE001  结构非法的旧版按重建处理
            pass
    return build_initial_builder(bp_content, task_sheet_raw)
