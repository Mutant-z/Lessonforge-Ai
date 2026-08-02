# 数据库说明

SQLAlchemy 2.x 模型位于 `backend/app/models/entities.py`，初始 Alembic 迁移为 `0001_initial`。SQLite 使用 WAL、外键和 5000ms busy timeout。

核心表：users、course_intake_sessions、course_intake_messages、course_intake_revisions、course_intake_turns、course_intake_events、course_projects、course_requirements、materials、material_chunks、course_blueprints、artifacts、artifact_locks、agent_chat_sessions、agent_messages、generation_runs、generation_steps、generation_events、quality_reports、quality_issues、files、prompt_templates、model_configs。

未确认材料通过 `materials.intake_session_id` 归属于需求会话；确认课程后改为 `course_id`。检查约束保证两种归属不会同时存在。

`model_configs` 使用 `context_window_tokens` 和 `supports_multimodal` 保存人工维护的模型能力元数据。需求会话和课程通过 `model_config_id` 保存默认模型；`agent_chat_sessions` 以 `(course_id, module_type)` 唯一约束保存各模块的独立选择。配置删除时引用置空，并在运行时回退到激活模型或系统默认模型。

UUID 以字符串存储，JSON 不依赖 SQLite 专属查询，便于迁移 PostgreSQL。
