# 课启智造 LessonForge AI — 前端视觉、交互与流式 Agent 体验重构交付报告

## 一、重构背景与目标总结
本项目（课启智造 LessonForge AI）是一个基于 FastAPI + LangChain + LangGraph + Vue 3 的多 Agent 教学微课生成平台。
本次升级成功将前端从“功能基础可用的开发原型”升级为一个专业、稳定、具有生命力与真实 AI 交互感的教育科技 SaaS 产品。

重构在**完全保留现有后端接口、数据结构、JWT 认证、SSE 流式管道与业务逻辑**的前提下，从以下三个核心维度完成了升级：
1. **静态视觉层**：建立了完整的现代教育 AI 设计系统（Tailored HSL Design Tokens、玻璃拟态、软阴影与卡片系统、无缝 Element Plus 主题润色、响应式三栏/两栏布局）。
2. **动态交互层**：引入平滑页面切换动画、Agent 实时节点变迁、任务栏指示器、全状态反馈 (Loading, Skeleton, Empty, Error, Paused, Waiting Human) 与 `@media (prefers-reduced-motion: reduce)` 支持。
3. **AI 输出层**：构建真实的 SSE 流式缓冲队列 (`StreamBuffer`)、去重与事件归一化、打字光标 (`StreamingCursor`)、可扩展的多格式内容渲染中心 (`ContentBlockRenderer`)、智能化跟随滚动 (`useAutoScroll`) 与专用教学资源渲染器（PPT 16:9 预览/缩略图、分时教学时间线、梯度练习题、分镜剧本、提词器模式等）。

---

## 二、架构设计与新增基础设施

### 2.1 设计系统 (Design System)
- **定义文件**: `src/assets/design-system.css`, `src/assets/animations.css`, `src/assets/base.css`
- **设计 Token**:
  - `Primary`: `#4f46e5` (AI Indigo)
  - `Secondary`: `#0284c7` (Educational Sky Blue)
  - `Agent`: `#7c3aed` (Agent Purple)
  - `Status`: Success (`#16a34a`), Warning (`#d97706`), Danger (`#dc2626`), Info (`#2563eb`)
  - `Surfaces & Glass`: `--bg-page: #f8fafc`, `--bg-surface: #ffffff`, `--bg-glass: rgba(255, 255, 255, 0.85)`
  - `Radii & Shadows`: `sm: 6px`, `md: 10px`, `lg: 14px`, `xl: 20px`, `floating: 0 20px 25px -5px rgba(...)`

### 2.2 全局布局框架 (Layout Framework)
- `AppSidebar.vue`: 可折叠/展开侧边栏，包含 Logo、新建课程快捷按钮、导航组、课程项目列表、选中态与折叠状态记忆。
- `AppHeader.vue`: 包含面包屑导航、正在运行的后台 Agent 任务提示 (`正在生成 X 个资源`)、用户状态与下拉菜单。
- `TaskCenterDrawer.vue`: 全局任务中心抽屉，可跨页面监视所有运行中的 Agent 任务并快捷跳转。

### 2.3 流式输出与 Agent 通讯基础设施
- `agentEventAdapter.ts`: 事件归一化服务，统一将服务端 SSE 事件转换为标准 `AgentStreamEvent`。
- `streamBuffer.ts`: `requestAnimationFrame` 驱动的流式字符缓冲队列，实现高频 Token 渲染性能防抖与 Sequence 去重。
- `useAgentStream.ts`: SSE 流式连接 Composables，支持 token 获取、断线自动指数退避重连、连接状态反馈 (`connecting`, `connected`, `reconnecting`, `failed`, `closed`)。
- `useAutoScroll.ts`: 智能自动滚动 Composables，用户在底部时跟随，主动向上阅读时暂停并提供“回到最新输出”浮动按钮。

### 2.4 多格式内容渲染中心 (Renderer Registry)
`ContentBlockRenderer.vue` 调度中心支持以下格式解析与展示：
1. **MarkdownRenderer.vue**: 支持 GFM、KaTeX 数学公式渲染、引用块、安全 HTML 清理。
2. **CodeBlockRenderer.vue**: Highlight.js 语法高亮、语言 Tag、一键复制代码。
3. **JsonTreeRenderer.vue** / **YamlRenderer.vue**: 高亮 JSON/YAML 树视图与原始代码切换。
4. **MermaidRenderer.vue**: Mermaid 流程图/架构图渲染、未闭合语法容错与源码预览。
5. **MathRenderer.vue**: KaTeX 行内/块级公式解析。
6. **ResponsiveTable.vue**: 响应式横向滚动表格，支持 CSV 导出。
7. **FileOutputCard.vue**: PPTX/DOCX/PDF/ZIP 生成产物文件卡片。
8. **CitationCard.vue**: 上传参考材料与基准语料引用来源卡片。

### 2.5 专用教学资源渲染器 (Domain Renderers)
1. **SlidePreview.vue** & **SlideThumbnail.vue**: 16:9 画布式 PPT 预览、左侧缩略图导航、视觉建议与演说逐字备注。
2. **TeachingTimeline.vue** & **ObjectiveCard.vue**: 分时教学环节表（教师活动、学生活动、设计意图、评价证据）与观察化目标卡片。
3. **ExerciseCard.vue**: 梯度练习题卡片（单选、多选、填空、简答）、难度 Badge、答案与解析显隐切换。
4. **TaskSheetCard.vue**: 项目化学习任务单卡片。
5. **StoryboardItem.vue**: 微课视频分镜剧本（画面构图、旁白配音、字幕贴字）。
6. **VerbatimSegment.vue**: 教师逐字稿段落，支持一键切换“全屏提词器黑夜模式”。
7. **QualityIssueCard.vue**: 规则缺陷定位、严重程度标签与 AI 一键修复 trigger。

---

## 三、核心页面升级成果

1. **工作台总览 (`DashboardView.vue`)**
   - 补充 4 大数据统计卡片（全部课程、正在生成、待审核、预计节省备课时间）。
   - 增加未登录公域 Landing 引导与步骤介绍。
   - 课程列表支持关键词实时搜索过滤与状态 Badge。

2. **新建课程向导 (`CourseWizardView.vue`)**
   - 四步分步向导（基础信息 -> 教学要求 -> 参考材料 -> 确认生成）。
   - 环形需求完整度百分比指示器。
   - 拖拽上传文件区与已选材料列表。

3. **课程蓝图确认 (`BlueprintView.vue`)**
   - 3 栏工作台布局（左侧章节导航，中间结构化/JSON 编辑，右侧 AI 建议、校验缺陷与引用来源）。
   - 一键确认蓝图并启动多 Agent 资源生成。

4. **多 Agent 运行监视 (`GenerationView.vue`)**
   - 全套 Agent 运行控制栏 (`GenerationToolbar`: 暂停、继续、后台运行、取消、重试)。
   - `AgentActivityCard` 展示运行时间、当前 Agent 职责与进度。
   - `AgentStepTimeline` 实时呈现 10 大节点状态变迁。
   - `AgentEventLog` 事件日志过滤。
   - `HumanReviewPanel` 终审节点卡片。

5. **教学资源工作台 (`WorkspaceView.vue`)**
   - 8 大资源 Tab 页签无缝切换。
   - 专属 Agent 模块侧边栏对话修改。
   - 领域专用渲染器（PPT 16:9 画布、教学时间线、练习题答案显隐、提词器模式等）。
   - 历史版本选择 Drawer (`VersionSelector`) 与内容锁定/编辑功能。

6. **导出与交付中心 (`ExportView.vue`)**
   - 资源清单 Checkbox 列表。
   - 格式说明与一键生成打包 ZIP。
   - 浏览器 Blob 触发文件下载。

7. **系统设置 (`SettingsView.vue`)**
   - LLM Provider（OpenAI-compatible / Mock）配置、加密 Key 维护与默认 PPT 模版设置。

8. **登录与注册 (`LoginView.vue`)**
   - 教育 AI 特色品牌墙与两栏式布局。

---

## 四、工程与测试结果
1. **TypeScript 检查**: `vue-tsc -b` 0 错误通过。
2. **生产构建**: `npm run build` (Vite) 成功构建为 production chunks。
3. **依赖兼容性**: 引入 `katex`, `mermaid`, `highlight.js`, `markdown-it`, `@element-plus/icons-vue` 等工具，完全保持对原有 package 的兼容。
