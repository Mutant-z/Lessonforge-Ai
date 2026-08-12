---
name: ppt-layout-design
version: 2.0.0
description: 根据页面内容、相邻页和模板设计动态页面布局，并保证空间分布合理。
capabilities:
  - layout-design
tags:
  - grid
  - typography
  - visual-hierarchy
  - whitespace
priority: 100
inputs_schema: {"type":"object","required":["slide_content","template_profile"]}
outputs_schema: {"type":"object","required":["elements","visual_focus"]}
tools_required:
  - inspect_slide
constraints:
  - 遵守安全边距与内容密度限制
  - 正文列必须纵向铺满内容区，禁止把所有文字挤在一角
estimated_cost: medium
---
# PPT Layout Design

先建立视觉焦点和阅读顺序，再确定 Grid、对齐、文本宽度、字号、留白和图像位置。内容过密时应重组或拆页，不通过无限缩小字号解决。

## 空间分布硬约束

- 画布 13.333 × 7.5 英寸。内容页标题固定在顶部（y≈0.55），正文列从 y≈1.7 起。
- 正文列必须覆盖至少 45% 的内容列高度：正文应纵向延伸到 y≈5.0 以上，不得把全部文字堆在页面一角。
- 正文条目逐条独立成框，条间距 ≥0.3 英寸，允许把剩余空白平均摊到条间距上以铺满整列。
- 正文列宽度应覆盖安全边距到右侧视觉槽的完整区间；禁止把文字压成窄条。
- 图片放在右侧安全槽位（x≥7.0、y≥1.7），与标题/正文至少保持 0.3 英寸间距。
- 不要用大空白装饰形状占位；页面空间应由文字与图片真实利用。

## 反模式

- 所有文本框使用相同或接近的坐标 → 文字叠成一团。
- 文字全部集中在左上角，下方/右侧大片空白。
- 用巨型形状填充页面制造“有内容”的错觉。
