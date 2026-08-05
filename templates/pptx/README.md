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

`export_service` 导出 PPT 时使用 `make_deck(bp, template_id)`：依据已批准蓝图生成与模板槽位
一一对应的内容，并按所选模板的槽位数整形（卡片模板条目更少、列表模板更多）；
由 `deck_renderer` 按模板 id 读取各自的槽位几何并填字。每套模板是**独立的视觉设计系统**
（封面/分栏/卡片/装饰/排版都不同），而不是只换配色。

## 模板重建

六套模板由 `scripts/build_generic_decks.py` 生成，每套使用独立设计系统，几何与
`templates/ppt_decks/deck_slots.json`（按模板存储）的锚点一一对应。修改版式后需重新执行
`.venv/bin/python scripts/build_generic_decks.py` 以同步槽位定义。

## PPT 设计技能

PPT Agent 的设计知识在 `templates/ppt_design/knowledge.json`，其中 `ppt_skills` 提供了
封面模式、版式模式、视觉技法、数据图示，以及每套模板的版式说明；Agent 依据所选模板
生成与之匹配的页面结构、layout 与 visual_suggestion。
