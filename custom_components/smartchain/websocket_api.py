"""Websocket commands backing the SmartChain panel.

The panel never defines a form. These commands serialise the very schema the
config flow builds, so the field list has one definition rather than two.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
import voluptuous_serialize
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import translation

from .client_util import async_fetch_models, supports
from .const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    CONF_ALLOWED_TOOLS,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID,
)

_MODEL_CACHE = "panel_model_cache"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every panel command."""
    websocket_api.async_register_command(hass, ws_agent_schema)
    websocket_api.async_register_command(hass, ws_agent_save)
    websocket_api.async_register_command(hass, ws_agent_duplicate)
    websocket_api.async_register_command(hass, ws_agent_delete)
    websocket_api.async_register_command(hass, ws_overview)


def _get_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    return entry


async def _models_for(
    hass: HomeAssistant, entry: ConfigEntry, *, refresh: bool, purpose: str = CAPABILITY_CHAT
) -> list[str]:
    """Model list for an entry, fetched once and reused until asked to refresh.

    A flow dialog pays the network cost once per open. The panel would pay it on
    every click between agents, so the list is cached and an explicit refresh is
    the only invalidation. Keyed by entry id *and* purpose — a chat fetch and an
    embeddings fetch on the same entry must not serve each other's list.
    """
    cache: dict[tuple[str, str], list[str]] = hass.data.setdefault(DOMAIN, {}).setdefault(
        _MODEL_CACHE, {}
    )
    key = (entry.entry_id, purpose)
    if refresh or key not in cache:
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        cache[key] = await async_fetch_models(hass, engine, entry.data, purpose=purpose)
    return cache[key]


async def async_field_labels(hass: HomeAssistant, category: str) -> dict[str, str]:
    """Translated labels for the fields of one flow category.

    The schema's field names are exactly the keys in the integration's
    translation files, so no mapping table is needed — and none should be added,
    because a mapping table is a second place for the field list to live.

    Returns whatever it can. A field with no translation is simply absent, and
    the panel falls back to the raw name: a field added without a translation
    must still render.
    """
    resources = await translation.async_get_translations(
        hass, hass.config.language, category, [DOMAIN]
    )
    labels: dict[str, str] = {}
    for key, value in resources.items():
        # Keys look like `component.smartchain.<category>.….data.<field>`.
        marker = ".data."
        index = key.rfind(marker)
        if index == -1:
            continue
        labels.setdefault(key[index + len(marker) :], value)
    return labels


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/schema",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_agent_schema(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serialise the agent form's schema, with current values when editing."""
    from .config_flow import subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    defaults: dict[str, Any] = {}
    subentry_id = msg.get("subentry_id")
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
            connection.send_error(msg["id"], "not_found", "Unknown agent")
            return
        defaults = dict(subentry.data)

    models = await _models_for(hass, entry, refresh=msg["refresh"], purpose=CAPABILITY_CHAT)
    schema = subentry_schema(hass, entry.unique_id, defaults, models=models)

    # The schema is conditional (multi-agent tools, allowed tools, GigaChat-only
    # fields all come and go with entry state). Serving a stale key the schema
    # no longer declares would make <ha-form> echo it back, and PREVENT_EXTRA in
    # ws_agent_save would then reject it forever — see F1. Deriving the allowed
    # set from the schema itself, rather than a hand-written list, keeps this
    # correct as the schema changes.
    declared = {str(key.schema) for key in schema.schema}
    served = {name: value for name, value in defaults.items() if name in declared}

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer),
            "data": served,
            "labels": await async_field_labels(hass, "config_subentries"),
        },
    )


def _describe_invalid(err: vol.Invalid) -> str:
    """A validation message that names the offending field.

    Never `str(err)`: voluptuous embeds the value that failed, which would leak
    a credential if one were ever validated. Only the field name and a short
    reason travel.
    """
    fields = sorted(
        {str(sub.path[0]) for sub in getattr(err, "errors", [err]) if getattr(sub, "path", None)}
    )
    if not fields:
        return "invalid_data"
    return f"invalid_data: {', '.join(fields)}"


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/save",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_agent_save(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update an agent, validating exactly as the config flow does."""
    from .config_flow import agent_title, normalize_model_input, subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    subentry_id = msg.get("subentry_id")
    subentry = None
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
            connection.send_error(msg["id"], "not_found", "Unknown agent")
            return

    models = await _models_for(hass, entry, refresh=False, purpose=CAPABILITY_CHAT)
    defaults = dict(subentry.data) if subentry is not None else {}
    schema = subentry_schema(hass, entry.unique_id, defaults, models=models)

    try:
        data = dict(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    error = normalize_model_input(data)
    if error:
        connection.send_error(msg["id"], "invalid_data", error)
        return

    title = agent_title(data)
    if subentry is None:
        new = ConfigSubentry(
            data=data,
            subentry_type=SUBENTRY_TYPE_CONVERSATION,
            title=title,
            unique_id=None,
        )
        hass.config_entries.async_add_subentry(entry, new)
        connection.send_result(msg["id"], {"subentry_id": new.subentry_id})
        return

    hass.config_entries.async_update_subentry(entry, subentry, data=data, title=title)
    connection.send_result(msg["id"], {"subentry_id": subentry.subentry_id})


def _resolve_agent(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[ConfigEntry, Any] | None:
    """Entry and agent subentry named by the message, or None after sending an error."""
    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return None
    subentry = entry.subentries.get(msg["subentry_id"])
    if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
        connection.send_error(msg["id"], "not_found", "Unknown agent")
        return None
    return entry, subentry


def _unique_copy_title(entry: ConfigEntry, base: str) -> str:
    """A copy title not already in use on this entry.

    Duplicating twice must not produce two identically-titled agents — that is
    the ambiguity the suffix exists to prevent.
    """
    existing = {subentry.title for subentry in entry.subentries.values()}
    candidate = f"{base} (copy)"
    counter = 2
    while candidate in existing:
        candidate = f"{base} (copy {counter})"
        counter += 1
    return candidate


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/duplicate",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_agent_duplicate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Copy an agent, so a tuned prompt can be reused without retyping it."""
    resolved = _resolve_agent(hass, connection, msg)
    if resolved is None:
        return
    entry, subentry = resolved

    copy = ConfigSubentry(
        data=dict(subentry.data),
        subentry_type=SUBENTRY_TYPE_CONVERSATION,
        # A copy sharing the original's title is indistinguishable in a list.
        title=_unique_copy_title(entry, subentry.title),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, copy)
    connection.send_result(msg["id"], {"subentry_id": copy.subentry_id})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/delete",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_agent_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove an agent."""
    resolved = _resolve_agent(hass, connection, msg)
    if resolved is None:
        return
    entry, subentry = resolved

    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/overview"})
@websocket_api.async_response
async def ws_overview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List SmartChain entries and their conversation agents."""
    entries = [_describe_entry(hass, entry) for entry in hass.config_entries.async_entries(DOMAIN)]
    connection.send_result(msg["id"], {"entries": entries})


def _describe_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Public description of an entry.

    Assembled field by field on purpose. `entry.data` holds the provider
    credential, so forwarding it wholesale — now or by a later edit — would put
    an API key on the wire.
    """
    engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "engine": engine,
        "engine_label": UNIQUE_ID.get(engine, engine),
        "supports_embeddings": supports(engine, CAPABILITY_EMBEDDINGS),
        "agents": [
            _describe_agent(subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_CONVERSATION
        ],
    }


def _describe_agent(subentry: Any) -> dict[str, Any]:
    data = subentry.data
    model = (data.get(CONF_CHAT_MODEL_USER) or "").strip() or data.get(CONF_CHAT_MODEL, "")
    allowed = data.get(CONF_ALLOWED_TOOLS)
    return {
        "subentry_id": subentry.subentry_id,
        "title": subentry.title,
        "model": model,
        # None means "every tool"; the panel shows a dash rather than a count it
        # cannot know without building the registry.
        "tool_count": len(allowed) if allowed is not None else None,
    }
