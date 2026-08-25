"""Websocket commands backing the SmartChain panel.

The panel never defines a form. These commands serialise the very schema the
config flow builds, so the field list has one definition rather than two.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
import voluptuous_serialize
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .client_util import async_fetch_models
from .const import CONF_ENGINE, DOMAIN, ID_GIGACHAT

_MODEL_CACHE = "panel_model_cache"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every panel command."""
    websocket_api.async_register_command(hass, ws_agent_schema)


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
