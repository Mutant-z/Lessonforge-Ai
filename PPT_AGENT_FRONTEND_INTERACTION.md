# PPT Agent Frontend Interaction

左侧为 Conversation、Plan、Agent 摘要、Tool、Skill、Handoff、QA/Repair 与 Composer；右侧为 16:9 主预览、虚拟化页面导航、页面状态、预览/内容/结构、Diff、版本和模板 Gallery。

单击选择当前页，Cmd/Ctrl 支持多选；Composer 自动携带 `selected_slide_ids`。新版本完成前保持旧预览。标准 Event Adapter 负责把后端事件转换为 UI Node；以 `event_id`、`message_id`、`run_id` 去重，绝不按文本去重。

