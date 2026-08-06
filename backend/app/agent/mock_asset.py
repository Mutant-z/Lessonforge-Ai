"""确定性占位图生成（mock 图片工具）。

真实图片生成（exercise_visual_service.generate_image）需要配置图片模型；
本地/测试环境用 PIL 按模板配色生成带标签的占位图，保证 PPT 编辑工具、
图片落盘与 QA 全链路可跑通。
"""
from pathlib import Path

from PIL import Image, ImageDraw


def _hex(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def generate_placeholder_image(
    prompt: str,
    palette: dict[str, str],
    size: tuple[int, int] = (1024, 768),
    output: Path | None = None,
) -> tuple[Path, int, int]:
    """生成与模板配色一致的占位图（左上主色块 + 提示词标签）。"""
    width, height = size
    image = Image.new("RGB", (width, height), _hex(palette.get("background", "#FFFFFF")))
    draw = ImageDraw.Draw(image)
    primary = _hex(palette.get("primary", "#1F4E79"))
    secondary = _hex(palette.get("secondary", "#D6E4F0"))
    surface = _hex(palette.get("surface", "#F4F7FB"))
    # 几何占位：主色对角线斜条 + 副色圆
    draw.rectangle([0, 0, int(width * 0.12), height], fill=primary)
    draw.ellipse([int(width * 0.55), int(height * 0.18), int(width * 0.82), int(height * 0.62)], fill=secondary)
    draw.rectangle([int(width * 0.18), int(height * 0.68), int(width * 0.82), int(height * 0.72)], fill=surface)
    label = (prompt or "示意图")[:36]
    draw.text((int(width * 0.2), int(height * 0.79)), label, fill=_hex(palette.get("muted", "#6B7280")))
    if output is None:
        import tempfile
        output = Path(tempfile.gettempdir()) / "ppt_asset_placeholder.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output, width, height
