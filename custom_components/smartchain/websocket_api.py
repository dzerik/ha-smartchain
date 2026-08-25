"""Websocket commands backing the SmartChain panel.

The panel never defines a form. These commands serialise the very schema the
config flow builds, so the field list has one definition rather than two.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import voluptuous as vol
import voluptuous_serialize
import yaml
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
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
    SUBENTRY_TYPE_EMBEDDINGS,
    UNIQUE_ID,
)
from .tools.loader import LoaderError, load_tools_file
from .tools.memory.registry import MemoryRegistry

LOGGER = logging.getLogger(__name__)

_MODEL_CACHE = "panel_model_cache"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every panel command."""
    websocket_api.async_register_command(hass, ws_agent_schema)
    websocket_api.async_register_command(hass, ws_agent_save)
    websocket_api.async_register_command(hass, ws_settings_get)
    websocket_api.async_register_command(hass, ws_settings_save)
    websocket_api.async_register_command(hass, ws_agent_duplicate)
    websocket_api.async_register_command(hass, ws_agent_delete)
    websocket_api.async_register_command(hass, ws_embeddings_schema)
    websocket_api.async_register_command(hass, ws_embeddings_save)
    websocket_api.async_register_command(hass, ws_embeddings_delete)
    websocket_api.async_register_command(hass, ws_overview)
    websocket_api.async_register_command(hass, ws_tools_get)
    websocket_api.async_register_command(hass, ws_tools_validate)
    websocket_api.async_register_command(hass, ws_tools_reload)
    websocket_api.async_register_command(hass, ws_tools_save)
    websocket_api.async_register_command(hass, ws_tools_rollback)


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


async def _async_field_texts(
    hass: HomeAssistant, category: str, marker: str, *, subentry_type: str | None = None
) -> dict[str, str]:
    """Shared walk behind `async_field_labels` and `async_field_descriptions`.

    Both are "translated text for the fields of one flow, not a whole
    category" — one reading `.data.<field>` keys (labels), the other
    `.data_description.<field>` keys (helper text). Only the marker differs,
    so the scoping logic — the `subentry_type` prefix, the F1 story below —
    lives once rather than twice.
    """
    resources = await translation.async_get_translations(
        hass, hass.config.language, category, [DOMAIN]
    )
    prefix = f"component.{DOMAIN}.{category}.{subentry_type}." if subentry_type else None
    texts: dict[str, str] = {}
    for key, value in resources.items():
        if prefix is not None and not key.startswith(prefix):
            continue
        index = key.rfind(marker)
        if index == -1:
            continue
        texts.setdefault(key[index + len(marker) :], value)
    return texts


async def async_field_labels(
    hass: HomeAssistant, category: str, *, subentry_type: str | None = None
) -> dict[str, str]:
    """Translated labels for the fields of one flow, not a whole category.

    The schema's field names are exactly the keys in the integration's
    translation files, so no mapping table is needed — and none should be added,
    because a mapping table is a second place for the field list to live.

    `config_subentries` holds every subentry type in one translation file, and
    two of them — conversation and embeddings — declare fields with the same
    name (`model`, `model_user`) that mean different things. Flattening the
    whole category with `setdefault`, as this used to, let whichever type's
    keys were iterated first win for both forms — a real translation, just for
    the wrong form (F1). Passing `subentry_type` scopes matching to the keys
    under that type's own subtree, so a caller asks for the labels of one form
    rather than of everything sharing its translation category. Leave it None
    for a category with no such split, e.g. `options`.

    Returns whatever it can. A field with no translation is simply absent, and
    the panel falls back to the raw name: a field added without a translation
    must still render.
    """
    return await _async_field_texts(hass, category, ".data.", subentry_type=subentry_type)


async def async_field_descriptions(
    hass: HomeAssistant, category: str, *, subentry_type: str | None = None
) -> dict[str, str]:
    """Translated helper text for the fields of one flow, not a whole category.

    The `data_description` counterpart to `async_field_labels` — same file,
    same `subentry_type` scoping and the same reason it exists (F1): a
    category-wide flatten would let the embeddings tab's `model` helper text
    win, or lose, against the conversation tab's, depending on dict iteration
    order. Reusing `_async_field_texts` rather than re-deriving that scoping
    is the point, not just convenient — a second copy of the F1 fix is a
    second place for it to silently stop applying.

    Returns whatever it can. A field with no description is simply absent;
    the panel falls back to an empty string so the form still renders.
    """
    return await _async_field_texts(
        hass, category, ".data_description.", subentry_type=subentry_type
    )


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
            "labels": await async_field_labels(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_CONVERSATION
            ),
            "descriptions": await async_field_descriptions(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_CONVERSATION
            ),
        },
    )


def _describe_invalid(err: vol.Invalid) -> str:
    """A validation message that names the offending field.

    Built from `err.path`, not `str(err)` or `humanize_error`: those walk
    voluptuous's own formatting, which is free to change and, for some
    validators, includes the value that failed. Only the field name and a
    short reason travel here, so the message stays safe regardless of how
    voluptuous chooses to render itself.
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


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/settings/get",
        vol.Required("entry_id"): str,
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_settings_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serve the entry's options form — the same schema the agent form uses."""
    from .config_flow import subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    defaults = dict(entry.options)
    models = await _models_for(hass, entry, refresh=msg["refresh"], purpose=CAPABILITY_CHAT)
    schema = subentry_schema(hass, entry.unique_id, defaults, models=models)

    # Same trap as ws_agent_schema (see F1): the schema is conditional, so a
    # stale option key it no longer declares must not be served — <ha-form>
    # would echo it back and PREVENT_EXTRA in ws_settings_save would reject it
    # forever.
    declared = {str(key.schema) for key in schema.schema}
    served = {name: value for name, value in defaults.items() if name in declared}

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer),
            "data": served,
            "labels": await async_field_labels(hass, "options"),
            "descriptions": await async_field_descriptions(hass, "options"),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/settings/save",
        vol.Required("entry_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_settings_save(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save the entry's options, validating exactly as the agent form does.

    Written with ``options=``, never ``data=`` — ``entry.data`` is where the
    provider credential lives.
    """
    from .config_flow import normalize_model_input, subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    models = await _models_for(hass, entry, refresh=False, purpose=CAPABILITY_CHAT)
    schema = subentry_schema(hass, entry.unique_id, dict(entry.options), models=models)

    try:
        data = dict(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    error = normalize_model_input(data)
    if error:
        connection.send_error(msg["id"], "invalid_data", error)
        return

    hass.config_entries.async_update_entry(entry, options=data)
    connection.send_result(msg["id"], {"entry_id": entry.entry_id})


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
    """List SmartChain entries with their conversation agents and embeddings bindings."""
    entries = [_describe_entry(hass, entry) for entry in hass.config_entries.async_entries(DOMAIN)]
    connection.send_result(msg["id"], {"entries": entries})


def _describe_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Public description of an entry.

    Assembled field by field on purpose. `entry.data` holds the provider
    credential, so forwarding it wholesale — now or by a later edit — would put
    an API key on the wire.
    """
    engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
    # Tolerated missing: the panel can open before any memory store is
    # configured, at which point hass.data[DOMAIN] may not carry "memory" yet
    # (or, in principle, DOMAIN itself). An empty bound_stores list is the
    # right answer then, not an error.
    registry = hass.data.get(DOMAIN, {}).get("memory")
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
        "embeddings": [
            _describe_binding(registry, subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_EMBEDDINGS
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


def _describe_binding(registry: Any, subentry: Any) -> dict[str, Any]:
    """Public description of one embeddings binding.

    `bound_stores` travels here so the list can show, at a glance, which
    bindings a memory store depends on — the panel warns before a rename, and
    warning is more useful when the user could already see the risk.
    """
    data = subentry.data
    model = (data.get(CONF_CHAT_MODEL_USER) or "").strip() or data.get(CONF_CHAT_MODEL, "")
    return {
        "subentry_id": subentry.subentry_id,
        "title": subentry.title,
        "model": model,
        "bound_stores": registry.stores_bound_to(subentry.title) if registry else [],
    }


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/embeddings/schema",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_embeddings_schema(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serialise the embeddings form's schema, with current values when editing.

    Fetches with purpose=CAPABILITY_EMBEDDINGS, not the chat list ws_agent_schema
    uses — a chat model here would offer models that cannot embed.
    """
    from .config_flow import embeddings_subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    defaults: dict[str, Any] = {}
    subentry = None
    subentry_id = msg.get("subentry_id")
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_EMBEDDINGS:
            connection.send_error(msg["id"], "not_found", "Unknown embeddings binding")
            return
        defaults = {**subentry.data, "name": subentry.title}

    models = await _models_for(hass, entry, refresh=msg["refresh"], purpose=CAPABILITY_EMBEDDINGS)
    schema = embeddings_subentry_schema(models, defaults)

    # Same trap as ws_agent_schema (see F1): only serve fields the schema
    # still declares.
    declared = {str(key.schema) for key in schema.schema}
    served = {name: value for name, value in defaults.items() if name in declared}

    registry: MemoryRegistry = hass.data[DOMAIN]["memory"]

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer),
            "data": served,
            "labels": await async_field_labels(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_EMBEDDINGS
            ),
            "descriptions": await async_field_descriptions(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_EMBEDDINGS
            ),
            # A memory store binds by title. Both fields let the panel warn
            # before a write, not after: bound_stores names what a rename would
            # unbind, title_taken_by flags that this subentry's *current*
            # title already collides elsewhere (possible even before any edit,
            # e.g. two entries independently given the same title).
            "bound_stores": registry.stores_bound_to(subentry.title) if subentry else [],
            "title_taken_by": (
                _title_claimed_by_another(hass, subentry.title, subentry.subentry_id)
                if subentry
                else None
            ),
        },
    )


def _title_claimed_by_another(
    hass: HomeAssistant, title: str, subentry_id: str | None
) -> str | None:
    """The entry title of another SmartChain entry whose embeddings subentry
    already claims this title, or None if no *other* subentry holds it.

    `subentry_id` is excluded before anything is counted, not after.
    MemoryRegistry._embeddings_subentries collapses a title held by two or
    more subentries down to a bare None, discarding which subentries they
    were — so filtering `subentry_id` out of that already-collapsed result is
    not possible (F4): editing either half of an existing collision could
    never be saved again, not even to fix something unrelated, because
    "someone else has this title" could no longer be told apart from "I am
    one of the two someones". This walks entries directly instead — the same
    walk _embeddings_subentries does — keeping every claimant so self can be
    dropped before anything is collapsed.

    The return value also carries what ws_embeddings_save's error message
    needs (F3): which entry already holds the name, not just that someone
    does — a `title_taken_by` nobody could read either misleads or ships
    dead.
    """
    others = [
        (entry, subentry)
        for entry in hass.config_entries.async_entries(DOMAIN)
        for subentry in (entry.subentries or {}).values()
        if subentry.subentry_type == SUBENTRY_TYPE_EMBEDDINGS
        and subentry.title == title
        and subentry.subentry_id != subentry_id
    ]
    if not others:
        return None
    if len(others) == 1:
        return others[0][0].title
    return "more than one existing embeddings binding"


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/embeddings/save",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_embeddings_save(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update an embeddings binding, refusing an already-taken title.

    A title claimed by a second subentry maps to None in
    MemoryRegistry._embeddings_subentries, which silently unbinds every store
    that referenced it — exactly as a rename does. The panel shows every entry
    at once, so this is checked before anything is written, not discovered
    later when a store quietly stops resolving.
    """
    from .config_flow import _resolve_embeddings_model, embeddings_subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    subentry_id = msg.get("subentry_id")
    subentry = None
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_EMBEDDINGS:
            connection.send_error(msg["id"], "not_found", "Unknown embeddings binding")
            return

    models = await _models_for(hass, entry, refresh=False, purpose=CAPABILITY_EMBEDDINGS)
    defaults = {**subentry.data, "name": subentry.title} if subentry is not None else {}
    schema = embeddings_subentry_schema(models, defaults)

    try:
        data = dict(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    model = _resolve_embeddings_model(data)
    if not model:
        connection.send_error(msg["id"], "invalid_data", "model_required")
        return

    title = data["name"]
    # A save that keeps the subentry's own current title changes nothing
    # about who holds what, even if that title is already contested by a
    # different subentry — refusing it here would block the one edit a user
    # could make without touching the name field at all. Renaming away from a
    # contested title (the branch below) is the actual fix for the collision
    # itself, and that path is unaffected by this shortcut.
    if subentry is None or title != subentry.title:
        taken_by = _title_claimed_by_another(hass, title, subentry_id)
        if taken_by is not None:
            connection.send_error(
                msg["id"],
                "invalid_data",
                f"invalid_data: name (already used by {taken_by})",
            )
            return

    stored = {"model": model, "model_user": data.get("model_user", "")}

    if subentry is None:
        new = ConfigSubentry(
            data=stored,
            subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
            title=title,
            unique_id=None,
        )
        hass.config_entries.async_add_subentry(entry, new)
        connection.send_result(msg["id"], {"subentry_id": new.subentry_id})
        return

    hass.config_entries.async_update_subentry(entry, subentry, data=stored, title=title)
    connection.send_result(msg["id"], {"subentry_id": subentry.subentry_id})


def _resolve_embeddings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[ConfigEntry, Any] | None:
    """Entry and embeddings subentry named by the message, or None after sending an error."""
    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return None
    subentry = entry.subentries.get(msg["subentry_id"])
    if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_EMBEDDINGS:
        connection.send_error(msg["id"], "not_found", "Unknown embeddings binding")
        return None
    return entry, subentry


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/embeddings/delete",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_embeddings_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove an embeddings binding, reporting what it unbinds before it does."""
    resolved = _resolve_embeddings(hass, connection, msg)
    if resolved is None:
        return
    entry, subentry = resolved

    registry: MemoryRegistry = hass.data[DOMAIN]["memory"]
    bound_stores = registry.stores_bound_to(subentry.title)

    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    connection.send_result(msg["id"], {"bound_stores": bound_stores})


def _read_tools_file(path: Path) -> dict[str, Any]:
    """Text and status of tools.yaml on disk, never raising into the executor job.

    Blocking I/O only — no YAML parsing here. `load_tools_file` resolves
    `!secret` references against `secrets.yaml`, so the parsed structure
    holds real credentials. The raw text on disk holds only the reference
    name (`!secret my_key`), which is what `smartchain/tools/get` may
    safely return.

    `hash` is the sha256 hex digest of exactly the text served, `None` when
    the file does not exist (or couldn't be read as text). Task 2's save
    path compares a client-supplied `base_hash` against this to detect a
    file that changed underneath the editor.

    `exists=False` means the normal first-run state — no file at all — and
    is not an error. A file that *is* there but can't be read as text (wrong
    permissions, a directory sitting at that path, non-UTF-8 bytes) reports
    `exists=True` with a distinguishable `error`, rather than letting the
    exception escape the executor job: uncaught, it would reach HA's generic
    websocket exception handler and collapse to an opaque "Unknown error",
    leaving the panel with no way to tell the user what's actually wrong.
    """
    if not path.exists():
        return {"text": "", "exists": False, "error": None, "hash": None}
    try:
        text = path.read_text()
        return {
            "text": text,
            "exists": True,
            "error": None,
            "hash": hashlib.sha256(text.encode()).hexdigest(),
        }
    except (OSError, UnicodeDecodeError) as err:
        return {
            "text": "",
            "exists": True,
            "error": f"{type(err).__name__}: {path.name} could not be read",
            "hash": None,
        }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tools/get"})
@websocket_api.async_response
async def ws_tools_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """The file as it sits on disk.

    Never the parsed structure: `load_tools_file` resolves `!secret`, so the
    parsed form holds real credentials, while the raw text holds only the
    reference name.
    """
    from . import _tools_yaml_path

    path = _tools_yaml_path(hass)
    result = await hass.async_add_executor_job(_read_tools_file, path)
    connection.send_result(msg["id"], {"path": str(path), **result})


# A parse failure comes from Home Assistant's YAML reader (or, in principle,
# a bare yaml.YAMLError), which fails *before* any `!secret` is resolved — its
# message carries a line and column and no credential. A schema failure comes
# from voluptuous (`vol.Invalid` / `MultipleInvalid`), whose messages embed the
# offending value, and HA resolves `!secret` on mapping *keys* as well as
# values, so that value can be a live credential.
#
# Whitelist the safe case, never blacklist the unsafe one: forward the message
# only when the cause is a known parse-error type, and fall back to the bare
# type name for everything else, including causes nobody enumerated. A
# blacklist inverts the failure mode — an unfamiliar exception would be
# forwarded rather than withheld — and this file has already shipped one leak
# from exactly that shape (see the `.path` note below).
_PARSE_ERROR_CAUSES = (yaml.YAMLError, HomeAssistantError)


def _safe_loader_error(err: LoaderError) -> str:
    """A validation failure summary that cannot carry a resolved secret.

    A YAML *syntax* error (`HomeAssistantError` from HA's loader, or a bare
    `yaml.YAMLError`) is safe to forward verbatim: the parser fails before any
    `!secret` is resolved, so its message carries a line and column and no
    credential — and a text editor without a line number is much harder to
    use. Everything else — in particular a schema failure from voluptuous —
    reports only the exception's type name. Nothing about a `vol.Invalid` /
    `MultipleInvalid` — not its message, not its `.path` — is safe to forward:

    - `str(err)` / `.msg`: two of this schema's own validators
      (`_validate_action`, `_validate_mcp_server` in tools/schema.py) build
      their message with the offending value interpolated straight in, e.g.
      ``unknown action type 'sk-...'`` — exactly what a `!secret` resolving
      into a `type:` field produces.
    - `err.path`: looked safe at first, since it is normally a list of dict
      keys and list indices describing *where* validation failed —
      structural coordinates, not a value. But `!secret` resolves on
      mapping **keys** as well as values, and every schema here uses
      voluptuous's default `extra=PREVENT_EXTRA`, so a `!secret` used as an
      unexpected key raises "extra keys not allowed" with that resolved key
      appended to `.path` itself — a document value smuggled through the
      one place that looked structural. Reproduced end to end: a tools.yaml
      with `!secret my_key` as an extra key inside a rejected block put the
      resolved secret directly in `err.path`.

    A safe subset of `.path` would need an allowlist of every literal key
    each schema declares, but the discriminating validators above dispatch
    to sub-schemas this module doesn't own and that aren't structured for
    generic introspection — an allowlist built by hand would silently drift
    out of sync as tools/schema.py changes. Rather than approximate that,
    only the exception type is reported for a schema failure. The full
    original message is logged server-side by the caller, where only an
    admin can read it.

    `vol.Invalid` is a subclass of neither whitelist entry today, so a schema
    failure cannot satisfy the `isinstance` check above — the explicit
    `not isinstance(cause, vol.Invalid)` guard is redundant against the
    current class hierarchy. It stays anyway: it is free, and it stops a
    future Home Assistant that reparented `Invalid` under `HomeAssistantError`
    from silently turning this whitelist into a leak.
    """
    cause = err.__cause__
    if isinstance(cause, _PARSE_ERROR_CAUSES) and not isinstance(cause, vol.Invalid):
        return str(cause)
    return type(cause).__name__ if cause is not None else type(err).__name__


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tools/validate"})
@websocket_api.async_response
async def ws_tools_validate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Validate tools.yaml server-side without ever forwarding a resolved secret.

    Runs `load_tools_file` — the only way to know whether the file is valid,
    since that is what actually parses and schema-checks it — but reports
    only pass/fail plus a safe location. See `_safe_loader_error` for why
    the exception's own message never crosses the wire.
    """
    from . import _tools_yaml_path

    path = _tools_yaml_path(hass)
    try:
        await hass.async_add_executor_job(load_tools_file, path, Path(hass.config.config_dir))
    except LoaderError as err:
        LOGGER.warning("tools.yaml validation failed: %s", err)  # detail stays server-side
        connection.send_result(msg["id"], {"valid": False, "error": _safe_loader_error(err)})
        return
    connection.send_result(msg["id"], {"valid": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tools/reload"})
@websocket_api.async_response
async def ws_tools_reload(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Re-read tools.yaml into the live registry and report how many tools loaded."""
    from . import _reload_registry

    try:
        count = await _reload_registry(hass)
    except LoaderError as err:
        LOGGER.warning("tools.yaml reload failed: %s", err)  # detail stays server-side
        connection.send_error(msg["id"], "invalid_data", _safe_loader_error(err))
        return
    connection.send_result(msg["id"], {"tools": count})


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def _tmp_path(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _restore_backup(path: Path) -> bool:
    """Restore `.bak` onto `path` through the same atomic replace `save` uses.

    Deliberately does **not** validate the backup first: it is, by
    construction, a file that once passed `load_tools_file` (nothing but a
    successful save ever creates one), and refusing to restore it would
    strand the user exactly when they most need the escape hatch.

    Returns False, doing nothing, when there is no backup to restore.
    """
    backup = _backup_path(path)
    if not backup.is_file():
        return False
    os.replace(backup, path)
    return True


def _write_tools_file(path: Path, text: str, config_dir: Path) -> tuple[str, str | None]:
    """Blocking half of a save: write, validate, back up, atomically replace.

    Runs entirely off the event loop — the temp-file write, the real
    `load_tools_file` validation (the integration's own loader, so what
    passes here is what will load at startup), and the backup copy are all
    blocking I/O.

    Returns `(status, error)`:
    - `("ok", None)` — the file is now on disk at `path`.
    - `("invalid", detail)` — the submitted text failed to load; nothing was
      written to `path`. `detail` is already `_safe_loader_error`'s output,
      never a raw exception message.
    - `("write_failed", detail)` — a filesystem error; `detail` is only the
      exception's type name, never its message (which can embed a path or,
      in principle, other detail not meant for the wire).

    The temp file is removed on every exit path: a stray `.tmp` beside a
    config file is confusing at best, and `os.replace` already consumes it
    on the success path, so `missing_ok=True` covers both.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        try:
            tmp.write_text(text)
        except OSError as err:
            return "write_failed", type(err).__name__

        try:
            load_tools_file(tmp, config_dir)
        except LoaderError as err:
            LOGGER.warning("tools.yaml save validation failed: %s", err)  # server-side only
            return "invalid", _safe_loader_error(err)

        try:
            backup = _backup_path(path)
            if path.exists():
                shutil.copy2(path, backup)
            os.replace(tmp, path)
        except OSError as err:
            return "write_failed", type(err).__name__

        return "ok", None
    finally:
        tmp.unlink(missing_ok=True)


def _restore_after_failed_reload(path: Path) -> None:
    """Undo a save whose reload failed.

    Ordinarily there is a `.bak` — the pre-save file — to put back. The one
    case there is not is a first-ever save on a fresh install, where `path`
    did not exist before this save either; then "restore" means removing
    the file `save` just wrote, returning to that same fresh-install state
    rather than leaving a file nothing backs up.
    """
    if not _restore_backup(path):
        # No prior file means nothing here has adopted this text yet, and a
        # file that fails to reload now will fail identically at Home
        # Assistant's next startup — leaving it on disk doesn't preserve the
        # user's work, it schedules a breakage for their next restart. The
        # panel still holds their text, so removing it loses nothing visible.
        path.unlink(missing_ok=True)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/tools/save",
        vol.Required("text"): str,
        vol.Required("base_hash"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_tools_save(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Write `text` to tools.yaml, refusing anything that could take the
    integration down.

    The order below is the safety argument and must not be rearranged:

    1. Refuse if the file's hash no longer matches `base_hash` — someone may
       be editing through a file editor, SSH, or a second tab. Refusing is
       the whole behaviour; there is no merge and no last-write-wins.
    2. Write the submitted text to a temp file beside the target, so the
       later `os.replace` stays on one filesystem and therefore stays
       atomic.
    3. Validate the temp file with `load_tools_file` — what passes here is
       what will load at startup.
    4. Back up the current file, before the replace.
    5. `os.replace` the temp file onto the target — atomic, so a crash
       mid-write cannot leave a truncated file.
    6. Reload the registry. If the reload raises, restore from the backup
       and reload again, then report: the user asked to save a file, not to
       lose their tools. A file can validate and still fail to load — an MCP
       server that will not start, an embeddings binding that no longer
       resolves.

    Nothing here parses `text` into a structure and re-serialises it — raw
    text in, raw text out — which is what lets `!secret openai_key` survive
    a save as a reference instead of being written back as the resolved
    key.
    """
    from . import _reload_registry, _tools_yaml_path

    path = _tools_yaml_path(hass)
    config_dir = Path(hass.config.config_dir)

    # 1. Refuse a stale edit.
    current = await hass.async_add_executor_job(_read_tools_file, path)
    if current["hash"] != msg["base_hash"]:
        connection.send_result(msg["id"], {"ok": False, "reason": "stale"})
        return

    # 2-5: write, validate, back up, atomically replace — all in one executor
    # job so the sequence stays one uninterrupted piece of blocking I/O.
    status, error = await hass.async_add_executor_job(
        _write_tools_file, path, msg["text"], config_dir
    )
    if status != "ok":
        connection.send_result(msg["id"], {"ok": False, "reason": status, "error": error})
        return

    # 6. Reload; on failure, restore and report.
    try:
        await _reload_registry(hass)
    except LoaderError as err:
        LOGGER.warning(  # detail stays server-side
            "tools.yaml reload after save failed; restoring previous file: %s", err
        )
        await hass.async_add_executor_job(_restore_after_failed_reload, path)
        try:
            await _reload_registry(hass)
        except LoaderError:
            LOGGER.exception("tools.yaml reload after restoring the backup also failed")
        connection.send_result(
            msg["id"],
            {"ok": False, "reason": "reload_failed", "error": _safe_loader_error(err)},
        )
        return

    new = await hass.async_add_executor_job(_read_tools_file, path)
    connection.send_result(msg["id"], {"ok": True, "hash": new["hash"]})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tools/rollback"})
@websocket_api.async_response
async def ws_tools_rollback(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Restore `tools.yaml.bak` onto `tools.yaml` and reload.

    Does not validate the backup first — see `_restore_backup`. Refuses with
    `no_backup` when there is none.
    """
    from . import _reload_registry, _tools_yaml_path

    path = _tools_yaml_path(hass)
    restored = await hass.async_add_executor_job(_restore_backup, path)
    if not restored:
        connection.send_result(msg["id"], {"ok": False, "reason": "no_backup"})
        return

    try:
        await _reload_registry(hass)
    except LoaderError as err:
        LOGGER.warning("tools.yaml reload after rollback failed: %s", err)  # server-side only
        connection.send_result(
            msg["id"],
            {"ok": False, "reason": "reload_failed", "error": _safe_loader_error(err)},
        )
        return

    new = await hass.async_add_executor_job(_read_tools_file, path)
    connection.send_result(msg["id"], {"ok": True, "hash": new["hash"]})
