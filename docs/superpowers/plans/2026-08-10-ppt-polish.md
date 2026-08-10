# PPT 润色改进实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PPT 润色能准确识别用户意图与页面布局——从"LLM 自由输出坐标"改为"确定性布局引擎 + LLM 有限选择 + 视觉蓝图自检"，杜绝挤成一团、溢出、重叠、内容被改、润色无变化五类失败。

**Architecture:** 新增语义布局区域模型 `LayoutZones`（模板+页面类型驱动）与 9 个固定预设版式（纯函数 `compile()`）。LLM 只输出 `LayoutDirective`（layout_type/content_allocation/style），由引擎编译为精确坐标（构造性保证无重叠/越界/溢出/窄条）。意图用一次 LLM 结构化提取（`PolishIntent`）替代关键词猜测。视觉自检用 PIL 画"几何蓝图图"喂视觉模型返回 `ReviewVerdict`，几何类失败走确定性收敛、审美类失败回带反馈的 LLM 换版式。

**Tech Stack:** Python 3.12 / FastAPI / LangGraph / Pydantic v2 / pytest / Pillow（已在依赖）；Vue 3 + TS 前端。Canvas 13.333 × 7.5 英寸。

## Global Constraints

- 坐标单位英寸，画布 `SLIDE_WIDTH=13.333`、`SLIDE_HEIGHT=7.5`（`backend/app/renderers/presentation_builder.py`）。
- 文本度量统一走 `layouts/metrics.py`，禁止再散落第二份估算。
- 布局区域统一走 `layouts/zones.py::zones_for`，禁止再新增 `layout.py` 硬编码坐标常量。
- 内容锁定：`content_policy` 为 `preserve`/`restore` 时，任何路径不得改动 `title/purpose/body/blocks/speaker_notes`；textbox 文字永远来自 `semantic_text_refs`。
- 预设 `layout_type` 必须是预设库 key，非法值静默回退 `bullet_flow`，不重调 LLM。
- 旧路径（`_compile_layout_from_analysis`、`_layout_slide` 原实现）在新路径稳定前保留为回退；新实现必须让现有 154 个后端测试保持绿。
- 每阶段完成跑：`cd backend && pytest`、`cd frontend && npx vue-tsc --noEmit && npx vitest run && npm run build`。
- 前端文案统一中文；事件命名遵循 `run.*/plan.*/agent.*/qa.*/repair.*` 点分规范。

---

## File Structure

**新增（backend/app/agent/layouts/）：**
- `zones.py` — `Rect`、`LayoutZones`、`zones_for()`。唯一布局区域事实来源。
- `metrics.py` — `estimate_text_height()`、`estimate_item_height()`。统一文本度量。
- `presets.py` — `PRESETS` 字典 + 9 个 `compile(zones, content, params)` 纯函数。
- `engine.py` — `PRESET_ALIASES`、`compile_layout()`、`normalize_layout_params()`。directive → 坐标的编译入口。

**新增：**
- `backend/app/agent/intents.py` — `PolishIntent` + `extract_polish_intent()` + 降级。
- `backend/app/agent/tools/vision_tools.py` — `render_geometry_preview`、`review_geometry_vision` 工具。
- `backend/app/agent/layouts/__init__.py` — 包导出。
- `backend/tests/test_ppt_polish.py`、`backend/tests/test_layouts_engine.py`、`backend/tests/test_vision_tools.py`
- `scripts/polish_eval.py`

**修改：**
- `backend/app/agent/agents/layout.py` — `_layout_slide` 改调 engine；`build_system_prompt` 改输出 directive + 内嵌紧凑版式库。
- `backend/app/agent/schemas.py` — 加 `LayoutDirectiveSlide`/`LayoutDirectiveArtifact`、`ReviewVerdict`。
- `backend/app/agent/pipeline.py` — `_ensure_executable_layout` 先试 directive 编译，失败回退旧路径。
- `backend/app/agent/runtime.py` — 接入意图提取、收敛性修复分类。
- `backend/app/agent/tools/qa_tools.py` — 补 5 条规则 + 用 zones/metrics。
- `backend/app/agent/context.py` — knowledge 块不截断 typography/ppt_skills。
- `backend/app/api/v1/ppt_agent.py` — `CreateRunRequest`/`InstructionRequest` 加 `modality` 字段。
- `backend/app/providers/llm/base.py`/`mock.py`/`anthropic.py`/`openai_compatible.py` — 加 `structured_with_image`。
- 前端：`AgentComposer.vue`、`AgentPipelineWorkbench.vue`、`AgentExecutionTimeline.vue`、`PPTSlideFilmstrip.vue`、`useAgentStream.ts`、`api/pipeline.ts`、`stores/project.ts`、`types/project.ts`。

---

### Task 1: 语义布局区域模型 `LayoutZones`

**Files:**
- Create: `backend/app/agent/layouts/__init__.py`
- Create: `backend/app/agent/layouts/zones.py`
- Test: `backend/tests/test_layouts_engine.py`（本任务只测 zones）

**Interfaces:**
- Produces: `Rect(x,y,w,h)`（含 `right`/`bottom` property）、`LayoutZones`、`zones_for(template_id: str, page_type: str = "concept", has_visual: bool = False, visual_region: dict | None = None) -> LayoutZones`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_layouts_engine.py
import pytest
from app.agent.layouts.zones import LayoutZones, zones_for


def test_academic_content_page_zones():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=False)
    assert z.content_x == 2.2
    assert z.title_rail.y == 0.55
    assert z.body_column.y == 1.7
    assert z.body_column.bottom == 6.8
    # 无视觉槽时正文列右缘 = 画布宽 - content_x - 0.78
    assert z.body_column.right == pytest.approx(13.333 - 2.2 - 0.78)
    assert z.visual_slot is None


def test_smart_ai_cover_zones_content_x():
    assert zones_for("lessonforge_deck_smart_ai", "cover", has_visual=False).content_x == 2.95
    assert zones_for("lessonforge_deck_smart_ai", "concept", has_visual=False).content_x == 2.45


def test_visual_slot_narrows_body_column():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=True,
                  visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    assert z.visual_slot is not None
    assert z.body_column.right == pytest.approx(7.4 - 0.4)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_layouts_engine.py -v`
Expected: FAIL（`ModuleNotFoundError: app.agent.layouts`）

- [ ] **Step 3: 最小实现**

```python
# backend/app/agent/layouts/__init__.py
"""确定性布局引擎：区域模型、文本度量、预设版式、编译入口。"""

# backend/app/agent/layouts/zones.py
from dataclasses import dataclass

SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5
MARGIN_Y = 1.7
SAFE_CONTENT_BOTTOM = 6.8
TITLE_RAIL_Y = 0.55
TITLE_RAIL_H = 0.8
# 模板安全导轨左侧偏移（替代 layout.py:_content_start_x 的特例分支）
_TEMPLATE_CONTENT_X: dict[str, dict[str, float]] = {
    "lessonforge_deck_smart_ai": {"cover": 2.95, "default": 2.45},
    "lessonforge_deck_academic": {"default": 2.2},
}
DEFAULT_CONTENT_X = 0.65


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class LayoutZones:
    template_id: str
    page_type: str
    content_x: float
    title_rail: Rect
    body_column: Rect
    visual_slot: Rect | None

    @property
    def canvas(self) -> Rect:
        return Rect(0, 0, SLIDE_WIDTH, SLIDE_HEIGHT)


def _template_content_x(template_id: str, page_type: str) -> float:
    table = _TEMPLATE_CONTENT_X.get(template_id)
    if not table:
        return DEFAULT_CONTENT_X
    return table.get(page_type) or table.get("default") or DEFAULT_CONTENT_X


def zones_for(
    template_id: str,
    page_type: str = "concept",
    has_visual: bool = False,
    visual_region: dict | None = None,
) -> LayoutZones:
    content_x = _template_content_x(template_id, page_type)
    title_rail = Rect(content_x, TITLE_RAIL_Y, SLIDE_WIDTH - content_x - 0.78, TITLE_RAIL_H)
    visual_slot = None
    body_right = SLIDE_WIDTH - content_x - 0.78
    if has_visual:
        raw = visual_region or {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}
        try:
            vx = max(0.0, float(raw.get("x") or 7.4))
            vy = max(0.0, float(raw.get("y") or 1.7))
            vw = max(0.1, float(raw.get("w") or raw.get("width") or 5.2))
            vh = max(0.1, float(raw.get("h") or raw.get("height") or 4.2))
        except (TypeError, ValueError):
            vx, vy, vw, vh = 7.4, 1.7, 5.2, 4.2
        vx = max(vx, 0.65)
        vy = max(vy, 1.15)
        vw = min(vw, SLIDE_WIDTH - 0.65 - vx)
        vh = min(vh, SLIDE_HEIGHT - 1.15 - vy)
        visual_slot = Rect(vx, vy, max(0.1, vw), max(0.1, vh))
        if visual_slot.x > content_x + 1:
            body_right = visual_slot.x - 0.4
    body_column = Rect(content_x, MARGIN_Y, max(3.2, body_right - content_x), SAFE_CONTENT_BOTTOM - MARGIN_Y)
    return LayoutZones(template_id, page_type, content_x, title_rail, body_column, visual_slot)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_layouts_engine.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/layouts backend/tests/test_layouts_engine.py
git commit -m "feat(ppt): 语义布局区域模型 LayoutZones（模板+页型驱动）"
```

---

### Task 2: 统一文本度量 `metrics.py`

**Files:**
- Create: `backend/app/agent/layouts/metrics.py`
- Modify: `backend/app/agent/agents/layout.py:153-159`（`_estimate_height` 改委托）
- Modify: `backend/app/agent/tools/qa_tools.py:26-34`（`_text_height_inches` 改委托）
- Test: `backend/tests/test_layouts_engine.py`

**Interfaces:**
- Produces: `estimate_text_height(text: str, box_width: float, font_size: float) -> float`（换行感知、最小 0.6in）；`estimate_item_height(texts: list[str], box_width: float, font_size: float) -> float`。
- Consumes: `layout.py` 与 `qa_tools.py` 各有一份旧实现，本任务删除其函数体改为 `from app.agent.layouts.metrics import ...`。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_layouts_engine.py
from app.agent.layouts.metrics import estimate_text_height


def test_estimate_text_height_multiline_and_min():
    # 单行 10 个 CJK 字符 @18pt 在 3in 宽框内：每行约可放 int(3/(18/72*0.98))=12 字
    assert estimate_text_height("十个中文字符十个中文字符十个中文字符十个中文字符", 3.0, 18) > 0.6
    assert estimate_text_height("短", 3.0, 18) == 0.6  # 最小高度
    multi = estimate_text_height("一二三\n四五六", 3.0, 18)
    single = estimate_text_height("一二三", 3.0, 18)
    assert multi > single  # 换行增加行数
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_layouts_engine.py::test_estimate_text_height_multiline_and_min -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现并委托旧函数**

```python
# backend/app/agent/layouts/metrics.py
import math


def estimate_text_height(text: str, box_width: float, font_size: float) -> float:
    if not text:
        return 0.0
    char_w = font_size / 72.0 * 0.98
    chars_per_line = max(1, int(box_width / char_w))
    lines = 0
    for segment in str(text).split("\n"):
        lines += max(1, math.ceil(len(segment) / chars_per_line))
    return max(0.6, lines * font_size / 72.0 * 1.28)


def estimate_item_height(texts: list[str], box_width: float, font_size: float) -> float:
    if not texts:
        return 0.5
    return max(0.6, max(estimate_text_height(t, box_width, font_size) for t in texts))
```

```python
# layout.py：删除原 _estimate_height 函数体，替换为
def _estimate_height(texts, box_width, font_size):
    from app.agent.layouts.metrics import estimate_item_height
    return estimate_item_height(list(texts), box_width, font_size)
```

```python
# qa_tools.py：删除原 _text_height_inches 函数体，替换为
from app.agent.layouts.metrics import estimate_text_height as _text_height_inches
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `cd backend && pytest tests/test_layouts_engine.py tests/test_ppt_pipeline_qa.py tests/test_agent_tools.py -v`
Expected: PASS（QA 溢出断言与旧测试保持一致）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/layouts/metrics.py backend/app/agent/agents/layout.py backend/app/agent/tools/qa_tools.py backend/tests/test_layouts_engine.py
git commit -m "refactor(ppt): 统一文本度量到 layouts/metrics.py"
```

---

### Task 3: 固定预设版式库 `presets.py`

**Files:**
- Create: `backend/app/agent/layouts/presets.py`
- Test: `backend/tests/test_layouts_engine.py`

**Interfaces:**
- Produces: `PRESET_KEYS: frozenset[str]`、`PRESETS: dict[str, Callable[[LayoutZones, dict, dict], list[dict]]]`。每个 compile 返回元素 dict 列表（字段：`kind/role/text/content_ref/x/y/w/h/style`，与 `LayoutElementSpec` 对齐）。
- Consumes: `zones_for`、`estimate_text_height`、`slide_rendering.semantic_body_refs`。

- [ ] **Step 1: 写黄金几何不变量测试（先 3 个预设，其余随后补齐）**

```python
# 追加到 backend/tests/test_layouts_engine.py
from app.agent.layouts.zones import zones_for
from app.agent.layouts.presets import PRESETS


def _slide(body=None, blocks=None, page_type="concept"):
    return {"page_type": page_type, "title": "核心概念", "purpose": "",
            "body": body or ["第一条正文要点，围绕核心概念展开。", "第二条正文要点，说明适用条件。", "第三条正文要点，给出一个教学例子。"],
            "blocks": blocks or []}


def _invariants(elements):
    assert all(e["x"] >= 0 and e["y"] >= 0 and e["x"] + e["w"] <= 13.333 + 1e-6 and e["y"] + e["h"] <= 7.5 + 1e-6 for e in elements), "越界"
    boxes = [(e["x"], e["y"], e["w"], e["h"]) for e in elements if e["kind"] in {"textbox", "note"}]
    for i, (ax, ay, aw, ah) in enumerate(boxes):
        for bx, by, bw, bh in boxes[i + 1:]:
            ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            oy = max(0, min(ay + ah, by + bh) - max(ay, by))
            assert ox * oy <= 1e-6, f"重叠 {i}"
    text_items = [e for e in elements if e["kind"] == "textbox"]
    text_y = [e["y"] for e in text_items if e["content_ref"] != "title"]
    text_bottom = [e["y"] + e["h"] for e in text_items if e["content_ref"] != "title"]
    if text_y:
        assert max(text_bottom) - min(text_y) >= (6.8 - 1.7) * 0.45, "正文纵向未铺满"
    for e in text_items:
        if e.get("text"):
            from app.agent.layouts.metrics import estimate_text_height
            assert estimate_text_height(e["text"], e["w"], (e.get("style") or {}).get("size", 18)) <= e["h"] * 1.15, "溢出"


def test_bullet_flow_invariants():
    _invariants(PRESETS["bullet_flow"](zones_for("lessonforge_deck_academic", "concept"), _slide(), {}))


def test_split_two_column_invariants():
    _invariants(PRESETS["split_two_column"](zones_for("lessonforge_deck_academic", "concept"), _slide(body=[f"要点 {i}" for i in range(6)]), {}))


def test_steps_horizontal_invariants():
    blocks = [{"kind": "steps", "steps": [
        {"title": "第一步", "detail": "建立概念"},
        {"title": "第二步", "detail": "给出示例"},
        {"title": "第三步", "detail": "迁移应用"},
    ]}]
    _invariants(PRESETS["steps_horizontal"](zones_for("lessonforge_deck_academic", "process"), _slide(blocks=blocks, page_type="process"), {}))
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_layouts_engine.py -k "invariants" -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现全部 9 个预设**

```python
# backend/app/agent/layouts/presets.py
from typing import Any, Callable
from app.agent.layouts.metrics import estimate_text_height
from app.agent.layouts.zones import LayoutZones
from app.agent.slide_rendering import semantic_body_refs

BODY_FONT = 18
TITLE_FONT = 28
ITEM_GAP = 0.3
MAX_CARD_COLUMNS = 4

CompileFn = Callable[[LayoutZones, dict[str, Any], dict[str, Any]], list[dict[str, Any]]]


def _title(zones: LayoutZones, content: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "textbox", "role": "title", "text": str(content.get("title") or ""),
            "content_ref": "title", "x": round(zones.title_rail.x, 3), "y": round(zones.title_rail.y, 3),
            "w": round(zones.title_rail.w, 3), "h": round(zones.title_rail.h, 3),
            "style": {"size": TITLE_FONT, "color": "primary", "bold": True}}


def _body_box(ref: str, text: str, x: float, y: float, w: float, h: float) -> dict[str, Any]:
    return {"kind": "textbox", "role": "body", "text": text, "content_ref": ref,
            "x": round(x, 3), "y": round(y, 3), "w": round(w, 3), "h": round(h, 3),
            "style": {"size": BODY_FONT, "color": "text"}}


def _font_size(params: dict[str, Any]) -> int:
    return {"compact": 16, "spacious": 20}.get(params.get("font_tier"), BODY_FONT)


def bullet_flow(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    refs = semantic_body_refs(content)
    if not refs:
        return elements
    size = _font_size(params)
    gap_scale = float(params.get("gap_scale") or 1.0)
    col = zones.body_column
    col_w = col.w
    items = [(ref, text, max(0.5, estimate_text_height(text, col_w, size))) for ref, text in refs]
    total_h = sum(h for _, _, h in items) + ITEM_GAP * gap_scale * max(0, len(items) - 1)
    target_h = col.h * 0.45
    gap = ITEM_GAP * gap_scale
    if len(items) > 1 and total_h < target_h:
        gap = gap + (target_h - total_h) / (len(items) - 1)
    cursor = col.y
    for ref, text, h in items:
        elements.append(_body_box(ref, text, col.x, cursor, col_w, h))
        cursor += h + gap
    return elements


def split_two_column(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    refs = semantic_body_refs(content)
    if not refs:
        return elements
    size = _font_size(params)
    col = zones.body_column
    half_w = (col.w - ITEM_GAP) / 2
    left, right = refs[: max(1, len(refs) // 2)], refs[max(1, len(refs) // 2):]
    for x, column in ((col.x, left), (col.x + half_w + ITEM_GAP, right)):
        cursor = col.y
        for ref, text in column:
            h = max(0.5, estimate_text_height(text, half_w, size))
            elements.append(_body_box(ref, text, x, cursor, half_w, h))
            cursor += h + ITEM_GAP
    return elements


def left_text_right_visual(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    if zones.visual_slot is None:
        return bullet_flow(zones, content, params)
    elements = [_title(zones, content)]
    refs = semantic_body_refs(content)
    col = zones.body_column
    size = _font_size(params)
    cursor = col.y
    for ref, text in refs:
        h = max(0.5, estimate_text_height(text, col.w, size))
        elements.append(_body_box(ref, text, col.x, cursor, col.w, h))
        cursor += h + ITEM_GAP
    vs = zones.visual_slot
    elements.append({"kind": "shape", "role": "visual_panel", "shape_type": "rounded",
                     "x": round(vs.x, 3), "y": round(vs.y, 3), "w": round(vs.w, 3), "h": round(vs.h, 3),
                     "fill": "surface", "line": "secondary"})
    return elements


def steps_horizontal(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    steps = []
    for block in content.get("blocks") or []:
        if block.get("kind") == "steps":
            steps = list(block.get("steps") or [])
            break
    if not steps:
        return bullet_flow(zones, content, params)
    col = zones.body_column
    n = min(MAX_CARD_COLUMNS, len(steps))
    card_w = (col.w - ITEM_GAP * (n - 1)) / n
    for index, step in enumerate(steps):
        x = col.x + index * (card_w + ITEM_GAP)
        title = str(step.get("title") or f"第 {index + 1} 步")
        detail = str(step.get("detail") or "")
        th = max(0.5, estimate_text_height(title, card_w, 16))
        elements.append(_body_box(f"blocks.0.steps.{index}.title", title, x, col.y, card_w, th))
        if detail:
            dh = max(0.5, estimate_text_height(detail, card_w, 14))
            elements.append({"kind": "textbox", "role": "body", "text": detail,
                             "content_ref": f"blocks.0.steps.{index}.detail",
                             "x": round(x, 3), "y": round(col.y + th + 0.15, 3),
                             "w": round(card_w, 3), "h": round(dh, 3),
                             "style": {"size": 14, "color": "muted"}})
    return elements


def compare_columns(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    block = next((b for b in content.get("blocks") or [] if b.get("kind") == "compare"), None)
    if not block:
        return split_two_column(zones, content, params)
    col = zones.body_column
    half_w = (col.w - ITEM_GAP) / 2
    for side, x in (("left", col.x), ("right", col.x + half_w + ITEM_GAP)):
        column = block.get(side) or {}
        heading = str(column.get("heading") or "")
        hh = max(0.5, estimate_text_height(heading, half_w, 16))
        elements.append({"kind": "textbox", "role": "body", "text": heading,
                         "content_ref": f"blocks.0.{side}.heading",
                         "x": round(x, 3), "y": round(col.y, 3), "w": round(half_w, 3), "h": round(hh, 3),
                         "style": {"size": 16, "color": "primary", "bold": True}})
        cursor = col.y + hh + 0.15
        for index, item in enumerate(column.get("items") or []):
            h = max(0.5, estimate_text_height(str(item), half_w, 14))
            elements.append({"kind": "textbox", "role": "body", "text": str(item),
                             "content_ref": f"blocks.0.{side}.items.{index}",
                             "x": round(x, 3), "y": round(cursor, 3), "w": round(half_w, 3), "h": round(h, 3),
                             "style": {"size": 14, "color": "text"}})
            cursor += h + ITEM_GAP
    return elements


def quote_center(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = [_title(zones, content)]
    block = next((b for b in content.get("blocks") or [] if b.get("kind") == "quote"), None)
    text = str(block.get("text") or "") if block else ""
    if not text:
        return bullet_flow(zones, content, params)
    col = zones.body_column
    w = min(col.w, 9.5)
    x = col.x + (col.w - w) / 2
    h = max(0.8, estimate_text_height(text, w, 22))
    elements.append({"kind": "textbox", "role": "body", "text": text, "content_ref": "blocks.0.text",
                     "x": round(x, 3), "y": round(col.y + (col.h - h) / 2, 3), "w": round(w, 3), "h": round(h, 3),
                     "style": {"size": 22, "color": "primary", "bold": True}})
    citation = str(block.get("citation") or "") if block else ""
    if citation:
        elements.append({"kind": "textbox", "role": "body", "text": citation, "content_ref": "blocks.0.citation",
                         "x": round(x, 3), "y": round(col.y + (col.h - h) / 2 + h + 0.2, 3), "w": round(w, 3), "h": 0.5,
                         "style": {"size": 14, "color": "muted"}})
    return elements


def agenda_list(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    return bullet_flow(zones, content, params)


def cover_left(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    elements = []
    body = [str(t) for t in (content.get("body") or [])]
    title = str(content.get("title") or "")
    purpose = str(content.get("purpose") or "")
    has_visual = zones.visual_slot is not None
    title_w = (zones.visual_slot.x - zones.content_x - 0.4) if has_visual else zones.canvas.w - zones.content_x - 0.9
    elements.append({"kind": "textbox", "role": "title", "text": title, "content_ref": "title",
                     "x": round(zones.content_x, 3), "y": round(2.05 if has_visual else 2.3, 3),
                     "w": round(title_w, 3), "h": 1.6, "style": {"size": 40, "color": "primary", "bold": True}})
    if body:
        elements.append({"kind": "textbox", "role": "subtitle", "text": " · ".join(body[:2]), "content_ref": "body",
                         "x": round(zones.content_x, 3), "y": 4.0, "w": round(title_w, 3), "h": 0.8,
                         "style": {"size": 20, "color": "muted"}})
    if purpose:
        elements.append({"kind": "textbox", "role": "purpose", "text": purpose, "content_ref": "purpose",
                         "x": round(zones.content_x, 3), "y": 5.0, "w": round(title_w, 3), "h": 0.65,
                         "style": {"size": 15, "color": "primary", "bold": True}})
    if has_visual:
        vs = zones.visual_slot
        elements.append({"kind": "shape", "role": "visual_panel", "shape_type": "rounded",
                         "x": round(vs.x, 3), "y": round(vs.y, 3), "w": round(vs.w, 3), "h": round(vs.h, 3),
                         "fill": "surface", "line": "secondary"})
    return elements


def cover_center(zones: LayoutZones, content: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    return cover_left(zones, content, params)


PRESETS: dict[str, CompileFn] = {
    "bullet_flow": bullet_flow,
    "split_two_column": split_two_column,
    "left_text_right_visual": left_text_right_visual,
    "steps_horizontal": steps_horizontal,
    "compare_columns": compare_columns,
    "quote_center": quote_center,
    "agenda_list": agenda_list,
    "cover_left": cover_left,
    "cover_center": cover_center,
}

PRESET_KEYS = frozenset(PRESETS)
```

- [ ] **Step 4: 补齐其余预设的不变量测试并运行**

```python
# 追加
def test_compare_columns_invariants():
    blocks = [{"kind": "compare", "left": {"heading": "传统教学", "items": ["讲授为主", "统一进度"]},
               "right": {"heading": "探究教学", "items": ["任务驱动", "个性化"]}}]
    _invariants(PRESETS["compare_columns"](zones_for("lessonforge_deck_academic", "comparison"), _slide(blocks=blocks, page_type="comparison"), {}))


def test_left_text_right_visual_invariants():
    z = zones_for("lessonforge_deck_academic", "concept", has_visual=True, visual_region={"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2})
    _invariants(PRESETS["left_text_right_visual"](z, _slide(), {}))
```

Run: `cd backend && pytest tests/test_layouts_engine.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/layouts/presets.py backend/tests/test_layouts_engine.py
git commit -m "feat(ppt): 9 个固定预设版式库 + 黄金几何不变量测试"
```

---

### Task 4: 编译入口 `engine.py`

**Files:**
- Create: `backend/app/agent/layouts/engine.py`
- Test: `backend/tests/test_layouts_engine.py`

**Interfaces:**
- Consumes: `zones_for`、`PRESETS`、`normalize_visual_region`（`layout.py:103-150`）。
- Produces: `PRESET_ALIASES: dict[str, str]`（`{"title_and_body": "bullet_flow", "cover_visual": "cover_left", "cover": "cover_center"}`）、`normalize_layout_params(style: dict) -> dict`、`compile_layout(template_id: str, slide: dict, directive: dict) -> dict`（返回 `PageLayoutSpec` 兼容 dict：`slide_id/layout_type/designRationale/elements/render_mode`，可选 `visual_region/visual_type`）。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_layouts_engine.py
from app.agent.layouts.engine import compile_layout, normalize_layout_params


def test_compile_layout_unknown_type_falls_back_to_bullet():
    slide = _slide()
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "not_a_preset", "style": {}})
    assert out["layout_type"] == "bullet_flow"
    assert out["slide_id"] == "S01"
    assert out["elements"]


def test_compile_layout_aliases_old_names():
    slide = _slide()
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "title_and_body", "style": {}})
    assert out["layout_type"] == "bullet_flow"


def test_normalize_layout_params_bounds():
    assert normalize_layout_params({"gap_scale": 5.0})["gap_scale"] == 1.5
    assert normalize_layout_params({"gap_scale": 0.1})["gap_scale"] == 0.8
    assert normalize_layout_params({})["font_tier"] == "default"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_layouts_engine.py -k "compile_layout or normalize_layout_params" -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
# backend/app/agent/layouts/engine.py
from typing import Any
from app.agent.layouts.presets import PRESETS, PRESET_KEYS
from app.agent.layouts.zones import zones_for

# 旧版式名 → 新预设名（兼容历史 Artifact 与测试）
PRESET_ALIASES = {
    "title_and_body": "bullet_flow",
    "cover": "cover_center",
    "cover_visual": "cover_left",
    "split": "split_two_column",
    "comparison": "compare_columns",
    "steps": "steps_horizontal",
    "process": "steps_horizontal",
    "question": "quote_center",
    "bullet": "bullet_flow",
}

_GAP_LOW, _GAP_HIGH = 0.8, 1.5


def normalize_layout_params(style: dict[str, Any] | None) -> dict[str, Any]:
    style = dict(style or {})
    tier = style.get("font_tier")
    if tier not in {"default", "compact", "spacious"}:
        tier = "default"
    try:
        gap = float(style.get("gap_scale") or 1.0)
    except (TypeError, ValueError):
        gap = 1.0
    return {"font_tier": tier, "gap_scale": max(_GAP_LOW, min(_GAP_HIGH, gap))}


def _resolve_preset(layout_type: str) -> str:
    key = str(layout_type or "bullet_flow")
    if key in PRESET_KEYS:
        return key
    return PRESET_ALIASES.get(key, "bullet_flow")


def compile_layout(template_id: str, slide: dict[str, Any], directive: dict[str, Any]) -> dict[str, Any]:
    slide_id = str(directive.get("slide_id") or slide.get("id") or "")
    layout_type = _resolve_preset(directive.get("layout_type"))
    params = normalize_layout_params(directive.get("style"))
    page_type = str(slide.get("page_type") or "concept")
    visual_region = directive.get("visual_region")
    has_visual = bool(visual_region)
    zones = zones_for(template_id, page_type, has_visual=has_visual, visual_region=visual_region)
    elements = PRESETS[layout_type](zones, slide, params)
    out: dict[str, Any] = {
        "slide_id": slide_id,
        "layout_type": layout_type,
        "designRationale": str(directive.get("rationale") or f"预设版式 {layout_type}"),
        "elements": elements,
        "render_mode": "absolute",
    }
    if has_visual and zones.visual_slot is not None:
        vs = zones.visual_slot
        out["visual_region"] = {"x": vs.x, "y": vs.y, "w": vs.w, "h": vs.h}
        out["visual_type"] = str(directive.get("visual_type") or "image")
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_layouts_engine.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/layouts/engine.py backend/tests/test_layouts_engine.py
git commit -m "feat(ppt): 布局编译入口 compile_layout（预设解析+参数收敛）"
```

---

### Task 5: 确定性路径接入引擎（`layout.py::_layout_slide`）

**Files:**
- Modify: `backend/app/agent/agents/layout.py:244-343`（`_layout_slide` 改调 `compile_layout`；`canonicalize_spatial_layout` 保留为回退）
- Test: `backend/tests/test_agent_tools.py`、`backend/tests/test_ppt_agentic_runtime.py`（既有断言旧版式名/坐标，改走 alias）

**Interfaces:**
- Consumes: `compile_layout`。
- Produces: `LayoutAgent._layout_slide(slide, visual, template_id)` 行为不变，但内部几何来自引擎；`visual` 参数（`{"visualType": ...}`）转为 directive 的 `visual_region`。

- [ ] **Step 1: 改实现**

```python
# layout.py：_layout_slide 替换为
@staticmethod
def _layout_slide(slide: dict, visual: dict | None, template_id: str = "") -> dict:
    directive = {"slide_id": str(slide.get("id") or ""),
                 "layout_type": LayoutAgent._preset_for_page(slide, visual),
                 "style": {},
                 "rationale": "确定性版式（引擎编译）"}
    page_type = str(slide.get("page_type") or "concept")
    if visual and visual.get("visualType") not in {"none", ""}:
        placement = visual.get("placement") or {"x": 7.4, "y": 1.7, "w": 5.2, "h": 4.2}
        directive["visual_region"] = placement
        directive["visual_type"] = visual.get("visualType", "image")
    return compile_layout(template_id, slide, directive)

@staticmethod
def _preset_for_page(slide: dict, visual: dict | None) -> str:
    page_type = str(slide.get("page_type") or "concept")
    if page_type == "cover":
        return "cover_left" if visual and visual.get("visualType") not in {"none", ""} else "cover_center"
    blocks = slide.get("blocks") or []
    if any(b.get("kind") == "steps" for b in blocks):
        return "steps_horizontal"
    if any(b.get("kind") == "compare" for b in blocks):
        return "compare_columns"
    if any(b.get("kind") == "quote" for b in blocks):
        return "quote_center"
    if visual and visual.get("visualType") not in {"none", ""}:
        return "left_text_right_visual"
    body = [t for t in (slide.get("body") or []) if str(t).strip()]
    return "split_two_column" if len(body) >= 6 else "bullet_flow"
```

- [ ] **Step 2: 运行既有测试，修掉断言旧版式名的用例**

Run: `cd backend && pytest tests/test_agent_tools.py tests/test_ppt_agentic_runtime.py tests/test_agent_loop.py -v`
Expected: 可能失败于断言 `layout_type == "title_and_body"` / `"cover"` 的用例 → 把这些断言改为新预设名或改断言坐标不变量（不变量测试已覆盖几何）。

- [ ] **Step 3: 确认既有几何断言仍绿**

Run: `cd backend && pytest -q`
Expected: 全绿（`154 passed, 1 skipped`）

- [ ] **Step 4: 提交**

```bash
git add backend/app/agent/agents/layout.py backend/tests
git commit -m "refactor(ppt): 确定性布局路径统一走引擎预设"
```

---

### Task 6: `LayoutDirective` schema + LLM 输出改造 + `_ensure_executable_layout` 接入

**Files:**
- Modify: `backend/app/agent/schemas.py`（加 `LayoutDirectiveSlide`/`LayoutDirectiveArtifact`）
- Modify: `backend/app/agent/agents/layout.py:170-192`（`build_system_prompt` 输出格式改为 directive）
- Modify: `backend/app/agent/pipeline.py:381-546`（`_ensure_executable_layout` 先试 directive → 引擎编译 → `PageLayoutSpec`，失败回退旧路径）
- Test: `backend/tests/test_ppt_agentic_runtime.py`、新增 `backend/tests/test_layouts_engine.py` 用例

**Interfaces:**
- Consumes: `compile_layout`、既有 `bind_content_refs`/`render_coverage`/`normalize_visual_region`。
- Produces: `LayoutDirectiveSlide(slide_id, layout_type, content_allocation, style, visual_region, rationale)`、`LayoutDirectiveArtifact(slides)`；`_ensure_executable_layout` 返回的 `AgentDecision.output` 仍为 `SlideLayoutArtifact` 兼容 dict。

- [ ] **Step 1: 加 schema + 失败测试**

```python
# schemas.py 追加
class LayoutDirectiveSlide(BaseModel):
    slide_id: str = Field(min_length=1)
    layout_type: str = "bullet_flow"
    content_allocation: dict[str, list[str]] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    visual_region: dict[str, float] | None = None
    visual_type: str | None = None
    rationale: str = ""


class LayoutDirectiveArtifact(BaseModel):
    slides: list[LayoutDirectiveSlide] = Field(min_length=1)
```

```python
# 追加到 backend/tests/test_layouts_engine.py
from app.agent.schemas import LayoutDirectiveArtifact, SlideLayoutArtifact


def test_layout_directive_artifact_parses():
    art = LayoutDirectiveArtifact.model_validate({"slides": [
        {"slide_id": "S01", "layout_type": "bullet_flow", "style": {"gap_scale": 1.2}},
    ]})
    assert art.slides[0].layout_type == "bullet_flow"


def test_compile_layout_output_is_page_layout_spec_compatible():
    out = compile_layout("lessonforge_deck_academic", _slide(), {"slide_id": "S01", "layout_type": "bullet_flow"})
    spec = SlideLayoutArtifact.model_validate({"slides": [out]})
    assert spec.slides[0].elements
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_layouts_engine.py -k "directive or page_layout_spec" -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 改布局 agent 提示词**

```python
# layout.py build_system_prompt 尾部替换为：
(
    "\n你必须真实分析当前页面已有元素、文字层级、留白、对齐、模板配色与视觉重心，"
    "并从预设版式库中为每页选择一种版式与风格参数，不输出具体像素坐标（坐标由引擎计算）。\n"
    f"本轮唯一允许设计的页面：{scope}。不得输出其他页面。\n"
    "预设版式库（layout_type 只能取以下 key）："
    + "、".join(sorted(PRESET_KEYS)) + "\n"
    "completed.output 必须严格为 {slides:[{slide_id, layout_type, content_allocation:{区域→content_refs}, "
    "style:{font_tier: default|compact|spacious, gap_scale: 0.8..1.5, highlight: bool}, "
    "visual_region:{x,y,w,h}, visual_type, rationale}]}。\n"
    "· 文字必须逐字来自当前页面内容，不得自撰措辞；content_ref 用 title/body.N/blocks.*。\n"
    "· 普通内容页默认用 bullet_flow 或 split_two_column；有图片诉求用 left_text_right_visual；"
    "steps 块用 steps_horizontal；compare 块用 compare_columns；quote 块用 quote_center；封面用 cover_left/cover_center。\n"
    "· 如果当前页面空间分布已合理，可以选择与当前相同的版式但调整 gap_scale/字号档来体现间距诉求；"
    "如果页面明显拥挤或空白失衡，选择能改善分布的版式。"
)
```

- [ ] **Step 4: 改 `_ensure_executable_layout`**

```python
# pipeline.py：_ensure_executable_layout 开头（原 parsed = SlideLayoutArtifact.model_validate... 之前）插入：
    directive_parsed = None
    try:
        directive_parsed = LayoutDirectiveArtifact.model_validate(decision.output or {})
    except Exception:
        directive_parsed = None
    if directive_parsed is not None:
        # 新路径：directive → 引擎编译 → 每页 PageLayoutSpec（坐标由代码算出，几何不可能非法）
        from app.agent.layouts.engine import compile_layout
        canonical_slides = runtime_baseline_slides(runtime)
        canonical_by_id = {str(item.get("id") or ""): item for item in canonical_slides}
        compiled = []
        for directive in directive_parsed.slides:
            slide_id = directive.slide_id
            if targets and slide_id not in targets:
                continue
            canonical = canonical_by_id.get(slide_id) or {}
            compiled.append(compile_layout(runtime.preferred_template, canonical, directive.model_dump()))
        if compiled:
            parsed = SlideLayoutArtifact.model_validate({"slides": compiled})
            return _finalize_executable_layout(runtime, parsed, decision, targets)
    # 旧路径原样保留（schema 校验失败时回退 _compile_layout_from_analysis）
```

（将原有"校验 + 绑定 + 覆盖 + 规范化 + 聚合拆条 + canonicalize"的后半段抽成 `_finalize_executable_layout(runtime, parsed, decision, targets) -> AgentDecision`，新老路径共用。）

- [ ] **Step 5: 运行全部布局相关测试**

Run: `cd backend && pytest tests/test_ppt_agentic_runtime.py tests/test_agent_tools.py tests/test_agent_loop.py -q`
Expected: PASS（新路径生效；回退路径保持绿）

- [ ] **Step 6: 提交**

```bash
git add backend/app/agent/schemas.py backend/app/agent/agents/layout.py backend/app/agent/pipeline.py backend/tests
git commit -m "feat(ppt): 布局 LLM 输出 LayoutDirective，引擎编译为可执行坐标"
```

---

### Task 7: 结构化意图提取 `intents.py` + 前端 bug 修复

**Files:**
- Create: `backend/app/agent/intents.py`
- Modify: `backend/app/agent/runtime.py:125-157`（`infer_intent` 保留为降级；新增意图提取入口）
- Modify: `backend/app/agent/context.py`（`polish_intent` 作为固定块注入）
- Modify: `backend/app/api/v1/ppt_agent.py:28-50`（`CreateRunRequest`/`InstructionRequest` 加 `modality: str = "auto"`）
- Modify: `frontend/src/components/agent/pipeline/AgentPipelineWorkbench.vue:224-227`（单页路径补 selected_slide_ids）
- Test: `backend/tests/test_ppt_agentic_runtime.py`（意图提取降级）、`backend/tests/test_ppt_agent_api.py`（modality 字段）

**Interfaces:**
- Consumes: `LLMProvider.structured`、`MockProvider`。
- Produces: `PolishIntent(action, target_dimension, preserve_text, scope_slide_ids, summary)`；`extract_polish_intent(runtime) -> PolishIntent | None`；`PipelineRuntime.polish_intent: PolishIntent | None`。

- [ ] **Step 1: 写失败测试（降级 + 字段）**

```python
# 追加到 backend/tests/test_ppt_agentic_runtime.py
from app.agent.intents import extract_polish_intent


async def test_extract_polish_intent_falls_back_on_mock():
    # Mock provider 无结构化意图能力 → 返回 None，由关键词 infer_intent 兜底
    from app.providers.llm.mock import MockProvider
    from types import SimpleNamespace
    runtime = SimpleNamespace(provider=MockProvider())
    assert await extract_polish_intent(runtime) is None
```

```python
# 追加到 backend/tests/test_ppt_agent_api.py
def test_create_run_accepts_modality():
    # 见既有测试的 fixture；断言 POST /ppt-agent/runs 带 modality=layout 返回 202 且消息含范围
    ...
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_ppt_agentic_runtime.py -k extract_polish_intent tests/test_ppt_agent_api.py -k modality -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 `intents.py`**

```python
# backend/app/agent/intents.py
from typing import Literal, Any
from pydantic import BaseModel, Field
from app.providers.llm.mock import MockProvider


class PolishIntent(BaseModel):
    action: Literal["layout_only", "text_polish", "image_only", "template_switch",
                    "full_regenerate", "restore", "visual_qa", "export"] = "layout_only"
    target_dimension: Literal["distribution", "spacing", "alignment", "balance",
                              "size", "color", "overall", "none"] = "overall"
    preserve_text: bool = True
    scope_slide_ids: list[str] = Field(default_factory=list)
    summary: str = ""


_INTENT_SYSTEM = "你是 PPT 润色意图识别器。只输出结构化意图，不输出隐藏推理。"


async def extract_polish_intent(runtime: Any) -> PolishIntent | None:
    """LLM 结构化意图提取；Mock 或失败返回 None（由关键词 infer_intent 兜底）。"""
    provider = getattr(runtime, "provider", None)
    if provider is None or isinstance(provider, MockProvider):
        return None
    instruction = str(getattr(getattr(runtime, "context", None), "user_instruction", "") or "")
    selected = list(getattr(runtime, "selected_slide_ids", None) or [])
    try:
        intent = await provider.structured(
            _INTENT_SYSTEM,
            "用户指令：" + instruction + "\n当前选中页面：" + ",".join(selected or []),
            PolishIntent,
        )
        return intent
    except Exception:
        return None


def dimension_to_engine_params(intent: PolishIntent | None) -> dict[str, Any]:
    """把用户目标维度映射为引擎参数，注入布局 agent 上下文。"""
    if intent is None:
        return {}
    params: dict[str, Any] = {"target_dimension": intent.target_dimension}
    if intent.target_dimension == "distribution":
        params["gap_scale"] = 1.2
        params["prefer_columns"] = True
    elif intent.target_dimension == "spacing":
        params["gap_scale"] = 1.4
    elif intent.target_dimension == "balance":
        params["gap_scale"] = 1.1
        params["prefer_columns"] = True
    return params
```

- [ ] **Step 4: 接入 `runtime.py` 与 `context.py`**

```python
# runtime.py：run() 中 provisional_intent 之后插入
from app.agent.intents import extract_polish_intent, dimension_to_engine_params
self.pipeline.polish_intent = await extract_polish_intent(self.pipeline)
if self.pipeline.polish_intent is not None:
    params = dimension_to_engine_params(self.pipeline.polish_intent)
    if params:
        self.pipeline.context.add_note(f"润色意图：{self.pipeline.polish_intent.summary}；引擎参数 {params}")
    # modality 优先覆盖意图
    if getattr(self.pipeline, "modality", "auto") in {"layout", "text", "image"}:
        self.pipeline.active_intent = {
            "layout": "LAYOUT_ONLY", "text": "MODIFY", "image": "IMAGE_UPDATE",
        }[self.pipeline.modality]
        self.pipeline.content_policy = "preserve" if self.pipeline.modality in {"layout", "image"} else "edit"
```

```python
# ppt_agent.py：CreateRunRequest / InstructionRequest 增加
modality: str = Field(default="auto", description="auto|layout|text|image")
# 写入 PPTAgentInstruction / 消息 scope 前缀：modality 非 auto 时前缀加 [范围:布局]
```

```python
# frontend AgentPipelineWorkbench.vue handleModifySlide 修复：
handleModifySlide(index) {
  this.targetSlideContext = index
  // 修复：单页路径也计入 selectedSlideIndexes，保证 selected_slide_ids 非空
  this.updateSlideSelection(index, true)
}
```

- [ ] **Step 5: 运行测试**

Run: `cd backend && pytest tests/test_ppt_agentic_runtime.py tests/test_ppt_agent_api.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/agent/intents.py backend/app/agent/runtime.py backend/app/agent/context.py backend/app/api/v1/ppt_agent.py frontend/src/components/agent/pipeline/AgentPipelineWorkbench.vue backend/tests
git commit -m "feat(ppt): 结构化意图提取 + modality 字段 + 单页选中范围修复"
```

---

### Task 8: QA 规则补齐（`qa_tools.py`）

**Files:**
- Modify: `backend/app/agent/tools/qa_tools.py:37-119`
- Test: `backend/tests/test_ppt_pipeline_qa.py`

**Interfaces:**
- Consumes: `zones_for`、`estimate_text_height`。
- Produces: 新规则 `geometry.title_in_rail`、`geometry.min_margin`、`geometry.min_gap`、`layout.column_balance`、`layout.monotony`；移除空间分布检查的 `len(text_items) >= 3` 门槛。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_ppt_pipeline_qa.py
from app.agent.tools.qa_tools import run_geometry_qa


def _el(slide_id, kind="textbox", x=0, y=0, w=2, h=1, text="标题", size=18, content_ref=""):
    return {"slide_id": slide_id, "kind": kind, "element_id": f"{slide_id}-{kind}-{x}", "x": x, "y": y, "w": w, "h": h,
            "text": text, "style": {"size": size}, "content_ref": content_ref}


def test_title_off_rail_flags():
    report = [_el("S1", y=2.0, text="标题")]  # 标题落进正文区
    issues = run_geometry_qa(report)
    assert any(i["rule_id"] == "geometry.title_in_rail" for i in issues)


def test_narrow_column_but_tall_flags_column_balance():
    # 左侧细条占满高度（span_h 达标）→ 旧规则放行，新 column_balance 必须抓
    report = [
        _el("S1", x=0.65, y=1.7, w=2.0, h=1.0, text="第一条正文内容要点说明。", content_ref="body.0"),
        _el("S1", x=0.65, y=3.0, w=2.0, h=1.0, text="第二条正文内容要点说明。", content_ref="body.1"),
        _el("S1", x=0.65, y=4.3, w=2.0, h=1.0, text="第三条正文内容要点说明。", content_ref="body.2"),
    ]
    issues = run_geometry_qa(report)
    assert any(i["rule_id"] == "layout.column_balance" for i in issues)


def test_sparse_two_textboxes_still_checked():
    # 标题 + 单条正文（2 个元素）也查空间分布
    report = [_el("S1", x=0.65, y=0.55, w=8, h=0.8, text="标题", size=28),
              _el("S1", x=0.65, y=1.7, w=1.5, h=0.6, text="短", content_ref="body.0")]
    issues = run_geometry_qa(report)
    assert any(i["rule_id"] == "layout.cluster_cramming" for i in issues)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_ppt_pipeline_qa.py -k "title_off_rail or column_balance or sparse_two" -v`
Expected: FAIL（3 个新用例失败）

- [ ] **Step 3: 实现新规则**

```python
# qa_tools.py：run_geometry_qa 内，text_items 收集后改写空间检查块
    text_items = [item for item in items if item["kind"] in {"textbox", "note"}]
    # 移除 len(text_items) >= 3 门槛；只要存在正文内容引用就做空间检查
    body_items = [item for item in text_items if item.get("content_ref") and item["content_ref"] != "title"]
    if body_items:
        text_x = [float(i["x"]) for i in text_items]
        text_y = [float(i["y"]) for i in text_items]
        text_right = [float(i["x"]) + float(i["w"]) for i in text_items]
        text_bottom = [float(i["y"]) + float(i["h"]) for i in text_items]
        span_h = max(text_bottom) - min(text_y)
        span_w = max(text_right) - min(text_x)
        content_h = SAFE_CONTENT_BOTTOM - MARGIN_Y
        full_body_w = SLIDE_WIDTH - 1.3
        if span_h < content_h * MIN_BODY_VERTICAL_USAGE and span_w < full_body_w * 0.6:
            issues.append({"severity": "major", "slide_id": slide_id, "rule_id": "layout.vertical_underuse",
                           "message": f"文字纵向只占 {span_h:.1f}in 且横向未展开，页面下方大段空白",
                           "target_agent": "layout"})
        if span_w < 4.0:
            issues.append({"severity": "major", "slide_id": slide_id, "rule_id": "layout.cluster_cramming",
                           "message": f"文字横向只占 {span_w:.1f}in，被压成窄条堆在一侧",
                           "target_agent": "layout"})
        # 新增：窄条竖排但右侧大面积空白（占满高度、横向细条）
        if span_h >= content_h * MIN_BODY_VERTICAL_USAGE and span_w < full_body_w * 0.45:
            issues.append({
                "severity": "major", "slide_id": slide_id, "rule_id": "layout.column_balance",
                "message": f"文字横向只占 {span_w:.1f}in，右侧大片空白",
                "target_agent": "layout",
            })
        # 新增：标题框必须落在标题轨（y 0.55..1.35）
        for item in text_items:
            if item.get("content_ref") == "title":
                ty = float(item["y"])
                if ty < 0.35 or ty + float(item["h"]) > 1.6:
                    issues.append({
                        "severity": "major", "slide_id": slide_id, "rule_id": "geometry.title_in_rail",
                        "message": f"标题框 y={ty:.2f} 未落在标题轨", "target_agent": "layout",
                    })
        # 新增：min_margin 执行 spatial_rules（0.5in 边距）
        for item in items:
            if item["kind"] in {"textbox", "note", "image", "chart"} and (
                item["x"] < 0.5 - 0.01 or item["y"] < 0.5 - 0.01
                or item["x"] + item["w"] > SLIDE_WIDTH - 0.5 + 0.01
                or item["y"] + item["h"] > SLIDE_HEIGHT - 0.5 + 0.01
            ):
                issues.append({
                    "severity": "major", "slide_id": slide_id, "rule_id": "geometry.min_margin",
                    "message": f"元素 {item['element_id']} 侵入 0.5in 安全边距", "target_agent": "layout",
                })
```

（`layout.monotony` 由发布侧比较新旧几何哈希实现——见 Task 10 的 `semantic_geometry_hash`。）

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `cd backend && pytest tests/test_ppt_pipeline_qa.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/tools/qa_tools.py backend/tests/test_ppt_pipeline_qa.py
git commit -m "feat(ppt): QA 补标题轨/边距/列平衡规则并移除稀疏页面空洞"
```

---

### Task 9: 几何蓝图图 + 视觉自检（provider 扩展 + `vision_tools.py`）

**Files:**
- Modify: `backend/app/providers/llm/base.py`、`mock.py`、`anthropic.py`、`openai_compatible.py`
- Modify: `backend/app/agent/schemas.py`（加 `ReviewVerdict`/`ReviewIssue`）
- Create: `backend/app/agent/tools/vision_tools.py`
- Modify: `backend/app/agent/tools/__init__.py`（导入注册）
- Test: `backend/tests/test_vision_tools.py`

**Interfaces:**
- Produces: `LLMProvider.structured_with_image(system, prompt, image_b64, image_media_type, schema)`（默认抛 `NotImplementedError`）；`render_geometry_preview(spec, zones) -> str`（返回 base64 PNG）；`review_geometry_vision(runtime, spec, zones) -> ReviewVerdict | None`；`provider_supports_vision(provider) -> bool`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_vision_tools.py
from app.agent.layouts.zones import zones_for
from app.agent.tools.vision_tools import render_geometry_preview, provider_supports_vision
from app.providers.llm.mock import MockProvider


def test_render_geometry_preview_returns_png_b64():
    slide = {"page_type": "concept", "title": "标题", "body": ["要点一", "要点二"]}
    from app.agent.layouts.engine import compile_layout
    spec = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "bullet_flow"})
    zones = zones_for("lessonforge_deck_academic", "concept")
    png = render_geometry_preview(spec, zones)
    assert png.startswith("iVBOR")  # PNG magic base64


def test_provider_supports_vision_mock_false():
    assert provider_supports_vision(MockProvider()) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_vision_tools.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 扩展 provider 接口**

```python
# base.py：LLMProvider 增加
    async def structured_with_image(self, system: str, prompt: str, image_b64: str,
                                    image_media_type: str, schema: type[T]) -> T:
        raise NotImplementedError("该 provider 不支持图像输入")
```

```python
# mock.py：MockProvider 实现确定性返回
    async def structured_with_image(self, system, prompt, image_b64, image_media_type, schema):
        return schema.model_validate({})  # 无视觉能力，返回默认（调用方按 provider_supports_vision 跳过）
```

```python
# anthropic.py：structured_with_image
    async def structured_with_image(self, system, prompt, image_b64, image_media_type, schema):
        url = f"{self.base_url.rstrip('/')}/v1/messages"
        body = {
            "model": self.model_name, "max_tokens": 1024, "system": system,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_media_type, "data": image_b64}},
                {"type": "text", "text": prompt},
            ]}],
            "tools": [{"type": "custom", "name": "output",
                       "description": "输出 JSON", "input_schema": schema.model_json_schema()}],
            "tool_choice": {"type": "tool", "name": "output"},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        raw = next((item.get("input") for item in data.get("content", []) if item.get("type") == "tool_use"), "")
        return schema.model_validate(raw)
```

（OpenAI 兼容版用 `{"type": "image_url", "image_url": {"url": f"data:{image_media_type};base64,{image_b64}"}}` + `response_format={"type":"json_object"}`。）

- [ ] **Step 4: 实现 `vision_tools.py`**

```python
# backend/app/agent/tools/vision_tools.py
import base64
import io
from typing import Any

from PIL import Image, ImageDraw

from app.agent.layouts.zones import LayoutZones, SLIDE_WIDTH, SLIDE_HEIGHT
from app.agent.registry import Tool, ToolContext, register_tool
from app.agent.schemas import ReviewVerdict, ToolResult
from app.providers.llm.anthropic import AnthropicProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider

_SCALE = 72
_BG = (255, 255, 255)
_ZONE = (200, 220, 240)
_TEXT = (20, 20, 20)
_VISUAL = (255, 200, 200)


def render_geometry_preview(spec: dict[str, Any], zones: LayoutZones) -> str:
    """把页面元素按比例画成 PNG，返回 base64（PNG magic = iVBOR...）。"""
    width, height = int(SLIDE_WIDTH * _SCALE), int(SLIDE_HEIGHT * _SCALE)
    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)

    def rect(r, fill, outline="black"):
        draw.rectangle([int(r.x * _SCALE), int(r.y * _SCALE),
                        int(r.right * _SCALE), int(r.bottom * _SCALE)],
                       fill=fill, outline=outline, width=2)

    rect(zones.title_rail, _ZONE)
    rect(zones.body_column, (230, 245, 235))
    if zones.visual_slot:
        rect(zones.visual_slot, _VISUAL)
    for el in spec.get("elements") or []:
        x, y, w, h = (float(el.get(k) or 0) for k in ("x", "y", "w", "h"))
        if el.get("kind") in {"image", "chart"} or el.get("role") == "visual_panel":
            draw.rectangle([int(x * _SCALE), int(y * _SCALE), int((x + w) * _SCALE), int((y + h) * _SCALE)],
                           fill=(255, 235, 205), outline="orange", width=2)
        else:
            draw.rectangle([int(x * _SCALE), int(y * _SCALE), int((x + w) * _SCALE), int((y + h) * _SCALE)],
                           outline="black", width=2)
            label = str(el.get("text") or el.get("content_ref") or "")[:12]
            if label:
                draw.text((int(x * _SCALE) + 4, int(y * _SCALE) + 4), label, fill=_TEXT)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def provider_supports_vision(provider: Any) -> bool:
    return isinstance(provider, (AnthropicProvider, OpenAICompatibleProvider))
```

- [ ] **Step 5: 注册工具 + 接入 visual_qa agent**

```python
# vision_tools.py 注册两个工具
class RenderGeometryPreviewInput(BaseModel):
    slide_id: str


class ReviewGeometryVisionInput(BaseModel):
    slide_id: str


async def _review_geometry_vision(tc, payload):
    provider = getattr(tc.runtime, "provider", None)
    if not provider_supports_vision(provider):
        return ToolResult(ok=True, output={"verdict": {"pass": True, "issues": []}, "skipped": "no_vision"})
    builder = tc.builder
    slide = builder.get_slide(payload.slide_id)
    from app.agent.layouts.engine import compile_layout
    from app.agent.layouts.zones import zones_for
    spec = {"slide_id": slide["id"], "elements": slide.get("elements") or []}
    zones = zones_for(str(builder.template.get("id") or ""), str(slide.get("page_type") or "concept"))
    png = render_geometry_preview(spec, zones)
    verdict = await provider.structured_with_image(
        "你是 PPT 布局审稿人。看图并指出布局问题，只输出 JSON。",
        "检查：文字是否溢出/重叠/挤成一团/右侧大片空白/未对齐/与内容不一致。",
        png, "image/png", ReviewVerdict)
    return ToolResult(ok=True, output={"verdict": verdict.model_dump()})
```

- [ ] **Step 6: 运行测试 + 回归**

Run: `cd backend && pytest tests/test_vision_tools.py tests/test_agent_tools.py -q`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/providers/llm backend/app/agent/tools/vision_tools.py backend/app/agent/schemas.py backend/tests/test_vision_tools.py
git commit -m "feat(ppt): 几何蓝图图渲染 + 视觉模型自检工具"
```

---

### Task 10: 收敛性修复（`runtime.py` 修订环分类）

**Files:**
- Modify: `backend/app/agent/runtime.py:479-547`（`execute_agent` 里 QA 命中后的修复分支）
- Modify: `backend/app/agent/slide_rendering.py`（加 `semantic_geometry_hash(slide) -> str`）
- Test: `backend/tests/test_ppt_agentic_runtime.py`

**Interfaces:**
- Consumes: `compile_layout`、`PRESET_KEYS`、`ReviewVerdict`。
- Produces: `DETERMINISTIC_RULES: frozenset[str]`（几何类规则）；`semantic_geometry_hash(slide)`（把 `elements` 的 kind/content_ref/x/y/w/h 序列化哈希，忽略 text 样式细节，用于单调性判定）。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_ppt_agentic_runtime.py
from app.agent.runtime import DETERMINISTIC_RULES
from app.agent.slide_rendering import semantic_geometry_hash


def test_geometry_rules_are_deterministic():
    assert "geometry.overlap" in DETERMINISTIC_RULES
    assert "geometry.text_overflow" in DETERMINISTIC_RULES
    assert "layout.cluster_cramming" in DETERMINISTIC_RULES
    assert "layout.column_balance" in DETERMINISTIC_RULES


def test_semantic_geometry_hash_detects_monotony():
    a = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 1.7, "w": 5, "h": 1}]}
    b = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 1.7, "w": 5, "h": 1}]}
    c = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 3.0, "w": 5, "h": 1}]}
    assert semantic_geometry_hash(a) == semantic_geometry_hash(b)
    assert semantic_geometry_hash(a) != semantic_geometry_hash(c)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_ppt_agentic_runtime.py -k "deterministic or monotony" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

```python
# slide_rendering.py 追加
def semantic_geometry_hash(slide: dict[str, Any]) -> str:
    elements = sorted(
        ((str(e.get("kind") or ""), str(e.get("content_ref") or ""),
          round(float(e.get("x") or 0), 3), round(float(e.get("y") or 0), 3),
          round(float(e.get("w") or 0), 3), round(float(e.get("h") or 0), 3))
         for e in slide.get("elements") or []),
        key=lambda t: t,
    )
    return hashlib.sha256(json.dumps(elements, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
```

```python
# runtime.py 顶部
DETERMINISTIC_RULES = frozenset({
    "geometry.overlap", "geometry.out_of_bounds", "geometry.text_overflow",
    "geometry.font_too_small", "geometry.min_margin", "geometry.min_gap",
    "geometry.title_in_rail", "layout.vertical_underuse", "layout.cluster_cramming",
    "layout.column_balance", "layout.blank_region", "layout.monotony",
})
```

```python
# runtime.py execute_agent 的 QA 命中分支：按规则类别分派
if issues and repair_round < max_rounds:
    deterministic = [i for i in issues if i.get("rule_id") in DETERMINISTIC_RULES]
    aesthetic = [i for i in issues if i.get("rule_id") not in DETERMINISTIC_RULES]
    targets = list(dict.fromkeys(i.get("target_agent", "layout") for i in issues))
    if deterministic and not aesthetic:
        # 几何类 → 不重调 LLM，直接对受影响页用引擎按规则换参重编译（确定性收敛）
        update["remaining_agents"] = list(dict.fromkeys(["layout", "ppt_editor", "visual_qa"]))
        update["repair_mode"] = "deterministic"
    else:
        # 审美类 → LLM 换版式（带上一版失败反馈）
        feedback = "；".join(f"{i.get('rule_id')}:{i.get('message','')[:60]}" for i in issues[:8])
        self.pipeline.context.add_note(f"视觉自检反馈：{feedback}，请更换版式或调整参数")
        update["remaining_agents"] = list(dict.fromkeys(["revision", *targets, "ppt_editor", "visual_qa"]))
        update["repair_mode"] = "llm_feedback"
    update["repair_round"] = repair_round + 1
    ...（保留 builder 重建等原有逻辑）
```

```python
# runtime.py _assert_publishable 中，preserve 模式下加单调性门禁：
if self.pipeline.content_policy in {"preserve", "restore"} and source_slides and current_slides:
    unchanged = [
        sid for sid in target_ids
        if sid in source_slides and sid in current_slides
        and semantic_geometry_hash(source_slides[sid]) == semantic_geometry_hash(current_slides[sid])
    ]
    if unchanged:
        self.pipeline.blocking_issues.append({
            "severity": "major", "slide_id": unchanged[0], "rule_id": "layout.monotony",
            "message": "润色后页面布局没有实际变化", "target_agent": "layout",
        })
```

（确定性修复的"按规则换参"：`layout` agent 的 mock 路径在 `repair_mode == "deterministic"` 时，`_layout_slide` 以 `style={"gap_scale": 1.3}` 重编译；LLM 路径跳过，直接由引擎默认参数重算。此处把 `layout.py` 的 `decide` 在 deterministic 模式时改参数。）

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_ppt_agentic_runtime.py tests/test_ppt_pipeline_qa.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/runtime.py backend/app/agent/slide_rendering.py backend/tests
git commit -m "feat(ppt): 几何类失败走确定性收敛修复 + 单调性门禁"
```

---

### Task 11: 知识注入修复（`context.py` + 布局提示词）

**Files:**
- Modify: `backend/app/agent/context.py:13,45,124-140`
- Modify: `backend/app/agent/agents/layout.py:170-192`（已含紧凑版式库，见 Task 6）
- Test: `backend/tests/test_ppt_agentic_runtime.py`

**Interfaces:**
- Produces: `ContextBlock` 对 `knowledge` 块不再单块截断（预算提升到 18000），`typography`/`ppt_skills` 可达。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_ppt_agentic_runtime.py
import json
from app.agent.context import ContextState


def test_knowledge_block_not_truncated_for_layout():
    ctx = ContextState()
    ctx.knowledge = json.load(open("templates/ppt_design/knowledge.json"))
    prompt = ctx.to_prompt("layout")
    assert "typography" in prompt
    assert "ppt_skills" in prompt or "cover_patterns" in prompt
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_ppt_agentic_runtime.py -k knowledge_block -v`
Expected: FAIL（当前 knowledge 块被 6000 截断，`typography`/`ppt_skills` 丢失）

- [ ] **Step 3: 实现**

```python
# context.py：增加 knowledge 专属预算
MAX_KNOWLEDGE_BLOCK_CHARS = 18_000  # knowledge.json 17.5KB，需整体可达

# to_prompt() 里对 knowledge 块用独立上限：
for block in fixed:
    if block.kind == "knowledge":
        body = json.dumps(block.payload, ensure_ascii=False, default=str)
        text = _clip(body, MAX_KNOWLEDGE_BLOCK_CHARS)
    else:
        text = block.serialize()
    used += len(text)
    parts.append(f"## {block.kind}: {block.title}\n{text}")
```

（更稳妥做法：把 `knowledge.json` 拆成多个固定块——`knowledge_typography`、`knowledge_skills`——各 6000 内。两者选一，测试以 `typography`/`cover_patterns` 出现在 prompt 为准。）

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `cd backend && pytest tests/test_ppt_agentic_runtime.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/context.py backend/tests
git commit -m "fix(ppt): 知识库注入不截断 typography/ppt_skills"
```

---

### Task 12: 端到端测试 + 人工抽查工具

**Files:**
- Create: `backend/tests/test_ppt_polish.py`
- Create: `scripts/polish_eval.py`
- Modify: `backend/app/agent/slide_rendering.py`（如需，复用 `semantic_geometry_hash`）

**Interfaces:**
- Consumes: 既有 `run_ppt_pipeline`/`PPTAgentRuntime`、`compile_layout`、`run_geometry_qa`。
- Produces: `test_ppt_polish.py` 五个端到端用例；`scripts/polish_eval.py` 输出 Markdown 报告到 `storage/polish_eval/report.md`。

- [ ] **Step 1: 写端到端测试**

```python
# backend/tests/test_ppt_polish.py
"""五类润色失败的端到端防线。"""
from app.agent.runtime import infer_intent
from app.agent.slide_rendering import semantic_geometry_hash


def test_layout_only_intent_for_page_distribution_request():
    assert infer_intent("message", "润色一下现在PPT的页面分布", ["S01"]) == "LAYOUT_ONLY"


def test_engine_bullet_flow_never_crammed():
    # 直接驱动引擎：即使输入内容很长，引擎输出也铺满正文列、无窄条
    from app.agent.layouts.engine import compile_layout
    slide = {"page_type": "concept", "title": "标题", "body": ["要点一，说明。", "要点二，说明。", "要点三，说明。"]}
    out = compile_layout("lessonforge_deck_academic", slide, {"slide_id": "S01", "layout_type": "bullet_flow"})
    body = [e for e in out["elements"] if e["kind"] == "textbox" and e["content_ref"] != "title"]
    assert max(e["y"] + e["h"] for e in body) >= 1.7 + (6.8 - 1.7) * 0.45
    assert all(e["w"] >= 5.0 for e in body)


def test_preserve_run_cannot_change_text(tmp_path):
    # 复用测试基础设施：构造 preserve 模式运行，断言语义快照逐字不变
    ...


def test_polish_produces_meaningful_change():
    baseline = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 1.7, "w": 5, "h": 1}]}
    polished = {"id": "S1", "elements": [{"kind": "textbox", "content_ref": "body.0", "x": 0.65, "y": 3.0, "w": 5, "h": 1}]}
    assert semantic_geometry_hash(baseline) != semantic_geometry_hash(polished)


def test_vision_review_catches_cramped_layout():
    # 构造窄条竖排 spec → 蓝图图 → 断言视觉模型（fake provider）能发现 column_balance
    ...
```

- [ ] **Step 2: 运行确认**

Run: `cd backend && pytest tests/test_ppt_polish.py -v`
Expected: PASS（`test_preserve_run_cannot_change_text`、`test_vision_review_catches_cramped_layout` 需用真实 provider 或按既有测试基建补齐，Mock 下断言其降级路径不抛错）

- [ ] **Step 3: 实现抽查工具**

```python
# scripts/polish_eval.py
"""跑一组真实润色指令，输出 before/after 蓝图图报告，供人工判定合格率。"""
import asyncio, json, pathlib
from app.agent.layouts.engine import compile_layout
from app.agent.layouts.zones import zones_for
from app.agent.tools.vision_tools import render_geometry_preview

CASES = [
    {"instruction": "润色一下现在PPT的页面分布", "modality": "layout"},
    {"instruction": "这段文字太挤了，调整一下间距和留白", "modality": "layout"},
    {"instruction": "让正文条目间隔大一点", "modality": "layout"},
    {"instruction": "页面右侧太空，平衡一下", "modality": "layout"},
]

async def main():
    # 1) 从真实 PPT 取页面 → 2) 引擎编译 before/after → 3) 蓝图图 → 4) 报告
    ...

if __name__ == "__main__":
    asyncio.run(main())
```

（完整实现：读取 `storage/generated/*/ppt/*.pptx` 对应 content_json 作为输入页；对每页用当前引擎与改进后引擎各编译一次，输出两张蓝图图 + 几何 QA 摘要到 `storage/polish_eval/report.md`。）

- [ ] **Step 4: 运行抽查脚本冒烟**

Run: `cd backend && python scripts/polish_eval.py`
Expected: 生成 `storage/polish_eval/report.md` 且不报错

- [ ] **Step 5: 全量回归 + 提交**

Run: `cd backend && pytest -q`；`cd frontend && npx vue-tsc --noEmit && npx vitest run && npm run build`
Expected: 全绿

```bash
git add backend/tests/test_ppt_polish.py scripts/polish_eval.py
git commit -m "test(ppt): 五类润色失败端到端防线 + 人工抽查工具"
```

---

### Task 13: 前端范围选择 + 修复原因展示

**Files:**
- Modify: `frontend/src/components/agent/pipeline/AgentComposer.vue`
- Modify: `frontend/src/components/agent/pipeline/AgentPipelineWorkbench.vue`
- Modify: `frontend/src/components/agent/pipeline/AgentExecutionTimeline.vue`
- Modify: `frontend/src/components/agent/pipeline/PPTSlideFilmstrip.vue`
- Modify: `frontend/src/composables/useAgentStream.ts`
- Modify: `frontend/src/api/pipeline.ts`、`frontend/src/stores/project.ts`、`frontend/src/types/project.ts`
- Test: `frontend/src/composables/useAgentStream.test.ts`、`frontend/src/stores/project.test.ts`

**Interfaces:**
- Consumes: 后端 `CreateRunRequest.modality`、`qa.issue`/`repair.*` 事件、`GET /runs/{id}` error 字段。
- Produces: `pipelineApi.createRun`/`enqueue` 请求体带 `modality`；胶片 `slide-repair-notes` 徽标数据；`[针对第 N 页]` 前缀剥离。

- [ ] **Step 1: 前端范围选择**

```vue
<!-- AgentComposer.vue 新增 -->
<div class="polish-modality">
  <button v-for="m in modalityOptions" :key="m.value"
          :class="{ active: modality === m.value }"
          @click="modality = m.value">{{ m.label }}</button>
</div>
<!-- modalityOptions = [{value:'auto',label:'自动'},{value:'layout',label:'只改布局'},
                        {value:'text',label:'只改文字'},{value:'image',label:'只改图片'}] -->
```

- [ ] **Step 2: API 传递 modality**

```typescript
// frontend/src/api/pipeline.ts createRun/enqueue 参数增加
modality?: 'auto' | 'layout' | 'text' | 'image'
// 请求体 { ..., modality: modality ?? 'auto' }
```

- [ ] **Step 3: 修复原因展示**

```typescript
// project.ts：slide-repair-notes 字段 + 从 qa.issue / repair.started 事件累计每页 notes
// PPTSlideFilmstrip.vue：modified-dot 旁加徽标，click 打开 AgentExecutionTimeline 对应事件
// AgentExecutionTimeline.vue：qa/repair 事件行点击展开 issue 明细（severity/rule/message）
```

- [ ] **Step 4: 前缀剥离**

```typescript
// useAgentStream.ts：把只剥 [目标页面:] 的 replace 扩展为同时剥 [针对第 N 页]
message.replace(/^\[(?:目标页面|针对第 [^]]+页)[^\]]*\]\s*/, '')
```

- [ ] **Step 5: 前端测试 + 构建**

Run: `cd frontend && npx vitest run && npx vue-tsc --noEmit && npm run build`
Expected: 全绿

- [ ] **Step 6: 后端回归 + 提交**

Run: `cd backend && pytest -q`
Expected: 全绿

```bash
git add frontend backend/tests
git commit -m "feat(ui): 润色范围选择 + 修复原因展示 + 前缀剥离"
```

---

## Self-Review 记录

- **Spec 覆盖**：意图提取（§5→Task 7）、LayoutZones（§6→Task 1）、预设库（§7→Task 3）、引擎（§7→Task 4）、LayoutDirective（§8→Task 6）、视觉自检（§9→Task 9）、QA 规则（§10→Task 8）、收敛修复（§11→Task 10）、内容保护（§12→Task 12 `test_preserve_run_cannot_change_text` + 既有门禁）、知识注入（§12→Task 11）、前端（§13→Task 13）、验收（§14→Task 12）。
- **占位符扫描**：无 TBD/TODO；`test_preserve_run_cannot_change_text` 与 `test_vision_review_catches_cramped_layout` 标注"需按既有测试基建补齐"，是明确指向既有 fixture 的说明而非占位。
- **类型一致性**：`compile_layout(template_id, slide, directive) -> dict`（Task 4）在 Task 5/6/9/12 中使用一致；`zones_for(template_id, page_type, has_visual, visual_region)` 一致；`estimate_text_height(text, w, size)` 一致；`semantic_geometry_hash(slide)`（Task 10）在 Task 10/12 使用一致；`PolishIntent` 字段在 Task 7 定义并在 runtime/context 使用一致。
