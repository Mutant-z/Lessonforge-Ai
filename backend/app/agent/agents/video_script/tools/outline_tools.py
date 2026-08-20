"""视频脚本工具集：章节（大纲）编辑工具。

只修改内存中的 VideoScriptBuilder 候选稿，绝不直接写正式 Artifact。
每个编辑工具检查：目标章节存在、锁定路径；违规返回可修复的
ToolResult(ok=False) 让 Agent 调整方案，不得静默覆盖。

每个编辑工具返回：修改摘要、受影响 ID、草稿修订号与 JSON Patch
（RFC 6902 风格，path 以章节 ID 寻址，供前端实时局部更新）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agent.agents.video_script.tools.read_tools import _builder, _locked_paths
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool


def _lock_guard(tc: ToolContext, requested_paths: list[str] | None = None) -> None:
    locked = [str(path or "") for path in _locked_paths(tc)]
    if any(path in {"", "$"} for path in locked):
        raise ValueError("当前任务文件已整体锁定，不允许修改")
    for requested in requested_paths or []:
        normalized = requested.replace("/", ".").strip(".$")
        for locked_path in locked:
            locked_normalized = locked_path.replace("/", ".").strip(".$")
            if locked_normalized and (
                normalized == locked_normalized
                or normalized.startswith(f"{locked_normalized}.")
                or locked_normalized.startswith(f"{normalized}.")
            ):
                raise ValueError(f"修改路径已锁定：{locked_path}")


def _patch(path: str, op: str = "replace", value: Any = None) -> dict[str, Any]:
    patch: dict[str, Any] = {"op": op, "path": path}
    if value is not None:
        patch["value"] = value
    return patch


# 允许 LLM 使用简写形式（如 "update" 代替 "update_section_metadata"）
OUTLINE_OPS = {
    "add_section", "rename_section", "update_section_metadata",
    "move_section", "merge_sections", "delete_section",
}
OUTLINE_OPS_ALIASES = {
    "add": "add_section",
    "rename": "rename_section",
    "update": "update_section_metadata",
    "move": "move_section",
    "merge": "merge_sections",
    "delete": "delete_section",
}


class ApplyVideoScriptOutlineOpsInput(BaseModel):
    operations: list[dict[str, Any]] = Field(min_length=1, description="原子章节操作列表，顺序执行")

    @model_validator(mode="before")
    @classmethod
    def validate_ops(cls, value):
        operations = value.get("operations", [])
        for i, operation in enumerate(operations):
            op = operation.get("op")
            # 规范化简写形式
            if op in OUTLINE_OPS_ALIASES:
                operations[i]["op"] = OUTLINE_OPS_ALIASES[op]
                op = operations[i]["op"]
            if op not in OUTLINE_OPS:
                raise ValueError(f"不支持的章节操作：{operation.get('op')}")
            if op == "delete_section":
                if not operation.get("move_scenes_to") and not operation.get("reason"):
                    raise ValueError("删除章节必须指定 move_scenes_to 或按指令删除的 reason")
        return value


async def _vs_apply_outline_ops(tc: ToolContext, inp: ApplyVideoScriptOutlineOpsInput) -> ToolResult:
    builder = _builder(tc)
    requested_paths = [
        f"$.outline.sections.{operation.get('section_id') or 'new'}"
        for operation in inp.operations
    ]
    _lock_guard(tc, requested_paths)
    before = builder.to_content()
    before_revision = builder.revision
    affected_ids: list[str] = []
    patches: list[dict[str, Any]] = []
    summary: list[str] = []
    try:
        for operation in inp.operations:
            op = operation.get("op")
            section_id = operation.get("section_id")
            if op == "add_section":
                node = builder.add_section(
                    operation.get("title", ""),
                    purpose=operation.get("purpose"),
                    objective_ids=operation.get("objective_ids"),
                    knowledge_point_ids=operation.get("knowledge_point_ids"),
                )
                affected_ids.append(node.get("id"))
                patches.append(_patch(f"/outline/sections/{node.get('id')}", "add", node))
                summary.append(f"新增章节 {node.get('id')}")
            elif op == "rename_section":
                node = builder.rename_section(section_id, operation.get("title", ""))
                affected_ids.append(section_id)
                patches.append(_patch(f"/outline/sections/{section_id}/title", value=node.get("title")))
                summary.append(f"重命名章节 {section_id}")
            elif op == "update_section_metadata":
                node = builder.update_section_metadata(
                    section_id, purpose=operation.get("purpose"),
                    objective_ids=operation.get("objective_ids"),
                    knowledge_point_ids=operation.get("knowledge_point_ids"),
                )
                affected_ids.append(section_id)
                if operation.get("purpose") is not None:
                    patches.append(_patch(f"/outline/sections/{section_id}/purpose", value=node.get("purpose")))
                if operation.get("objective_ids") is not None:
                    patches.append(_patch(f"/outline/sections/{section_id}/objective_ids", value=node.get("objective_ids")))
                if operation.get("knowledge_point_ids") is not None:
                    patches.append(_patch(f"/outline/sections/{section_id}/knowledge_point_ids", value=node.get("knowledge_point_ids")))
                summary.append(f"更新章节元数据 {section_id}")
            elif op == "move_section":
                node = builder.move_section(section_id, to_sequence=int(operation.get("to_sequence", 1)))
                affected_ids.append(section_id)
                patches.append(_patch(f"/outline/sections/{section_id}/sequence", value=node.get("sequence")))
                summary.append(f"移动章节 {section_id} 到第 {node.get('sequence')} 位")
            elif op == "merge_sections":
                merged = builder.merge_sections(section_id, operation.get("absorbed_section_id", ""))
                affected_ids.extend([section_id, operation.get("absorbed_section_id", "")])
                patches.append(_patch(f"/outline/sections/{operation.get('absorbed_section_id')}", "remove"))
                patches.append(_patch(f"/outline/sections/{section_id}", "replace", merged))
                summary.append(f"合并章节 {operation.get('absorbed_section_id')} 到 {section_id}")
            elif op == "delete_section":
                deleted = builder.delete_section(section_id, move_scenes_to=operation.get("move_scenes_to"))
                affected_ids.append(section_id)
                patches.append(_patch(f"/outline/sections/{section_id}", "remove"))
                summary.append(f"删除章节 {section_id}")
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True,
            "summary": "；".join(summary),
            "affected_section_ids": sorted(set(affected_ids)),
            "before_revision": before_revision, "after_revision": revision, "revision": revision,
            "patch": patches,
            "section_count": builder.count_sections(),
            "scene_count": builder.count_scenes(),
        })
    except Exception as exc:  # noqa: BLE001
        builder.restore(before, before_revision)
        return ToolResult(ok=False, error=f"章节操作失败：{str(exc)[:300]}", error_code="outline_op_failed", retryable=True)


def _register_outline_tools() -> None:
    register_tool(Tool("vs_apply_outline_ops", "原子章节操作：新增/重命名/更新元数据/移动/合并/删除章节",
                       ApplyVideoScriptOutlineOpsInput, _vs_apply_outline_ops))
