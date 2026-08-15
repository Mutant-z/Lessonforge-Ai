"""视频脚本工具集：分镜编辑工具。

只修改内存中的 VideoScriptBuilder 候选稿。分镜拆分必须保持完整语句；
时间重平衡优先保留锁定分镜与教师明确指定时长。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agent.agents.video_script.tools.outline_tools import _lock_guard, _patch
from app.agent.agents.video_script.tools.read_tools import _builder
from app.agent.registry import Tool, ToolContext, ToolResult, register_tool

SCENE_OPS = {"add_scene", "update_scene", "move_scene", "split_scene", "merge_scenes", "delete_scene"}


class ApplyVideoScriptSceneOpsInput(BaseModel):
    operations: list[dict[str, Any]] = Field(min_length=1, description="原子分镜操作列表，顺序执行")

    @model_validator(mode="before")
    @classmethod
    def validate_ops(cls, value):
        for operation in value.get("operations", []):
            if operation.get("op") not in SCENE_OPS:
                raise ValueError(f"不支持的分镜操作：{operation.get('op')}")
        return value


async def _vs_apply_scene_ops(tc: ToolContext, inp: ApplyVideoScriptSceneOpsInput) -> ToolResult:
    _lock_guard(tc)
    builder = _builder(tc)
    affected_ids: list[str] = []
    patches: list[dict[str, Any]] = []
    summary: list[str] = []
    try:
        for operation in inp.operations:
            op = operation.get("op")
            scene_id = operation.get("scene_id")
            if op == "add_scene":
                scene = operation.get("scene") or {}
                added = builder.add_scene(operation.get("section_id", ""), scene)
                affected_ids.append(added.get("id"))
                patches.append(_patch(f"/scenes/{added.get('id')}", "add", added))
                summary.append(f"新增分镜 {added.get('id')}")
            elif op == "update_scene":
                patch = operation.get("patch") or {}
                if not patch:
                    raise ValueError("update_scene 缺少 patch")
                updated = builder.update_scene(scene_id, patch)
                affected_ids.append(scene_id)
                for key in patch:
                    if key == "duration_seconds":
                        continue
                    patches.append(_patch(f"/scenes/{scene_id}/{key}", value=updated.get(key)))
                summary.append(f"更新分镜 {scene_id}")
            elif op == "move_scene":
                moved = builder.move_scene(scene_id, operation.get("section_id", ""), index=operation.get("index"))
                affected_ids.append(scene_id)
                patches.append(_patch(f"/scenes/{scene_id}/section_id", value=moved.get("section_id")))
                summary.append(f"移动分镜 {scene_id} 到章节 {moved.get('section_id')}")
            elif op == "split_scene":
                new_scene = builder.split_scene(
                    scene_id, split_at_seconds=float(operation.get("split_at_seconds", 0)),
                    new_title=operation.get("new_title", ""), new_spoken_text=operation.get("new_spoken_text", ""),
                )
                affected_ids.extend([scene_id, new_scene.get("id")])
                patches.append(_patch(f"/scenes/{scene_id}/spoken_text", value=builder.find_scene(scene_id).get("spoken_text")))
                patches.append(_patch(f"/scenes/{new_scene.get('id')}", "add", new_scene))
                summary.append(f"拆分分镜 {scene_id} → {new_scene.get('id')}")
            elif op == "merge_scenes":
                merged = builder.merge_scenes(
                    list(operation.get("scene_ids") or []),
                    title=operation.get("title", ""), spoken_text=operation.get("spoken_text", ""),
                )
                affected_ids.append(merged.get("id"))
                for removed in (operation.get("scene_ids") or [])[1:]:
                    patches.append(_patch(f"/scenes/{removed}", "remove"))
                patches.append(_patch(f"/scenes/{merged.get('id')}", "replace", merged))
                summary.append(f"合并分镜 {operation.get('scene_ids')} → {merged.get('id')}")
            elif op == "delete_scene":
                deleted = builder.delete_scene(scene_id)
                affected_ids.append(scene_id)
                patches.append(_patch(f"/scenes/{scene_id}", "remove"))
                summary.append(f"删除分镜 {scene_id}")
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True,
            "summary": "；".join(summary),
            "affected_scene_ids": sorted(set(affected_ids)),
            "revision": revision,
            "patch": patches,
            "scene_count": builder.count_scenes(),
            "target_duration_seconds": builder.target_duration_seconds,
        })
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"分镜操作失败：{str(exc)[:300]}", error_code="scene_op_failed", retryable=True)


class RewriteSpokenTextInput(BaseModel):
    scene_id: str = Field(min_length=1)
    spoken_text: str = Field(min_length=1, max_length=3000)


async def _vs_rewrite_spoken_text(tc: ToolContext, inp: RewriteSpokenTextInput) -> ToolResult:
    """重写单个分镜口播；必需事实基准随新口播同步校验。"""
    _lock_guard(tc)
    builder = _builder(tc)
    try:
        node = builder.rewrite_spoken_text(inp.scene_id, inp.spoken_text)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": f"重写分镜 {inp.scene_id} 口播",
            "affected_scene_ids": [inp.scene_id], "revision": revision,
            "patch": [_patch(f"/scenes/{inp.scene_id}/spoken_text", value=node.get("spoken_text"))],
        })
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"口播重写失败：{str(exc)[:300]}", error_code="rewrite_failed", retryable=True)


class UpdateVisualDirectionInput(BaseModel):
    scene_id: str = Field(min_length=1)
    visual_prompt: str = Field(min_length=1, max_length=6000)
    camera_beats: list[dict[str, Any]] | None = None


async def _vs_update_visual_direction(tc: ToolContext, inp: UpdateVisualDirectionInput) -> ToolResult:
    """重写单个分镜的画面提示词与镜头节拍。"""
    _lock_guard(tc)
    builder = _builder(tc)
    try:
        node = builder.update_visual_direction(inp.scene_id, inp.visual_prompt, inp.camera_beats)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": f"更新分镜 {inp.scene_id} 画面与镜头",
            "affected_scene_ids": [inp.scene_id], "revision": revision,
            "patch": [
                _patch(f"/scenes/{inp.scene_id}/visual_prompt", value=node.get("visual_prompt")),
                _patch(f"/scenes/{inp.scene_id}/camera_beats", value=node.get("camera_beats")),
            ],
        })
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"画面更新失败：{str(exc)[:300]}", error_code="visual_update_failed", retryable=True)


class UpdateContinuityInput(BaseModel):
    scene_id: str = Field(min_length=1)
    continuity_group: str = Field(min_length=1, max_length=120)


async def _vs_update_continuity(tc: ToolContext, inp: UpdateContinuityInput) -> ToolResult:
    """调整单个分镜的连续性分组。"""
    _lock_guard(tc)
    builder = _builder(tc)
    try:
        node = builder.update_continuity(inp.scene_id, inp.continuity_group)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": f"更新分镜 {inp.scene_id} 连续性分组",
            "affected_scene_ids": [inp.scene_id], "revision": revision,
            "patch": [_patch(f"/scenes/{inp.scene_id}/continuity_group", value=node.get("continuity_group"))],
        })
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"连续性更新失败：{str(exc)[:300]}", error_code="continuity_update_failed", retryable=True)


class RebalanceTimelineInput(BaseModel):
    durations: dict[str, float] = Field(default_factory=dict, description="教师指定分镜时长（scene_id → 秒，可选）")


async def _vs_rebalance_timeline(tc: ToolContext, inp: RebalanceTimelineInput) -> ToolResult:
    """按口播长度重算时间轴：优先保留锁定分镜与指定时长，总时长守恒、每段 4–15 秒。"""
    _lock_guard(tc)
    builder = _builder(tc)
    try:
        result = builder.rebalance_timeline(durations=inp.durations)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": "已重平衡分镜时间轴",
            "revision": revision,
            "timeline": result.get("scenes"),
            "target_duration_seconds": result.get("target_duration_seconds"),
            "patch": [_patch("/scenes", "replace", [
                {"id": scene.get("id"), "start_seconds": scene.get("start_seconds"), "end_seconds": scene.get("end_seconds")}
                for scene in result.get("scenes", [])
            ])],
        })
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"时间轴重平衡失败：{str(exc)[:300]}", error_code="rebalance_failed", retryable=True)


def _register_scene_tools() -> None:
    register_tool(Tool("vs_apply_scene_ops", "原子分镜操作：新增/更新/移动/拆分/合并/删除分镜",
                       ApplyVideoScriptSceneOpsInput, _vs_apply_scene_ops))
    register_tool(Tool("vs_rewrite_spoken_text", "重写单个分镜口播并同步事实基准",
                       RewriteSpokenTextInput, _vs_rewrite_spoken_text))
    register_tool(Tool("vs_update_visual_direction", "更新单个分镜画面提示词与镜头节拍",
                       UpdateVisualDirectionInput, _vs_update_visual_direction))
    register_tool(Tool("vs_update_continuity", "调整单个分镜连续性分组",
                       UpdateContinuityInput, _vs_update_continuity))
    register_tool(Tool("vs_rebalance_timeline", "按口播长度重算时间轴（保留锁定与指定时长）",
                       RebalanceTimelineInput, _vs_rebalance_timeline))
