# PPT Agent Skill System

Skill 位于 `backend/app/agent/skills/<name>/SKILL.md`。Registry 启动时只读取 YAML metadata；Orchestrator 根据 capability/tag 发现候选，选中后才加载正文并写入上下文。

首批 Skill：storytelling、template analysis、layout design、teaching diagram、visual QA、content QA、template relayout、slide repair。Skill 描述“如何完成复杂任务”，Tool 描述“执行哪个原子动作”，二者不得混用。

