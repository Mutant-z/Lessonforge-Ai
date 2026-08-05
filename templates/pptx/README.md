# 内置 PPT 模板

`catalog.json` 是内置模板的唯一目录，前端在线预览和后端 PPTX 导出共同读取其中的颜色、字体与模板文件映射。

## 模板来源

六套模板均为 `templates/PPT_template/` 下的**真实成品 .pptx**（每套 15 页、16:9），
导出时由 `deck_renderer.py` 按 `templates/ppt_decks/deck_slots.json` 的角色+位置锚点
把生成内容填入对应文本形状，保留模板的装饰、图表与视觉设计。

| 模板 id | 模板文件 | 适用场景 |
| --- | --- | --- |
| `lessonforge_deck_academic` | `Academic_Template.pptx` | 科研、学术、深度课程 |
| `lessonforge_deck_ai_future` | `AI_Future_Template.pptx` | AI、科技、前沿课程 |
| `lessonforge_deck_business` | `Business_Template.pptx` | 商务、管理、培训课程 |
| `lessonforge_deck_cartoon` | `Cartoon_Template.pptx` | 小学、启蒙、趣味课程 |
| `lessonforge_deck_chinese_culture` | `Chinese_Culture_Template.pptx` | 人文、国学、文化课程 |
| `lessonforge_deck_smart_ai` | `Smart_AI_Template.pptx` | 智慧课堂、个性化学习 |

## 默认与回退

默认模板为 `lessonforge_deck_academic`。旧课件缺少模板标识或模板已失效（例如历史版本
引用的旧设计模板已不在目录中）时，统一回退到默认模板。

## 内容映射

`export_service` 导出 PPT 时使用 `make_deck`：依据已批准蓝图生成与 15 页槽位一一对应的
完整内容（封面/导入/目标/知识地图/核心知识/案例/讨论/总结/测验/课后任务/结课），
由 `deck_renderer` 填入成品模板。模板槽位宽松并支持填字时自动缩放字号，避免内容溢出。

## 模板重建

六套模板由 `scripts/build_generic_decks.py` 统一生成（仅配色不同），几何与
`templates/ppt_decks/deck_slots.json` 的锚点一一对应。修改版式后需重新执行
`.venv/bin/python scripts/build_generic_decks.py` 以同步槽位定义。
