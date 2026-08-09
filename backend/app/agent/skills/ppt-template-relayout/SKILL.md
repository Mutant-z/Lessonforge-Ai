---
name: ppt-template-relayout
version: 1.0.0
description: 在保留内容和资源的前提下适配新模板并重新布局。
capabilities:
  - template-relayout
tags:
  - template
  - layout
priority: 95
inputs_schema: {"type":"object","required":["slides","template_profile"]}
outputs_schema: {"type":"object","required":["slide_layouts"]}
tools_required:
  - inspect_template
constraints:
  - 必须创建新版本并保留旧版本
estimated_cost: high
---
# PPT Template Relayout

保留教学结构、确认内容、图表数据和可复用资源，重新计算布局、字体、色彩、间距和视觉层级。不得只替换 theme 字段。

