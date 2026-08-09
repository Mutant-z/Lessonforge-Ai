# PPT Agent Test Plan

- Runtime：多轮 LLM、Tool 回喂、Handoff、动态路由、Checkpoint、Pause/Resume/Cancel。
- Skill/Tool：发现、懒加载、组合、失败、超时、重试、输出校验。
- Artifact：PPT/Slide 版本、Diff、模板切换、旧版本恢复。
- PPT：生成、单页/多页修改、图片/Diagram、可编辑 PPTX、Render、QA、Repair。
- SSE/UI：顺序、重连、去重、页面 patch、消息隔离、多页选择和 50 页性能。
- 回归：`pytest`、`vitest`、`vue-tsc --noEmit`、Vite production build。
