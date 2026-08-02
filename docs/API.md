# LessonForge AI API

基础路径为 `/api/v1`，OpenAPI 页面为 `/docs`。

- `POST /auth/register`、`POST /auth/login`、`GET /auth/me`
- `/courses`：创建、列表、详情、修改、软删除、复制、归档
- `/course-intakes`：创建持久化需求会话、对话抽取、需求卡修正、会话材料和确认转换
- `/course-intakes/turns/{id}/events`：需求 Agent 的真实流式回复与需求快照事件
- `/courses/{id}/materials`：上传与解析参考材料
- `/courses/{id}/blueprint/generate`、`/blueprints/{id}/approve`：蓝图生成与审核
- `/courses/{id}/generations`、`/generations/{id}/events`：启动工作流与 SSE
- `/courses/{id}/artifacts`、`/artifacts/{id}`：资源、版本、锁定、局部重生成与审核
- `/courses/{id}/quality/latest`：质量报告
- `/courses/{id}/exports`：渲染并打包课程资源
- `/settings`、`/settings/models`：模型端点、上下文窗口、多模态能力和默认模型管理；API Key 永不返回前端
- `/courses/{id}/modules/{module}/chat/*`：模块 Agent 历史、会话模型选择和结构化产物修订

除注册、登录、健康检查外，请使用 `Authorization: Bearer <token>`。

## 对话式创建课程

1. `POST /course-intakes` 创建一个不会出现在课程列表中的需求会话，可通过 `model_config_id` 指定已配置模型。
2. `POST /course-intakes/{id}/materials` 上传会话材料。
3. `POST /course-intakes/{id}/messages` 提交自然语言需求，响应包含 `turn_id`。
4. 通过 `POST /course-intakes/turns/{turn_id}/stream-token` 与 `GET /course-intakes/turns/{turn_id}/events` 接收分析和回复事件。
5. 使用 `PATCH /course-intakes/{id}/draft` 精确修正单个字段。
6. 使用 `PATCH /course-intakes/{id}/model` 在 Agent 空闲时切换会话模型。
7. `POST /course-intakes/{id}/confirm` 原子创建课程、继承模型选择、迁移材料并返回后台蓝图任务 `run_id`。

消息、字段修正和确认均需携带当前 `expected_revision`。确认还需提供客户端持久化的 `idempotency_key`。

模块 Agent 的历史接口返回 `{ messages, model_config_id }`。模型选择按课程模块独立保存；真实模型输出必须通过对应产物 Schema、锁定路径和报告事实约束后才创建新版本。
