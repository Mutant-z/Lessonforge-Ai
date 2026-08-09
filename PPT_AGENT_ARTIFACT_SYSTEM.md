# PPT Agent Artifact System

`Artifact` 继续作为课程模块最终版本；`PPTRevision` 记录整套演示版本；`PPTSlideArtifact` 记录页面当前状态；`PPTSlideRevision` 保存页面快照和字段级 Diff。

页面生命周期：`planned → content_generating → layout_generating → asset_generating → building → rendering → qa → repairing → ready/failed`。修改创建新版本，不覆盖旧版本。Graph Checkpoint 仅用于恢复执行位置，不作为领域真相。

