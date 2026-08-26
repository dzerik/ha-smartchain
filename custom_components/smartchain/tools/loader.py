"""Load and validate /config/smartchain/tools.yaml."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import Secrets
from homeassistant.util.yaml import load_yaml as ha_load_yaml

from ..const import RESERVED_TOOL_NAMES
from .mcp.config import HTTPConfig, MCPServerConfig, SSEConfig, StdioConfig
from .memory.config import (
    BackendConfig,
    EntitySourceConfig,
    LogbookConfig,
    MemorySettings,
    StoreConfig,
)
from .model import (
    ACTION_DEFAULT_TIMEOUT,
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


# List sections whose entries carry a `name`, so a validation failure inside
# one can be reported by name instead of by index.
_NAMED_SECTIONS = ("tools", "mcp_servers")


def _locate(raw: object, err: vol.Invalid) -> str:
    """Return a `tool 'weather': ` prefix for an error inside a named entry.

    Voluptuous reports the position — `... @ data['tools'][3]['parameters']` —
    and nobody counts list items in a file they wrote by hand. The name is read
    back out of the RAW mapping, because validation aborted and there is no
    validated copy to read it from. Anything unexpected yields an empty prefix:
    this decorates the error, it must never replace or suppress it.
    """
    path = list(err.path)
    if len(path) < 2 or path[0] not in _NAMED_SECTIONS or not isinstance(path[1], int):
        return ""
    if not isinstance(raw, dict):
        return ""
    section = raw.get(path[0])
    if not isinstance(section, list) or not 0 <= path[1] < len(section):
        return ""
    entry = section[path[1]]
    if not isinstance(entry, dict):
        return ""
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return ""
    label = "tool" if path[0] == "tools" else "mcp_server"
    return f"{label} {name!r}: "


def load_tools_file(path: Path, config_dir: Path | None = None) -> LoaderResult:
    """Read, validate and convert a tools.yaml file into CustomTool objects.

    Uses HA's yaml loader, so `!include` resolves. `!secret` resolves too, but
    only when `config_dir` is supplied: HA's loader needs a `Secrets` store
    rooted at the configuration directory, and without one it fails the whole
    file with "Secrets not supported in this YAML file". Callers inside Home
    Assistant pass `Path(hass.config.config_dir)`; the default keeps the
    no-secrets behaviour for standalone callers.

    Both `Secrets` construction and its lookups are plain blocking file I/O, so
    this stays safe to run in an executor.

    Returns an empty result if the file does not exist. Raises LoaderError on
    YAML parse error or schema validation failure. Duplicate-name and
    reserved-name entries are dropped with an error logged but do not raise.
    """
    if not path.is_file():
        return LoaderResult()

    secrets = Secrets(config_dir) if config_dir is not None else None
    try:
        # HA renders a missing secret as "Secret <name> not defined" — the name,
        # never the value — so this message is safe to surface to the user.
        raw = ha_load_yaml(str(path), secrets)
    except HomeAssistantError as err:
        raise LoaderError(f"tools.yaml parse error: {err}") from err

    if raw is None:
        return LoaderResult()

    try:
        validated = TOOLS_FILE_SCHEMA(raw)
    except vol.Invalid as err:
        raise LoaderError(f"tools.yaml validation error: {_locate(raw, err)}{err}") from err

    out: list[CustomTool] = []
    seen: set[str] = set()
    disabled_count = 0
    for entry in validated["tools"]:
        name = entry["name"]
        if name in RESERVED_TOOL_NAMES:
            LOGGER.error("Tool %s uses a reserved built-in name; skipping", name)
            continue
        if name in seen:
            LOGGER.error("Duplicate tool name %s in tools.yaml; skipping later entry", name)
            continue
        # Skip before claiming the name. A disabled tool does not exist for this
        # run, so it must not reserve its name against an enabled one — otherwise
        # switching a tool off and adding its replacement under the same name
        # silently drops the replacement as a duplicate.
        if not entry.get("enabled", True):
            disabled_count += 1
            continue
        seen.add(name)
        out.append(
            CustomTool(
                name=name,
                description=entry["description"],
                parameters=entry["parameters"],
                action=action_from_dict(entry["action"]),
                enabled=True,
            )
        )
    if disabled_count:
        LOGGER.info("Skipped %d disabled tool(s) in tools.yaml", disabled_count)
    return LoaderResult(
        yaml_tools=out,
        mcp_servers=_servers_from_validated(validated),
        memory_settings=_memory_from_validated(validated),
    )


def action_from_dict(d: dict[str, Any]) -> ToolAction:
    """Convert a validated action dict into a typed ToolAction.

    Public because `tools/subentry_source.py` builds a subentry tool with this
    same function: two sources, one dataclass, so nothing downstream can tell
    a YAML tool from a form-built one.
    """
    t = d["type"]
    if t == "service":
        return ServiceAction(
            domain=d["domain"],
            service=d["service"],
            target=d.get("target", {}),
            data=d.get("data", {}),
            response=d.get("response", False),
            timeout=d.get("timeout", ACTION_DEFAULT_TIMEOUT),
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
            timeout=d.get("timeout", ACTION_DEFAULT_TIMEOUT),
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
        source_raw = entry.get("source")
        source = (
            EntitySourceConfig(
                type=source_raw["type"],
                preset=source_raw.get("preset", "optimal"),
                index_states=source_raw.get("index_states", False),
                include=list(source_raw.get("include") or []),
                exclude=list(source_raw.get("exclude") or []),
            )
            if isinstance(source_raw, dict)
            else None
        )
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
                source=source,
            )
        )
    return MemorySettings(stores=stores)
