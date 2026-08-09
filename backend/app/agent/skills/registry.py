"""Filesystem skill registry.

Only YAML frontmatter is indexed during discovery. The instruction body is read only
when a selected skill is loaded, keeping prompt and startup costs bounded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    version: str
    description: str
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    priority: int = 0
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    outputs_schema: dict[str, Any] = field(default_factory=dict)
    tools_required: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    estimated_cost: str = "low"
    path: Path = Path()

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "description": self.description,
            "capabilities": list(self.capabilities), "tags": list(self.tags),
            "priority": self.priority, "inputs_schema": self.inputs_schema,
            "outputs_schema": self.outputs_schema, "tools_required": list(self.tools_required),
            "constraints": list(self.constraints), "estimated_cost": self.estimated_cost,
        }


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if value.isdigit():
        return int(value)
    return value.strip("\"'")


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md 缺少 YAML frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ValueError("SKILL.md frontmatter 未闭合")
    header, body = text[4:marker], text[marker + 5:]
    data: dict[str, Any] = {}
    active_list: str | None = None
    for raw in header.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and active_list:
            data.setdefault(active_list, []).append(_scalar(line[4:]))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        parsed = _scalar(value)
        if parsed == "":
            data[key] = []
            active_list = key
        else:
            data[key] = parsed
            active_list = None
    return data, body.strip()


class SkillRegistry:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parent
        self._metadata: dict[str, SkillMetadata] = {}
        self._loaded: dict[str, str] = {}

    def index(self, *, force: bool = False) -> list[SkillMetadata]:
        if self._metadata and not force:
            return list(self._metadata.values())
        self._metadata = {}
        for path in sorted(self.root.glob("*/SKILL.md")):
            raw = path.read_text(encoding="utf-8")
            data, _ = _frontmatter(raw)
            name = str(data.get("name") or path.parent.name)
            metadata = SkillMetadata(
                name=name, version=str(data.get("version") or "1.0.0"),
                description=str(data.get("description") or ""),
                capabilities=tuple(data.get("capabilities") or ()),
                tags=tuple(data.get("tags") or ()), priority=int(data.get("priority") or 0),
                inputs_schema=data.get("inputs_schema") if isinstance(data.get("inputs_schema"), dict) else {},
                outputs_schema=data.get("outputs_schema") if isinstance(data.get("outputs_schema"), dict) else {},
                tools_required=tuple(data.get("tools_required") or ()),
                constraints=tuple(data.get("constraints") or ()),
                estimated_cost=str(data.get("estimated_cost") or "low"), path=path,
            )
            if name in self._metadata:
                raise ValueError(f"Skill 重复注册：{name}")
            self._metadata[name] = metadata
        return list(self._metadata.values())

    def all_metadata(self) -> list[SkillMetadata]:
        return sorted(self.index(), key=lambda item: (-item.priority, item.name))

    def discover(self, capabilities: list[str], *, limit: int = 6) -> list[SkillMetadata]:
        wanted = {item.lower() for item in capabilities if item}
        scored: list[tuple[int, SkillMetadata]] = []
        for item in self.all_metadata():
            haystack = {value.lower() for value in (*item.capabilities, *item.tags, item.name)}
            overlap = len(wanted & haystack)
            if overlap:
                scored.append((overlap * 100 + item.priority, item))
        return [item for _, item in sorted(scored, key=lambda row: (-row[0], row[1].name))[:limit]]

    def load(self, name: str) -> str:
        if name in self._loaded:
            return self._loaded[name]
        metadata = self._metadata.get(name) or next((x for x in self.index() if x.name == name), None)
        if metadata is None:
            raise KeyError(f"未知 Skill：{name}")
        _, body = _frontmatter(metadata.path.read_text(encoding="utf-8"))
        self._loaded[name] = body
        return body

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.index()
    return registry

