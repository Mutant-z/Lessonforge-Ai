# 教师工作台 / 微课项目 Dashboard 前端视觉重构报告

## 1. 原页面问题分析

重构前对 Dashboard 进行了全方位问题审查，主要问题如下：

1. **强行视口锁定与空置空白**: 旧布局设置 `100vh` + `overflow: hidden`，导致当只有 **1 个微课项目** 时，项目卡片缩在左上角 360px，下方空出 500px+ 巨大白色板面，右侧空出 1200px+ 无意义空白。
2. **字体与控件普遍偏小**: 全局标题仅 19px，主要正文/输入框/按钮仅 11.5px ~ 13.5px，在大屏上产生严重的传统 ERP/OA 系统收缩感，缺乏现代 AI SaaS Workbench 气场。
3. **AI 快速创建入口感弱**: 仅为一条约 34px 高的普通单行 Input，无法承载多模态材料上传与智能提示。
4. **待处理事项不突出**: 仅为一行黄色 Alert 提示条，未能作为教师进入工作台的“第一行动焦点”。
5. **项目 Card 信息粗糙**: 缺乏“当前阶段”与动态主操作（CTA）。按钮永远是静态“进入工作台”，交付物被嵌入多层矩形容器内（Card inside Card）。

---

## 2. 原页面结构 vs 重构后结构

### 原页面结构:
```text
TeacherDashboard
├── MasterHeaderStrip (19px 小标题 + 新建按钮)
├── OverviewBand (就绪率 0% + 5张扁平 Pills)
├── InlineAiQuickStrip (单行薄输入框)
├── InlineStatusAlertStrip (淡黄色 Alert)
└── MasterCoursesCol
    └── CoursesGridList (固定 360px 卡片)
```

### 重构后新结构:
```text
TeacherDashboard Shell (自适应响应式容器 max-width: 1680px)
├── DashboardPageHeader (26px 标题 + DASHBOARD Eyebrow + 主新建操作)
├── DashboardCommandCenter [NEW]
│   ├── AI Command Composer (70% 宽，110px+ 质感输入框、材料上传、例句 Chips、AI极速生成)
│   └── Action Center 待处理中心 (30% 宽，高亮显示待确认蓝图/草稿/失败任务，立即处理 CTA)
├── DashboardSummary [NEW]
│   ├── Deliverables Readiness Surface (课程交付物就绪率与横向进度)
│   └── Integrated Metrics Surface (全部/已打包/待审核/Agent生成中/节省工时 5大指标)
└── ProjectLibrary [NEW]
    ├── LibraryToolbar (我的微课项目库、筛选 Tabs、300px 搜索框)
    ├── Single Project Wide Surface (100% 全宽卡片，含当前阶段、6大资源状态、动态 CTA)
    ├── Multi Projects Grid (2~6+ 项目 Responsive Grid auto-fill)
    └── Zero Projects Guided Onboarding (0项目智能引导与样例导入)
```

---

## 3. 修改过的文件清单

| 文件路径 | 修改性质 | 说明 |
| :--- | :--- | :--- |
| [`design-system.css`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/assets/design-system.css) | MODIFY | 调整 Header 高度 (64px)、内容最大宽度 (1680px) 与全局 Theme 变量 |
| [`base.css`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/assets/base.css) | MODIFY | 优化全局 Typography 基础重置与容器间距 |
| [`DashboardSummary.vue`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/components/dashboard/DashboardSummary.vue) | NEW | 整合型 Dashboard 统计 Surface 组件 |
| [`DashboardCommandCenter.vue`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/components/dashboard/DashboardCommandCenter.vue) | NEW | AI Command Composer + Action Center 双栏组件 |
| [`ProjectLibrary.vue`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/components/dashboard/ProjectLibrary.vue) | NEW | 支持 Single Wide Card / Multi Grid / Dynamic CTA / 资源状态组件 |
| [`DashboardView.vue`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/views/DashboardView.vue) | MODIFY | 组装调度 Dashboard 视图，连接 Pinia Stores 与 Intake 逻辑 |
| [`AppHeader.vue`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/components/layout/AppHeader.vue) | MODIFY | 升级 Header 64px 高度、全局搜索框宽度与用户菜单样式 |
| [`AppSidebar.vue`](file:///Users/mutant/Documents/project/LessonForge%20AI/frontend/src/components/layout/AppSidebar.vue) | MODIFY | 调整侧边栏导航字号、状态 Pill 与悬浮交互 |

---

## 4. 字体与控件尺寸提升

- **页面主标题**: 19px → **26px** (800 Weight)
- **模块标题**: 16px → **19px** (800 Weight)
- **项目标题**: 16px → **22px** (Single Wide Card) / **17px** (Grid Card)
- **输入框与正文**: 12.5px ~ 13.5px → **15px** (Command Composer Textarea)
- **按钮与导航**: 12.5px → **14px ~ 14.5px**
- **辅助/时间/标签**: 11.5px → **13px ~ 13.5px**
- **Header 高度**: 52px → **64px**

---

## 5. Header / Sidebar 优化

- Header 高度升级至 **64px**，全局搜索框扩展至 **300px~480px**，用户头像下拉菜单增加卡片质感浮层与圆角。
- 弱化 Header 中重复强 purple 按钮，突出页面上下文与主操作区。

---

## 6. Statistics 统计区域优化

- 消除旧版 5 个独立粗框卡片的堆叠感，升级为统一 **Dashboard Summary Surface**。
- 清晰表达微课全套产物打包就绪率，使用微动效进度条。
- 【待教师审核】在 `review > 0` 时开启高亮 Amber 警示 badge；【Agent 生成中】在 `running > 0` 时开启 Violet 呼吸脉冲点。

---

## 7. AI Composer & Pending Tasks (Command Center)

- 左侧 **AI Command Composer (70%)**: 高度 110px+ 复合卡片，支持直接输入多行教学要求、`+ 添加材料` 文件入口、学科点快捷 Chips。
- 右侧 **Action Center (30%)**: 独立的今日待处理面板，将等待教师审核确认的蓝图/草稿/失败任务高亮排列，提供【立即处理 →】强导向按钮。

---

## 8. 单项目 (Single Wide Card) vs 多项目 (Multi Grid)

- **单项目 (1 Project)**: 自动激活 **Wide Project Surface** 全宽大卡片，占据项目区 100% 横向空间，完全消除下部 500px 与右侧 1200px 巨大空白。
  - 明晰展示【当前阶段】（如：`教学设计等待教师确认`）；
  - 完整平铺 6 大教学资源交付状态（教学设计、PPT、任务单、课后练习、视频脚本、教师逐字稿）的就绪状态；
  - 放置高亮动态主按钮（如：`[ 处理待确认 → ]` 或 `[ 查看生成进度 → ]`）。
- **多项目 (2 ~ 6+ Projects)**: 自适应响应式网格 `grid-template-columns: repeat(auto-fill, minmax(380px, 1fr))`。

---

## 9. 动态 UI 与 Agent 状态

- **Agent 生成中 (`running`)**: 显示动画呼吸点 `live-pulse-dot` 与 Spinner，CTA 自动切为 `查看生成进度` (Violet Gradient)。
- **待审核 (`blueprint_review`/`teacher_review`)**: 显示 Warning 色【教学设计等待确认】，CTA 自动切为 `处理待确认` (Amber Gradient)。
- **已完成 (`completed`)**: 显示 Success 色【全套教学资源已准备完成】，CTA 自动切为 `进入工作台` (Primary Gradient)。
- **生成失败 (`failed`)**: 显示 Danger 色【生成遇到问题】，CTA 自动切为 `查看问题` (Danger Red Gradient)。

---

## 10. 工程验证结果

### TypeScript 检查 (`npx vue-tsc -b`)
```text
The command exited with code 0.
0 errors found.
```

### 单元测试套件 (`npm run test`)
```text
 RUN  v3.2.7 /Users/mutant/Documents/project/LessonForge AI/frontend

 Test Files  10 passed (10)
      Tests  88 passed (88)
   Duration  561ms
```

### 生产构建打包 (`npm run build`)
```text
✓ 1943 modules transformed.
rendering chunks...
computing gzip size...
dist/assets/DashboardView-4UBWOVNV.js   39.50 kB │ gzip: 13.27 kB
✓ built in 2.73s
The command exited with code 0.
```

---

## 11. 已知限制与后续建议

- 当前 Dashboard 展示的所有数据（项目列表、Task 状态、生成进度、待处理事项）均源自真实的 API 与 Store。后端后续若扩展 SSE 实时通知推流，`DashboardCommandCenter` 与 `ProjectLibrary` 均已做好响应式属性绑定的接口支持。
