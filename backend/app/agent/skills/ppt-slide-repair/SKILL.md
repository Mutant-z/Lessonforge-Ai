---
name: ppt-slide-repair
version: 1.0.0
description: 根据 QA 问题只修复受影响页面和元素。
capabilities:
  - slide-repair
tags:
  - repair
  - slide
priority: 100
inputs_schema: {"type":"object","required":["issues","slides"]}
outputs_schema: {"type":"object","required":["changes"]}
tools_required:
  - update_slide
constraints:
  - 不得无故重建整套 PPT
estimated_cost: medium
---
# PPT Slide Repair

按 issue 的 slide_id 和 target_agent 定位修改范围，优先最小修复。完成后只重渲染受影响页并再次 QA。

