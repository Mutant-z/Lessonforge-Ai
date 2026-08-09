---
name: ppt-visual-qa
version: 1.0.0
description: 检查页面几何、溢出、重叠、对比度和视觉一致性。
capabilities:
  - visual-qa
tags:
  - qa
  - render
priority: 100
inputs_schema: {"type":"object","required":["slides"]}
outputs_schema: {"type":"object","required":["issues","score"]}
tools_required:
  - inspect_geometry
constraints:
  - 每个问题必须定位到 slide_id
estimated_cost: low
---
# PPT Visual QA

先用确定性几何规则检查，再在真实渲染可用时检查裁剪、对比度和视觉层级。问题按 critical、major、minor 分级并给出目标修复 Agent。

