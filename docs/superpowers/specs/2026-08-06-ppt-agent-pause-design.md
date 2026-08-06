# PPT Agent 动态暂停按键交互设计规范

## 1. 概述
在 LessonForge AI 的 PPT Agent 推演工作台（Agent Pipeline Workbench）中，补充 PPT Agent 运行过程中的“动态暂停/中止”功能。用户在 Agent 正在推演/生成 PPT 时，可通过位于底部 Composer 操作区域的原“发送”按钮位置点击“暂停”，优雅中断当前推演循环并恢复指令输入。

## 2. 界面与交互设计 (UI & Component Interaction)

### 2.1 `AgentComposer.vue`
- **组件属性扩展**：
  - 新增 Emits 事件：`@pause`。
  - 新增 Loading 状态支持 `pauseLoading`（通过内部 ref 或属性管理），防止多次并发调用。
- **按钮状态切换规则**：
  - **运行状态 (`isRunning === false`)**：
    - 图标：`Promotion` (纸飞机图标)
    - class / 样式：标准的圆形发送按钮（`.send-circle-btn`）
    - tooltip: `"发送修改指令"`
    - 点击事件：触发 `handleSubmit` 发送消息
    - 禁用条件：`!input.trim() || isRunning`
  - **推演中状态 (`isRunning === true`)**：
    - 图标：`VideoPause` (暂停图标)
    - class / 样式：高亮警告样式（如 `.send-circle-btn.is-pausing`，带淡红色/琥珀色背景与平滑过度动画）
    - tooltip: `"暂停 Agent 推演"`
    - 点击事件：触发 `emit('pause')`
    - 禁用条件：仅在 `pauseLoading === true` 时禁用
- **输入框展示**：
  - 当 `isRunning === true` 时，输入框禁用状态维持，占位符更新提示：`"Agent 正在推演 PPT 页面，点击右下角按钮可暂停..."`。

### 2.2 `AgentPipelineWorkbench.vue` & `TaskWorkspaceView.vue`
- **事件绑定**：
  - `<AgentComposer @pause="handlePause" ... />`
- **逻辑绑定**：
  - `handlePause` 调用 `pipelineStore.pause(courseId, taskType)`，在请求期间设置 `pauseLoading = true`。
  - 联动顶部 Header 的状态展示区（将“运行中”动态切为“已暂停”）。

## 3. 数据流与后端接入 (Data Flow & Backend API)

1. 用户点击处于运行态的暂停按钮。
2. 前端发起 HTTP 请求：`POST /api/v1/courses/{course_id}/tasks/{task_type}/pause`。
3. 后端 API 处理器捕获请求，更新数据库中的 `GenerationRun.status = 'paused'`，并触发对应的 `PAUSE_EVENTS[generation_run_id].set()` 事件通知。
4. 后端 `run_ppt_pipeline` agent 循环检测到 pause event 后安全中止当前步骤，并通过 SSE 向前端广播 `status_changed` (`status: paused`)。
5. 前端 SSE 监听器收到状态改变通知，更新 Pinia 中的状态，驱动 `isRunning` 变为 `false`，`AgentComposer` 按钮自动还原为发送状态，允许用户再次输入与调整。

## 4. 边界处理与容错 (Edge Cases & Resilience)

- **防抖与 Loading**：在发起 `pause` 请求后立即进入 `pauseLoading` 状态，响应完成后取消，防止用户重复猛击。
- **请求失败提示**：若网络故障导致请求失败，前端通过 `ElMessage.error` 给予通知，并将 `pauseLoading` 置回 `false`。
- **竞态消除**：若暂停指令触发瞬间 Agent 刚好推演完成，后端优雅无视或返回 `status: completed`，前端根据最终 SSE 状态平滑过渡。
