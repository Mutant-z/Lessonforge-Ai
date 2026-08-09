---
name: ppt-content-qa
version: 1.0.0
description: 检查教学目标覆盖、内容一致性、重复和页面密度。
capabilities:
  - content-qa
tags:
  - qa
  - education
priority: 90
inputs_schema: {"type":"object","required":["slides","course_context"]}
outputs_schema: {"type":"object","required":["issues","coverage"]}
tools_required:
  - check_ppt_against_knowledge
constraints:
  - 不擅自改变教师确认事实
estimated_cost: medium
---
# PPT Content QA

对照课程目标和来源材料检查事实、覆盖、重复、难度和密度。内容问题与视觉问题分开记录，并明确建议修改的页面。

