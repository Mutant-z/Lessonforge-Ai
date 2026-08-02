# FRONTEND REDESIGN PROGRESS - 课启智造 LessonForge AI

## 1. 当前前端架构
- **核心框架**: Vue 3 (Composition API + `<script setup lang="ts">`), TypeScript 5.7, Vite 6.0
- **UI 库 & 状态管理**: Element Plus, Pinia, Vue Router 4, Axios
- **内容处理**: Markdown-it, KaTeX, Mermaid, Highlight.js
- **路由与结构**:
  - `/login`: 登录 / 注册
  - `/`: 总览 dashboard
  - `/courses/new`: 新建课程四步向导
  - `/courses/:id/blueprint`: 课程蓝图确认与编辑 (JSON / 结构化视图)
  - `/courses/:id/generation/:runId`: 多 Agent 运行与流式生成监视
  - `/courses/:id/workspace`: 教学资源全功能编辑工作台 (教学设计、PPT、任务单、练习、视频脚本、逐字稿、质量报告、引用)
  - `/courses/:id/export`: 课程包打包与 ZIP 导出
  - `/settings`: 模型与默认偏好配置

## 2. 设计系统与重构实施记录
- **设计系统 CSS**: `src/assets/design-system.css`, `src/assets/animations.css`, `src/assets/base.css`
- **公共组件库**:
  - `layout/`: `AppHeader`, `AppSidebar`, `PageHeader`, `TaskCenterDrawer`
  - `feedback/`: `StatusBadge`, `ConnectionStatus`, `EmptyState`, `ErrorState`, `SkeletonBlock`
  - `agent/`: `AgentActivityCard`, `AgentThinkingIndicator`, `AgentStepTimeline`, `AgentEventLog`, `GenerationToolbar`, `StreamingCursor`, `HumanReviewPanel`
  - `content-renderers/`: `ContentBlockRenderer`, `MarkdownRenderer`, `CodeBlockRenderer`, `JsonTreeRenderer`, `YamlRenderer`, `MermaidRenderer`, `MathRenderer`, `ResponsiveTable`, `FileOutputCard`, `CitationCard`, `UnknownBlockRenderer`
  - `domain/`: `ObjectiveCard`, `TeachingTimeline`, `SlidePreview`, `SlideThumbnail`, `ExerciseCard`, `TaskSheetCard`, `StoryboardItem`, `VerbatimSegment`, `QualityIssueCard`, `VersionSelector`
- **基础设施 & Composables**: `useAgentStream`, `useAutoScroll`, `useReducedMotion`, `streamBuffer`, `agentEventAdapter`, `contentParser`, `taskCenter` store

## 3. 核心升级进展状态
- [x] 第一阶段：项目审查与设计方案确认
- [x] npm 依赖扩展与环境搭建
- [x] 第二阶段：设计系统与主题 CSS 体系搭建
- [x] 第三阶段：全局 AppLayout、AppSidebar、Header 与 TaskCenterDrawer
- [x] 第四阶段：流式 infrastructure (`useAgentStream`, `streamBuffer`, `agentEventAdapter`, `useAutoScroll`)
- [x] 第五阶段：多格式与教学专用 Renderers 建立
- [x] 第六阶段：8 大核心页面（Dashboard, Wizard, Blueprint, Generation, Workspace, Export, Settings, Login）重构
- [x] 第七阶段：状态全覆盖 (Loading, Skeleton, Empty, Error, Paused, Reconnecting, Waiting Human)
- [x] 第八阶段：测试、代码清理、TypeScript 类型检查与生产构建验证 (`vue-tsc -b && vite build` PASS)

## 4. 构建与测试结果
- TypeScript 检查: PASS (vue-tsc -b 0 errors)
- Vite 生产构建: PASS (1881 modules transformed, dist generated cleanly)
- 交付报告文档: `FRONTEND_REDESIGN_REPORT.md` (已完成)
