# LessonForge AI 开发进度

更新时间：2026-08-02

## 实施清单与状态

| 阶段 | 状态 | 主要实现 |
|---|---|---|
| 工程骨架、配置、数据库与迁移 | 已完成 | FastAPI/Vue、18 张表、Alembic、SQLite WAL |
| 认证、课程、材料与蓝图 | 已完成 | JWT、数据隔离、CRUD、5 类材料解析、蓝图版本与审核 |
| 多 Agent、资源、SSE 与质量 | 已完成 | 两段 LangGraph、Supervisor、8 类 Artifact、对话、版本、锁定、规则 QA |
| 文件渲染与导出 | 已完成 | 可编辑 PPTX/DOCX、Markdown/JSON、ZIP、manifest/SHA256 |
| Vue 教师工作台 | 已完成 | 登录、总览、向导、蓝图、运行中心、8 标签资源台、导出、设置 |
| 测试、Docker 与验收 | 已完成 | 9 项后端测试、前端构建、迁移与 Compose 配置校验 |

## 已完成模块

- 完整阅读并按 `功能需求规格说明书 → 多 Agent 技术方案 → 项目背景` 的优先级实现。
- 用户注册/登录、Argon2 密码哈希、JWT、课程级权限隔离。
- 课程创建、列表、搜索筛选、修改、软删除、复制和归档。
- PDF、DOCX、PPTX、TXT、Markdown 文件安全上传、解析、分块、摘要、用途策略与扫描 PDF 提示。
- CourseBlueprintSchema、结构化目标/知识点/时间线/评价、版本、编辑、退回、锁定与确认门禁。
- Requirement、Material、Pedagogy Blueprint、Supervisor、Lesson Plan、PPT、Task Sheet、Exercise、Video Script、Verbatim、QA 和返工路由节点。
- LangGraph 状态图、并行资源分支、依赖串联、事件落库、SSE、短期事件流令牌、取消与终审继续。
- 8 类 Artifact、在线 Markdown 编辑、新版本、历史、局部重生成、路径锁定、审核与模块专属对话。
- 确定性质量检查：时长、ID、目标覆盖、页面引用、题目结构、选项、语速字数等。
- OpenAI-compatible Provider、超时、Tenacity 重试、结构化输出与 Mock Provider；教师 API Key 加密落库且不回显。
- PPTX、DOCX、ZIP、manifest 与 SHA256 渲染校验，内置 Office 模板。
- Dockerfile、Compose、环境示例、开发/迁移脚本、API/数据库/工作流文档。
- 后台启动、优雅关闭、重启和聚合日志脚本；PID/日志统一保存在 `.runtime/`。
- 公开首页与按需登录门禁：访客可浏览主页面，只有课程、生成、导出和设置等服务需要登录。

## 已知问题与限制

- 当前机器 Docker daemon 未运行，因此完成了 Compose 配置校验，但未能在本机实际构建镜像。
- 扫描 PDF OCR、学校 PPT 母版解析、团队审批、富文本块级差异、提词器、成本面板属于 P1/P2，MVP 未实现。
- MVP 为单进程 AsyncIO 长任务；运行、步骤、事件与产物会持久化，但多实例和自动跨进程续跑需迁移独立 Worker。
- 前端构建提示主包大于 500 kB，是 Element Plus 体积警告，不影响构建产物运行。
- LangGraph 依赖产生一条未来默认值变更警告，不影响当前测试。

## 测试结果

- 后端：`9 passed`，覆盖认证、权限隔离、课程 CRUD、模型密钥不回显、Schema/时长/覆盖规则、文件名、LangGraph、返工上限、PPTX、DOCX、ZIP、完整 API 链路。
- 前端：`vue-tsc -b && vite build` 成功。
- 数据库：Alembic `0001_initial` 执行成功，创建 18 张表。
- Docker：`docker compose config --quiet` 成功；镜像构建因本机 Docker daemon 未运行而未执行。
- 运维脚本：完成启动、健康检查、重启、日志读取、关闭和端口释放的真实流程验证。
- 访客访问：浏览器验证公开首页直接打开、服务入口跳转登录并携带原目标、登录页可返回首页，控制台无错误。

## 重要技术决策

- 课程蓝图是六类核心资源的唯一事实源，未确认蓝图不能启动资源生成。
- 模型仅产出 Pydantic 结构化内容，Office 文件由确定性 Renderer 生成。
- 二进制材料由 Python 解析，材料内容被标记为 reference data，不能覆盖系统指令。
- SSE 使用 5 分钟、绑定 run_id 和用户的专用令牌，不把长期 JWT 暴露给事件流。
- 模型 API Key 使用由服务端 SECRET_KEY 派生的 Fernet 密钥加密，接口只返回配置状态。
- 同一 QA 定向返工最多两次，之后进入教师人工处理。
