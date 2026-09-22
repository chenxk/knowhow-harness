"""Load SKILL.md files. The body is used only after a skill is selected."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    tool: str
    triggers: tuple[str, ...]
    body: str


def load_skills(directory: Path) -> list[Skill]:
    """Read each `skills/<name>/SKILL.md`. An empty directory is a startup error."""
    paths = sorted(directory.glob("*/SKILL.md"))
    if not paths:
        raise RuntimeError(f"no skills in {directory}")
    return [_parse_skill(path) for path in paths]


def guidance_for(tool_name: str, skills: list[Skill]) -> str:
    """Return the selected skill body. Unknown tools carry no guidance."""
    if not tool_name:
        return ""
    for skill in skills:
        if skill.tool == tool_name:
            return skill.body
    return ""


def _parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise RuntimeError(f"{path} is missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise RuntimeError(f"{path} frontmatter is not closed")
    loaded = yaml.safe_load(parts[1])
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} frontmatter must be a mapping")
    name = _text(loaded.get("name"), path, "name")
    description = _text(loaded.get("description"), path, "description")
    tool = _text(loaded.get("tool"), path, "tool")
    body = parts[2].strip()
    if not body:
        raise RuntimeError(f"{path} body is empty")
    triggers = loaded.get("triggers") or []
    if not isinstance(triggers, list) or not all(
        isinstance(item, str) and item for item in triggers
    ):
        raise RuntimeError(f"{path} triggers must be a list of strings")
    return Skill(
        name=name,
        description=description,
        tool=tool,
        triggers=tuple(triggers),
        body=body,
    )


def _text(value: object, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{path} field {field} must be a non-empty string")
    return value.strip()
