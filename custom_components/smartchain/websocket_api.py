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

from .client_util import async_fetch_models, supports
from .const import (
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
    websocket_api.async_register_command(hass, ws_overview)


def _get_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    return entry


async def _models_for(hass: HomeAssistant, entry: ConfigEntry, *, refresh: bool) -> list[str]:
    """Model list for an entry, fetched once and reused until asked to refresh.

    A flow dialog pays the network cost once per open. The panel would pay it on
    every click between agents, so the list is cached and an explicit refresh is
    the only invalidation.
    """
    cache: dict[str, list[str]] = hass.data.setdefault(DOMAIN, {}).setdefault(_MODEL_CACHE, {})
    if refresh or entry.entry_id not in cache:
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        cache[entry.entry_id] = await async_fetch_models(hass, engine, entry.data)
    return cache[entry.entry_id]


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
        if subentry is None:
            connection.send_error(msg["id"], "not_found", "Unknown agent")
            return
        defaults = dict(subentry.data)

    models = await _models_for(hass, entry, refresh=msg["refresh"])
    schema = subentry_schema(hass, entry.unique_id, defaults, models=models)

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer),
            "data": defaults,
        },
    )


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
        if subentry is None:
            connection.send_error(msg["id"], "not_found", "Unknown agent")
            return

    models = await _models_for(hass, entry, refresh=False)
    defaults = dict(subentry.data) if subentry is not None else {}
    schema = subentry_schema(hass, entry.unique_id, defaults, models=models)

    try:
        data = dict(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", str(err))
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
