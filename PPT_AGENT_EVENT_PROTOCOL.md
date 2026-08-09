# PPT Agent Event Protocol

标准事件信封：`event_id, sequence, run_id, timestamp, type, agent, message, progress, artifact, slide, payload`。`GenerationEvent.id` 是唯一续传和去重顺序源。

事件命名空间：`run.*`、`plan.*`、`agent.*`、`skill.*`、`tool.*`、`artifact.*`、`slide.*`、`qa.*`、`repair.*`、`human.*`。后端在迁移期映射旧 snake_case 事件；前端只对标准事件建模。SSE 使用 `Last-Event-ID/after` 续传，普通 UI 不展示 Raw JSON 或模型隐式推理。

