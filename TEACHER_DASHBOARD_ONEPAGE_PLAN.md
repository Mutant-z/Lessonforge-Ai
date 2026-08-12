# Teacher Dashboard One-Page Refactoring Implementation Plan

## Goal Description
Refactor the Teacher Dashboard (`/` route in LessonForge AI) into a true single-screen ("One Page") workspace on standard desktop resolutions (1536×864, 1440×900, 1920×1080, 1280×800) without reducing font sizes, sacrificing readability, or removing existing business features.

---

## User Review Required

> [!IMPORTANT]
> **Key Architecture Decisions:**
> 1. **Fixed Shell Height Contract**: The main Dashboard container will enforce `height: calc(100vh - var(--header-height)); overflow: hidden;` on desktop resolutions (>=1024px).
> 2. **Single Internal Scroll Container**: Only the `ProjectLibrary` content container will scroll vertically when project items overflow the available space. The page itself, Command Center, and Workflow Summary will remain static on screen.
> 3. **No Font Degradation**: Font sizes will strictly maintain current standards (Titles: 24-26px, Section Titles: 18-19px, Body: 14-15px, Badges/Meta: 12-13px). No font size will be reduced below 12px.
> 4. **Compact Component Redesign**:
>    - **Dashboard Header**: Compact single-strip layout (~52px height).
>    - **Command Center**: Height fixed between 210px–230px; text input min-height 68px with inline tool buttons; Pending tasks panel simplified into an integrated list without nested card-in-card bloat.
>    - **Workflow Overview**: Transformed into a sleek, low-profile Summary Bar (~125px–135px height) combining the progress indicator and 5 key metric numbers into a single surface.
>    - **Project Library**: Single Wide Card compressed to ~180px–210px height, guaranteeing 100% visibility on 1440×900 and 1536×864 screens.

---

## Current vs Target Height Allocation Budget (1536×864 Viewport)

| Module / Component | Current Height | Target Height | Space Saved | Optimization Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Shell Outer Padding** | 84px (24px top / 60px bottom) | 32px (16px top / 16px bottom) | **-52px** | Delete excessive 60px bottom margin |
| **Dashboard Header** | ~68px (+24px margin) | ~52px (+12px gap) | **-28px** | Combine Eyebrow, Title, Subtitle, and Action into a single visual row |
| **Command Center** | ~290px (+20px gap) | ~220px (+12px gap) | **-78px** | Compact input textarea, inline file upload button, slim pending tasks panel |
| **Workflow Overview** | ~196px (+20px gap) | ~130px (+12px gap) | **-74px** | Convert 5 separate cards into 1 integrated Summary Bar with inline progress |
| **Project Library Header** | ~48px (+16px gap) | ~42px (+10px gap) | **-12px** | Slim search input and filter tabs height |
| **Project Card (Single Wide)** | ~306px | ~190px–210px | **-96px** | Streamline stage banner and 6 deliverable chips into 1 tight row |
| **Total Height Required** | **1072px** *(Overflow: ~272px)* | **~800px** *(100% Fit!)* | **-340px** | **Zero Page Scroll Required on Desktop** |

---

## Proposed Component Changes

### 1. `DashboardView.vue`
- Change outer shell style to locked flex column: `height: calc(100vh - var(--header-height)); overflow: hidden; padding: 16px 28px;`.
- Ensure main container `.dashboard-content` uses `height: 100%; display: flex; flex-direction: column; min-height: 0; gap: 12px;`.
- Update header to compact inline layout (`.dashboard-page-header`).

### 2. `DashboardCommandCenter.vue`
- Restructure outer container height to ~220px.
- **AI Composer**:
  - Integrate title and resume button inline.
  - Textarea: `min-height: 64px; max-height: 90px; padding: 8px 12px;`.
  - Tool bar: inline attachment chips + "+ 添加材料" and "AI 极速生成" button inside the input container bottom bar.
  - Prompt chips: single compact horizontal wrap row.
- **Today's Pending Tasks (Right Panel)**:
  - Remove card-in-card wrapper.
  - Use integrated divider and clean typography to display urgent tasks.

### 3. `DashboardSummary.vue`
- Convert top banner + 5 separate floating metric cards into a single low-profile **Workflow Summary Bar** (~125px–135px height).
- Move "Deliverable Progress (可交付微课比例)" into the Summary Bar Header right side.
- Align metrics horizontally with subtle vertical dividers (`|`).

### 4. `ProjectLibrary.vue`
- Set root container to `flex: 1; min-height: 0; display: flex; flex-direction: column;`.
- Set card list area to `flex: 1; min-height: 0; overflow-y: auto;`.
- **Wide Project Card (Single Project)**:
  - Reduce padding from 24px to 14px 18px.
  - Deliverable 6-cell grid: compact icon + label + status badge (cell height ~38px).
  - Overall card height reduced to ~180px–200px.
- **Multi Project Grid**:
  - Responsive 2-column or 3-column grid with `overflow-y: auto` inside the project section.

---

## Verification Plan

### Automated Build & Code Checks
```bash
# 1. Run Vue TypeScript check & Vite build
cd frontend && npm run build
```

### Manual Visual Verification
1. **1536×864 & 1440×900 Resolution**: Verify that Header, Dashboard Title, AI Creation, Pending Items, Workflow Summary, and at least 1 complete Project Card are 100% visible on screen without scrolling the window.
2. **Project Overflow Testing**: Add multiple mock projects to verify that only the `ProjectLibrary` container scrolls internally while the main Dashboard layout remains anchored.
3. **Font Readability Check**: Ensure no text drops below 12px and core font sizes remain 14px–26px.
4. **Interactive Flows**: Test AI prompt submission, sample course creation, task action redirects, filter tab switching, and search querying.
