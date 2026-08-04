import json
from functools import lru_cache
from pathlib import Path
from typing import Any

KNOWLEDGE_PATH = Path(__file__).resolve().parents[3] / "templates" / "ppt_design" / "knowledge.json"
REQUIRED_SECTIONS = {
    "version", "design_principles", "page_type_guidance", "density_limits",
    "layout_library", "visual_suggestion_guidelines", "diagram_guidance", "quality_checklist",
}
DENSITY_LIMIT_KEYS = ("title_chars", "body_chars", "body_items", "item_chars", "speaker_notes_chars")


@lru_cache(maxsize=1)
def load_ppt_design_knowledge() -> dict[str, Any]:
    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    if not knowledge.get("version") or not REQUIRED_SECTIONS.issubset(knowledge):
        raise RuntimeError("PPT 设计知识库缺少必要区块")
    limits = knowledge["density_limits"]
    if any(not isinstance(limits.get(key), int) or limits[key] <= 0 for key in DENSITY_LIMIT_KEYS):
        raise RuntimeError("PPT 设计知识库密度上限无效")
    if not isinstance(knowledge["layout_library"], dict) or not knowledge["layout_library"]:
        raise RuntimeError("PPT 设计知识库缺少版式库")
    return knowledge
