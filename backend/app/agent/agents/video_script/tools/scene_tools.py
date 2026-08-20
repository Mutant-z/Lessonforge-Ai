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
# 允许 LLM 使用简写形式（如 "update" 代替 "update_scene"）
SCENE_OPS_ALIASES = {
    "add": "add_scene",
    "update": "update_scene",
    "move": "move_scene",
    "split": "split_scene",
    "merge": "merge_scenes",
    "delete": "delete_scene",
}


class ApplyVideoScriptSceneOpsInput(BaseModel):
    operations: list[dict[str, Any]] = Field(min_length=1, description="原子分镜操作列表，顺序执行")

    @model_validator(mode="before")
    @classmethod
    def validate_ops(cls, value):
        operations = value.get("operations", [])
        for i, operation in enumerate(operations):
            op = operation.get("op")
            # 规范化简写形式
            if op in SCENE_OPS_ALIASES:
                operations[i]["op"] = SCENE_OPS_ALIASES[op]
                op = operations[i]["op"]
            if op not in SCENE_OPS:
                raise ValueError(f"不支持的分镜操作：{operation.get('op')}")
            # 如果是 update_scene 但 LLM 直接传了字段（而不是嵌套在 patch 里），自动包装
            if op == "update_scene" and "patch" not in operation:
                patch = {k: v for k, v in operation.items() if k not in {"op", "scene_id"}}
                if patch:
                    operations[i]["patch"] = patch
        return value


async def _vs_apply_scene_ops(tc: ToolContext, inp: ApplyVideoScriptSceneOpsInput) -> ToolResult:
    builder = _builder(tc)
    requested_paths = [
        f"$.scenes.{operation.get('scene_id') or 'new'}"
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
            "before_revision": before_revision, "after_revision": revision, "revision": revision,
            "patch": patches,
            "scene_count": builder.count_scenes(),
            "target_duration_seconds": builder.target_duration_seconds,
        })
    except Exception as exc:  # noqa: BLE001
        builder.restore(before, before_revision)
        return ToolResult(ok=False, error=f"分镜操作失败：{str(exc)[:300]}", error_code="scene_op_failed", retryable=True)


class RewriteSpokenTextInput(BaseModel):
    scene_id: str = Field(min_length=1)
    spoken_text: str = Field(min_length=1, max_length=3000)


async def _vs_rewrite_spoken_text(tc: ToolContext, inp: RewriteSpokenTextInput) -> ToolResult:
    """重写单个分镜口播；必需事实基准随新口播同步校验。"""
    _lock_guard(tc, [f"$.scenes.{inp.scene_id}.spoken_text"])
    builder = _builder(tc)
    before = builder.to_content()
    before_revision = builder.revision
    try:
        node = builder.rewrite_spoken_text(inp.scene_id, inp.spoken_text)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": f"重写分镜 {inp.scene_id} 口播",
            "affected_scene_ids": [inp.scene_id],
            "before_revision": before_revision, "after_revision": revision, "revision": revision,
            "patch": [_patch(f"/scenes/{inp.scene_id}/spoken_text", value=node.get("spoken_text"))],
        })
    except Exception as exc:  # noqa: BLE001
        builder.restore(before, before_revision)
        return ToolResult(ok=False, error=f"口播重写失败：{str(exc)[:300]}", error_code="rewrite_failed", retryable=True)


class UpdateVisualDirectionInput(BaseModel):
    scene_id: str = Field(min_length=1)
    visual_prompt: str | None = Field(default=None, min_length=1, max_length=6000)
    camera_beats: list[dict[str, Any]] | None = None
    voice_direction: str | None = Field(default=None, min_length=1, max_length=300)
    sound_design: list[str] | None = None

    @model_validator(mode="after")
    def require_audiovisual_change(self):
        if all(value is None for value in (
            self.visual_prompt, self.camera_beats, self.voice_direction, self.sound_design,
        )):
            raise ValueError("至少提供一项画面或声音修改")
        return self


async def _vs_update_visual_direction(tc: ToolContext, inp: UpdateVisualDirectionInput) -> ToolResult:
    """重写单个分镜的画面提示词与镜头节拍。"""
    requested = [
        f"$.scenes.{inp.scene_id}.{field}"
        for field, value in {
            "visual_prompt": inp.visual_prompt, "camera_beats": inp.camera_beats,
            "voice_direction": inp.voice_direction, "sound_design": inp.sound_design,
        }.items() if value is not None
    ]
    _lock_guard(tc, requested)
    builder = _builder(tc)
    before = builder.to_content()
    before_revision = builder.revision
    try:
        node = builder.update_visual_direction(
            inp.scene_id, inp.visual_prompt, inp.camera_beats, inp.voice_direction, inp.sound_design,
        )
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": f"更新分镜 {inp.scene_id} 画面与镜头",
            "affected_scene_ids": [inp.scene_id],
            "before_revision": before_revision, "after_revision": revision, "revision": revision,
            "patch": [
                _patch(f"/scenes/{inp.scene_id}/{field}", value=node.get(field))
                for field, value in {
                    "visual_prompt": inp.visual_prompt, "camera_beats": inp.camera_beats,
                    "voice_direction": inp.voice_direction, "sound_design": inp.sound_design,
                }.items() if value is not None
            ],
        })
    except Exception as exc:  # noqa: BLE001
        builder.restore(before, before_revision)
        return ToolResult(ok=False, error=f"画面更新失败：{str(exc)[:300]}", error_code="visual_update_failed", retryable=True)


class UpdateContinuityInput(BaseModel):
    scene_id: str = Field(min_length=1)
    continuity_group: str = Field(min_length=1, max_length=120)


async def _vs_update_continuity(tc: ToolContext, inp: UpdateContinuityInput) -> ToolResult:
    """调整单个分镜的连续性分组。"""
    _lock_guard(tc, [f"$.scenes.{inp.scene_id}.continuity_group"])
    builder = _builder(tc)
    before = builder.to_content()
    before_revision = builder.revision
    try:
        node = builder.update_continuity(inp.scene_id, inp.continuity_group)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": f"更新分镜 {inp.scene_id} 连续性分组",
            "affected_scene_ids": [inp.scene_id],
            "before_revision": before_revision, "after_revision": revision, "revision": revision,
            "patch": [_patch(f"/scenes/{inp.scene_id}/continuity_group", value=node.get("continuity_group"))],
        })
    except Exception as exc:  # noqa: BLE001
        builder.restore(before, before_revision)
        return ToolResult(ok=False, error=f"连续性更新失败：{str(exc)[:300]}", error_code="continuity_update_failed", retryable=True)


class RebalanceTimelineInput(BaseModel):
    durations: dict[str, float] = Field(default_factory=dict, description="教师指定分镜时长（scene_id → 秒，可选）")


async def _vs_rebalance_timeline(tc: ToolContext, inp: RebalanceTimelineInput) -> ToolResult:
    """按口播长度重算时间轴：优先保留锁定分镜与指定时长，总时长守恒、每段 4–15 秒。"""
    _lock_guard(tc, ["$.scenes"])
    builder = _builder(tc)
    before = builder.to_content()
    before_revision = builder.revision
    try:
        result = builder.rebalance_timeline(durations=inp.durations)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True, "summary": "已重平衡分镜时间轴",
            "before_revision": before_revision, "after_revision": revision, "revision": revision,
            "timeline": result.get("scenes"),
            "target_duration_seconds": result.get("target_duration_seconds"),
            "patch": [_patch("/scenes", "replace", [
                {"id": scene.get("id"), "start_seconds": scene.get("start_seconds"), "end_seconds": scene.get("end_seconds")}
                for scene in result.get("scenes", [])
            ])],
        })
    except Exception as exc:  # noqa: BLE001
        builder.restore(before, before_revision)
        return ToolResult(ok=False, error=f"时间轴重平衡失败：{str(exc)[:300]}", error_code="rebalance_failed", retryable=True)


class UpdateProductionSettingsInput(BaseModel):
    patch: dict[str, Any] = Field(min_length=1)


async def _vs_update_production_settings(tc: ToolContext, inp: UpdateProductionSettingsInput) -> ToolResult:
    builder = _builder(tc)
    _lock_guard(tc, [f"$.production_settings.{key}" for key in inp.patch])
    before = builder.to_content()
    before_revision = builder.revision
    try:
        settings = builder.update_production_settings(inp.patch)
        revision = builder.bump_revision()
        return ToolResult(output={
            "ok": True,
            "summary": f"更新制作参数：{', '.join(sorted(inp.patch))}",
            "before_revision": before_revision, "after_revision": revision, "revision": revision,
            "patch": [
                _patch(f"/production_settings/{key}", value=settings.get(key))
                for key in inp.patch
            ],
        })
    except Exception as exc:  # noqa: BLE001
        builder.restore(before, before_revision)
        return ToolResult(ok=False, error=f"制作参数更新失败：{str(exc)[:300]}", error_code="settings_update_failed", retryable=True)


def _register_scene_tools() -> None:
    register_tool(Tool("vs_apply_scene_ops", "原子分镜操作：新增/更新/移动/拆分/合并/删除分镜",
                       ApplyVideoScriptSceneOpsInput, _vs_apply_scene_ops))
    register_tool(Tool("vs_rewrite_spoken_text", "重写单个分镜口播并同步事实基准",
                       RewriteSpokenTextInput, _vs_rewrite_spoken_text))
    register_tool(Tool("vs_update_visual_direction", "更新单个分镜画面提示词与镜头节拍",
                       UpdateVisualDirectionInput, _vs_update_visual_direction))
    register_tool(Tool("vs_update_continuity", "调整单个分镜连续性分组",
                       UpdateContinuityInput, _vs_update_continuity))
    register_tool(Tool("vs_update_production_settings", "更新视频比例、目标时长与全局视听风格",
                       UpdateProductionSettingsInput, _vs_update_production_settings))
    register_tool(Tool("vs_rebalance_timeline", "按口播长度重算时间轴（保留锁定与指定时长）",
                       RebalanceTimelineInput, _vs_rebalance_timeline))
