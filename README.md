# 课启智造 LessonForge AI

面向教师与教学团队的高效多 Agent 教学微课 AI 智能开发平台。教师只需输入课程意图或上传参考资料，系统即可通过多 Agent 协同工作流生成符合教学规范的全套课程资源（教学设计、PPT 课件、学习任务单、课后练习、视频脚本与教师逐字稿）。资源支持可视化渲染、在线编辑修改、版本管理、质量审核以及一键导出可编辑的 Office 文件（.pptx / .docx）和整包 ZIP。

---

## 🌟 现阶段项目整体情况总结

项目已全面完成从**多 Agent 工作流编排、后端 API 引擎、全套渲染导出工具链**到**前端响应式三栏工作台**的全栈开发与联调，并通过了自动化测试与构建校验。

### 1. 核心架构与技术栈

| 模块 | 技术栈 | 核心功能与职责 |
| :--- | :--- | :--- |
| **Backend** | Python 3.12, FastAPI, LangGraph, SQLAlchemy, Alembic, Pydantic v2 | - 基于 LangGraph 实现多 Agent 状态机编排<br>- 提供 RESTful & SSE 流式实时响应接口<br>- JWT 身份认证、密码哈希与权限隔离<br>- 内置确定性教学质量检查规则引擎 |
| **Frontend** | Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS / Design System | - 响应式多视角界面（控制台、需求对话、制作工作台、导出中心、设置）<br>- 支持 SSE 流式传输与 Agent 思考推理打字机呈现<br>- 三栏式课程项目编辑器，支持构件在线微调与锁版 |
| **Renderers** | `python-docx`, `python-pptx`, Zipfile | - 负责将 Agent 生成的结构化 JSON/Markdown 转为符合排版标准的 Office 格式文件与 Zip 打包 |
| **Infrastructure** | Docker Compose, Shell Scripts, SQLite | - 支持开箱即用的本地开发与 Docker 单机一键部署<br>- 完善的服务生命周期管理脚本 (`scripts/`) |

### 2. 主要功能特性

- 🤖 **需求智能抽取 (Intake Agent)**: 支持自然语言对话与参考资料上传，智能提取课程基本信息、教学目标、课时规划及学习者分析。
- 📋 **统一课程蓝图 (Blueprint)**: 自动生成标准化课程蓝图，确保后端各内容生成 Agent 在统一的教学逻辑约束下协同工作。
- ⚡ **多 Agent 并行生成 (Generators)**:
  - **教学设计 (Lesson Plan)**: 包含教学重难点、教学环节分配与互动设计。
  - **PPT 课件 (Slide Draft)**: 包含页面大纲、视觉元素建议与逐页演讲备注。
  - **学习任务单 (Task Sheet)**: 包含自主学习引导、任务要求与完成标准。
  - **课后练习 (Exercises)**: 包含单选/多选/问答题及详细解析与考查意图。
  - **视频脚本 (Video Script)**: 包含分镜镜头、画面描述与配音脚本。
  - **教师逐字稿 (Teacher Script)**: 包含完整讲授脚本与互动提示。
- 🔍 **确定性质量规则检测 (Quality Engine)**: 校验教学重难点覆盖率、习题难度梯度、课件字数与格式规范，提供智能修改建议。
- 📦 **多格式导出与模板定制 (Export Engine)**: 一键生成可编辑 `.pptx` 与 `.docx` 格式文档，提供瑞士蓝与标准排版模板。
- ⚙️ **灵活的大模型接入 (LLM Router)**:
  - 内置 `mock` 模式：无需 API Key 即可进行完整业务闭环测试。
  - 支持 `openai_compatible` / `anthropic` 等主流大模型服务商配置，支持自定义 Base URL、模型名称与 API Key。

---

## 🚀 快速开始

### 环境准备
- **Python**: 3.11+
- **Node.js**: 20+

### 1. 本地开发启动

```bash
# 1. 复制环境变量文件
cp .env.example .env

# 2. 创建并激活 Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # macOS / Linux

# 3. 安装后端依赖
pip install -e './backend[dev]'

# 4. 安装前端依赖
cd frontend && npm install && cd ..

# 5. 初始化 SQLite 数据库及 Migration
./scripts/init_db.sh

# 6. 一键启动前后端开发服务
./scripts/dev.sh
```

- **前端访问地址**: `http://localhost:5173`
- **后端 Swagger API 文档**: `http://localhost:8000/docs`
- 首次使用可以在前端登录页面注册教师账号。

---

## 🐳 Docker Compose 一键部署

```bash
cp .env.example .env
# 可根据需要修改 .env 中的 SECRET_KEY 和 LLM_PROVIDER 参数
docker compose up --build -d
```

- **应用访问地址**: `http://localhost:8080`
- 数据库与生成文件会自动持久化在本地的 `storage/` 目录下。

---

## 🛠️ 项目管理与运维脚本

项目根目录下提供了全套管理脚本，用于便捷操控前后端服务：

```bash
./scripts/start.sh                 # 后台启动前端和后端服务
./scripts/stop.sh                  # 优雅停止前端和后端服务
./scripts/restart.sh               # 重启前后端服务
./scripts/logs.sh                  # 实时查看前后端融合日志
./scripts/logs.sh backend          # 仅查看后端日志
./scripts/logs.sh frontend         # 仅查看前端日志
LOG_FOLLOW=false ./scripts/logs.sh # 仅输出最近日志（非持续跟踪）
LOG_LINES=300 ./scripts/logs.sh    # 指定初始日志显示行数
```

---

## 🧪 自动化测试与校验

在提交代码或发布前，可运行以下命令验证代码质量：

```bash
# 运行后端单元测试与集成测试
cd backend && ../.venv/bin/pytest -q

# 运行前端类型检查与生产环境打包
cd ../frontend && npm run build
```

---

## 📂 项目目录结构概览

```text
LessonForge AI/
├── backend/                  # FastAPI 后端服务
│   ├── alembic/              # 数据库迁移脚本
│   ├── app/
│   │   ├── agents/           # 领域 Agent 结构化生成逻辑
│   │   ├── api/v1/           # RESTful API & SSE 端点
│   │   ├── core/             # 配置、数据库与安全逻辑
│   │   ├── models/           # SQLAlchemy 实体模型
│   │   ├── providers/llm/    # LLM Router 与多提供商适配器
│   │   ├── renderers/        # PPTX / DOCX / ZIP 渲染器
│   │   ├── schemas/          # Pydantic Schema 校验
│   │   ├── services/         # 业务逻辑服务层
│   │   └── workflows/        # LangGraph 状态机与工作流图
│   └── tests/                # 后端自动化测试集
├── frontend/                 # Vue 3 前端应用
│   ├── src/
│   │   ├── api/              # API 请求客户端
│   │   ├── components/       # 业务组件 (Agent、Domain、Intake、Layout等)
│   │   ├── composables/      # 组合式函数 (流式响应处理等)
│   │   ├── stores/           # Pinia 状态管理
│   │   ├── types/            # TypeScript 类型定义
│   │   └── views/            # 页面视图
├── docs/                     # 详细技术文档 (API, DATABASE, WORKFLOW)
├── scripts/                  # 项目构建与运行运维脚本
├── templates/                # DOCX 与 PPTX 导出样式模板
├── docker-compose.yml        # Docker Compose 编排文件
└── README.md                 # 项目说明文档
```

---

## 📌 MVP 当前范围与后续规划

### 当前 MVP 范围
- 扫描版 PDF 文件不进行强制 OCR 提取，上传时会返回友情提示。
- 内置 PPT 导出采用结构清晰、排版规范的默认版式，暂不包含复杂图层动画。
- 异步长任务由 AsyncIO 在进程内执行，数据库状态与生成产物实现本地持久化。

### 未来规划 (P1 / P2)
- 引入 OCR 识别支持扫描件解析。
- 支持学校自定义 PPTX 母版上传与主题匹配。
- 增加协同审批、差异对比视图 (Diff View) 与多版本融合功能。
