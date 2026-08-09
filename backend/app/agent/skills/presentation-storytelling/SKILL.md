---
name: presentation-storytelling
version: 1.0.0
description: 将课程内容组织成有节奏的教学演示叙事。
capabilities:
  - storytelling
tags:
  - presentation
  - education
priority: 90
inputs_schema: {"type":"object","required":["course_context"]}
outputs_schema: {"type":"object","required":["slides"]}
tools_required:
  - get_upstream_artifacts
constraints:
  - 保持教学目标与事实不变
estimated_cost: medium
---
# Presentation Storytelling

先确定学习者、时长、目标和教学节奏，再规划开场、解释、练习、反馈和总结。每页只承担一个清晰教学任务，并为相邻页面建立自然过渡。

