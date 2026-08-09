---
name: teaching-diagram-design
version: 1.0.0
description: 把抽象教学内容转化为清晰的流程图、时间线和关系图。
capabilities:
  - teaching-diagram
tags:
  - diagram
  - visual
priority: 80
inputs_schema: {"type":"object","required":["concepts"]}
outputs_schema: {"type":"object","required":["diagram_spec"]}
tools_required:
  - render_diagram
constraints:
  - 图中节点文字必须简短
estimated_cost: medium
---
# Teaching Diagram Design

选择最符合知识关系的图示类型，限制节点数量，使用明确方向和层级。图示必须帮助解释，而不是装饰页面。

