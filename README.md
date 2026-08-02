# 🎓 LessonForge AI - 教学微课多 Agent 智能开发平台

> **LessonForge AI** 是一款面向教师与教育工作者的**项目式智能微课开发平台**。
> 平台采用 **Master Agent 总控初始化 + 多子 Agent 驻留微调** 架构，以“课程蓝图”为唯一事实源，解决大模型生成教学资源脱节、超纲与样式混乱问题。

---

## 🌟 核心亮点

- 🗂️ **项目式服务管理**：以独立课程项目为单位管理上下文，支持全生命周期版本追踪。
- 🤖 **Master-Agent 总控**：输入一句话/参考资料，Master Agent 自动生成课程大纲并智能初始化各个专属子 Agent。
- 🖥️ **三栏交互工作台**：左侧项目管理 + 顶部模块 Tab + 中间专属 Agent 增量对话 + 右侧文件/PPT 实时预览。
- 📦 **6+2 资源一键打包**：一键导出结构对齐的教学设计 (.docx)、PPT 课件 (.pptx)、学习任务单、课后练习、视频脚本、教师逐字稿及 ZIP 全套资源包。

---

## 📁 目录结构

```text
LessonForge AI/
├── docs/                      # 架构设计与需求文档
│   ├── 01_项目背景与建设分析.md
│   ├── 02_功能需求规格说明书.md
│   └── 03_多Agent技术开发方案.md
├── .gitignore
└── README.md
```

---

## 🛠️ 技术栈

- **后端**: Python 3.11+, FastAPI, LangChain, LangGraph, SQLite (SQLAlchemy + Alembic)
- **前端**: Vue 3 / React, SSE (Server-Sent Events), Tailwind CSS
- **文件渲染**: `python-pptx`, `python-docx`

---

## 📄 文档索引

关于详细的设计规范与架构方案，请参阅 `/docs` 目录：
1. [01_项目背景与建设分析](./docs/01_项目背景与建设分析.md)
2. [02_功能需求规格说明书](./docs/02_功能需求规格说明书.md)
3. [03_多Agent技术开发方案](./docs/03_多Agent技术开发方案.md)
