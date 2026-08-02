# 课启智造 LessonForge AI — 前端视觉、交互与多 Agent 流式体验重构设计规范

**规范文档版本**: 1.0.0  
**日期**: 2026-08-02  
**状态**: Approved  

---

## 1. 概述与设计目标

课启智造 LessonForge AI 是一套面向教育领域的 AI 辅助教学微课开发平台。本规范旨在将前端从“功能基础可用的开发原型”全方位提升为“现代教育科技 SaaS 产品”。重构包含静态视觉系统、动态交互与反馈机制、多 Agent 真实流式输出引擎及 8 大教学领域专用渲染器。

---

## 2. 静态视觉层与设计系统 (Design System)

### 2.1 CSS Tokens 与主题变量
基于 HSL 规范定义系统 Token，统一管理于 `src/assets/design-system.css`：
- **Primary Color**: `#4f46e5` (AI Indigo)
- **Secondary Color**: `#0284c7` (Educational Sky Blue)
- **Agent Accent Color**: `#7c3aed` (Agent Purple)
- **Status Colors**: Success (`#16a34a`), Warning (`#d97706`), Danger (`#dc2626`), Info (`#2563eb`)
- **Surfaces & Glass**: `--bg-page: #f8fafc`, `--bg-surface: #ffffff`, `--bg-glass: rgba(255, 255, 255, 0.85)`
- **Radii & Shadows**: `sm: 6px`, `md: 10px`, `lg: 14px`, `xl: 20px`, `floating: 0 20px 25px -5px rgba(15, 23, 42, 0.1)`

### 2.2 响应式 App 布局框架
- **AppSidebar (`src/components/layout/AppSidebar.vue`)**:
  - 支持 240px 展开态与 72px 折叠态。
  - 具备 Logo、快捷新建课程按钮、导航组高亮与折叠状态持久化记忆。
- **AppHeader (`src/components/layout/AppHeader.vue`)**:
  - 提供动态面包屑导航。
  - 集成全局运行中后台 Agent 任务指示器与 TaskCenter 抽屉触发器。
- **TaskCenterDrawer (`src/components/layout/TaskCenterDrawer.vue`)**:
  - 全局抽屉式任务监视中心，可跨页面监视、暂停、重试或跳转正在运行的 Agent 任务。

---

## 3. 动态交互与全状态机制 (Dynamic Interaction & States)

### 3.1 页面过渡与微动效
- `src/assets/animations.css` 提供淡入、平移缩放、呼吸光晕 (`pulse-glow`) 及流式打字光标 (`streaming-cursor`)。
- 全面适配 `@media (prefers-reduced-motion: reduce)`，主动禁用非必要的大幅度平移动画。

### 3.2 全状态组件
- **EmptyState (`src/components/feedback/EmptyState.vue`)**: 用于无课程、无任务或空搜索时的引导插图与行动按钮。
- **ErrorState (`src/components/feedback/ErrorState.vue`)**: 友情提示错误原因、保留当前内容进度并提供重试手势。
- **Skeleton屏**: 提供对应课程卡片、时间线及 PPT 画布真实尺寸的渐变骨架加载占位。

---

## 4. Agent 运行与流式输出基础设施 (Agent Streaming Pipeline)

### 4.1 SSE 通讯与字符缓冲队列
- **`agentEventAdapter.ts`**: 负责将服务端原始 SSE 事件归一化为标准的 `AgentStreamEvent` 结构。
- **`streamBuffer.ts`**: 采用 `requestAnimationFrame` 驱动的 Token 字符缓冲队列，消除高频 DOM 抖动，按 Sequence 序号去重。
- **`useAgentStream.ts`**: Composables 接入层，支持指数退避算法自动重连 (`connecting` -> `connected` -> `reconnecting` -> `failed`)。

### 4.2 智能跟随滚动
- **`useAutoScroll.ts`**:
  - 当教师处于容器底部时自动开启 Stream 跟随。
  - 当教师主动向上查阅历史生成时自动挂起滚动，并浮现“回到最新输出”交互按钮。

---

## 5. 多格式内容渲染中心 (ContentBlockRenderer Registry)

通过 `ContentBlockRenderer.vue` 调度中心处理 Agent 吐出的多样化数据结构：
1. **MarkdownRenderer.vue**: 支持 GFM 语法、KaTeX 行内/块级数学公式解析。
2. **CodeBlockRenderer.vue**: Highlight.js 语法高亮与一键复制代码。
3. **JsonTreeRenderer.vue / YamlRenderer.vue**: JSON/YAML 结构化树视图。
4. **MermaidRenderer.vue**: Mermaid 流程图/架构图渲染与语法未闭合容错。
5. **ResponsiveTable.vue**: 响应式横向滚动表格，支持一键导出 CSV。
6. **FileOutputCard.vue / CitationCard.vue**: 产物文件卡片与语料来源卡片。

---

## 6. 8 大教学领域专用渲染器 (Domain Renderers)

1. **SlidePreview & SlideThumbnail**: 16:9 画布式 PPT 预览、左侧缩略图导航与备注逐字稿展示。
2. **TeachingTimeline & ObjectiveCard**: 教学活动环节表（教师/学生/意图/证据）与 Bloom 分层目标卡。
3. **ExerciseCard**: 梯度练习题卡片，包含答案与解析控制开关。
4. **TaskSheetCard & StoryboardItem**: 探究学习任务单与微课视频分镜剧本。
5. **VerbatimSegment**: 教师口播逐字稿，支持全屏黑夜提词器模式。
6. **QualityIssueCard**: AI 规则缺陷检测面板，支持一键触发规则缺陷自动修复。

---

## 7. 页面升级规划

- **DashboardView.vue**: 4 大数据统计卡片、课程搜索过滤与公域引导 Landing。
- **CourseIntakeView.vue**: 持久化需求 Agent 对话、材料输入、实时需求证据卡与人工确认门禁。
- **BlueprintView.vue**: 三栏蓝图确认工作台（章节树 + 结构编辑 + AI 建议门禁）。
- **GenerationView.vue**: 10 大 Agent 节点变迁时间线、活动卡片与终审卡片。
- **WorkspaceView.vue**: 8 大资源 Tab 无缝切换、侧边栏 AI 对话修改与历史版本 Drawer。
- **ExportView.vue / SettingsView.vue**: 打包交付中心与 LLM 加密 Key 维护页。

---
