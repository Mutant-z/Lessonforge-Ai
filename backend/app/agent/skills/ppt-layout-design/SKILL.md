---
name: ppt-layout-design
version: 1.0.0
description: 根据页面内容、相邻页和模板设计动态页面布局。
capabilities:
  - layout-design
tags:
  - grid
  - typography
  - visual-hierarchy
priority: 100
inputs_schema: {"type":"object","required":["slide_content","template_profile"]}
outputs_schema: {"type":"object","required":["elements","visual_focus"]}
tools_required:
  - inspect_slide
constraints:
  - 遵守安全边距与内容密度限制
estimated_cost: medium
---
# PPT Layout Design

先建立视觉焦点和阅读顺序，再确定 Grid、对齐、文本宽度、字号、留白和图像位置。内容过密时应重组或拆页，不通过无限缩小字号解决。

