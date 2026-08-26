"""One inventory of what an agent can actually do.

Until v5.4.0 an agent's tools were assembled inline in
`conversation.py::_async_handle_message` and reported — differently, and
wrongly — by `websocket_api._describe_agent`, which counted `allowed_tools`
entries and so never mentioned a single built-in. A user therefore had no
place to look that answered "what can this agent do": the six built-ins were
each governed somewhere else (two by their own switch, four by nothing at
all), and `allowed_tools` only rendered when the tools registry happened to be
non-empty.

This module is that place. `describe_agent_tools` returns every tool the agent
could have, built-in and custom, each with whether it is on and why not when
it is off; `builtin_tool_names` and `custom_tools_for` return the same sets in
the shape the runtime needs. `_async_handle_message` builds its `bind_tools`
argument from the latter two, so the report and the runtime read the same
gates and cannot drift.

Authority, decided in v5.4.0
----------------------------
`allowed_tools` is the single control. It lists built-ins alongside custom
tools, and it is authoritative for both. The two switches that used to gate a
built-in (`enable_history_tool`, `enable_multi_agent_tools`) are gone from the
agent form; `async_migrate_entry` folds their stored values into an explicit
`allowed_tools` list for every existing agent, so no agent changes behaviour
and nothing is left that could disagree with the list.

Their values are still honoured for an agent that has no `allowed_tools` key
at all — an entry whose migration has not run, or a subentry built directly by
a test or a downstream integration. That is the one legacy branch, and it is
the only reason those two constants are still read here.

Semantics of `allowed_tools`, unchanged from v4.1.0 where they overlap:

- absent (``None``) — no restriction. Every custom tool, and every built-in
  its own switch allows.
- contains ``ALL_TOOLS_SENTINEL`` — every *custom* tool. Deliberately not
  "every tool": the sentinel has always meant the custom set, and widening it
  would make "all custom tools, but not `search_memory`" inexpressible.
- otherwise — exactly the names listed, custom and built-in alike.
- empty list — nothing.

The ordering matters and is deliberate: a tool added *after* an agent was
restricted is not granted to it. That now applies to a newly added built-in
too, which is the price of making built-ins listable, and the same price the
custom set has always paid.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    ALL_TOOLS_SENTINEL,
    BUILTIN_TOOL_NAMES,
    CONF_ALLOWED_TOOLS,
    CONF_ENABLE_HISTORY_TOOL,
    CONF_ENABLE_MULTI_AGENT_TOOLS,
    CONF_LLM_HASS_API,
    CRITIQUE_TOOL_NAME,
    DEFAULT_ENABLE_HISTORY_TOOL,
    DEFAULT_ENABLE_MULTI_AGENT_TOOLS,
    DELEGATE_MANY_TOOL_NAME,
    DELEGATE_TOOL_NAME,
    DOMAIN,
    ENTITY_TOOL_NAME,
    HISTORY_TOOL_NAME,
    MEMORY_TOOL_NAME,
    SUBENTRY_TYPE_CONVERSATION,
)
from .model import CustomTool, MCPAction
from .subentry_source import SOURCE_YAML

# Where a row in the inventory comes from.
SOURCE_ASSIST = "assist"
SOURCE_BUILTIN = "builtin"
SOURCE_MCP = "mcp"

# Why a tool the agent could have is not bound right now. Machine-readable
# keys, not sentences: the panel renders them, and a sentence here would be
# untranslatable.
REASON_NOT_ALLOWED = "not_allowed"
REASON_NO_SIBLINGS = "no_siblings"
REASON_NO_MEMORY_STORE = "no_memory_store"
REASON_NO_ENTITY_STORE = "no_entity_store"
REASON_ASSIST_API = "assist_api"

# The two multi-agent tools shared one switch, so one legacy switch maps to two
# names. Splitting them in the list is strictly more expressive than the switch
# was; folding them back is only needed on the legacy path.
_MULTI_AGENT_TOOL_NAMES = (DELEGATE_MANY_TOOL_NAME, CRITIQUE_TOOL_NAME)


def sibling_agents(entry: ConfigEntry, subentry_id: str | None) -> list[dict[str, str]]:
    """The other *conversation* agents on this same config entry.

    Deliberately not "the other subentries": an embeddings binding and a memory
    store are subentries too, and delegating to one is meaningless. This is the
    same set `SmartChainConversationEntity._sibling_agents` builds, extracted so
    the inventory can answer for an agent that has no live entity — the panel
    asks about agents that may not be loaded.
    """
    if not subentry_id or not entry.subentries:
        return []
    return [
        {"name": subentry.title, "sub_id": sub_id}
        for sub_id, subentry in entry.subentries.items()
        if sub_id != subentry_id and subentry.subentry_type == SUBENTRY_TYPE_CONVERSATION
    ]


def _allowed(options: Mapping[str, Any]) -> list[str] | None:
    value = options.get(CONF_ALLOWED_TOOLS)
    if value is None:
        return None
    return list(value)


def builtin_admitted(options: Mapping[str, Any], name: str) -> bool:
    """Does this agent's `allowed_tools` admit the built-in `name`?

    Availability is a separate question — `search_memory` can be admitted and
    still not bound because no memory store exists.
    """
    allowed = _allowed(options)
    if allowed is not None:
        # The list is authoritative. The sentinel is not consulted: it means
        # "every custom tool", so a built-in still needs its own name here.
        return name in allowed
    # No list at all: the legacy shape. Only two built-ins ever had a switch;
    # the other four were unconditional.
    if name == HISTORY_TOOL_NAME:
        return bool(options.get(CONF_ENABLE_HISTORY_TOOL, DEFAULT_ENABLE_HISTORY_TOOL))
    if name in _MULTI_AGENT_TOOL_NAMES:
        return bool(options.get(CONF_ENABLE_MULTI_AGENT_TOOLS, DEFAULT_ENABLE_MULTI_AGENT_TOOLS))
    return True


def custom_admitted(options: Mapping[str, Any], name: str) -> bool:
    """Does this agent's `allowed_tools` admit the custom tool `name`?"""
    allowed = _allowed(options)
    if allowed is None:
        return True
    return ALL_TOOLS_SENTINEL in allowed or name in allowed


def materialise_allowed_tools(options: Mapping[str, Any]) -> list[str]:
    """The explicit `allowed_tools` list equivalent to this agent's legacy state.

    Used by the migration, so that after it runs the list says exactly what the
    switches used to say and the switches can be deleted. Idempotent: an agent
    that already carries a list gets it back untouched.
    """
    allowed = _allowed(options)
    custom_part = [ALL_TOOLS_SENTINEL] if allowed is None else list(allowed)
    builtin_part = [
        name
        for name in BUILTIN_TOOL_NAMES
        if name not in custom_part and builtin_admitted(options, name)
    ]
    return [*custom_part, *builtin_part]


def _memory_registry(hass: HomeAssistant) -> Any:
    return hass.data.get(DOMAIN, {}).get("memory")


def _builtin_unavailable_reason(
    hass: HomeAssistant, name: str, siblings: list[dict[str, str]]
) -> str:
    """Why this built-in cannot work right now, or "" when it can.

    Structural preconditions only — nothing here is a user preference. Each one
    mirrors a condition `_async_handle_message` applied inline before v5.4.0.
    """
    if name in (DELEGATE_TOOL_NAME, *_MULTI_AGENT_TOOL_NAMES) and not siblings:
        return REASON_NO_SIBLINGS
    registry = _memory_registry(hass)
    if name == MEMORY_TOOL_NAME and not (registry is not None and len(registry) > 0):
        return REASON_NO_MEMORY_STORE
    if name == ENTITY_TOOL_NAME and not (
        registry is not None and bool(registry.entity_store_names())
    ):
        return REASON_NO_ENTITY_STORE
    return ""


def builtin_tool_names(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str | None,
    options: Mapping[str, Any],
) -> set[str]:
    """The built-ins this agent would be bound with right now."""
    siblings = sibling_agents(entry, subentry_id)
    return {
        name
        for name in BUILTIN_TOOL_NAMES
        if builtin_admitted(options, name) and not _builtin_unavailable_reason(hass, name, siblings)
    }


def custom_tools_for(hass: HomeAssistant, options: Mapping[str, Any]) -> list[CustomTool]:
    """The registry tools this agent would be bound with right now."""
    registry = hass.data.get(DOMAIN, {}).get("tools")
    if registry is None:
        return []
    return [tool for tool in registry.all() if custom_admitted(options, tool.name)]


def _custom_source(hass: HomeAssistant, tool: CustomTool) -> str:
    if isinstance(tool.action, MCPAction):
        return SOURCE_MCP
    sources = hass.data.get(DOMAIN, {}).get("tool_sources") or {}
    return sources.get(tool.name, SOURCE_YAML)


def describe_agent_tools(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str | None,
    options: Mapping[str, Any],
    llm_api: Any = None,
) -> list[dict[str, Any]]:
    """Every tool this agent could have: `[{name, source, enabled, reason}]`.

    Includes the ones that are off, which is the point — a list of only the
    live tools answers "what is on" but never "what could be on, and what is
    stopping it".

    `llm_api` is the live `chat_log.llm_api` when there is one. Without it the
    Home Assistant Assist API cannot be expanded into its individual tools —
    that expansion needs a conversation context that does not exist while a
    panel is merely describing an agent — so one row stands for the whole API,
    with `reason` `assist_api`. Assist tools are never filtered by
    `allowed_tools`: which entities and intents Assist exposes is Home
    Assistant's own setting, and shadowing it here would give the same switch
    two homes again.
    """
    rows: list[dict[str, Any]] = []

    if llm_api is not None:
        rows.extend(
            {"name": tool.name, "source": SOURCE_ASSIST, "enabled": True, "reason": ""}
            for tool in llm_api.tools
        )
    else:
        for api_id in _configured_llm_apis(options):
            rows.append(
                {
                    "name": api_id,
                    "source": SOURCE_ASSIST,
                    "enabled": True,
                    "reason": REASON_ASSIST_API,
                }
            )

    siblings = sibling_agents(entry, subentry_id)
    for name in BUILTIN_TOOL_NAMES:
        reason = _builtin_unavailable_reason(hass, name, siblings)
        if not reason and not builtin_admitted(options, name):
            reason = REASON_NOT_ALLOWED
        rows.append(
            {
                "name": name,
                "source": SOURCE_BUILTIN,
                "enabled": not reason,
                "reason": reason,
            }
        )

    registry = hass.data.get(DOMAIN, {}).get("tools")
    for tool in registry.all() if registry is not None else []:
        admitted = custom_admitted(options, tool.name)
        rows.append(
            {
                "name": tool.name,
                "source": _custom_source(hass, tool),
                "enabled": admitted,
                "reason": "" if admitted else REASON_NOT_ALLOWED,
            }
        )

    return rows


def _configured_llm_apis(options: Mapping[str, Any]) -> Iterable[str]:
    value = options.get(CONF_LLM_HASS_API)
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)
