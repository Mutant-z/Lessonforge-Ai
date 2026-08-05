from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_PPT_TEMPLATE_ID = "lessonforge_deck_academic"
CATALOG_PATH = Path(__file__).resolve().parents[3] / "templates" / "pptx" / "catalog.json"
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
REQUIRED_PALETTE_KEYS = {
    "background", "surface", "primary", "secondary", "text", "muted", "on_primary",
}
REQUIRED_TYPOGRAPHY_KEYS = {"heading", "body", "latin"}


@lru_cache(maxsize=1)
def load_ppt_template_catalog() -> dict[str, Any]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    templates = catalog.get("templates") or []
    if not catalog.get("version") or not templates:
        raise RuntimeError("PPT 模板目录缺少版本或模板")
    seen: set[str] = set()
    for template in templates:
        template_id = template.get("id")
        if not template_id or template_id in seen:
            raise RuntimeError("PPT 模板目录包含空标识或重复标识")
        seen.add(template_id)
        if not template.get("name") or not template.get("composition"):
            raise RuntimeError(f"PPT 模板 {template_id} 缺少名称或构图策略")
        template_file = template.get("file")
        template_path = CATALOG_PATH.parent / str(template_file or "")
        if not template_file or template_path.suffix.lower() != ".pptx" or not template_path.is_file():
            raise RuntimeError(f"PPT 模板 {template_id} 缺少可用的 PPTX 文件")
        palette = template.get("palette") or {}
        typography = template.get("typography") or {}
        if set(palette) != REQUIRED_PALETTE_KEYS or any(not HEX_COLOR.fullmatch(value) for value in palette.values()):
            raise RuntimeError(f"PPT 模板 {template_id} 的颜色配置无效")
        if set(typography) != REQUIRED_TYPOGRAPHY_KEYS or any(not value for value in typography.values()):
            raise RuntimeError(f"PPT 模板 {template_id} 的字体配置无效")
    if DEFAULT_PPT_TEMPLATE_ID not in seen:
        raise RuntimeError("PPT 模板目录缺少默认模板")
    return catalog


def list_ppt_templates() -> list[dict[str, Any]]:
    return load_ppt_template_catalog()["templates"]


def ppt_template_catalog_version() -> str:
    return str(load_ppt_template_catalog()["version"])


def get_ppt_template(template_id: str | None) -> dict[str, Any] | None:
    if not template_id:
        return None
    return next((item for item in list_ppt_templates() if item["id"] == template_id), None)


def resolve_ppt_template(template_id: str | None) -> dict[str, Any]:
    return get_ppt_template(template_id) or get_ppt_template(DEFAULT_PPT_TEMPLATE_ID)  # type: ignore[return-value]
