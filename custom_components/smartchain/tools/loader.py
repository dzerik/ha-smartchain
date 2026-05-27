"""Load and validate /config/smartchain/tools.yaml."""

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import load_yaml as ha_load_yaml

from ..const import RESERVED_TOOL_NAMES
from .model import (
    CustomTool,
    RESTAction,
    ScriptAction,
    ServiceAction,
    TemplateAction,
    ToolAction,
)
from .schema import TOOLS_FILE_SCHEMA

LOGGER = logging.getLogger(__name__)


class LoaderError(Exception):
    """Raised when tools.yaml cannot be parsed or validated."""


def load_tools_file(path: Path) -> list[CustomTool]:
    """Read, validate and convert a tools.yaml file into CustomTool objects.

    Uses HA's yaml loader so `!secret` and `!include` resolve correctly.
    Returns an empty list if the file does not exist. Raises LoaderError on
    YAML parse error or schema validation failure. Duplicate-name and
    reserved-name entries are dropped with an error logged but do not raise.
    """
    if not path.is_file():
        return []

    try:
        raw = ha_load_yaml(str(path))
    except HomeAssistantError as err:
        raise LoaderError(f"tools.yaml parse error: {err}") from err

    if raw is None:
        return []

    try:
        validated = TOOLS_FILE_SCHEMA(raw)
    except vol.Invalid as err:
        raise LoaderError(f"tools.yaml validation error: {err}") from err

    out: list[CustomTool] = []
    seen: set[str] = set()
    for entry in validated["tools"]:
        name = entry["name"]
        if name in RESERVED_TOOL_NAMES:
            LOGGER.error("Tool %s uses a reserved built-in name; skipping", name)
            continue
        if name in seen:
            LOGGER.error("Duplicate tool name %s in tools.yaml; skipping later entry", name)
            continue
        seen.add(name)
        out.append(
            CustomTool(
                name=name,
                description=entry["description"],
                parameters=entry["parameters"],
                action=_action_from_dict(entry["action"]),
            )
        )
    return out


def _action_from_dict(d: dict[str, Any]) -> ToolAction:
    """Convert validated action dict into a typed ToolAction."""
    t = d["type"]
    if t == "service":
        return ServiceAction(
            domain=d["domain"],
            service=d["service"],
            target=d.get("target", {}),
            data=d.get("data", {}),
            response=d.get("response", False),
        )
    if t == "template":
        return TemplateAction(value_template=d["value_template"])
    if t == "rest":
        return RESTAction(
            method=d["method"],
            url=d["url"],
            headers=d.get("headers", {}),
            payload=d.get("payload"),
            timeout=d.get("timeout", 10),
            response_format=d.get("response_format", "text"),
        )
    if t == "script":
        return ScriptAction(
            script=d["script"],
            variables=d.get("variables", {}),
        )
    raise LoaderError(f"unknown action type {t!r}")
