---
name: ppt-template-analysis
version: 1.0.0
description: 从真实 PPTX 中提取可复用的视觉语言与布局约束。
capabilities:
  - template-analysis
tags:
  - template
  - design-system
priority: 95
inputs_schema: {"type":"object","required":["template_id"]}
outputs_schema: {"type":"object","required":["typography","color_system","layout_patterns"]}
tools_required:
  - inspect_template
constraints:
  - 模板作为设计上下文而非占位容器
estimated_cost: low
---
# PPT Template Analysis

分析主题色、字体、Master、Layout、Shape、留白、装饰节奏和示例页。输出设计规则，不把内容机械映射到 placeholder。

