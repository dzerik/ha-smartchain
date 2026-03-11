"""Skill system for SmartChain — load custom skills from YAML files."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)
SKILLS_DIR = "smartchain/skills"


@dataclass
class Skill:
    """A loaded skill definition."""

    name: str
    description: str
    prompt: str


def load_skills(config_dir: str) -> list[Skill]:
    """Load all skill YAML files from the skills directory."""
    skills_path = Path(config_dir) / SKILLS_DIR
    if not skills_path.is_dir():
        return []

    skills: list[Skill] = []
    for yaml_file in sorted(skills_path.glob("*.yaml")):
        try:
            skill = _load_skill_file(yaml_file)
            if skill:
                skills.append(skill)
                LOGGER.debug("Loaded skill: %s from %s", skill.name, yaml_file.name)
        except Exception:
            LOGGER.exception("Failed to load skill from %s", yaml_file)

    LOGGER.info("Loaded %d skills from %s", len(skills), skills_path)
    return skills


def _load_skill_file(path: Path) -> Skill | None:
    """Load a single skill YAML file."""
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None

    name = data.get("name")
    prompt = data.get("prompt")
    if not name or not prompt:
        LOGGER.warning("Skill file %s missing 'name' or 'prompt'", path.name)
        return None

    return Skill(
        name=str(name),
        description=str(data.get("description", "")),
        prompt=str(prompt),
    )


def skills_to_prompt(skills: list[Skill]) -> str:
    """Format loaded skills as additional system prompt text."""
    if not skills:
        return ""

    parts = ["\n\nAdditional skills and knowledge:"]
    for skill in skills:
        header = f"\n### {skill.name}"
        if skill.description:
            header += f" — {skill.description}"
        parts.append(header)
        parts.append(skill.prompt)

    return "\n".join(parts)
