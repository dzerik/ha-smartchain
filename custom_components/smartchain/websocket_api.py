"""Websocket commands backing the SmartChain panel.

The panel never defines a form. These commands serialise the very schema the
config flow builds, so the field list has one definition rather than two.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from collections.abc import Iterable, Mapping
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

from .client_util import (
    ModelFetchError,
    async_fetch_models,
    connection_data,
    static_models,
    supports,
)
from .const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    MEMORY_DEFAULT_BACKEND,
    MEMORY_SECRET_FIELDS,
    MEMORY_SOURCE_TYPE_NONE,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    SUBENTRY_TYPE_TOOL,
    TOOL_DEFAULT_ACTION_TYPE,
    TOOL_PARAMS_MODE_ADVANCED,
    TOOL_PARAMS_MODE_SIMPLE,
    UNIQUE_ID,
)
from .storable import UNSTORABLE_TEXT, UnstorableValue, ensure_storable
from .tools.loader import LoaderError, load_tools_file
from .tools.memory.registry import MemoryRegistry
from .tools.subentry_source import SOURCE_SUBENTRY, SOURCE_YAML

LOGGER = logging.getLogger(__name__)

_MODEL_CACHE = "panel_model_cache"
# Per-entry digest of the connection each cached list was fetched over — see
# `async_invalidate_stale_model_cache`.
_CONNECTION_DIGESTS = "panel_model_cache_connections"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every panel command."""
    websocket_api.async_register_command(hass, ws_agent_schema)
    websocket_api.async_register_command(hass, ws_agent_save)
    websocket_api.async_register_command(hass, ws_agent_tools)
    websocket_api.async_register_command(hass, ws_settings_get)
    websocket_api.async_register_command(hass, ws_settings_save)
    websocket_api.async_register_command(hass, ws_agent_duplicate)
    websocket_api.async_register_command(hass, ws_agent_delete)
    websocket_api.async_register_command(hass, ws_embeddings_schema)
    websocket_api.async_register_command(hass, ws_embeddings_save)
    websocket_api.async_register_command(hass, ws_embeddings_delete)
    websocket_api.async_register_command(hass, ws_store_schema)
    websocket_api.async_register_command(hass, ws_store_save)
    websocket_api.async_register_command(hass, ws_store_delete)
    websocket_api.async_register_command(hass, ws_store_status)
    websocket_api.async_register_command(hass, ws_tool_schema)
    websocket_api.async_register_command(hass, ws_tool_save)
    websocket_api.async_register_command(hass, ws_tool_delete)
    websocket_api.async_register_command(hass, ws_tool_list)
    websocket_api.async_register_command(hass, ws_tool_presets)
    websocket_api.async_register_command(hass, ws_tool_preset_install)
    websocket_api.async_register_command(hass, ws_tools_import)
    websocket_api.async_register_command(hass, ws_tools_export)
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
    every click between agents, so the list is cached. Keyed by entry id *and*
    purpose — a chat fetch and an embeddings fetch on the same entry must not
    serve each other's list.

    Two things invalidate it: an explicit Refresh models, and a change to the
    connection the list was fetched over (`async_invalidate_stale_model_cache`).
    The second was missing, and it made the hub's own settings look broken
    rather than merely stale: Verify SSL began feeding this fetch in v5.4.11, so
    a user whose network needs certificate checking would turn the switch on,
    reopen the panel, and be served the list cached from the failing
    connection — with nothing to suggest the setting had not taken.

    A *failed* fetch is not cached. It used to be, and the consequence was out
    of all proportion to its cause: one blip while the panel was first opening
    replaced the provider's catalogue with the shipped list, and that stayed
    until Home Assistant restarted or the user found "Refresh models" — by
    which time their own model was missing from every agent form and every save
    was refused. Only an answer is worth remembering; a non-answer is worth
    trying again.
    """
    cache: dict[tuple[str, str], list[str]] = hass.data.setdefault(DOMAIN, {}).setdefault(
        _MODEL_CACHE, {}
    )
    key = (entry.entry_id, purpose)
    if not refresh and key in cache:
        return cache[key]

    engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
    try:
        models = await async_fetch_models(
            hass, engine, connection_data(entry), purpose=purpose, strict=True
        )
    except ModelFetchError:
        # Deliberately outside the cache: the next open retries.
        return static_models(engine, purpose)
    cache[key] = models
    return models


@callback
def async_invalidate_stale_model_cache(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop an entry's cached model lists when its *connection* has changed.

    Called from `update_listener`, which fires for every write to the entry —
    including an agent subentry save, which has nothing to do with which models
    the provider serves. Invalidating on all of those would make the cache
    little better than absent, so the trigger is narrowed to what a fetch
    actually depends on: `connection_data(entry)`, the same view of the entry
    the fetch itself is handed. Credentials, base URL and Verify SSL change the
    answer; a prompt does not.

    Both purposes go together. They are separate cache entries because they
    hold different lists, but they are fetched over the one connection, so a
    connection that has changed invalidates both.

    The stored value is a one-way digest, never the connection itself:
    `connection_data` carries the API key. It stays in `hass.data`, is never
    returned, logged or sent anywhere, and nothing else may start reporting it.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    digests: dict[str, str] = domain_data.setdefault(_CONNECTION_DIGESTS, {})
    digest = hashlib.sha256(
        json.dumps(connection_data(entry), sort_keys=True, default=repr).encode()
    ).hexdigest()

    if digests.get(entry.entry_id) == digest:
        return
    digests[entry.entry_id] = digest

    cache: dict[tuple[str, str], list[str]] = domain_data.setdefault(_MODEL_CACHE, {})
    for purpose in (CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS):
        cache.pop((entry.entry_id, purpose), None)


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


# Where the panel-facing text of a preset lives, and the one convention chosen
# for it: `config_panel.presets.<preset name>.{name,description}`.
#
# `config_panel` because it is the only category Home Assistant defines for text
# a custom panel shows — hassfest validates it as a free-form tree of
# translation keys down to strings, which is exactly the shape needed, and it
# says in the key itself that this text is for the panel and not for a flow.
# `presets` scopes it the way `config_subentries` is scoped by subentry type, so
# a second kind of panel text added later cannot collide with a preset name.
#
# The split it establishes is the point: `<preset>.name` and
# `<preset>.description` are UI strings and are translated, while the tool's own
# `description` — the sentence the *model* reads to decide whether to call it —
# stays in English in `tools/presets.py` and is never read from here. They are
# different audiences, so they are different strings in different places.
PRESET_TEXT_CATEGORY = "config_panel"
PRESET_TEXT_PREFIX = f"component.{DOMAIN}.{PRESET_TEXT_CATEGORY}.presets."


async def async_preset_texts(hass: HomeAssistant) -> dict[str, dict[str, str]]:
    """`{preset name: {"name": ..., "description": ...}}` in the user's language.

    Returns whatever it can, like `async_field_labels` does: a preset with no
    translation is simply absent from the map and the panel falls back to the
    tool's own name, so a preset added without a translation still renders.
    """
    resources = await translation.async_get_translations(
        hass, hass.config.language, PRESET_TEXT_CATEGORY, [DOMAIN]
    )
    texts: dict[str, dict[str, str]] = {}
    for key, value in resources.items():
        if not key.startswith(PRESET_TEXT_PREFIX):
            continue
        preset, _, field = key[len(PRESET_TEXT_PREFIX) :].partition(".")
        if field not in ("name", "description"):
            continue
        texts.setdefault(preset, {})[field] = value
    return texts


# Said only when the translation file has nothing to say — an English sentence
# rather than a key, because the bare key is exactly what a new user used to
# be shown. The rule is about both fields, so it names both.
MODEL_REQUIRED_FALLBACK = "select a model from the list, or type a custom model name"
MODEL_REQUIRED_FIELDS = (CONF_CHAT_MODEL, CONF_CHAT_MODEL_USER)

# The other half of the same story. `model_required` covers "you picked
# nothing"; this covers "you picked something the list has never heard of",
# which is what a user whose provider has just shipped a model — or whose
# provider was unreachable when the panel opened — actually hits. It says which
# of the two it is likely to be, and both ways out.
MODEL_UNKNOWN_FALLBACK = (
    "that model is not in the list we could get from the provider just now — "
    "press Refresh models if the connection was down, or type the exact name "
    "into the custom model field to use it anyway"
)


async def async_flow_error_text(
    hass: HomeAssistant,
    key: str,
    category: str,
    *,
    fallback: str,
    subentry_type: str | None = None,
) -> str:
    """The `error.<key>` sentence a config flow would show, for the panel.

    A config flow renders `errors={"base": key}` through `strings.json`, so
    every rule already has a translated sentence written for it. The panel has
    no translation layer of its own, and the websocket commands that enforce
    the *same* rules were sending the bare key instead — which is why a new
    user's first Save toasted `model_required` at them. This reads the sentence
    that already exists, in the user's own language, rather than adding a
    second English-only copy of it to Python.

    Same walk as `async_field_labels`, same `subentry_type` scoping, and for
    the same reason: `conversation` and `embeddings` both define
    `model_required`, and they are not the same sentence.
    """
    texts = await _async_field_texts(hass, category, ".error.", subentry_type=subentry_type)
    return texts.get(key) or fallback


def _prefill(schema: vol.Schema, served: dict[str, Any]) -> None:
    """Rewrite `served` with the values a Home Assistant dialog would render.

    `description={"suggested_value": …}` is how a config-flow form tells the
    frontend what to put in a field, and it is not always the stored value:
    `subentry_schema` filters `llm_hass_api` against the live API registry and
    expands a legacy `allowed_tools`. The panel builds its own form from the
    serialised schema but takes its values from `data`, so anything the schema
    decided on the way out was decided for one front only — and the two fronts
    then disagreed about the same agent. Reading the decision back out of the
    schema keeps it written once, in the flow, where the reasoning for it lives.

    Every field the schema declares a suggestion for is answered, not only the
    ones storage already had a key for. That restriction looked conservative
    and was the third instance of the very split this function exists to close:
    the two suggestions that are *computed* rather than echoed —
    `materialise_allowed_tools` and `DEFAULT_PROMPT` — are exactly the ones an
    agent has no stored key for, so the dialog opened showing a legacy agent's
    four built-in tools while the panel opened showing an empty tool picker for
    the same agent. A user who then added one tool on the panel replaced all
    four, from a screen that had told them there were none.

    A suggestion of `None` is a decision too, and the opposite one: it is what
    `_live_llm_apis` returns to mean "there is no selection to offer", which a
    dialog renders as a blank field and no value. So the key is *removed*
    rather than left holding whatever storage happened to have. Leaving it was
    the last corner of the ghost-API bug: an `llm_hass_api` stored as `""` — the
    shape Home Assistant's own conversation integrations wrote — reached the
    panel as `""`, came back in the next save, and was refused by the
    multi-select with `invalid_data: llm_hass_api`, on a field the panel had
    rendered as empty. The dialog walks out of that state without noticing;
    now so does the panel.

    Mutates `served` because the two outcomes are "use this value" and "have no
    value", and a returned dict can only express the first.
    """
    for key in schema.schema:
        description = getattr(key, "description", None)
        if not isinstance(description, Mapping) or "suggested_value" not in description:
            continue
        name = str(key.schema)
        suggested = description["suggested_value"]
        if suggested is None:
            served.pop(name, None)
        else:
            served[name] = suggested


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
    # Same argument one step further in. Pruning undeclared *keys* is not enough
    # when the schema also rewrites a declared *value*: `subentry_schema` filters
    # the stored `llm_hass_api` against `llm.async_get_apis` before suggesting
    # it, so the dialog never proposes an id whose integration is gone — while
    # this command, reading `subentry.data` directly, went on proposing it. The
    # picker's options are filtered either way, so the panel rendered a value its
    # own select could not hold and the next save came back `invalid_data` on a
    # field the user had never touched.
    _prefill(schema, served)

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


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/tools",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_agent_tools(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Everything this agent can do, and what is stopping the rest.

    The one screen that answers the question. Carries no configuration values —
    only tool names, where each comes from, and whether it is on — so nothing
    from `subentry.data` (which may hold a provider key on a legacy entry)
    reaches the wire through here.
    """
    from .tools.inventory import describe_agent_tools

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    subentry = entry.subentries.get(msg["subentry_id"])
    if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
        connection.send_error(msg["id"], "not_found", "Unknown agent")
        return

    connection.send_result(
        msg["id"],
        {"tools": describe_agent_tools(hass, entry, subentry.subentry_id, subentry.data)},
    )


def invalid_data(fields: Iterable[str], detail: str | None = None) -> str:
    """The one shape every save command reports a rejected field in.

    `invalid_data: <field>[, <field>…][ — <human text>]`. The field list is
    what lets `<sc-config-form>` attach the message to the control the user is
    looking at instead of toasting it; the optional text after the em dash is
    what makes the message worth attaching. Both halves are optional in
    practice — a failure with no identifiable field degrades to a bare
    `invalid_data` — and the separator is an em dash precisely because a field
    name can never contain one, so the split is unambiguous on the panel side.

    Written down here, once, because three files used to spell it out
    independently and one of them (`normalize_model_input`'s "model_required")
    did not spell it at all — which is how a new user's very first Save came to
    toast a machine key.
    """
    joined = ", ".join(fields)
    if not joined:
        return f"invalid_data — {detail}" if detail else "invalid_data"
    return f"invalid_data: {joined} — {detail}" if detail else f"invalid_data: {joined}"


def _describe_invalid(err: vol.Invalid) -> str:
    """A validation message that names the offending field.

    Built from `err.path`, not `str(err)` or `humanize_error`: those walk
    voluptuous's own formatting, which is free to change and, for some
    validators, includes the value that failed. Only the field name and a
    short reason travel here, so the message stays safe regardless of how
    voluptuous chooses to render itself.

    `UnstorableValue` is the single exception, and it is a type rather than a
    string comparison: its message is a module constant built from nothing the
    client sent, so carrying it through is provably safe in a way that reading
    an arbitrary `vol.Invalid`'s message would not be.
    """
    suberrors = getattr(err, "errors", None) or [err]
    fields = _invalid_fields(err)
    detail = UNSTORABLE_TEXT if any(isinstance(sub, UnstorableValue) for sub in suberrors) else None
    return invalid_data(fields, detail)


def _invalid_fields(err: vol.Invalid) -> list[str]:
    """The schema field names one `vol.Invalid` names, deduplicated and sorted."""
    suberrors = getattr(err, "errors", None) or [err]
    return sorted({str(sub.path[0]) for sub in suberrors if getattr(sub, "path", None)})


async def _describe_model_invalid(hass: HomeAssistant, err: vol.Invalid, subentry_type: str) -> str:
    """`_describe_invalid`, plus a sentence when the model is what was rejected.

    The model select is the one field on these forms whose valid values are
    decided elsewhere — by whatever the provider listed when the panel opened.
    So it is the one field a user can be refused on without having touched it:
    open an agent, edit the prompt, save, and be told `invalid_data: model`
    about a model that has been working all week. v5.4.7 fixed exactly this
    shape of dead end for the stores form; v5.4.10 carried it to the agent
    form and stopped there, leaving the embeddings form — whose stored value
    is *more* likely to be off-list, because the docs tell people to type it
    into Custom Model — reporting the raw machine key this release had just
    finished removing one file over.

    Both forms name the field `model` (`CONF_CHAT_MODEL`), so only the
    translation scope differs and it is a parameter rather than a second copy
    of this function.

    Every other field keeps the plain description: they fail because of
    something the user typed, and the control they typed it into is the
    message.
    """
    fields = _invalid_fields(err)
    if CONF_CHAT_MODEL not in fields:
        return _describe_invalid(err)
    text = await async_flow_error_text(
        hass,
        "model_unknown",
        "config_subentries",
        fallback=MODEL_UNKNOWN_FALLBACK,
        subentry_type=subentry_type,
    )
    return invalid_data(fields, text)


def _write_subentry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry | None,
    *,
    subentry_type: str,
    data: Mapping[str, Any],
    title: str,
) -> str:
    """Create or update one subentry, and return its id.

    Every subentry this integration writes goes through here, so the
    JSON-serialisability guard is structural rather than a line someone has to
    remember at each of the six call sites. That matters more than the
    deduplication: a value orjson cannot encode does not corrupt *this*
    subentry, it kills every subsequent write of `core.config_entries` for
    every integration on the system (see `storable`), and the failure surfaces
    as a `TypeError` in a delayed-write task that nobody sees.

    Raises `vol.Invalid` — the same exception the schema raises, carrying the
    same `path` — so a caller's existing `except vol.Invalid` branch reports it
    with no new error handling.
    """
    stored = ensure_storable(data)
    if subentry is None:
        new = ConfigSubentry(data=stored, subentry_type=subentry_type, title=title, unique_id=None)
        hass.config_entries.async_add_subentry(entry, new)
        return new.subentry_id
    hass.config_entries.async_update_subentry(entry, subentry, data=stored, title=title)
    return subentry.subentry_id


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
        data = ensure_storable(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(
            msg["id"],
            "invalid_data",
            await _describe_model_invalid(hass, err, SUBENTRY_TYPE_CONVERSATION),
        )
        return

    error = normalize_model_input(data)
    if error:
        # Named fields and a sentence, not a bare key: this is the very first
        # Save a new user performs — `DEFAULT_CHAT_MODEL` is "" so "+ Agent"
        # opens with nothing selected — and it used to toast "model_required".
        text = await async_flow_error_text(
            hass,
            error,
            "config_subentries",
            fallback=MODEL_REQUIRED_FALLBACK,
            subentry_type=SUBENTRY_TYPE_CONVERSATION,
        )
        connection.send_error(msg["id"], "invalid_data", invalid_data(MODEL_REQUIRED_FIELDS, text))
        return

    # Keep what this schema does not declare. `ws_agent_schema` strips undeclared
    # keys before serving them (see F1 there), so a conditional field that is out
    # of schema right now comes back absent — and replacing `subentry.data`
    # wholesale would then delete the stored value. Merging is the actual fix;
    # the field being conditional is only the trigger, and the next conditional
    # field would reintroduce it.
    declared = {str(key.schema) for key in schema.schema}
    preserved = (
        {name: value for name, value in subentry.data.items() if name not in declared}
        if subentry is not None
        else {}
    )
    data = {**preserved, **data}

    try:
        result_id = _write_subentry(
            hass,
            entry,
            subentry,
            subentry_type=SUBENTRY_TYPE_CONVERSATION,
            data=data,
            title=agent_title(data),
        )
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return
    connection.send_result(msg["id"], {"subentry_id": result_id})


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
    """Serve the entry's *connection* form.

    Not the agent schema: an entry is a connection, and the model, prompt and
    tools live on a conversation subentry. Most providers therefore have no
    connection settings at all, which is why the result carries ``empty`` — the
    panel must say so rather than render a form with no fields. ``refresh`` is
    accepted and ignored; a connection form has no model list, so it must not
    pay a network round trip to open.
    """
    from .config_flow import connection_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    defaults = dict(entry.options)
    engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
    schema = connection_schema(engine, defaults)

    # Same trap as ws_agent_schema (see F1): the schema is conditional, so a
    # stale option key it no longer declares must not be served — <ha-form>
    # would echo it back and PREVENT_EXTRA in ws_settings_save would reject it
    # forever. It also keeps a legacy entry's leftover agent options off the
    # wire entirely.
    declared = {str(key.schema) for key in schema.schema}
    served = {name: value for name, value in defaults.items() if name in declared}

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer),
            "data": served,
            "empty": not schema.schema,
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
    """Save the entry's connection settings.

    Written with ``options=``, never ``data=`` — ``entry.data`` is where the
    provider credential lives. There is no ``normalize_model_input`` here: the
    connection schema declares no model, so that check would reject every
    submission with "model_required".
    """
    from .config_flow import connection_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    stored = dict(entry.options)
    engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
    schema = connection_schema(engine, stored)
    if not schema.schema:
        connection.send_error(
            msg["id"], "not_supported", "This provider has no connection settings"
        )
        return

    try:
        # `entry.options` reaches storage through the same
        # `as_storage_fragment` a subentry does, so the connection form is
        # guarded on the same terms — see `storable`.
        data = ensure_storable(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    # Merge, never replace: a legacy entry that also has agents keeps its old
    # agent-shaped options in storage untouched — they simply stop being
    # presented — and replacing wholesale would destroy them on the first save.
    hass.config_entries.async_update_entry(entry, options={**stored, **data})
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

    try:
        copy_id = _write_subentry(
            hass,
            entry,
            None,
            subentry_type=SUBENTRY_TYPE_CONVERSATION,
            data=dict(subentry.data),
            # A copy sharing the original's title is indistinguishable in a list.
            title=_unique_copy_title(entry, subentry.title),
        )
    except vol.Invalid as err:
        # Only reachable if the *original* already holds something unstorable,
        # in which case duplicating it would spread the damage rather than
        # start it.
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return
    connection.send_result(msg["id"], {"subentry_id": copy_id})


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
            _describe_agent(hass, entry, subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_CONVERSATION
        ],
        "embeddings": [
            _describe_binding(registry, subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_EMBEDDINGS
        ],
        "stores": [
            _describe_store(registry, subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_MEMORY_STORE
        ],
        # Present so the Tools tab knows which entry to create a tool on and
        # which tools this entry already hosts. The tab's own list comes from
        # `smartchain/tool/list`, which also covers tools.yaml and MCP.
        "tools": [
            _describe_tool_subentry(entry, subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_TOOL
        ],
    }


def _describe_agent(hass: HomeAssistant, entry: ConfigEntry, subentry: Any) -> dict[str, Any]:
    """Public description of one agent, including how many tools it really has.

    `tool_count` used to be `len(allowed_tools)`, or `None` for "all tools" —
    a count of one *setting*, which never mentioned a built-in and so
    understated every agent that had one. It is now the number of tools the
    agent would actually be bound with, taken from the same inventory
    `_async_handle_message` binds from.
    """
    from .tools.inventory import describe_agent_tools

    data = subentry.data
    model = (data.get(CONF_CHAT_MODEL_USER) or "").strip() or data.get(CONF_CHAT_MODEL, "")
    inventory = describe_agent_tools(hass, entry, subentry.subentry_id, data)
    return {
        "subentry_id": subentry.subentry_id,
        "title": subentry.title,
        "model": model,
        "tool_count": sum(1 for row in inventory if row["enabled"]),
        "tool_total": len(inventory),
    }


def _describe_store(registry: Any, subentry: Any) -> dict[str, Any]:
    """Public description of one memory store subentry.

    Assembled field by field for the same reason `_describe_entry` is:
    `subentry.data` holds `dsn` and `api_key`, so forwarding it wholesale —
    now or by a later edit — would put a database password on the wire. Only
    whether a credential is held travels, never the credential.
    """
    data = subentry.data
    name = subentry.title
    # `is not None`, not truthiness: MemoryRegistry defines __len__ over its
    # *live* stores, so a registry whose every store failed is falsy — and the
    # row that most needed a reason was the one guaranteed to be told `None`.
    failures = getattr(registry, "failures", None) or {}
    live = registry is not None and name in registry.stores
    return {
        "subentry_id": subentry.subentry_id,
        "title": name,
        "embeddings": data.get("embeddings", ""),
        "backend_type": data.get("backend_type", MEMORY_DEFAULT_BACKEND),
        "source_type": data.get("source_type", MEMORY_SOURCE_TYPE_NONE),
        "secrets_set": {field: bool(data.get(field)) for field in MEMORY_SECRET_FIELDS},
        "ok": live,
        "reason": None if live else failures.get(name),
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
        # `is not None` for the reason spelled out in `_describe_store`: an
        # all-failed registry is falsy and would answer this as "nothing is
        # bound", which is a different claim from "nothing came up".
        "bound_stores": registry.stores_bound_to(subentry.title) if registry is not None else [],
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
        data = ensure_storable(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(
            msg["id"],
            "invalid_data",
            await _describe_model_invalid(hass, err, SUBENTRY_TYPE_EMBEDDINGS),
        )
        return

    model = _resolve_embeddings_model(data)
    if not model:
        # Same rule, same fields and the same reason for spelling it out as in
        # `ws_agent_save` — but this subentry type's own sentence, which is not
        # the conversation one.
        text = await async_flow_error_text(
            hass,
            "model_required",
            "config_subentries",
            fallback=MODEL_REQUIRED_FALLBACK,
            subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        )
        connection.send_error(msg["id"], "invalid_data", invalid_data(MODEL_REQUIRED_FIELDS, text))
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
                invalid_data(["name"], f"already used by {taken_by}"),
            )
            return

    try:
        result_id = _write_subentry(
            hass,
            entry,
            subentry,
            subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
            data={"model": model, "model_user": data.get("model_user", "")},
            title=title,
        )
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    # A store binds to this title, and nothing rebuilds the memory registry on
    # its own — without this a new binding did nothing until
    # `smartchain.reload_tools` or a restart, with no error to explain why.
    reload_error = await _rebuild_after_subentry_write(hass)
    connection.send_result(msg["id"], {"subentry_id": result_id, "reload_error": reload_error})


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
    reload_error = await _rebuild_after_subentry_write(hass)
    connection.send_result(msg["id"], {"bound_stores": bound_stores, "reload_error": reload_error})


async def _rebuild_after_subentry_write(hass: HomeAssistant) -> str | None:
    """Rebuild the tool/MCP/memory registry after a subentry changed.

    Adding a memory store or an embeddings binding used to do nothing until
    `smartchain.reload_tools` or a restart — the store simply was not there,
    with no error to explain why. `async_add_subentry` fires no event the
    memory subsystem listens for, so the rebuild has to be explicit.

    Never raises: the write already happened and reporting it as a failure
    would be a lie. A tools.yaml that no longer loads, or an MCP server that
    will not start, comes back as a safe reason string for the panel to show
    beside the successful save — via `_safe_loader_error`, so a `!secret` that
    a validation error interpolated cannot travel with it.

    `only_if_changed` because the same write also fires `update_listener` as a
    background task, and whichever of the two arrives second has nothing left
    to do: the fingerprint check inside `_reload_registry` runs under the
    rebuild lock, so exactly one of them rebuilds. Before that gate the panel
    handler rebuilt unconditionally and the pair cost two — two MCP bounces,
    two reopened backends, and two embedding dimension probes, each a fresh
    OAuth exchange under a 30 s timeout.

    Every caller of this function writes a subentry and nothing else. A handler
    that edits tools.yaml — `tools/save`, `tools/rollback` — calls
    `_reload_registry` directly and ungated, because the fingerprint digests
    subentries and would not see the file move.

    When the gate skips, the standing tools.yaml error is still what comes
    back: the file is as broken as it was a moment ago, and reporting the save
    as clean would hide a banner the user needs.
    """
    from . import _reload_registry

    try:
        rebuilt = await _reload_registry(hass, only_if_changed=True)
    except Exception as err:  # noqa: BLE001 — the write succeeded regardless
        LOGGER.warning(  # detail stays server-side
            "registry rebuild after a subentry change failed: %s", err
        )
        return _safe_loader_error(err)
    if rebuilt is None:
        return hass.data.get(DOMAIN, {}).get("yaml_error")
    return None


def _store_defaults(subentry: Any) -> dict[str, Any]:
    """Stored values for the store form. The title *is* the store name."""
    return {**subentry.data, "name": subentry.title}


def _resolve_store(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[ConfigEntry, Any] | None:
    """Entry and store subentry named by the message, or None after an error."""
    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return None
    subentry = entry.subentries.get(msg["subentry_id"])
    if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_MEMORY_STORE:
        connection.send_error(msg["id"], "not_found", "Unknown memory store")
        return None
    return entry, subentry


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/store/schema",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Optional("data"): dict,
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_store_schema(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serialise the memory-store form, reshaped around the choices made so far.

    Which fields a store has depends on its backend and on whether it indexes
    entities, and `<ha-form>` cannot change shape by itself. So this command
    accepts the in-progress form values in `data` and rebuilds the schema
    around them; `reactive` tells the panel which fields are worth a round
    trip. The panel therefore still declares no field name of its own — the
    list of fields that reshape the form comes from here, like everything else.

    `dsn` and `api_key` are never served from storage — only `secrets_set`
    says whether one is held. A value the *client itself* just sent comes back
    (it is already the client's own), so a credential typed before switching
    backends is not silently dropped.
    """
    from .config_flow import memory_store_subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    stored: dict[str, Any] = {}
    subentry_id = msg.get("subentry_id")
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_MEMORY_STORE:
            connection.send_error(msg["id"], "not_found", "Unknown memory store")
            return
        stored = _store_defaults(subentry)

    draft = dict(msg.get("data") or {})
    defaults = {**stored, **draft}
    schema = memory_store_subentry_schema(hass, defaults)

    # Same trap as ws_agent_schema (see F1): only serve fields the schema still
    # declares, or <ha-form> echoes a stale key back and PREVENT_EXTRA rejects
    # the save forever.
    declared = {str(key.schema) for key in schema.schema}
    served = {
        name: value
        for name, value in defaults.items()
        if name in declared and (name not in MEMORY_SECRET_FIELDS or name in draft)
    }

    from .tools.memory.registry import embeddings_subentries_by_title

    available = embeddings_subentries_by_title(hass)

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer),
            "data": served,
            "labels": await async_field_labels(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_MEMORY_STORE
            ),
            "descriptions": await async_field_descriptions(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_MEMORY_STORE
            ),
            # Changing one of these changes which fields exist, so the panel
            # asks for the schema again rather than guessing.
            "reactive": ["backend_type", "source_type"],
            "secrets_set": {field: bool(stored.get(field)) for field in MEMORY_SECRET_FIELDS},
            # A title claimed twice resolves to nothing (see
            # embeddings_subentries_by_title). Named here so the tab can warn
            # before a write rather than explain a dead store afterwards.
            "embeddings_ambiguous": sorted(
                title for title, binding in available.items() if binding is None
            ),
            "embeddings_available": sorted(available),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/store/save",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_store_save(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update a memory store, then rebuild the registry.

    Validated with exactly the schema `ws_store_schema` served and exactly the
    rules the config-flow dialog applies (`validate_store_input`), so a store
    made here and one made through Devices & Services are the same store.

    Nothing about the submission is echoed back: `msg["data"]` can carry a
    database password, so no error message is built from a submitted value —
    `_describe_invalid` reports field names only, and a rule failure reports a
    field name plus a fixed sentence keyed by `STORE_ERROR_TEXT`.
    """
    from .config_flow import (
        STORE_ERROR_TEXT,
        memory_store_subentry_schema,
        merge_store_secrets,
        validate_store_input,
    )

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    subentry_id = msg.get("subentry_id")
    subentry = None
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_MEMORY_STORE:
            connection.send_error(msg["id"], "not_found", "Unknown memory store")
            return

    stored = _store_defaults(subentry) if subentry is not None else {}
    submitted = dict(msg["data"])
    # The schema's *shape* follows the submission, not what is stored: a save
    # that switches the backend must be validated against the new backend's
    # fields. Only the two shaping keys are taken on trust here, and the
    # selectors in the schema reject an unknown value for either.
    shape = {
        **stored,
        "backend_type": submitted.get("backend_type") or MEMORY_DEFAULT_BACKEND,
        "source_type": submitted.get("source_type") or MEMORY_SOURCE_TYPE_NONE,
    }
    schema = memory_store_subentry_schema(hass, shape)
    declared = {str(key.schema) for key in schema.schema}

    # Rules first, schema second. The other way round — as this was — the
    # `embeddings` dropdown answers for itself before any rule runs: it is
    # vol.Required, and on an install with no embeddings binding its option
    # list is *empty*, so the first Save a new user presses returns
    # `required key not provided` and the panel labels an unanswerable field
    # `invalid_data: embeddings`. Every sentence in STORE_ERROR_TEXT about
    # `embeddings` was unreachable on this path. Nothing is validated less:
    # a submission that clears the rules still goes through the schema below,
    # and the rules read only strings the schema does not coerce.
    #
    # Same shape of failure, and the same fix, as `model_required` on the
    # agent form (see `MODEL_REQUIRED_FALLBACK`): named fields plus a
    # translated sentence, never a bare key.
    error = validate_store_input(
        hass,
        # Merged, because "keep the stored credential" is what an empty `dsn`
        # means — validating the raw submission would report `dsn_required`
        # for an untouched pgvector store.
        merge_store_secrets(submitted, stored, declared),
        subentry_id=subentry_id,
    )
    if error is not None:
        field, key = error
        text = await async_flow_error_text(
            hass,
            key,
            "config_subentries",
            fallback=STORE_ERROR_TEXT[key],
            subentry_type=SUBENTRY_TYPE_MEMORY_STORE,
        )
        connection.send_error(msg["id"], "invalid_data", invalid_data([field], text))
        return

    try:
        data = ensure_storable(schema(submitted))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    data = merge_store_secrets(data, stored, declared)

    title = str(data.pop("name")).strip()

    try:
        result_id = _write_subentry(
            hass,
            entry,
            subentry,
            subentry_type=SUBENTRY_TYPE_MEMORY_STORE,
            data=data,
            title=title,
        )
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    reload_error = await _rebuild_after_subentry_write(hass)
    registry = hass.data.get(DOMAIN, {}).get("memory")
    connection.send_result(
        msg["id"],
        {
            "subentry_id": result_id,
            "reload_error": reload_error,
            # The write succeeded; the store it describes may still not have
            # come up — a wrong DSN, an embeddings binding that resolves to
            # nothing. `MemoryRegistry.build` contains that failure so the
            # other stores start, which left this command answering a plain
            # success and the panel toasting a green "Saved" over a store that
            # never ran. The reason is the same safe text `store/status`
            # serves, taken straight after the rebuild that produced it.
            "store_error": (getattr(registry, "failures", None) or {}).get(title),
            # A YAML store of the same name is now ignored. Reported rather
            # than left to a log line nobody reads.
            "shadows_yaml": title in (hass.data.get(DOMAIN, {}).get("store_shadowed") or []),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/store/delete",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_store_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a memory store and rebuild the registry.

    The vectors themselves are not deleted: a file-based backend keeps its
    `.db` beside the others and a remote one keeps its table or collection, so
    re-creating the store under the same name finds its contents again. Saying
    otherwise would be the more dangerous default.
    """
    resolved = _resolve_store(hass, connection, msg)
    if resolved is None:
        return
    entry, subentry = resolved
    name = subentry.title

    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    reload_error = await _rebuild_after_subentry_write(hass)
    connection.send_result(msg["id"], {"name": name, "reload_error": reload_error})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/store/status"})
@websocket_api.async_response
async def ws_store_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Which configured stores are actually live, and why the others are not.

    `MemoryRegistry.build` contains it when one store fails so the rest still
    come up — which used to mean a failure left no trace outside the log, and
    every command that touched memory reported success over a subsystem that
    never started.
    """
    registry: MemoryRegistry | None = hass.data.get(DOMAIN, {}).get("memory")
    connection.send_result(
        msg["id"],
        {
            "stores": registry.status() if registry is not None else [],
            "shadowed_yaml": list(hass.data.get(DOMAIN, {}).get("store_shadowed") or []),
        },
    )


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

    `backup_exists` lets `smartchain/tools/get` tell the panel whether
    `smartchain/tools/rollback` has anything to do — otherwise the panel can
    only guess from its own session, and a backup made before a restart
    would never surface the Rollback button.

    Read and hashed as UTF-8 explicitly, not the platform locale encoding:
    `load_tools_file` and the hash this is compared against both assume
    UTF-8, and a Cyrillic file under a non-UTF-8 locale must not silently
    mismatch or mojibake.
    """
    backup_exists = _backup_path(path).is_file()
    if not path.exists():
        return {
            "text": "",
            "exists": False,
            "error": None,
            "hash": None,
            "backup_exists": backup_exists,
        }
    try:
        text = path.read_text(encoding="utf-8")
        return {
            "text": text,
            "exists": True,
            "error": None,
            "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "backup_exists": backup_exists,
        }
    except (OSError, UnicodeDecodeError) as err:
        return {
            "text": "",
            "exists": True,
            "error": f"{type(err).__name__}: {path.name} could not be read",
            "hash": None,
            "backup_exists": backup_exists,
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


def _safe_loader_error(err: Exception) -> str:
    """A validation failure summary that cannot carry a resolved secret.

    A YAML *syntax* error (`HomeAssistantError` from HA's loader, or a bare
    `yaml.YAMLError`) is safe to forward verbatim: the parser fails before any
    `!secret` is resolved, so its message carries a line and column and no
    credential — and a text editor without a line number is much harder to
    use. Everything else — in particular a schema failure from voluptuous —
    reports only the exception's type name. Nothing about a `vol.Invalid` /
    `MultipleInvalid` — not its message, not its `.path` — is safe to forward:

    - `str(err)` / `.msg`: two of this schema's own validators
      (`validate_action`, `_validate_mcp_server` in tools/schema.py) build
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

    `save` and `rollback` also pass a plain exception here that isn't a
    `LoaderError` at all — `_reload_registry` can raise more than
    `LoaderError` (an MCP server that won't start, a memory backend that
    won't build), and none of that is a `LoaderError` either. The same logic
    still applies unchanged: no whitelisted cause, so only the type name of
    whatever was raised crosses the wire.
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
    """Restore `.bak` onto `path`, swapping rather than consuming it.

    Deliberately does **not** validate the backup first: it is, by
    construction, a file that once passed `load_tools_file` (nothing but a
    successful save ever creates one), and refusing to restore it would
    strand the user exactly when they most need the escape hatch.

    That is *not* the same as saying the backup is known-good at the moment
    of restore. `save` copies whatever is currently on disk to `.bak`
    *before* validating the new text — by design, so a bad current file
    doesn't block writing a fix — which means the backup can itself be the
    broken file the user is trying to get away from. If a plain
    `os.replace(backup, path)` then consumed it, a rollback that lands on a
    bad backup would destroy the good file it just overwrote, with no way
    back: exactly the case rollback exists to protect against. So the file
    being replaced becomes the *new* backup instead of being discarded — a
    swap, not a one-way move. That makes every rollback its own undo: one
    that lands on a bad file is itself recoverable with a second rollback.

    Returns False, doing nothing, when there is no backup to restore.
    """
    backup = _backup_path(path)
    if not backup.is_file():
        return False
    if path.exists():
        tmp = _tmp_path(path)
        try:
            shutil.copy2(path, tmp)
            os.replace(backup, path)
            os.replace(tmp, backup)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        os.replace(backup, path)
    return True


def _write_tools_file(
    path: Path, text: str, base_hash: str | None, config_dir: Path
) -> tuple[str, str | None]:
    """Blocking body of a save: check staleness, write, validate, back up,
    atomically replace — all inside one executor job.

    The staleness check lives here rather than in a separate executor call
    before this one so that nothing can slip in between "the file matches
    base_hash" and "the file is being written": two hops give the event loop
    a yield point between them where another save could land; one hop
    doesn't.

    The temp-file write, the real `load_tools_file` validation (the
    integration's own loader, so what passes here is what will load at
    startup), and the backup copy are all blocking I/O, which is why this
    whole thing runs off the event loop as a unit.

    Returns `(status, error)`:
    - `("ok", None)` — the file is now on disk at `path`.
    - `("stale", None)` — `base_hash` no longer matches the file on disk;
      nothing was touched.
    - `("invalid", detail)` — the submitted text failed to load; nothing was
      written to `path`. `detail` is already `_safe_loader_error`'s output,
      never a raw exception message.
    - `("write_failed", detail)` — a filesystem or encoding error; `detail`
      is only the exception's type name, never its message (which can embed
      a path or other detail not meant for the wire).

    Reads and writes as UTF-8 explicitly, not the platform locale encoding
    — `load_tools_file` and the hash comparison above both assume UTF-8, so
    a Cyrillic `tools.yaml` under a non-UTF-8 locale must not mojibake, and
    a `UnicodeEncodeError` (not an `OSError`) must still land in
    `write_failed` rather than escape uncaught.

    The temp file is removed on every exit path, including `mkdir` and
    `write_text` failures: a stray `.tmp` beside a config file is confusing
    at best, and `os.replace` already consumes it on the success path, so
    `missing_ok=True` covers both.
    """
    current = _read_tools_file(path)
    if current["hash"] != base_hash:
        return "stale", None

    tmp = _tmp_path(path)
    try:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
        except (OSError, UnicodeError) as err:
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
        except (OSError, UnicodeError) as err:
            return "write_failed", type(err).__name__

        return "ok", None
    finally:
        # Best-effort: `missing_ok=True` only swallows FileNotFoundError.
        # When `path.parent` itself turned out not to be a directory (the
        # write_failed case exercised by
        # test_write_failure_is_reported_as_write_failed), unlinking a path
        # beneath it raises NotADirectoryError instead — cleanup must not
        # itself raise and mask the real status this function already
        # decided on.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _restore_after_failed_reload(path: Path) -> None:
    """Undo a save whose reload failed.

    Ordinarily there is a `.bak` — the pre-save file — to put back, via the
    same swap `_restore_backup` always does. The one case there is not is a
    first-ever save on a fresh install, where `path` did not exist before
    this save either; then "restore" means removing the file `save` just
    wrote, returning to that same fresh-install state rather than leaving a
    file nothing backs up.
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
       the whole behaviour; there is no merge and no last-write-wins. This
       check and the write below both happen inside `_write_tools_file`'s
       single executor job, not two separate ones — see its docstring for
       why two hops would leave a race the event loop could step into.
    2. Write the submitted text to a temp file beside the target, so the
       later `os.replace` stays on one filesystem and therefore stays
       atomic.
    3. Validate the temp file with `load_tools_file` — what passes here is
       what will load at startup.
    4. Back up the current file, before the replace.
    5. `os.replace` the temp file onto the target — atomic, so a crash
       mid-write cannot leave a truncated file.
    6. Reload the registry. If the reload raises *anything* — not only a
       `LoaderError`; `_reload_registry` also runs unguarded MCP and memory
       shutdown/startup calls that can raise their own exceptions — restore
       from the backup and reload again, then report: the user asked to
       save a file, not to lose their tools. A file can validate and still
       fail to load — an MCP server that will not start, an embeddings
       binding that no longer resolves.

    Nothing here parses `text` into a structure and re-serialises it — raw
    text in, raw text out — which is what lets `!secret openai_key` survive
    a save as a reference instead of being written back as the resolved
    key.
    """
    from . import _reload_registry, _tools_yaml_path

    path = _tools_yaml_path(hass)
    config_dir = Path(hass.config.config_dir)

    # 1-5: check staleness, write, validate, back up, atomically replace —
    # all in one executor job. See _write_tools_file for why.
    status, error = await hass.async_add_executor_job(
        _write_tools_file, path, msg["text"], msg["base_hash"], config_dir
    )
    if status != "ok":
        connection.send_result(msg["id"], {"ok": False, "reason": status, "error": error})
        return

    # 6. Reload; on failure, restore and report. Deliberately `Exception`,
    # not `LoaderError`: see the docstring note above.
    try:
        await _reload_registry(hass)
    except Exception as err:  # noqa: BLE001
        LOGGER.warning(  # detail stays server-side
            "tools.yaml reload after save failed; restoring previous file: %s", err
        )
        await hass.async_add_executor_job(_restore_after_failed_reload, path)
        try:
            await _reload_registry(hass)
        except Exception:  # noqa: BLE001
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
    """Swap `tools.yaml.bak` onto `tools.yaml` and reload.

    Does not validate the backup first — see `_restore_backup`. Refuses with
    `no_backup` when there is none. On a reload failure the file that was
    just replaced (which may itself have been a good config, if the backup
    it swapped in turns out to be broken) is left in place as the *new*
    backup by `_restore_backup`'s swap — not restored a second time here —
    so a second rollback can undo this one.
    """
    from . import _reload_registry, _tools_yaml_path

    path = _tools_yaml_path(hass)
    restored = await hass.async_add_executor_job(_restore_backup, path)
    if not restored:
        connection.send_result(msg["id"], {"ok": False, "reason": "no_backup"})
        return

    try:
        await _reload_registry(hass)
    except Exception as err:  # noqa: BLE001
        LOGGER.warning("tools.yaml reload after rollback failed: %s", err)  # server-side only
        connection.send_result(
            msg["id"],
            {"ok": False, "reason": "reload_failed", "error": _safe_loader_error(err)},
        )
        return

    new = await hass.async_add_executor_job(_read_tools_file, path)
    connection.send_result(msg["id"], {"ok": True, "hash": new["hash"]})


# ----- custom tools ------------------------------------------------------


def _resolve_tool(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[ConfigEntry, Any] | None:
    """Entry and tool subentry named by the message, or None after an error."""
    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return None
    subentry = entry.subentries.get(msg["subentry_id"])
    if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_TOOL:
        connection.send_error(msg["id"], "not_found", "Unknown tool")
        return None
    return entry, subentry


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/tool/schema",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Optional("data"): dict,
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_tool_schema(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serialise the tool constructor, reshaped around the choices made so far.

    This is what makes the Tools tab a constructor rather than a text editor,
    and it is deliberately the *only* place the tool's field names exist on the
    wire: the panel renders whatever arrives through `<sc-config-form>`, the
    same way the agents, embeddings and stores tabs do. Which fields a tool has
    depends on its action type and on how its arguments are being authored, and
    `<ha-form>` cannot change shape by itself — so this accepts the in-progress
    values in `data` and rebuilds the schema around them, and `reactive` names
    the two fields worth a round trip.

    A `rest` action's *stored* header values are never served — only their
    names, plus `headers_set` to say which ones hold something. A value the
    client itself just sent comes back untouched, since it is already the
    client's own; redacting the merged dict blanked the draft too, so a header
    typed just before a reshaping round trip came home empty and saved empty on
    a new tool, or silently reverted to the stored value on an edit. This is
    the same per-field rule `ws_store_schema` applies to `dsn` / `api_key`.
    """
    from .config_flow import tool_form_defaults, tool_subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    stored: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    subentry_id = msg.get("subentry_id")
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_TOOL:
            connection.send_error(msg["id"], "not_found", "Unknown tool")
            return
        stored = tool_form_defaults(subentry)
        raw = tool_form_defaults(subentry, redact=False)

    draft = dict(msg.get("data") or {})
    # `stored` already arrives redacted — `tool_form_defaults` redacts by
    # default and only the save paths ask for `redact=False` — so the merge
    # needs no second pass, and must not have one: redacting `{**stored,
    # **draft}` blanked the client's own draft as well as storage. The rule is
    # `ws_store_schema`'s, `name not in secrets or name in draft`, applied to
    # the one field that holds a map: the draft's `headers` replaces the stored
    # map wholesale, which is also what lets a header be deleted in the form.
    defaults = {**stored, **draft}
    schema = tool_subentry_schema(hass, defaults)

    # Same trap as ws_agent_schema (see F1): only serve fields the schema still
    # declares, or <ha-form> echoes a stale key back and PREVENT_EXTRA rejects
    # the save forever.
    declared = {str(key.schema) for key in schema.schema}
    served = {name: value for name, value in defaults.items() if name in declared}

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer),
            "data": served,
            "labels": await async_field_labels(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_TOOL
            ),
            "descriptions": await async_field_descriptions(
                hass, "config_subentries", subentry_type=SUBENTRY_TYPE_TOOL
            ),
            # Changing one of these changes which fields exist, so the panel
            # asks for the schema again rather than guessing.
            "reactive": ["action_type", "params_mode"],
            "headers_set": {key: bool(value) for key, value in (raw.get("headers") or {}).items()},
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/tool/save",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_tool_save(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update a custom tool, then rebuild the registry.

    Validated with exactly the schema `ws_tool_schema` served and exactly the
    rules the config-flow dialog applies (`build_tool_subentry_data`), so a
    tool made here and one made through Devices & Services are the same tool —
    and both end at `tools.schema.validate_action` and `PARAMETERS_SCHEMA`, the
    validators tools.yaml goes through.

    Nothing about the submission is echoed back: `msg["data"]` can carry a REST
    header holding a bearer token, so `_describe_invalid` reports field names
    only and a rule failure reports a field name plus fixed text from
    `TOOL_ERROR_TEXT`.
    """
    from .config_flow import (
        TOOL_ERROR_TEXT,
        build_tool_subentry_data,
        merge_tool_secrets,
        tool_form_defaults,
        tool_subentry_schema,
    )

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    subentry_id = msg.get("subentry_id")
    subentry = None
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_TOOL:
            connection.send_error(msg["id"], "not_found", "Unknown tool")
            return

    stored = tool_form_defaults(subentry, redact=False) if subentry is not None else {}
    submitted = dict(msg["data"])
    # The schema's *shape* follows the submission, not what is stored: a save
    # that switches the action type must be validated against the new type's
    # fields. Only the two shaping keys are taken on trust here, and the
    # selectors in the schema reject an unknown value for either.
    shape = {
        **stored,
        "action_type": submitted.get("action_type") or TOOL_DEFAULT_ACTION_TYPE,
        "params_mode": submitted.get("params_mode") or TOOL_PARAMS_MODE_SIMPLE,
    }
    schema = tool_subentry_schema(hass, shape)

    try:
        # `target` is the field this exists for: `selector.TargetSelector`
        # hands back a `Template` object for `entity_id: "{{ entity }}"` — the
        # shape docs/USAGE.md §7.1 teaches and the importer stores as a plain
        # string — and writing that object into the subentry breaks every
        # later write of `core.config_entries`, for every integration. Run
        # before `build_tool_subentry_data` so a refusal names the form field
        # the user can see rather than the composed `action` block.
        form = ensure_storable(schema(submitted))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    form = merge_tool_secrets(form, stored)
    data, error = build_tool_subentry_data(hass, form, subentry_id=subentry_id)
    if error is not None:
        field, key = error
        connection.send_error(
            msg["id"], "invalid_data", invalid_data([field], TOOL_ERROR_TEXT[key])
        )
        return

    title = str(form["name"]).strip()

    try:
        result_id = _write_subentry(
            hass,
            entry,
            subentry,
            subentry_type=SUBENTRY_TYPE_TOOL,
            data=data,
            title=title,
        )
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", _describe_invalid(err))
        return

    reload_error = await _rebuild_after_subentry_write(hass)
    connection.send_result(
        msg["id"],
        {
            "subentry_id": result_id,
            "reload_error": reload_error,
            # A YAML tool of the same name is now ignored. Reported rather than
            # left to a log line nobody reads.
            "shadows_yaml": title in (hass.data.get(DOMAIN, {}).get("tools_shadowed") or []),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/tool/delete",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_tool_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a custom tool and rebuild the registry."""
    resolved = _resolve_tool(hass, connection, msg)
    if resolved is None:
        return
    entry, subentry = resolved
    name = subentry.title

    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    reload_error = await _rebuild_after_subentry_write(hass)
    connection.send_result(msg["id"], {"name": name, "reload_error": reload_error})


def _describe_tool_subentry(entry: ConfigEntry, subentry: Any) -> dict[str, Any]:
    """Public description of one tool subentry.

    Assembled field by field for the same reason `_describe_store` is: a REST
    action's headers can hold a bearer token, so `subentry.data` is never
    forwarded wholesale. Only whether a header holds a value travels.
    """
    data = subentry.data
    action = dict(data.get("action") or {})
    return {
        "entry_id": entry.entry_id,
        "subentry_id": subentry.subentry_id,
        "name": subentry.title,
        "description": data.get("description", ""),
        "action_type": action.get("type", ""),
        "enabled": bool(data.get("enabled", True)),
        "source": SOURCE_SUBENTRY,
        "headers_set": {key: bool(value) for key, value in (action.get("headers") or {}).items()},
    }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tool/list"})
@websocket_api.async_response
async def ws_tool_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Every tool the installation has, and where each one comes from.

    Three sources reach one registry, and the panel can only edit one of them,
    so saying which is which is the whole point: a subentry tool is editable
    here, a tools.yaml tool is editable in the Import/Export box, and an MCP
    tool is not editable at all because it is discovered from a server.

    Disabled subentry tools are listed even though they are *not* in the
    registry — they exist, the user turned them off, and a list that hid them
    would leave no way to turn one back on.
    """
    from .tools.model import MCPAction
    from .tools.subentry_source import tool_subentries

    tools = [_describe_tool_subentry(entry, subentry) for entry, subentry in tool_subentries(hass)]

    registry = hass.data.get(DOMAIN, {}).get("tools")
    sources = hass.data.get(DOMAIN, {}).get("tool_sources") or {}
    subentry_names = {tool["name"] for tool in tools}
    for tool in registry.all() if registry is not None else []:
        if tool.name in subentry_names:
            continue
        tools.append(
            {
                "entry_id": None,
                "subentry_id": None,
                "name": tool.name,
                "description": tool.description,
                "action_type": tool.action.type,
                "enabled": True,
                "source": "mcp"
                if isinstance(tool.action, MCPAction)
                else sources.get(tool.name, SOURCE_YAML),
                "headers_set": {},
            }
        )

    connection.send_result(
        msg["id"],
        {
            "tools": sorted(tools, key=lambda tool: tool["name"]),
            "shadowed_yaml": list(hass.data.get(DOMAIN, {}).get("tools_shadowed") or []),
            # A tools.yaml that will not load no longer takes the subentry
            # tools down with it, which means the list below looks perfectly
            # healthy while the file's own tools are missing. Say so here: a
            # standing line on the tab, not a toast tied to whichever action
            # happened to trigger the rebuild. Already passed through
            # `_safe_loader_error` in `_reload_registry`.
            "yaml_error": hass.data.get(DOMAIN, {}).get("yaml_error"),
        },
    )


def _scan_for_secret_tags(text: str) -> bool:
    """Does this YAML text use `!secret` anywhere?

    A cheap textual scan, on purpose. The alternative — parsing with a
    `Secrets` store and inspecting the result — would resolve the secret in
    order to find out that it is there, which is exactly what the import must
    not do.
    """
    return "!secret" in text


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/tools/import",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_tools_import(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Turn the tools already in tools.yaml into editable `tool` subentries.

    Parsed **without** a `Secrets` store, and refused outright if the file uses
    `!secret` anywhere. Resolving one here would write the plaintext value into
    `.storage`, silently moving a credential out of `secrets.yaml` — the same
    rule and the same reasoning as the memory-store importer. The user is told
    to replace those references with values typed into the form, where they are
    at least stored knowingly.

    tools.yaml is left exactly as it is. An imported tool then shadows its YAML
    twin, which `tool/list` reports; deleting it from the file is the user's
    call to make, not an importer's.
    """
    from . import _tools_yaml_path
    from .config_flow import validate_tool_name

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    path = _tools_yaml_path(hass)
    current = await hass.async_add_executor_job(_read_tools_file, path)
    if not current["exists"] or current["error"]:
        connection.send_result(msg["id"], {"ok": False, "reason": "no_file", "imported": []})
        return
    if _scan_for_secret_tags(current["text"]):
        connection.send_result(
            msg["id"], {"ok": False, "reason": "secrets_present", "imported": []}
        )
        return

    try:
        # config_dir omitted deliberately — see the docstring. Without it HA's
        # loader refuses `!secret` rather than resolving it, so even a form the
        # scan above did not anticipate cannot leak.
        result = await hass.async_add_executor_job(load_tools_file, path)
    except LoaderError as err:
        LOGGER.warning("tools.yaml import failed: %s", err)  # detail stays server-side
        connection.send_result(
            msg["id"],
            {"ok": False, "reason": "invalid", "error": _safe_loader_error(err), "imported": []},
        )
        return

    imported: list[str] = []
    skipped: list[str] = []
    for tool in result.yaml_tools:
        form = {
            "name": tool.name,
            "description": tool.description,
            "enabled": True,
            "parameters": tool.parameters,
        }
        if validate_tool_name(hass, tool.name) is not None:
            skipped.append(tool.name)
            continue
        data = {
            "description": form["description"],
            "parameters": dict(tool.parameters),
            "action": _action_to_dict(tool.action),
            "enabled": True,
            "params_mode": _params_mode_for(tool.parameters),
        }
        try:
            _write_subentry(
                hass,
                entry,
                None,
                subentry_type=SUBENTRY_TYPE_TOOL,
                data=data,
                title=tool.name,
            )
        except vol.Invalid:
            # One tool that cannot be stored must not abort an import of
            # twenty, and it must not be reported by echoing its value — an
            # action can hold a bearer token. It joins the skipped list.
            skipped.append(tool.name)
            continue
        imported.append(tool.name)

    reload_error = await _rebuild_after_subentry_write(hass)
    connection.send_result(
        msg["id"],
        {
            "ok": True,
            "imported": imported,
            "skipped": skipped,
            "reload_error": reload_error,
        },
    )


# ----- the preset catalogue ---------------------------------------------


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tool/presets"})
@websocket_api.async_response
async def ws_tool_presets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """The ready-made tool catalogue, with each entry's install state.

    `installed` is derived from the tool subentries that exist right now rather
    than remembered anywhere, because there is nothing to remember: installing a
    preset writes an ordinary tool subentry and the integration keeps no mark on
    it afterwards. A user who renames an installed preset therefore sees the
    catalogue offer it again — correctly, since under that name it no longer
    exists.

    A tools.yaml tool of the same name does *not* count as installed. It is not
    a subentry, the panel cannot edit it, and installing over it is allowed —
    the result shadows the file, which `preset/install` reports the same way
    `tool/save` does.
    """
    from .tools.presets import PRESET_TOOLS
    from .tools.subentry_source import tool_subentries

    texts = await async_preset_texts(hass)
    installed = {subentry.title for _entry, subentry in tool_subentries(hass)}

    connection.send_result(
        msg["id"],
        {
            "presets": [
                {
                    "name": preset.name,
                    # The panel-facing pair, translated; falls back to the tool
                    # name and to nothing, so an untranslated preset still
                    # renders as a row the user can switch on.
                    "title": texts.get(preset.name, {}).get("name", preset.name),
                    "blurb": texts.get(preset.name, {}).get("description", ""),
                    "action_type": preset.action_type,
                    "installed": preset.name in installed,
                }
                for preset in PRESET_TOOLS
            ]
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/tool/preset/install",
        vol.Required("entry_id"): str,
        vol.Required("preset"): str,
    }
)
@websocket_api.async_response
async def ws_tool_preset_install(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Materialise one preset as an ordinary tool subentry.

    The same three writes `ws_tool_save` performs, in the same order and
    through the same functions: `validate_tool_name` for the reserved-name,
    duplicate-name and live-MCP-name rules, `_write_subentry` for the
    JSON-storability guard, `_rebuild_after_subentry_write` for the registry.
    Nothing here is a preset-specific code path, which is what makes the
    resulting tool an ordinary one — after this command the integration has no
    way of telling it apart from a tool built in the form, and does not try.

    A refusal comes back as `{"ok": False, "reason": ...}` rather than as a
    websocket error, following `tools/import` rather than `tool/save`: there is
    no form open and no field to attach a message to, so the panel needs a
    reason it can turn into its own sentence. `params_mode` is derived, not
    stored in the catalogue — see `preset_subentry_data`.
    """
    from .config_flow import validate_tool_name
    from .tools.presets import PRESETS_BY_NAME, preset_subentry_data

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    preset = PRESETS_BY_NAME.get(msg["preset"])
    if preset is None:
        connection.send_error(msg["id"], "not_found", "Unknown preset")
        return

    error = validate_tool_name(hass, preset.name)
    if error is not None:
        _field, key = error
        connection.send_result(msg["id"], {"ok": False, "reason": key})
        return

    data = preset_subentry_data(preset)
    data["params_mode"] = _params_mode_for(data["parameters"])

    try:
        subentry_id = _write_subentry(
            hass,
            entry,
            None,
            subentry_type=SUBENTRY_TYPE_TOOL,
            data=data,
            title=preset.name,
        )
    except vol.Invalid:
        # Unreachable with the catalogue as it stands — every entry is plain
        # JSON, and a test holds it to that — but the guard is structural in
        # `_write_subentry` and swallowing its refusal here would be the one
        # place that undoes it.
        LOGGER.warning("preset %r could not be stored", preset.name)
        connection.send_result(msg["id"], {"ok": False, "reason": "unstorable"})
        return

    reload_error = await _rebuild_after_subentry_write(hass)
    connection.send_result(
        msg["id"],
        {
            "ok": True,
            "name": preset.name,
            "subentry_id": subentry_id,
            "reload_error": reload_error,
            # Same report as `tool/save`: a tools.yaml tool of this name is now
            # ignored in favour of the one just written.
            "shadows_yaml": preset.name in (hass.data.get(DOMAIN, {}).get("tools_shadowed") or []),
        },
    )


def _params_mode_for(parameters: dict[str, Any]) -> str:
    from .config_flow import _parameters_are_row_expressible

    return (
        TOOL_PARAMS_MODE_SIMPLE
        if _parameters_are_row_expressible(parameters)
        else TOOL_PARAMS_MODE_ADVANCED
    )


def _action_to_dict(action: Any) -> dict[str, Any]:
    """A `ToolAction` dataclass back as the plain dict both sources store.

    `dataclasses.asdict` rather than a hand-written per-type mapping: the field
    names of `ServiceAction` and friends *are* the YAML keys, so a mapping
    table would be a second place for them to live and the first place to drift.
    """
    import dataclasses

    return dataclasses.asdict(action)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tools/export"})
@websocket_api.async_response
async def ws_tools_export(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Every tool subentry as tools.yaml text, for backup or for another install.

    **REST header values are exported blank**, and the tools whose headers were
    blanked are named in `redacted`. Export is a response like any other, and
    the rule that no response carries a credential does not acquire an
    exception because the user asked nicely — an `Authorization` header pasted
    into the form would otherwise come back out as plaintext into a browser and
    from there into wherever the text is pasted. The structure is complete and
    importable; the values are retyped, or written as `!secret` once the file
    is on disk.
    """
    from .tools.subentry_source import tool_from_subentry, tool_subentries

    tools: list[dict[str, Any]] = []
    redacted: list[str] = []
    for _entry, subentry in tool_subentries(hass):
        try:
            tool = tool_from_subentry(subentry)
        except Exception as err:  # noqa: BLE001 — one bad tool must not fail the export
            LOGGER.warning(
                "tool subentry %r could not be exported (%s)", subentry.title, type(err).__name__
            )
            continue
        action = _action_to_dict(tool.action)
        if action.get("headers"):
            action["headers"] = dict.fromkeys(action["headers"], "")
            redacted.append(tool.name)
        entry_dict: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "action": action,
        }
        if not tool.enabled:
            entry_dict["enabled"] = False
        tools.append(entry_dict)

    text = yaml.safe_dump({"tools": tools}, sort_keys=False, allow_unicode=True) if tools else ""
    connection.send_result(msg["id"], {"text": text, "count": len(tools), "redacted": redacted})
