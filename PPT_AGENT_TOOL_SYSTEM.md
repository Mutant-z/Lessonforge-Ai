# PPT Agent Tool System

Tool 定义统一包含 name、description、input/output schema、timeout、retry、idempotency 和 handler。执行器负责 Pydantic 校验、超时、有限重试、取消检查、错误归一化与结果回喂。

文件工具必须限制在 Run Workspace；修改工具必须作用于结构化 Builder；渲染、图片和图表工具输出路径或 Artifact ID，不把大二进制写进事件。Tool UI 只展示摘要，完整载荷仅开发者可见。

