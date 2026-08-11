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
