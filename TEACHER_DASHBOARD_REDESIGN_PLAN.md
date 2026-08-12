# 教师工作台 / 微课项目 Dashboard 前端视觉重构计划

## 一、 当前页面结构分析

通过对前端代码（`frontend/src/views/DashboardView.vue`、`AppLayout.vue`、`AppHeader.vue`、`AppSidebar.vue`、`design-system.css` 等）的详细深度探索，确定当前 Dashboard 的组件与 DOM 结构如下：

```text
AppLayout.vue (100vh Shell, flex vertical)
├── AppHeader.vue (52px 顶部导航栏)
├── AppSidebar.vue (270px / 80px 侧边栏)
└── DashboardView.vue (主容器 dashboard-root-view)
    ├── Guest Landing Shell (未登录状态)
    └── workspace-page-container (已登录状态, 100vh 强卡视口)
        └── master-workbench-card (单一卡片包裹层, flex vertical)
            ├── master-header-strip (顶部标题条 DASHBOARD + 新建按钮)
            ├── master-overview-band (欢迎词 + 打包就绪率 0% + 5张扁平统计卡)
            ├── inline-ai-quick-strip (单行薄型 AI 输入框 + 快捷 Chip)
            ├── inline-status-alert-strip (黄色 Alert 待处理提示条 + Agent 提示)
            └── master-body-split (主卡片容器)
                └── master-courses-col
                    └── dashboard-content-panel
                        ├── dashboard-toolbar (标题 + 4个状态 Pills + 220px 搜索框)
                        └── courses-body-content
                            ├── empty-onboarding-panel (0项目引导)
                            ├── EmptyState (无匹配)
                            └── courses-grid-list (repeat(auto-fill, minmax(360px, 1fr)))
                                └── course-card (360px 固定小卡片)
```

---

## 二、 定位到的核心问题与根因分析

### 1. 布局与页面空白问题 (Root Cause)
- **硬卡视口与过度嵌套**: `workspace-page-container` 与 `master-workbench-card` 设置了 `height: 100%; max-height: 100%; overflow: hidden;`，将所有内容塞入一个固定视口大卡片中。
- **单项目模式失衡**: 项目列表 `courses-grid-list` 使用 `repeat(auto-fill, minmax(360px, 1fr))`。当系统中只有 **1 个项目**（当前最典型的教师使用场景）时，只渲染一个 360px × 150px 的左上角小 Card，卡片右侧留出 1200px+ 无意义空白，卡片下方空出 500px+ 巨大白色板面，视觉极其不平衡且低效。
- **页面未设置合理 Max-Width**: 在 1920px / 2K 大屏下，内容拉伸严重但信息密度极低。

### 2. 字体与视觉比例过小问题 (Font Scale)
- 全局与页面 css 字体普遍严重偏小：
  - `main-title`:仅 19px (应为 24~26px)
  - `subtitle-text`: 13px (应为 14~15px)
  - `eyebrow-tag`: 11px (应为 12~13px)
  - `stat-label` / `stat-num small`: 11px ~ 12px
  - `inline-prompt-input` / `inline-send-btn`: 12.5px ~ 13.5px
  - `deliv-item` / `meta-tag` / `update-time`: 11.5px (极其微弱难读)
- 控件高度不足: 搜索框仅 28~32px，按钮仅 28~32px，在大屏上如同缩小至 80% 缩放比例。

### 3. 顶部统计区域缺乏层级 (Summary Hierarchy)
- 5 个统计 Pills ("全部项目", "已完成", "待审核", "Agent生成中", "预计节省工时") 横排堆叠，视觉权重完全一致。
- "微课全套产物打包就绪率 0%" 进度条语义模糊，未能直观表达真正的课程资源完成度或可交付项目数。

### 4. AI 快速创建入口存在感极弱 (Command Composer)
- `inline-ai-quick-strip` 仅为单行薄输入框（高约 34px），缺乏 AI Command Center / Composer 的体量与视觉冲击力。
- 缺少材料添加入口、模型配置切换与富交互动效。

### 5. 待处理任务不够突出 (Action Center)
- 待处理任务仅为一行淡黄色 Alert (`inline-status-alert-strip`)，容易被忽略，未能作为教师进入工作台的“第一行动焦点”。

### 6. 项目 Card 信息表达不明确
- 缺少“当前阶段”（如：`教学设计等待教师确认`、`PPT Agent 正在生成`、`课程资源已备齐`）。
- 按钮永远是静态的“进入工作台”，无法根据“待审核”、“生成中”、“已完成”、“失败”提供动态确切的下一步主操作（CTA）。
- 资源交付物状态被嵌入深层小 Card inside Card，容器层级过多。

### 7. 重复的“新建微课”按钮
- Header、Sidebar、Dashboard 三处均有“新建微课”按钮，且全部为强紫色 Primary 按钮，存在视觉竞争与功能割裂。

---

## 三、 详细重构方案设计

### 1. 字体与控件尺寸全面提升 (Font System Upgrade)
根据重构要求，统一调整全局与 Dashboard 字体层级：
- 页面主标题: **24 ~ 26px** (Font-weight: 800)
- 板块/模块标题: **18 ~ 20px** (Font-weight: 800)
- 项目标题: **17 ~ 19px** (Font-weight: 700)
- 正文与输入框文字: **15 ~ 16px**
- 导航/按钮文字: **14 ~ 15px**
- 辅助/时间/标签文字: **13 ~ 14px**
- Badge / Status Pill: **12 ~ 13px**
- 基础控件高度提升: 输入框 **42 ~ 44px**，主要按钮 **40 ~ 44px**，Header 高度由 `52px` 升级为 **64px**。

### 2. 页面容器与空间重新规划 (Layout & Surface Design)
- 消除强行 `100vh overflow:hidden` 挤压，使用响应式自适应布局。
- 引入统一内容容器 `.dashboard-content { width: 100%; max-width: 1680px; margin: 0 auto; }`。
- 桌面宽屏（≥1440px）下采用双栏网格与动态布局：
  - 上部: **AI Command Center (68~72%)** + **Action Center 待处理中心 (28~32%)**
  - 中部: 整合型 **Dashboard Summary Surface** 统计信息栏
  - 下部: **我的微课项目库 (主栏)** 与项目状态联动

### 3. AI 快速创建升级为 Command Composer
- 设计 **AI Command Composer**:
  - 默认高度 **110 ~ 130px** 质感卡片，包含清晰的 Prompt Placeholder、提示引导、材料上传入口 (`+ 添加材料`) 与 `AI 极速生成` 复合操作。
  - 快捷示例升级为更具体的学科点 Chip（如: `牛顿第二定律`、`勾股定理`、`氧化还原反应`），点击直接填充输入框。

### 4. “今日待处理”升级为 Action Center
- 从弱 Alert 升格为独立的 ** Action Center (待处理中心)** 卡片。
- 高亮显示等待教师确认的蓝图/教学设计，展示项目名称、阶段说明与强高亮【立即处理】主按钮。

### 5. 项目库与 Single / Multi Project 动态布局
- **单项目模式 (1 Project Wide Card)**:
  - 当项目数为 1 时，自动切换为 **全宽/大卡片布局 (Wide Project Surface)**。
  - 左侧展示课程元信息（学科、年级、时长）、当前阶段（高亮 Tag，如 `教学设计等待教师确认`）；
  - 中间展示 6 大教学资源交付状态（教学设计、PPT、任务单、练习、视频脚本、逐字稿）的完成/待确认/生成中 Badge；
  - 右侧展示明确的下一步主操作（如 `处理待确认` 或 `进入工作台 →`）。
  - 彻底消除左上角 360px 小 Card + 巨大空白的丑陋视觉。
- **多项目模式 (2 ~ 6+ Projects)**:
  - 2 个项目使用 2 列全宽 Grid；
  - 3~6 个项目使用 `grid-template-columns: repeat(auto-fill, minmax(380px, 1fr))` 响应式自适应 Grid。

### 6. 项目 Card CTA 与“当前阶段”动态化
- 根据后端真实 `course.status` 赋予明确的“当前阶段”描述与动态 CTA：
  - `blueprint_review` / `teacher_review`: 阶段标为【教学设计等待确认】，CTA 按钮为【处理待确认】(Warning 色)
  - `blueprint_generating` / `resource_generating`: 阶段标为【Agent 正在生成资源...】，CTA 按钮为【查看生成进度】(Pulse Agent 动效)
  - `completed`: 阶段标为【全套资源已准备完成】，CTA 按钮为【进入工作台】/【导出课程】(Primary)
  - `failed`: 阶段标为【生成遇到问题】，CTA 按钮为【查看问题】(Danger)

### 7. 顶部与侧边栏协调 (Header & Sidebar)
- Header 高度调整至 **64px**，优化搜索框宽度（380px~480px），统一操作层级，弱化 Header 中的重复新建按钮，突出工作台主视图。
- Sidebar 导航字号与激活状态优化，项目列表保持精炼紧凑。

---

## 四、 组件拆分与结构重构

为保持代码高可维护性与清晰架构，在 `src/components/dashboard/` 下重构与完善以下组件（不滥拆小组件）：

```text
src/
├── views/
│   └── DashboardView.vue (教师 AI 工作台主视图，调度状态与组件)
├── components/
│   └── dashboard/
│       ├── DashboardSummary.vue (整合型统计与完成度 Surface)
│       ├── DashboardCommandCenter.vue (AI Command Composer + Action Center)
│       └── ProjectLibrary.vue (动态项目库: 支持 Single Wide Card / Multi Grid / Dynamic CTA / 资源状态)
```

---

## 五、 修改文件清单

1. [MODIFY] `frontend/src/assets/design-system.css`
2. [MODIFY] `frontend/src/assets/base.css`
3. [NEW] `frontend/src/components/dashboard/DashboardSummary.vue`
4. [NEW] `frontend/src/components/dashboard/DashboardCommandCenter.vue`
5. [NEW] `frontend/src/components/dashboard/ProjectLibrary.vue`
6. [MODIFY] `frontend/src/views/DashboardView.vue`
7. [MODIFY] `frontend/src/components/layout/AppHeader.vue`
8. [MODIFY] `frontend/src/components/layout/AppSidebar.vue`

---

## 六、 验证方案

### 1. 自动化工程验证
- TypeScript 检查: `npx vue-tsc -b`
- 单元测试套件: `npm run test` (Vitest)
- 构建打包验证: `npm run build`

### 2. 界面与响应式验证
- 分辨率覆盖测试:
  - 1920 × 1080 (宽屏台式)
  - 1536 × 864 (标准笔记本)
  - 1440 × 900 (MacBook Pro 14")
  - 1280 × 800 (小屏笔记本)
  - 1024 × 768 (iPad / 平板)
  - 768px 以下 (移动端适配)
- 场景测试:
  - 0 个项目 (引导页 Empty State)
  - 1 个项目 (Wide Card 全宽大卡片测试)
  - 2~6 个项目 (多项目 Grid 布局测试)
  - 不同 `status` (待审核, 生成中, 已完成, 失败) 动态 CTA 与当前阶段测试
