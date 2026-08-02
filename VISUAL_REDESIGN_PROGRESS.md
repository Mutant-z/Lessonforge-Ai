# 课启智造 LessonForge AI 前端视觉与交互重构进度表

## 一、项目诊断与改造全景

### 1. 当前页面结构
* **公共路由层**：
  - Guest State: `/` (首页 Landing Page, `HomeNavbar.vue`, `HomeHero.vue`, `AgentWorkflowDemo.vue`, `ResourceBentoGrid.vue`, `CourseExamplePanel.vue`, `HomeCTA.vue`, `HomeFooter.vue`)
  - Authentication: `/login` (`LoginView.vue`, `AuthBrandPanel.vue`, `AuthFormCard.vue`, `AuthAgentPreview.vue`)
* **控制台路由层 (AppLayout)**:
  - Dashboard: `/` (教师工作台 Bento Grid, `DashboardView.vue`, `QuickCreatePanel.vue`, `ActiveAgentTasks.vue`, `PendingActions.vue`)
  - Course Wizard: `/courses/new` (`CourseWizardView.vue`)
  - Blueprint: `/courses/:id/blueprint` (`BlueprintView.vue`)
  - Agent Stream Run: `/courses/:id/generation/:runId` (`GenerationView.vue`)
  - Resource Workspace: `/courses/:id/workspace` (`WorkspaceView.vue`)
  - Export Center: `/courses/:id/export` (`ExportView.vue`)
  - System Settings: `/settings` (`SettingsView.vue`)

---

## 二、关键缺陷诊断与优化策略

### 1. 原首页问题
* **诊断**：平淡矩形切割，缺少 AI 产品的生命力与多 Agent 协作的可视化冲击。
* **重构策略**：采用 Glassmorphism 顶部导航，Hero 区域不对称双栏。左侧标语与主次 CTA；右侧基于真实控制台打造动态多 Agent 协作工作流（输入需求 → 蓝图 Master Agent → 4 大 Agent 并行生成 → 质检巡检 Agent → 6 类资源一键导出）。

### 2. 原登录页问题
* **诊断**：机械 50/50 割裂，缺少科技氛围与独立的浮动 Card 质感。
* **重构策略**：采用深色科技背景与 460px 悬浮 3D 浮动表单 Card。品牌区配置《机器学习基础》实时 Multi-Agent 状态预览；表单区加入“记住登录状态”、密码显隐切换与严谨错误 Alert。

### 3. 原登录后控制台问题
* **诊断**：只有 4 张平淡统计卡 + 静态搜索表格，宽屏下大面积无意义空白。
* **重构策略**：重构为非对称 **Bento Grid**。新增 `QuickCreatePanel.vue` (欢迎与快捷创建), `ActiveAgentTasks.vue` (运行中 Agent 节点与实时进度), `PendingActions.vue` (待确认蓝图与待修事项)。0 课程时展示四步可视化引导演示与样例一键导入。

### 4. 原动态 UI 与 Agent 输出问题
* **诊断**：生成等待时仅有普通 Spinner，缺乏具体的 Agent 阶段提示；没有全局后台任务抽屉。
* **重构策略**：
  - 顶部栏集成 `AppHeader.vue` 全局 Agent 运行指示器与待确认蓝图提醒。
  - 侧边栏集成 `TaskCenterDrawer.vue` 随时查看后台运行任务。
  - `GenerationView.vue` 引入 Step Timeline 脉冲动画、智能“回到最新”悬浮按钮、分阶段等待提示语与人工审核中断面板。

---

## 三、新增与重构的公共组件

1. `src/assets/design-system.css`: 全局 CSS Variables（包含 `--primary-50` ~ `--primary-700`, `--accent-*`, `--surface-*`, `--radius-*`, `--shadow-*` 等）。
2. `src/components/dashboard/QuickCreatePanel.vue`: 欢迎语与快捷创建卡片。
3. `src/components/dashboard/ActiveAgentTasks.vue`: 正在运行的 Agent 任务实时卡片。
4. `src/components/dashboard/PendingActions.vue`: 今日待处理事项卡片。
5. `src/components/home/AgentWorkflowDemo.vue`: 首页 Multi-Agent 工作流互动演示。
6. `src/components/home/ResourceBentoGrid.vue`: 6 类交付资源 Bento Grid。
7. `src/components/auth/AuthFormCard.vue`: 悬浮 3D 质感独立 Form Card。
8. `src/components/layout/TaskCenterDrawer.vue`: 全局 Agent 任务抽屉。

---

## 四、最终构建与验证结果

* **TypeScript 类型检查 (`vue-tsc -b`)**: ✅ 0 错误
* **Vite Production Build (`vite build`)**: ✅ 编译构建成功
* **构建产物**:
  - `dist/index.html` (0.84 kB)
  - `dist/assets/index-*.css` (383 kB)
  - `dist/assets/index-*.js` (1130 kB)

---

## 五、完成进度列表

- [x] 审查现有前端代码与 `package.json`
- [x] 统一设计系统与 CSS Variables 定义 (`design-system.css`)
- [x] 未登录产品首页重构 (`HomeNavbar`, `HomeHero`, `AgentWorkflowDemo`, `ResourceBentoGrid`, `CourseExamplePanel`, `HomeCTA`, `HomeFooter`)
- [x] 登录和注册认证页面重构 (`AuthBrandPanel`, `AuthFormCard`, `AuthAgentPreview`)
- [x] 登录后控制台 AppLayout 重构 (`AppSidebar`, `AppHeader`, `TaskCenterDrawer`)
- [x] 教师工作台 Bento Grid 重构 (`DashboardView`, `QuickCreatePanel`, `ActiveAgentTasks`, `PendingActions`)
- [x] 核心业务页面重构 (`CourseWizardView`, `BlueprintView`, `GenerationView`, `WorkspaceView`, `ExportView`, `SettingsView`)
- [x] 动态 UI 与 Agent 状态处理 (Step Timeline, Stream Cursor, AutoScroll, Skeleton/Empty/Error)
- [x] 生产构建验证 (`npm run build` 通过)
- [x] `VISUAL_REDESIGN_REPORT.md` 生成
