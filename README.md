# 课启智造 LessonForge AI

面向教师的多 Agent 教学微课 AI 开发平台。教师通过自然语言和参考材料与需求 Agent 对话，核对结构化需求后确认统一课程蓝图；随后由 LangGraph 工作流生成教学设计、PPT、学习任务单、课后练习、视频脚本和教师逐字稿。资源可在线修改、保存版本、锁定、审核，并导出可编辑 Office 文件与完整 ZIP。

## 本地启动

要求 Python 3.11+、Node.js 20+。

```bash
cp .env.example .env
python3.11 -m venv .venv
.venv/bin/pip install -e './backend[dev]'
cd frontend && npm install && cd ..
./scripts/init_db.sh
./scripts/dev.sh
```

访问前端 `http://localhost:5173`，API 文档 `http://localhost:8000/docs`。首次使用可在登录页注册教师账号。

## Docker Compose

```bash
cp .env.example .env
# 修改 SECRET_KEY；如需真实模型，配置 OPENAI_API_KEY 并设置 LLM_PROVIDER=openai_compatible
docker compose up --build
```

访问 `http://localhost:8080`。SQLite 与上传/导出文件持久化在 `storage/`。

## 验证

```bash
cd backend && ../.venv/bin/pytest -q
cd ../frontend && npm run build
```

## 日常运行脚本

```bash
./scripts/start.sh                 # 后台启动前端和后端
./scripts/stop.sh                  # 优雅关闭前端和后端
./scripts/restart.sh               # 重启全部服务
./scripts/logs.sh                  # 持续查看前后端日志
./scripts/logs.sh backend          # 只看后端日志
./scripts/logs.sh frontend         # 只看前端日志
LOG_FOLLOW=false ./scripts/logs.sh # 只输出最近日志，不持续跟踪
LOG_LINES=300 ./scripts/logs.sh    # 调整初始显示行数
```

PID 与日志保存在项目内的 `.runtime/`，该目录不会提交到 Git。

## 关键目录

- `backend/app/api/v1`：REST 与 SSE API
- `backend/app/workflows`：LangGraph 状态与节点编排
- `backend/app/agents`：各领域 Agent 的结构化生成逻辑
- `backend/app/services/quality_service.py`：确定性质量规则
- `backend/app/renderers`：PPTX、DOCX 与 ZIP 渲染
- `frontend/src/views`：教师端核心页面
- `templates`：内置 Office 模板
- `docs/API.md`、`docs/DATABASE.md`、`docs/WORKFLOW.md`：实现说明

## 模型配置

默认 `LLM_PROVIDER=mock`，用于无密钥本地联调并生成明确的确定性内容。真实模型兼容 OpenAI 风格的 Base URL、API Key 与模型名称。密钥只存在服务端环境变量，不写日志、不返回浏览器。

## MVP 已知边界

- 扫描 PDF 不做 OCR，会返回明确提示。
- 内置 PPT 使用可编辑的确定性版式，不承诺复杂动画。
- 单机长任务由进程内 AsyncIO 执行，状态与产物持久化；多实例生产部署应迁移到 PostgreSQL 与独立 Worker。
- 学校 PPT 母版上传、团队审批、差异视图和 OCR 属于 P1。
