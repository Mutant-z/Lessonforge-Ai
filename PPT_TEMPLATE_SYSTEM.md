# PPT Template System

模板解析读取实际 PPTX 的尺寸、主题、Master、Layout、Shape、字体、颜色、间距、装饰和示例页，产出缓存的 `TemplateDesignProfile`。Profile 以模板文件 hash 和 catalog version 失效。

模板切换创建新 Run 和新 Revision，保留页面教学逻辑、确认内容、图表数据和可复用视觉资源，重跑 Template Analysis、Layout、Builder、Render 与 QA。旧版本始终可恢复。

