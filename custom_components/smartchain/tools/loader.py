"""Load and validate /config/smartchain/tools.yaml."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import load_yaml as ha_load_yaml

from ..const import RESERVED_TOOL_NAMES
from .mcp.config import HTTPConfig, MCPServerConfig, SSEConfig, StdioConfig
from .memory.config import BackendConfig, LogbookConfig, MemorySettings, StoreConfig
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


@dataclass(frozen=True)
class LoaderResult:
    """Combined result of parsing tools.yaml."""

    yaml_tools: list[CustomTool] = field(default_factory=list)
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    memory_settings: MemorySettings = field(default_factory=MemorySettings)


def load_tools_file(path: Path) -> LoaderResult:
    """Read, validate and convert a tools.yaml file into CustomTool objects.

    Uses HA's yaml loader so `!secret` and `!include` resolve correctly.
    Returns an empty list if the file does not exist. Raises LoaderError on
    YAML parse error or schema validation failure. Duplicate-name and
    reserved-name entries are dropped with an error logged but do not raise.
    """
    if not path.is_file():
        return LoaderResult()

    try:
        raw = ha_load_yaml(str(path))
    except HomeAssistantError as err:
        raise LoaderError(f"tools.yaml parse error: {err}") from err

    if raw is None:
        return LoaderResult()

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
    return LoaderResult(
        yaml_tools=out,
        mcp_servers=_servers_from_validated(validated),
        memory_settings=_memory_from_validated(validated),
    )


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


def _servers_from_validated(validated: dict) -> list[MCPServerConfig]:
    """Convert validated `mcp_servers` block into MCPServerConfig dataclasses."""
    out: list[MCPServerConfig] = []
    for s in validated.get("mcp_servers", []) or []:
        out.append(_server_from_dict(s))
    return out


def _server_from_dict(d: dict) -> MCPServerConfig:
    transport = d["transport"]
    common = {
        "name": d["name"],
        "prefix": d.get("prefix"),
        "include_tools": list(d.get("include_tools") or []),
        "exclude_tools": list(d.get("exclude_tools") or []),
        "enabled": d.get("enabled", True),
    }
    if transport == "stdio":
        return StdioConfig(
            **common,
            command=d["command"],
            args=list(d.get("args") or []),
            env=dict(d.get("env") or {}),
        )
    if transport == "sse":
        return SSEConfig(
            **common,
            url=d["url"],
            headers=dict(d.get("headers") or {}),
            timeout=d.get("timeout", 30),
            verify_ssl=d.get("verify_ssl", True),
        )
    if transport == "http":
        return HTTPConfig(
            **common,
            url=d["url"],
            headers=dict(d.get("headers") or {}),
            timeout=d.get("timeout", 30),
            verify_ssl=d.get("verify_ssl", True),
        )
    raise LoaderError(f"unsupported transport {transport!r}")


def _memory_from_validated(validated: dict) -> MemorySettings:
    """Build MemorySettings from the validated `memory:` block."""
    raw = validated.get("memory") or {}
    stores: list[StoreConfig] = []
    for entry in raw.get("stores") or []:
        backend_raw = entry.get("backend") or {}
        logbook_raw = entry.get("ingest_logbook") or {}
        stores.append(
            StoreConfig(
                name=entry["name"],
                embeddings=entry["embeddings"],
                description=entry.get("description", ""),
                backend=BackendConfig(
                    type=backend_raw.get("type", "sqlite_numpy"),
                    path=backend_raw.get("path"),
                    dsn=backend_raw.get("dsn"),
                    table=backend_raw.get("table"),
                    url=backend_raw.get("url"),
                    api_key=backend_raw.get("api_key"),
                    collection=backend_raw.get("collection"),
                    verify_ssl=backend_raw.get("verify_ssl", True),
                ),
                retention_days=entry.get("retention_days", 90),
                ingest_conversation=entry.get("ingest_conversation", True),
                logbook=LogbookConfig(
                    enabled=logbook_raw.get("enabled", False),
                    domains=list(logbook_raw.get("domains") or []),
                    poll_interval_minutes=logbook_raw.get("poll_interval_minutes", 60),
                ),
            )
        )
    return MemorySettings(stores=stores)
