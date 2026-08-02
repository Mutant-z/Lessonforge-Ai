# LessonForge AI 前端视觉、交互与多 Agent 流式升级 执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LessonForge AI Web 前端全面升级为具备现代化 Design System、高响应度微动效、真实指数退避流式 SSE 管道、多格式 Renderers 以及 8 大领域教学渲染视图的专业级 SaaS 平台。

**Architecture:** 基于 Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router。封装底层 SSE `streamBuffer` 防抖与适应性渲染系统，解耦全局 App 框架与局部教研渲染器。

**Tech Stack:** Vue 3.5+, TypeScript 5.7+, Pinia 2.3+, Vite 6.0+, Element Plus 2.9+, markdown-it 14.1+

## Global Constraints

- 不修改后端现存 API 契约与 HTTP / SSE 接口字段。
- 支持全量 TypeScript 严格类型检查 (`vue-tsc -b`) 与生产打卷构建 (`vite build`)，确保 0 Build Errors。
- 支持暗色/亮色 CSS Design System 变量化适配与流畅降级动画 (@media prefers-reduced-motion)。

---

### Task 1: 验证与强化 Design System 和 App 全局 Layout

**Files:**
- Modify: `frontend/src/styles/design-system.css`
- Modify: `frontend/src/components/layout/AppSidebar.vue`
- Modify: `frontend/src/components/layout/AppHeader.vue`
- Test: `frontend/src/App.vue`

**Interfaces:**
- Consumes: CSS Design Tokens (--color-primary, --bg-glass, --sidebar-width)
- Produces: 响应式主框架与高亮当前 Active Route 侧边栏

- [ ] **Step 1: 检查并补充 CSS Design System 变量**

确认 `frontend/src/styles/design-system.css` 包含 `--bg-glass`, `--pulse-glow`, `--streaming-cursor`。

- [ ] **Step 2: 验证并编译 Vue TypeScript 类型**

运行: `cd frontend && npx vue-tsc -b`
Expected: PASS (0 errors)

- [ ] **Step 3: 运行全局 Vite 构建测试**

运行: `cd frontend && npm run build`
Expected: PASS with output artifacts in `dist/`

---

### Task 2: 强化流式输出与领域渲染组件体系

**Files:**
- Modify: `frontend/src/composables/useAgentStream.ts`
- Modify: `frontend/src/components/content-renderers/ContentBlockRenderer.vue`
- Modify: `frontend/src/components/artifact/SlidePreview.vue`
- Modify: `frontend/src/components/artifact/TeachingTimeline.vue`

**Interfaces:**
- Consumes: `AgentStreamEvent` / `ContentBlock` 规范
- Produces: 领域组件渲染逻辑 (16:9 Slide, 分时活动表格, Markdown 数学公式渲染)

- [ ] **Step 1: 检查使用 `useAgentStream` 的重连抖动缓冲**

确认 `frontend/src/composables/useAgentStream.ts` 在重连时保持去重与排序。

- [ ] **Step 2: 运行类型检查与构建验证**

运行: `cd frontend && npm run build`
Expected: PASS (成功生成最终 App 产物)

---
