"""PIL 图表 PNG 生成（柱/线/饼），作为 python-pptx 原生图表的兜底。

matplotlib/numpy 缺失时不引入新依赖；数据来自上游 Agent 的 datasets，
不得伪造数据——仅绘制给定 categories/series。
"""
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

BG = (255, 255, 255)


def _hex(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in ("/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/PingFang.ttc", "/Library/Fonts/Arial Unicode.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _series_values(series: list[dict]) -> list[float]:
    return [float(value) for value in series[0].get("values", [])] if series else []


def render_chart_png(chart_type: str, data: dict[str, Any], palette: dict[str, str],
                     size: tuple[int, int] = (960, 540), output: Path | None = None) -> Path:
    """绘制 bar/line/pie 图并保存 PNG，返回输出路径。"""
    categories = [str(item) for item in data.get("categories") or []]
    series = data.get("series") or []
    values = _series_values(series)
    if not categories or not values:
        raise ValueError("图表数据不足：需要 categories 与 series[0].values")

    width, height = size
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    primary = _hex(palette.get("primary", "#1F4E79"))
    secondary = _hex(palette.get("secondary", "#D6E4F0"))
    text = _hex(palette.get("text", "#1A1A1A"))
    muted = _hex(palette.get("muted", "#6B7280"))

    margin = {"l": 70, "r": 30, "t": 40, "b": 60}
    plot_w = width - margin["l"] - margin["r"]
    plot_h = height - margin["t"] - margin["b"]

    if chart_type == "pie":
        _draw_pie(draw, values, categories, primary, secondary, muted, width, height)
    elif chart_type == "line":
        _draw_line(draw, values, categories, primary, muted, margin, plot_w, plot_h, text)
    else:  # bar / column
        _draw_bar(draw, values, categories, primary, secondary, muted, margin, plot_w, plot_h, text)

    if output is None:
        import tempfile
        output = Path(tempfile.gettempdir()) / f"chart_{abs(hash((chart_type, tuple(values))))}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def _nice_max(values: list[float]) -> float:
    top = max(values) if values else 1.0
    if top <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(top))
    for multiplier in (1, 2, 2.5, 5, 10):
        candidate = magnitude * multiplier
        if top <= candidate:
            return candidate
    return top


def _draw_bar(draw, values, categories, primary, secondary, muted, margin, plot_w, plot_h, text):
    top = _nice_max(values)
    n = len(values)
    gap = plot_w * 0.06
    bar_w = max(8.0, (plot_w - gap * (n + 1)) / n)
    # 网格 + 刻度
    for step in range(5):
        y = margin["t"] + plot_h - plot_h * step / 4
        draw.line([(margin["l"], y), (margin["l"] + plot_w, y)], fill=(230, 233, 238), width=1)
        draw.text((margin["l"] - 8, y - 8), f"{top * step / 4:.0f}", fill=muted, font=_font(16), anchor="rm")
    for index, value in enumerate(values):
        h = max(4.0, plot_h * value / top)
        x = margin["l"] + gap + index * (bar_w + gap)
        y = margin["t"] + plot_h - h
        fill = primary if index % 2 == 0 else secondary
        draw.rectangle([x, y, x + bar_w, margin["t"] + plot_h], fill=fill)
        draw.text((x + bar_w / 2, margin["t"] + plot_h - h - 18), f"{value:.1f}", fill=text, font=_font(18), anchor="mm")
    # 分类标签（倾斜略省略）
    for index, category in enumerate(categories):
        x = margin["l"] + gap + index * (bar_w + gap) + bar_w / 2
        label = category if len(category) <= 6 else category[:5] + "…"
        draw.text((x, margin["t"] + plot_h + 12), label, fill=muted, font=_font(16), anchor="ma")


def _draw_line(draw, values, categories, primary, muted, margin, plot_w, plot_h, text):
    top = _nice_max(values)
    n = len(values)
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = margin["l"] + (plot_w * index / max(1, n - 1)) if n > 1 else margin["l"] + plot_w / 2
        y = margin["t"] + plot_h - plot_h * value / top
        points.append((x, y))
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=primary)
        draw.text((x, y - 22), f"{value:.1f}", fill=text, font=_font(18), anchor="mm")
    if len(points) > 1:
        draw.line(points, fill=primary, width=3, joint="curve")
    for index, category in enumerate(categories):
        x = margin["l"] + (plot_w * index / max(1, n - 1)) if n > 1 else margin["l"] + plot_w / 2
        label = category if len(category) <= 6 else category[:5] + "…"
        draw.text((x, margin["t"] + plot_h + 12), label, fill=muted, font=_font(16), anchor="ma")


def _draw_pie(draw, values, categories, primary, secondary, muted, width, height):
    total = sum(values) or 1.0
    box = (width * 0.12, height * 0.12, width * 0.68, height * 0.88)
    colors = [primary, secondary, (147, 130, 255), (250, 190, 120), (120, 200, 170)]
    start = 0.0
    legend_y = height * 0.2
    for index, value in enumerate(values):
        extent = 360 * value / total
        draw.pieslice(box, start=start, end=start + extent, fill=colors[index % len(colors)], outline=(255, 255, 255), width=2)
        start += extent
    for index, category in enumerate(values and categories or []):
        draw.text((width * 0.72, legend_y + index * 34), f"{category}  {values[index] if index < len(values) else ''}", fill=muted, font=_font(18))


def render_diagram_png(diagram_type: str, spec: dict[str, Any], palette: dict[str, str],
                       size: tuple[int, int] = (960, 540), output: Path | None = None) -> Path:
    """绘制流程/架构/时间线示意 PNG（PIL 绘制，无 cairosvg 依赖）。

    spec.nodes: [{id, label, detail?}]; spec.edges: [[from, to]] 或 [[from, to, label]]
    """
    width, height = size
    image = Image.new("RGB", (width, height), _hex(palette.get("background", "#FFFFFF")))
    draw = ImageDraw.Draw(image)
    primary = _hex(palette.get("primary", "#1F4E79"))
    secondary = _hex(palette.get("secondary", "#D6E4F0"))
    text = _hex(palette.get("text", "#1A1A1A"))
    nodes = spec.get("nodes") or []
    edges = spec.get("edges") or []
    if not nodes:
        nodes = [{"id": "n1", "label": "示意节点"}]

    margin = 60
    horizontal = diagram_type in {"process", "flow"}
    n = len(nodes)
    box_w = (width - 2 * margin - (n - 1) * 40) / n if horizontal else width * 0.32
    box_h = height * 0.5 if horizontal else height * 0.22
    positions: dict[str, tuple[float, float]] = {}
    center_x = width / 2
    if horizontal:
        for index, node in enumerate(nodes):
            x = margin + index * (box_w + 40)
            y = height * 0.25
            positions[node.get("id", f"n{index + 1}")] = (x + box_w / 2, y + box_h / 2)
            _diagram_node(draw, x, y, box_w, box_h, node.get("label", ""), node.get("detail", ""), primary, secondary, text)
    else:
        per_col = max(1, (n + 1) // 2)
        for index, node in enumerate(nodes):
            col = index // per_col
            row = index % per_col
            x = margin + col * (box_w + 60)
            y = height * 0.15 + row * (box_h + 60)
            positions[node.get("id", f"n{index + 1}")] = (x + box_w / 2, y + box_h / 2)
            _diagram_node(draw, x, y, box_w, box_h, node.get("label", ""), node.get("detail", ""), primary, secondary, text)
    # 连线
    for edge in edges:
        source_id = edge[0]
        target_id = edge[1]
        label = edge[2] if len(edge) > 2 else ""
        if source_id in positions and target_id in positions:
            sx, sy = positions[source_id]
            tx, ty = positions[target_id]
            draw.line([(sx, sy), (tx, ty)], fill=primary, width=2)
            mid = ((sx + tx) / 2, (sy + ty) / 2 - 10)
            if label:
                draw.text(mid, label, fill=_hex(palette.get("muted", "#6B7280")), font=_font(16), anchor="mm")
    if output is None:
        import tempfile
        output = Path(tempfile.gettempdir()) / f"diagram_{diagram_type}_{abs(hash(tuple(nodes)))}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def _diagram_node(draw, x, y, w, h, label, detail, primary, secondary, text):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=secondary, outline=primary, width=2)
    if detail:
        draw.text((x + w / 2, y + h * 0.35), label, fill=primary, font=_font(24), anchor="mm")
        draw.text((x + w / 2, y + h * 0.68), detail, fill=text, font=_font(16), anchor="mm")
    else:
        draw.text((x + w / 2, y + h / 2), label, fill=primary, font=_font(22), anchor="mm")
