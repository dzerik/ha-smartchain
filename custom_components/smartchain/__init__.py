"""The SmartChain integration."""

import asyncio
import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.camera import async_get_image
from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from langchain_core.messages import HumanMessage

from .client_util import get_client
from .helpers import async_generate_structured  # re-exported for downstream integrations
from .tools import ToolRegistry
from .tools.loader import LoaderError, LoaderResult, load_tools_file
from .tools.mcp import MCPManager
from .tools.memory.entity_context import SkeletonCache
from .tools.memory.registry import MemoryRegistry
from .tools.memory.subentry_source import merge_store_sources, stores_from_subentries
from .tools.subentry_source import (
    merge_tool_sources,
    subentry_tool_names,
    tools_from_subentries,
)

__all__ = ["async_generate_structured"]
from .const import (
    CONF_ALLOWED_TOOLS,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENABLE_HISTORY_TOOL,
    CONF_ENABLE_MULTI_AGENT_TOOLS,
    CONF_ENGINE,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    EVENT_ENTITIES_REINDEXED,
    EVENT_MEMORY_CLEARED,
    EVENT_TOOLS_RELOADED,
    ID_GIGACHAT,
    MEMORY_PERSIST_DIRNAME,
    PANEL_STATIC_PATH,
    SERVICE_CLEAR_MEMORY,
    SERVICE_REINDEX_ENTITIES,
    SERVICE_RELOAD_TOOLS,
    SIGNAL_NEW_ANALYSIS,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    SUBENTRY_TYPE_TOOL,
    TOOLS_YAML_PATH,
)

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR]

# SmartChain has no YAML-only configuration entry point — it is set up exclusively
# via config flow. Declaring this satisfies hassfest's CONFIG_SCHEMA check.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

try:
    from homeassistant.components import ai_task  # noqa: F401

    PLATFORMS.append(Platform.AI_TASK)
except (ImportError, AttributeError):
    pass


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Decide, per write, whether the hub reloads and whether the subsystems rebuild.

    Two different things are wired to the one update listener, and they cost
    very different amounts.

    **The reload** is what a change to the *entry* needs: its data, its options
    and its conversation subentries are what `async_setup_entry` builds every
    LLM client from, so an edited agent takes effect no other way. It is also
    the expensive one — it unloads every platform, so every `conversation.*`
    entity leaves the state machine and comes back, and an Assist request
    landing in that window fails.

    **The rebuild** is what a change to a *subsystem* subentry needs — a tool, a
    memory store, an embeddings binding — and it is here because Home
    Assistant's own subentry dialogs write through `async_add_subentry` /
    `async_update_and_abort` and call no rebuild path of their own. The panel's
    websocket handlers do call one; the config-flow dialogs never did, so a
    tool created through HA's own UI did nothing until `smartchain.reload_tools`
    or a restart, with no error anywhere.

    Until 5.4.8 the reload ran unconditionally, so the cheap change paid for the
    expensive one: switching on a single ready-made tool took every agent
    offline and back, and on a single-entry install — the shape most people
    have — it rebuilt the subsystems a *second* time on top of the rebuild the
    websocket handler had already awaited, because unloading the last entry
    sets `subsystems_stopped` and the following setup honours it
    unconditionally. Two rebuilds meant two dimension probes against the
    embeddings provider, each a fresh OAuth exchange under a 30 s timeout.

    So each half is now gated on its own fingerprint:

    - `_entry_fingerprint` covers everything `async_setup_entry` reads. It is
      written as *everything except the subsystem subentries* rather than as a
      list of the keys that matter, so a field added to the entry later is
      reloaded for by default — the safe direction.
    - `_subsystem_fingerprint` covers the subsystem subentries, and the check
      is made inside `_reload_registry`, under the rebuild lock, so that two
      paths reacting to the same write cannot both find it stale and both
      rebuild. That ordering was the second rebuild in the *two*-entry case.

    Ordered reload-then-rebuild on purpose: `async_reload` may itself tear the
    subsystems down and rebuild them, and a rebuild that ran first would simply
    be discarded by it — after which the gated call below is a no-op, because
    that rebuild recorded the current fingerprint.
    """
    # Imported here rather than at module scope: `websocket_api` imports from
    # this module, and the panel registration at the bottom of `async_setup`
    # defers for the same reason.
    from .websocket_api import async_invalidate_stale_model_cache

    # Before either branch, and unconditionally: the panel's model cache is
    # keyed by entry and invalidated by nothing but an explicit Refresh models,
    # so a connection edited here would otherwise keep serving the list fetched
    # over the *old* connection until a restart. The call decides for itself
    # whether this write touched the connection at all, so an agent save does
    # not throw the cache away.
    async_invalidate_stale_model_cache(hass, entry)

    if _entry_fingerprint(entry) != _entry_fingerprints(hass).get(entry.entry_id):
        await hass.config_entries.async_reload(entry.entry_id)

    try:
        await _reload_registry(hass, only_if_changed=True)
    except LoaderError as err:
        # The rebuild happened regardless; only tools.yaml failed to load, and
        # it is logged safely (never `str(err)` on a user surface — see
        # `_handle_reload_tools`). There is no caller to raise at: a config
        # entry update listener's exception goes nowhere a user would see.
        LOGGER.error("SmartChain tools.yaml load failed after a subentry change: %s", err)


# Subentry types the shared subsystems (tool registry, MCP, memory) are built
# from. A conversation subentry is not one of them: it configures an agent,
# which the entry reload already rebuilds.
_SUBSYSTEM_SUBENTRY_TYPES = frozenset(
    {SUBENTRY_TYPE_TOOL, SUBENTRY_TYPE_MEMORY_STORE, SUBENTRY_TYPE_EMBEDDINGS}
)


@callback
def _entry_fingerprints(hass: HomeAssistant) -> dict[str, str]:
    """Per-entry digest of what the last `async_setup_entry` was built from."""
    return hass.data.setdefault(DOMAIN, {}).setdefault("entry_fingerprints", {})


@callback
def _entry_fingerprint(entry: ConfigEntry) -> str:
    """Digest of everything a reload of this entry would pick up.

    Defined by exclusion: the entry's own data, options, title and minor
    version, plus every subentry that is *not* one the shared subsystems are
    built from. A conversation subentry is in here because its model and prompt
    are what `get_client` builds from and what the `conversation.*` entity is
    named after; a tool subentry is not, because nothing in setup reads one —
    `custom_tools_for` reads the live registry at request time, so a tool
    switched on is in the next message without the entity being touched.

    Excluding rather than listing is deliberate. A new key on the entry, or a
    fifth subentry type, is then reloaded for until someone decides otherwise,
    and the failure mode of getting it wrong is a redundant reload rather than
    a setting that silently does not apply.

    Entry data and subentry data can both hold a credential. This is a one-way
    digest kept in `hass.data`; it is never returned, logged or sent anywhere,
    and nothing else may start reporting it.
    """
    parts = [
        json.dumps(
            [entry.title, entry.minor_version, dict(entry.data), dict(entry.options)],
            sort_keys=True,
            default=repr,
        )
    ]
    for subentry in (entry.subentries or {}).values():
        if subentry.subentry_type in _SUBSYSTEM_SUBENTRY_TYPES:
            continue
        parts.append(
            json.dumps(
                [
                    subentry.subentry_id,
                    subentry.subentry_type,
                    subentry.title,
                    dict(subentry.data),
                ],
                sort_keys=True,
                default=repr,
            )
        )
    # Sorted for the same reason `_subsystem_fingerprint` sorts: a reload
    # rebuilds `entry.subentries` as a fresh mapping, and iteration order alone
    # must not read as a change.
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()


@callback
def _subsystem_fingerprint(hass: HomeAssistant) -> str:
    """Digest of every subentry the shared subsystems read.

    Order-independent (the parts are sorted) so that reloading an entry, which
    rebuilds `entry.subentries` as a fresh mapping, does not by itself look
    like a change.

    Subentry `data` can hold a credential — a qdrant key, a PostgreSQL DSN, a
    REST header. This value is a one-way digest kept in `hass.data` and is
    never returned, logged or sent anywhere; nothing else may start reporting
    it.
    """
    parts: list[str] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        for subentry in (entry.subentries or {}).values():
            if subentry.subentry_type not in _SUBSYSTEM_SUBENTRY_TYPES:
                continue
            parts.append(
                json.dumps(
                    [
                        subentry.subentry_id,
                        subentry.subentry_type,
                        subentry.title,
                        dict(subentry.data),
                    ],
                    sort_keys=True,
                    default=repr,
                )
            )
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()


@callback
def _rebuild_lock(hass: HomeAssistant) -> asyncio.Lock:
    """The one lock every rebuild and every teardown of the shared subsystems takes.

    `hass.config_entries.async_add_subentry` is `_async_update_entry`, which
    fires every update listener as a *background task* — so `update_listener`
    and the rebuild a websocket handler awaits after the same write used to run
    concurrently. Both call `_reload_registry`, which stops and restarts the
    one `MCPManager`, calls `replace_all` on the one `ToolRegistry`, and builds
    a `MemoryRegistry` to swap into `hass.data[DOMAIN]["memory"]`. Interleaved,
    both passes read the *same* old registry before either installs its new
    one, so the first new registry is never shut down: its retention, logbook
    and entity-index tasks keep running for the life of the process, against
    the same backend file the live registry is now using, ingesting every
    conversation turn twice.

    Created lazily rather than at import: the lock must belong to the running
    event loop, and a module-level `asyncio.Lock()` would be shared across the
    loops a test session creates.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    lock = domain_data.get("rebuild_lock")
    if lock is None:
        lock = domain_data["rebuild_lock"] = asyncio.Lock()
    return lock


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to the current minor version.

    Lives here rather than in `async_setup_entry` on purpose: it writes
    `entry.options`, and `update_listener` — registered as an update listener
    during setup — reloads the entry on any update, so writing options from
    inside setup would re-enter setup. `async_migrate_entry` is Home Assistant's
    dedicated pre-setup hook and runs before that listener exists.
    """
    if entry.minor_version < 2:
        options = _migrate_legacy_agent(hass, entry)
        if options is None:
            # The migration refused. Leave `minor_version` at 1 so the entry
            # stays on the legacy path, and so the attempt is retried on the
            # next start once whatever blocked it has been resolved. Minor
            # version 3 is not attempted either: the entry has no agent
            # subentry to write a tool list onto.
            return True
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)

    if entry.minor_version < 3:
        _migrate_agent_tool_lists(hass, entry)
        hass.config_entries.async_update_entry(entry, minor_version=3)

    if entry.minor_version < 4:
        options = _migrate_connection_keys(hass, entry)
        hass.config_entries.async_update_entry(entry, options=options, minor_version=4)

    return True


@callback
def _migrate_connection_keys(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Move the connection switches off every agent and onto the entry.

    Returns the options the entry should carry afterwards.

    `verify_ssl` and `profanity` describe a connection to a provider, and
    v5.1.0 moved them onto the entry for exactly that reason — but
    `subentry_schema` went on declaring both for GigaChat with a voluptuous
    `default=`, so every agent save injected them whether or not the user had
    ever seen the field, and `client_util.get_client` preferred the agent's
    copy. The hub form was a placebo. v5.4.1 removes the fields from the agent
    form; this migration removes the values they left behind.

    The one thing that must not happen is a working install changing
    behaviour, and there is exactly one case where it could: an agent whose
    stored value is what the client was actually being built with. So the
    value is lifted onto the entry when the entry has none of its own, and
    only then dropped. When the entry does carry the key the entry's value is
    already the answer the user configured on the connection screen, and the
    agent's copy is discarded — loudly, at INFO, if the two disagreed, because
    that is the only case where someone's client changes.

    Agents are visited in a fixed order, so two agents disagreeing over a key
    the entry does not have resolves the same way on every run; the second
    agent's value is then a disagreement with the freshly promoted one and is
    logged as such.
    """
    from .config_flow import CONNECTION_KEYS

    engine = entry.data.get(CONF_ENGINE) or ID_GIGACHAT
    keys = CONNECTION_KEYS.get(engine, ())
    options = dict(entry.options)
    if not keys:
        return options

    for subentry in list((entry.subentries or {}).values()):
        if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
            continue
        data = dict(subentry.data)
        for key in keys:
            if key not in data:
                continue
            stored = data.pop(key)
            if key not in options:
                options[key] = stored
                LOGGER.info(
                    "SmartChain entry %s: %r from agent %r now belongs to the connection",
                    entry.title,
                    key,
                    subentry.title,
                )
            elif options[key] != stored:
                LOGGER.info(
                    "SmartChain entry %s: agent %r carried %s=%r; the connection's %r is "
                    "what is used from now on. Change it on the connection's settings screen "
                    "if that is not what you want",
                    entry.title,
                    subentry.title,
                    key,
                    stored,
                    options[key],
                )
        if data == dict(subentry.data):
            continue
        hass.config_entries.async_update_subentry(entry, subentry, data=data)

    return options


@callback
def _migrate_agent_tool_lists(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Write down each agent's built-in tools, then delete the switches.

    Before v5.4.0 an agent's capabilities were split across three controls that
    could not see each other: `allowed_tools` (custom tools only, and only
    rendered when the tools registry was non-empty), `enable_history_tool` and
    `enable_multi_agent_tools`. v5.4.0 makes `allowed_tools` the one control
    and lists the built-ins in it, which leaves the two switches as a second
    opinion on the same question — so they are folded in here and removed.

    `legacy_allowed_tools` produces exactly the set the old three controls
    produced between them, so no agent changes behaviour. What does change, and
    is the point, is that the answer is now written down where the user can
    read and edit it.

    Note which function that is. `materialise_allowed_tools` hands a stored
    list straight back, which is right for the form and wrong here: an agent
    that already had an `allowed_tools` list had it under the *old* semantics,
    where it governed custom tools only and the six built-ins were granted
    elsewhere. Reading it as an answer about built-ins stripped all six from
    every such agent, and this function then deletes the switches that would
    have said otherwise.

    A consequence worth stating: every migrated agent now carries an explicit
    list, so a built-in added in a *later* release is not granted to it
    automatically. That is the same conservative rule `allowed_tools` has
    always applied to custom tools, now applied to built-ins as well.
    """
    from .tools.inventory import legacy_allowed_tools

    for subentry in list((entry.subentries or {}).values()):
        if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
            continue
        data = dict(subentry.data)
        data[CONF_ALLOWED_TOOLS] = legacy_allowed_tools(data)
        data.pop(CONF_ENABLE_HISTORY_TOOL, None)
        data.pop(CONF_ENABLE_MULTI_AGENT_TOOLS, None)
        if data == dict(subentry.data):
            continue
        hass.config_entries.async_update_subentry(entry, subentry, data=data)
        LOGGER.debug(
            "SmartChain entry %s: agent %r now lists its tools explicitly",
            entry.title,
            subentry.title,
        )


@callback
def _legacy_unique_ids(entry: ConfigEntry) -> list[tuple[str, str, str]]:
    """The unique ids a pre-agent entry's two entities were registered under.

    ``(platform domain, legacy unique id, the suffix an agent's carries)``. One
    list, so that "is this entry legacy" and "what has to be renamed" can never
    answer for different sets of entities.
    """
    return [
        ("conversation", entry.entry_id, ""),
        ("ai_task", f"{entry.entry_id}_ai_task", "_ai_task"),
    ]


@callback
def _has_legacy_entity(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Whether a registry row still sits at either legacy unique id."""
    ent_reg = er.async_get(hass)
    return any(
        ent_reg.async_get_entity_id(domain, DOMAIN, old_unique_id) is not None
        for domain, old_unique_id, _suffix in _legacy_unique_ids(entry)
    )


@callback
def _migrate_legacy_agent(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any] | None:
    """Turn a legacy entry's agent-shaped options into a real agent subentry.

    Returns the options the entry should carry afterwards, or ``None`` to refuse
    the migration and leave the entry exactly as it was found.

    The delicate part is the entity id. The legacy entity's unique id is the
    config entry id; an agent's is ``f"{entry_id}_{subentry_id}"``. Creating the
    subentry and letting a second entity appear would orphan the old one and
    break every automation, script and dashboard card naming it — so the
    existing registry rows are rewritten in place instead, which keeps the
    entity id, the friendly name and the area. There are two of them: the
    conversation entity and, when the AI Task platform is available, its
    counterpart. Moving one and orphaning the other is the same failure in a
    smaller costume.

    What makes an entry legacy is the entity, not the options. The test used to
    be "do the options look agent-shaped" alone, which lost the entity of every
    entry whose options were not: a hub created in 5.0.x and never configured
    has ``options == {}``, and one whose owner only ever moved the temperature
    slider has ``{"temperature": 0.9}`` — yet both did get a working
    ``conversation.*`` entity under 5.0.x, because that release built its
    single entity from whatever `entry.options` held. Taking the "nothing to
    do" path for those bumped `minor_version` past the refusal net in
    `conversation.py` and `ai_task.py`, and the entity simply disappeared with
    nothing created to replace it. So a registry row at either legacy unique id
    is enough on its own to migrate, whatever shape the options are in.
    """
    options = dict(entry.options)
    agent_shaped = any(
        key in options for key in (CONF_CHAT_MODEL, CONF_CHAT_MODEL_USER, CONF_PROMPT)
    )

    agents = [
        sub
        for sub in (entry.subentries or {}).values()
        if sub.subentry_type == SUBENTRY_TYPE_CONVERSATION
    ]
    if agents:
        # An entry that already has agents never needs another, and the entity
        # its agents own is the one the platforms create. A legacy registry row
        # left over beside them is an orphan of an entry that grew a subentry,
        # and renaming it onto an agent that already has an entity would
        # collide; leave it.
        if agent_shaped:
            # Both options and agents. The options have been dead configuration
            # since the first agent was created; clearing them would be tidier
            # and is the one irreversible act available here, for data that
            # costs nothing to leave alone. So: say so once, change nothing.
            LOGGER.info(
                "SmartChain entry %s carries legacy agent options alongside %d agent(s). "
                "The options are no longer used or presented; they are left in storage untouched",
                entry.title,
                len(agents),
            )
        return options

    if not agent_shaped and not _has_legacy_entity(hass, entry):
        # Neither agent-shaped options nor an entity to preserve: a
        # connection-only entry, or one already migrated by hand. Nothing to
        # do, and nothing to log about.
        return options

    from .config_flow import CONNECTION_KEYS, agent_title

    engine = entry.data.get(CONF_ENGINE) or ID_GIGACHAT
    # The connection switches stay with the connection and are not copied onto
    # the agent: `client_util.get_client` reads them off `entry.options` and
    # nowhere else, so a copy on the agent would be dead weight that the
    # 3 -> 4 migration would only have to delete again.
    connection_keys = CONNECTION_KEYS.get(engine, ())
    agent_data = {key: value for key, value in options.items() if key not in connection_keys}
    connection_only = {key: options[key] for key in connection_keys if key in options}

    subentry = ConfigSubentry(
        data=agent_data,
        subentry_type=SUBENTRY_TYPE_CONVERSATION,
        title=agent_title(agent_data),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)

    ent_reg = er.async_get(hass)
    moves = [
        (domain, old_unique_id, f"{entry.entry_id}_{subentry.subentry_id}{suffix}")
        for domain, old_unique_id, suffix in _legacy_unique_ids(entry)
    ]
    done: list[tuple[str, str]] = []
    for domain, old_unique_id, new_unique_id in moves:
        entity_id = ent_reg.async_get_entity_id(domain, DOMAIN, old_unique_id)
        if entity_id is None:
            # Legitimately absent: the AI Task platform is conditional, and a
            # user may have deleted the entity.
            continue
        try:
            ent_reg.async_update_entity(entity_id, new_unique_id=new_unique_id)
        except Exception as err:  # noqa: BLE001 - the registry raises ValueError today
            LOGGER.error(
                "SmartChain entry %s: refusing to migrate the legacy agent — could not move "
                "%s to its new unique id (%s). The entry is left on the legacy path; "
                "resolve the conflicting entity and restart Home Assistant",
                entry.title,
                entity_id,
                type(err).__name__,
            )
            _undo_unique_id_moves(ent_reg, done)
            hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
            return None
        done.append((entity_id, old_unique_id))

    LOGGER.info(
        "SmartChain entry %s: migrated legacy options into agent %r; %d entity(ies) kept "
        "their entity id",
        entry.title,
        subentry.title,
        len(done),
    )
    return connection_only


@callback
def _undo_unique_id_moves(ent_reg: er.EntityRegistry, done: list[tuple[str, str]]) -> None:
    """Put back the unique ids already rewritten before a migration refused."""
    for entity_id, old_unique_id in reversed(done):
        try:
            ent_reg.async_update_entity(entity_id, new_unique_id=old_unique_id)
        except Exception as err:  # noqa: BLE001
            LOGGER.error(
                "SmartChain: could not restore the unique id of %s after a refused "
                "migration (%s); the entity may need to be re-added",
                entity_id,
                type(err).__name__,
            )


def _resolve_client_args(options: dict) -> dict:
    """Build common LLM client args from options/subentry data dict."""
    model = options.get(CONF_CHAT_MODEL_USER)
    if not model or not model.strip():
        model = options.get(CONF_CHAT_MODEL)
    if not model or not model.strip() or model == "none":
        model = None
    temperature = options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
    max_tokens = options.get(CONF_MAX_TOKENS)

    common_args: dict = {
        "verbose": False,
        "model": model,
    }
    if temperature is not None:
        common_args["temperature"] = temperature
    if max_tokens is not None:
        common_args["max_tokens"] = max_tokens
    # `verify_ssl` and `profanity` used to be forwarded from here whenever the
    # agent's data carried them. They are connection settings and the entry
    # owns them, so nothing is forwarded any more and `client_util.get_client`
    # reads `entry.options` alone. This is the second half of the fix: the
    # 3 -> 4 migration deletes an agent's stored copy, and not forwarding means
    # a copy that survives anyway — hand-edited storage, a restore of an old
    # backup — is inert rather than quietly outranking the hub.
    return common_args


SERVICE_ASK = "ask"
SERVICE_ASK_SCHEMA = vol.Schema(
    {
        vol.Required("message"): str,
        vol.Optional("entity_id"): str,
    }
)

SERVICE_ANALYZE_IMAGE = "analyze_image"
SERVICE_ANALYZE_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): str,
        vol.Required("camera_entity_id"): str,
        vol.Optional("entity_id"): str,
        vol.Optional("notify_entity"): str,
    }
)

# Kept for backwards-compatibility with users who reference the entity_id from
# automations / templates. The actual entity is registered via the SENSOR platform
# in sensor.py.
SENSOR_LAST_ANALYSIS = f"sensor.{DOMAIN}_last_analysis"
EVENT_IMAGE_ANALYZED = f"{DOMAIN}_image_analyzed"

_GENERIC_LLM_ERROR = "LLM request failed; see Home Assistant logs for details."
_GENERIC_CAMERA_ERROR = "Failed to read camera image; see Home Assistant logs for details."


def _find_client(hass: HomeAssistant, entity_id: str | None = None):
    """Find a SmartChain LLM client, optionally routed by entity_id.

    Routing uses entity_registry to resolve `entity_id` -> `unique_id`, which is
    the only stable mapping back to a subentry / config entry (entity_id is
    derived from the title slug, not the unique_id).
    """
    if entity_id:
        ent_reg = er.async_get(hass)
        ent_entry = ent_reg.async_get(entity_id)
        if ent_entry and ent_entry.platform == DOMAIN and ent_entry.unique_id:
            unique_id = ent_entry.unique_id
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.runtime_data is None:
                    continue
                if isinstance(entry.runtime_data, dict):
                    for sub_id, client in entry.runtime_data.items():
                        if unique_id == f"{entry.entry_id}_{sub_id}":
                            return client
                elif unique_id == entry.entry_id:
                    return entry.runtime_data

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is None:
            continue
        if isinstance(entry.runtime_data, dict):
            for _sub_id, c in entry.runtime_data.items():
                return c
        else:
            return entry.runtime_data
    return None


def _panel_digest(panel_dir: Path) -> str:
    """Short digest of every panel file, so a redeploy changes the module URL.

    Blocking I/O, so it runs in an executor. Any failure degrades to a constant
    rather than taking the panel registration down with it — a stale cache is a
    far smaller problem than no panel at all.
    """
    import hashlib

    digest = hashlib.sha256()
    try:
        for path in sorted(panel_dir.rglob("*")):
            if path.is_file():
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
    except OSError:
        return "0"
    return digest.hexdigest()[:12]


def _tools_yaml_path(hass: HomeAssistant) -> Path:
    """Resolve the absolute path to tools.yaml under the HA config directory."""
    return Path(hass.config.config_dir) / TOOLS_YAML_PATH


def _memory_persist_dir(hass: HomeAssistant) -> Path:
    """Absolute path of the persist dir file-based backends write into."""
    return Path(hass.config.config_dir) / ".storage" / MEMORY_PERSIST_DIRNAME


async def _reload_registry(hass: HomeAssistant, *, only_if_changed: bool = False) -> int | None:
    """Serialise `_rebuild_subsystems`. Every caller goes through here.

    The rebuild is not re-entrant and there are several ways to start two at
    once — the loudest being that `async_add_subentry` fires `update_listener`
    as a background task while a websocket handler awaits its own rebuild after
    the same write. `_rebuild_lock` carries the full account of what interleaves
    and what it costs.

    Deliberately a wrapper around a private body rather than a lock taken
    inside it: the teardown in `async_unload_entry` needs the same lock, and
    keeping the acquisition at the boundary makes it impossible for a rebuild
    to acquire it twice and deadlock against itself.

    `only_if_changed` is for the callers that react to a *subentry* write: the
    update listener and every websocket handler that writes one. Those two
    respond to the same write, so without a gate they rebuilt twice — bouncing
    every MCP server, reopening every backend and spending a second embedding
    dimension probe, one fresh OAuth exchange under a 30 s timeout, for nothing.
    They pass it and get a rebuild only if some subsystem subentry actually
    differs from what the last rebuild recorded.

    The check is inside the lock, not at the call sites. Outside it, both paths
    could read the stale fingerprint before either recorded the new one and both
    would rebuild — which is exactly what happened on a two-entry install, where
    the listener won the race and the websocket handler, which never checked at
    all, rebuilt on top of it.

    Callers that change tools.yaml — `tools/save`, `tools/rollback`,
    `smartchain.reload_tools` — must not pass it. The fingerprint covers
    subentries only; the file is invisible to it.

    Returns the number of custom tools now in the registry, or None when the
    gate skipped the rebuild.
    """
    async with _rebuild_lock(hass):
        if only_if_changed and _subsystem_fingerprint(hass) == hass.data.get(DOMAIN, {}).get(
            "subentry_fingerprint"
        ):
            return None
        return await _rebuild_subsystems(hass)


async def _rebuild_subsystems(hass: HomeAssistant) -> int:
    """Re-read tools.yaml into the registry. Raises LoaderError on failure.

    Callers use `_reload_registry`, which holds `_rebuild_lock` for the whole
    of this; nothing here may be run concurrently with itself.

    Both tools and memory stores now have two sources: tools.yaml and config
    subentries. Each pair is merged by its own `merge_*_sources`, which is also
    where a name defined in both is resolved — in favour of the subentry, the
    editable one — and logged.

    **A tools.yaml failure is isolated to tools.yaml.** The load used to raise
    straight out of this function, before either merge ran, so a mis-indented
    line in the file took down every tool and every memory store configured
    through the panel: config that never went near the file died with it. The
    failure is now caught here, the rebuild continues, and the error is
    re-raised at the *end*, once everything the subentries define is live.

    What the rebuild continues *with* is the last `LoaderResult` the file
    produced, not an empty one. A broken file is a file that no longer says
    anything, not a file that says "nothing" — dropping to empty would let a
    typo silently delete the YAML tools, stores and MCP servers that were
    working a second ago, which is the failure this whole change is about.
    Before the first successful load there is nothing to fall back on, so a
    file broken at startup contributes nothing and only the subentries load.

    How the failure surfaces, so that "keep the old config" never becomes
    "pretend it worked": every existing channel still reports it, because the
    re-raise happens before returning — `_handle_reload_tools` raises
    `HomeAssistantError`, every websocket save path returns `reload_error`,
    startup logs it. Added on top, because a toast is tied to whichever action
    happened to trigger the rebuild and may never be seen:
    `hass.data[DOMAIN]["yaml_error"]` holds a `_safe_loader_error` summary,
    which `smartchain/tool/list` serves and the Tools tab shows as a standing
    banner until the file loads again.
    """
    path = _tools_yaml_path(hass)
    # The config dir is what lets HA's YAML loader resolve `!secret` against
    # secrets.yaml — without it the whole file fails on the first such tag.
    yaml_error: LoaderError | None = None
    try:
        result = await hass.async_add_executor_job(
            load_tools_file, path, Path(hass.config.config_dir)
        )
    except LoaderError as err:
        # The full text is safe *here* and nowhere else: a schema failure wraps
        # a `vol.Invalid` whose message interpolates the offending value, and
        # `!secret` is resolved before validation runs, so this log line can
        # hold a credential. It is server-side, admin-only. What travels to a
        # user surface is `_safe_loader_error`'s output.
        LOGGER.error("SmartChain tools.yaml could not be loaded: %s", err)
        yaml_error = err
        result = hass.data[DOMAIN].get("yaml_result") or LoaderResult()
    else:
        hass.data[DOMAIN]["yaml_result"] = result

    from .websocket_api import _safe_loader_error

    hass.data[DOMAIN]["yaml_error"] = None if yaml_error is None else _safe_loader_error(yaml_error)

    registry: ToolRegistry = hass.data[DOMAIN]["tools"]
    merged_tools, tool_sources, tools_shadowed = merge_tool_sources(
        result.yaml_tools, tools_from_subentries(hass), subentry_tool_names(hass)
    )

    # Stop MCP *before* the registry is replaced, not after. `manager.stop()`
    # deregisters by name from whatever the registry holds at that moment, so
    # running it second made it delete freshly merged tools that happened to
    # share a name with a tool the previous MCP session had registered — a tool
    # subentry called `fs_read` vanished on the next rebuild. Stopping first
    # means it only ever removes its own tools from its own generation of the
    # registry; `replace_all` then installs the merged set untouched.
    manager: MCPManager | None = hass.data[DOMAIN].get("mcp_manager")
    if manager is not None:
        await manager.stop()

    registry.replace_all(merged_tools)
    hass.data[DOMAIN]["tool_sources"] = tool_sources
    hass.data[DOMAIN]["tools_shadowed"] = tools_shadowed

    if manager is not None:
        manager.configure(result.mcp_servers)
        await manager.start()

    # --- Memory subsystem: build first, swap only on success ---
    # Constructed outside the try so the failure path can always close it:
    # build() may have registered and started retention / logbook tasks for the
    # stores it got through before raising, and discarding the object without a
    # shutdown() would leak those timers for the life of the process.
    settings, sources, shadowed = merge_store_sources(
        result.memory_settings.stores, stores_from_subentries(hass)
    )
    hass.data[DOMAIN]["store_shadowed"] = shadowed
    new_memory = MemoryRegistry(hass)
    try:
        await new_memory.build(settings, _memory_persist_dir(hass), sources)
    except Exception:  # noqa: BLE001
        await new_memory.shutdown()
        LOGGER.exception("memory rebuild failed; keeping the previous registry")
    else:
        old_memory: MemoryRegistry | None = hass.data[DOMAIN].get("memory")
        if old_memory is not None:
            await old_memory.shutdown()
        hass.data[DOMAIN]["memory"] = new_memory

    # A reload must not serve an entity skeleton map built before it.
    skeleton: SkeletonCache | None = hass.data[DOMAIN].get("entity_skeleton")
    if skeleton is not None:
        skeleton.invalidate()

    # Record what this pass built from, so `update_listener` can tell a
    # subentry change (rebuild) from an options change (nothing to do). Set
    # here rather than at the call site so that *every* rebuild updates it —
    # including the one `async_setup_entry` runs after a teardown, which is
    # what stops the listener rebuilding a second time straight after.
    # Recorded even when tools.yaml failed to load: the subentries are live
    # regardless, and re-running the rebuild would not fix the file.
    hass.data[DOMAIN]["subentry_fingerprint"] = _subsystem_fingerprint(hass)

    # Everything the subentries define is now live. Only now does the file's
    # failure propagate, so the caller still learns about it through the exact
    # channel it always did.
    if yaml_error is not None:
        raise yaml_error

    # What this counts, precisely: the custom tools in the registry right now —
    # tools.yaml plus tool subentries, after the collision merge. MCP tools are
    # *not* included: they arrive asynchronously after `manager.start()`, so at
    # this point the number of them is not yet knowable.
    return len(merged_tools)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up SmartChain domain (register services)."""

    async def _handle_ask(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.ask service call."""
        message = call.data["message"]
        entity_id = call.data.get("entity_id")

        client = _find_client(hass, entity_id)
        if not client:
            return {"response": "No SmartChain agent available."}

        try:
            result = await client.ainvoke([HumanMessage(content=message)])
            return {"response": result.content}
        except Exception:
            # Provider exception messages may embed credentials (e.g. OpenAI's
            # AuthenticationError includes the offending key fragment). Don't
            # surface them to service callers — full detail is in the log.
            LOGGER.exception("SmartChain ask service error")
            return {"response": _GENERIC_LLM_ERROR}

    async def _handle_analyze_image(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.analyze_image service call."""
        message = call.data["message"]
        camera_entity_id = call.data["camera_entity_id"]
        entity_id = call.data.get("entity_id")

        try:
            image = await async_get_image(hass, camera_entity_id, timeout=10)
        except Exception:
            LOGGER.exception("Failed to get image from %s", camera_entity_id)
            return {"response": _GENERIC_CAMERA_ERROR}

        encoded = base64.b64encode(image.content).decode("utf-8")
        mime_type = image.content_type or "image/jpeg"
        data_url = f"data:{mime_type};base64,{encoded}"

        client = _find_client(hass, entity_id)
        if not client:
            return {"response": "No SmartChain agent available."}

        multimodal_content = [
            {"type": "text", "text": message},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        try:
            result = await client.ainvoke([HumanMessage(content=multimodal_content)])
            response_text = result.content
        except Exception:
            LOGGER.exception("SmartChain analyze_image error")
            return {"response": _GENERIC_LLM_ERROR}

        now = dt_util.utcnow().isoformat()
        event_data = {
            "response": response_text,
            "camera_entity_id": camera_entity_id,
            "message": message,
            "timestamp": now,
        }

        hass.bus.async_fire(EVENT_IMAGE_ANALYZED, event_data)
        async_dispatcher_send(hass, SIGNAL_NEW_ANALYSIS, event_data)

        notify_entity = call.data.get("notify_entity")
        if notify_entity:
            try:
                await hass.services.async_call(
                    "notify",
                    "send_message",
                    {
                        "entity_id": notify_entity,
                        "message": response_text,
                        "title": f"SmartChain: {camera_entity_id}",
                    },
                )
            except Exception as err:
                LOGGER.warning("Failed to send notification to %s: %s", notify_entity, err)

        return {"response": response_text}

    # Initialise tools registry from /config/smartchain/tools.yaml (optional).
    hass.data.setdefault(DOMAIN, {})
    if "tools" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["tools"] = ToolRegistry()
    if "mcp_manager" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["mcp_manager"] = MCPManager(hass, hass.data[DOMAIN]["tools"])
    if "memory" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["memory"] = MemoryRegistry(hass)
    if "entity_skeleton" not in hass.data[DOMAIN]:
        cache = SkeletonCache(hass)
        cache.start()
        hass.data[DOMAIN]["entity_skeleton"] = cache
    try:
        initial = await _reload_registry(hass)
        LOGGER.info("SmartChain loaded %d custom tools", initial)
    except LoaderError as err:
        LOGGER.error("SmartChain tools.yaml load failed at startup: %s", err)

    async def _handle_reload_tools(call: ServiceCall) -> None:
        try:
            count = await _reload_registry(hass)
        except LoaderError as err:
            # Never `str(err)`. A LoaderError raised from a schema failure wraps
            # a `vol.Invalid` whose message interpolates the offending value,
            # and HA resolves `!secret` before validation runs — so calling this
            # action from Developer Tools on a tools.yaml the schema rejects
            # used to print the resolved secret in the UI toast and into the
            # automation trace. `_safe_loader_error` is the same guard the
            # websocket path already applies; the full message is logged
            # server-side, where only an admin can read it.
            from .websocket_api import _safe_loader_error

            LOGGER.warning("SmartChain tools reload failed: %s", err)
            raise HomeAssistantError(_safe_loader_error(err)) from err
        hass.bus.async_fire(EVENT_TOOLS_RELOADED, {"count": count})

    async def _handle_clear_memory(call: ServiceCall) -> None:
        registry: MemoryRegistry | None = hass.data.get(DOMAIN, {}).get("memory")
        if registry is None or not len(registry):
            raise HomeAssistantError("smartchain memory is not configured")

        requested = call.data.get("store")
        if requested is not None and requested not in registry.names():
            raise HomeAssistantError(
                f"unknown memory store {requested!r}; configured: {registry.names()}"
            )
        targets = [requested] if requested else registry.names()

        kind = call.data.get("kind", "any")
        agent_id = call.data.get("agent_id")
        where: dict[str, Any] = {}
        if kind != "any":
            where["kind"] = kind
        if agent_id:
            where["agent_id"] = agent_id

        deleted = 0
        for name in targets:
            store = registry.get(name)
            if store is not None:
                deleted += await store.clear(where or None)
            # An entity-index store cleared directly through `store.clear` is
            # now out of step with its index and nothing will rebuild it until
            # the next registry event or restart happens to trigger a sweep —
            # from the user's side that reads as "search_entities finds
            # nothing, permanently". Schedule a reconciling sweep for any
            # cleared store that has an indexer, as a background task so
            # clearing never blocks on re-embedding the whole home.
            indexer = registry.indexer_for(name)
            if indexer is not None:
                hass.async_create_background_task(
                    indexer.reconcile(), name="smartchain_entity_index_reclear_sweep"
                )

        hass.bus.async_fire(EVENT_MEMORY_CLEARED, {"deleted": deleted, "stores": targets})

    async def _handle_reindex_entities(call: ServiceCall) -> None:
        registry: MemoryRegistry | None = hass.data.get(DOMAIN, {}).get("memory")
        names = registry.entity_store_names() if registry is not None else []
        if not names:
            raise HomeAssistantError("no entity index is configured")

        requested = call.data.get("store")
        if requested is not None and requested not in names:
            raise HomeAssistantError(f"unknown entity index {requested!r}; configured: {names}")
        targets = [requested] if requested else names
        full = bool(call.data.get("full", False))

        totals = {"new": 0, "changed": 0, "removed": 0, "unchanged": 0}
        for name in targets:
            indexer = registry.indexer_for(name)
            if indexer is None:
                continue
            result = await indexer.reconcile(full=full)
            for key in totals:
                totals[key] += getattr(result, key)

        hass.bus.async_fire(EVENT_ENTITIES_REINDEXED, {"stores": targets, **totals})

    # Register sidebar panel (graceful — skip if frontend not available).
    # Failures here aren't fatal but they do mean the user has no UI — bump from
    # DEBUG to WARNING so the cause is actually visible in logs.
    try:
        panel_dir = Path(__file__).parent / "panel"
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            # A distinct prefix from `frontend_url_path` below. Registering both
            # at "/smartchain" made a page refresh return 403: the browser asks
            # the server for /smartchain, the static handler answers first and is
            # asked to serve a directory. Client-side navigation hid it, so it
            # only showed up on reload.
            [StaticPathConfig(PANEL_STATIC_PATH, str(panel_dir), False)]
        )
        import json

        manifest_path = Path(__file__).parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        panel_version = manifest.get("version", "0")
        # The release version alone is not enough to bust a browser cache: the
        # panel is edited and redeployed many times within one unreleased
        # version, and a stale shell paired with fresh component modules fails
        # in ways that look like data problems rather than caching. Fold a
        # digest of the panel's own bytes into the query so any redeploy that
        # changes a file changes the URL.
        panel_build = await hass.async_add_executor_job(_panel_digest, panel_dir)
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="SmartChain AI",
            sidebar_icon="mdi:robot",
            frontend_url_path="smartchain",
            config={
                "_panel_custom": {
                    "name": "smartchain-panel",
                    "module_url": (
                        f"{PANEL_STATIC_PATH}/smartchain-panel.js?v={panel_version}.{panel_build}"
                    ),
                },
                "version": panel_version,
            },
        )
    except Exception as err:
        LOGGER.warning("Could not register SmartChain panel: %s", err)

    from . import websocket_api as smartchain_websocket_api

    smartchain_websocket_api.async_register(hass)

    hass.data[DOMAIN]["find_client"] = _find_client

    hass.services.async_register(
        DOMAIN,
        SERVICE_ASK,
        _handle_ask,
        schema=SERVICE_ASK_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ANALYZE_IMAGE,
        _handle_analyze_image,
        schema=SERVICE_ANALYZE_IMAGE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    if not hass.services.has_service(DOMAIN, SERVICE_RELOAD_TOOLS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RELOAD_TOOLS,
            _handle_reload_tools,
            schema=vol.Schema({}),
        )
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_MEMORY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_MEMORY,
            _handle_clear_memory,
            schema=vol.Schema(
                {
                    vol.Optional("kind", default="any"): vol.In(["any", "conversation", "logbook"]),
                    vol.Optional("agent_id"): str,
                    vol.Optional("store"): str,
                }
            ),
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REINDEX_ENTITIES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REINDEX_ENTITIES,
            _handle_reindex_entities,
            schema=vol.Schema(
                {vol.Optional("store"): str, vol.Optional("full", default=False): bool}
            ),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize SmartChain."""
    # Deferred for the same reason as in `update_listener`: `websocket_api`
    # imports from this module.
    from .websocket_api import async_invalidate_stale_model_cache

    engine = entry.data.get(CONF_ENGINE) or ID_GIGACHAT

    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Record what this setup is building from, so `update_listener` can tell a
    # write that changed the entry — reload — from one that only moved a tool,
    # a store or an embeddings binding, which needs no reload at all and must
    # not take every `conversation.*` entity offline to get one. Taken at the
    # top rather than at the bottom because everything it digests is already
    # final here, and an early `return False` further down must not leave the
    # listener reloading forever on a fingerprint that was never written.
    _entry_fingerprints(hass)[entry.entry_id] = _entry_fingerprint(entry)

    # Same idea, different question, so it is seeded in the same place: record
    # the connection as it stands now, so the first write to reach
    # `update_listener` is compared against something. Unseeded, "no digest
    # yet" is indistinguishable from "the connection changed", and the first
    # agent save of a session would throw the model cache away for nothing.
    async_invalidate_stale_model_cache(hass, entry)

    # `async_setup` runs once per HA run, so if a previous unload tore the shared
    # subsystems down (last entry removed, or the user hitting "Reload" on their
    # only entry) nothing else would ever bring them back. Rebuild here, gated on
    # the marker rather than on "the registry is empty" — an install with no
    # `memory:` block legitimately has an empty registry, and rebuilding on that
    # would re-read tools.yaml and bounce every MCP server on each entry setup.
    if hass.data.get(DOMAIN, {}).pop("subsystems_stopped", False):
        try:
            await _reload_registry(hass)
        except LoaderError as err:
            LOGGER.error("SmartChain tools.yaml load failed on entry setup: %s", err)
        # `stop()` cleared its registry subscriptions; without this the cache
        # would silently stop invalidating for the rest of the HA run.
        #
        # `invalidate()` here rather than only inside `_reload_registry`: that
        # call sits under the `try` above, so a tools.yaml that fails to load
        # skips it, and `start()` would then resubscribe a cache still holding
        # a map built before the unload — during which window every registry
        # event went unheard. The two belong together.
        skeleton: SkeletonCache | None = hass.data.get(DOMAIN, {}).get("entity_skeleton")
        if skeleton is not None:
            skeleton.invalidate()
            skeleton.start()

    # One client per conversation agent. Filtering by subentry type rather than
    # asking `if entry.subentries:` matters: an entry whose only subentry is an
    # embeddings binding has no agents, and the old truthiness test silently
    # took it down the legacy single-entity path.
    clients: dict[str, object] = {}
    for sub_id, subentry in (entry.subentries or {}).items():
        if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
            continue
        common_args = _resolve_client_args(dict(subentry.data))
        clients[sub_id] = await get_client(hass, engine, entry, common_args)

    if not clients and entry.minor_version < 2:
        # Only reachable when `_migrate_legacy_agent` refused (it is the sole
        # path that leaves an entry below minor version 2). Refusing must
        # degrade nothing, so the legacy single client stays for that entry.
        common_args = _resolve_client_args(dict(entry.options))
        LOGGER.debug(
            "SmartChain setup: engine=%s, resolved_model=%s (legacy, migration refused)",
            engine,
            common_args.get("model"),
        )
        entry.runtime_data = await get_client(hass, engine, entry, common_args)
    else:
        # An entry with no agents is a connection nobody is using yet — a
        # coherent state, not an error, and not an entity.
        entry.runtime_data = clients

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload SmartChain."""
    # Stop MCP connections and memory tasks when the last config entry is unloaded.
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    # `hass.data[DOMAIN]` is read up front rather than through `.get(DOMAIN, {})`
    # three times, so that taking the rebuild lock — which has to `setdefault`
    # the domain dict to store itself — cannot turn "the domain was never set
    # up" into "the domain exists and is marked stopped".
    domain_data: dict[str, Any] | None = hass.data.get(DOMAIN)
    if domain_data is not None:
        # Nothing is built from this entry any more, so the digest of what it
        # was built from answers nothing. The map is keyed by `entry_id`, so
        # without this a user who adds and removes hubs accumulates one dead
        # digest per removal for the rest of the process.
        #
        # It is not guarding against a stale digest suppressing a reload: the
        # listener is registered through `entry.async_on_unload`, so unloading
        # takes the listener with it and no write on an unloaded entry reaches
        # `update_listener` at all. Setup writes a fresh digest on the way back
        # in regardless.
        domain_data.get("entry_fingerprints", {}).pop(entry.entry_id, None)
        # The panel's model cache is deliberately *not* dropped here, though it
        # is keyed by `entry_id` and accumulates the same way. Unload is not
        # removal: an agent save reloads the entry, so clearing the cache on
        # unload would refetch the model list on the next panel open after
        # every single agent edit — defeating the cache for the sake of one
        # dead list per hub a user removes. `async_invalidate_stale_model_cache`
        # already drops the lists that are *wrong*, which is the half that
        # matters.
    if not remaining and domain_data is not None:
        # Under the rebuild lock: this stops the very MCP manager, memory
        # registry and skeleton cache a `_reload_registry` in flight is
        # starting, and the two interleaved would leave the subsystems half
        # torn down and half rebuilt. See `_rebuild_lock`.
        async with _rebuild_lock(hass):
            manager: MCPManager | None = domain_data.get("mcp_manager")
            if manager is not None:
                await manager.stop()
            memory: MemoryRegistry | None = domain_data.get("memory")
            if memory is not None:
                await memory.shutdown()
            skeleton: SkeletonCache | None = domain_data.get("entity_skeleton")
            if skeleton is not None:
                await skeleton.stop()
        # Mark the teardown so the next `async_setup_entry` rebuilds all three —
        # a reload of the only config entry must not leave memory, MCP and the
        # entity skeleton cache dead for the rest of the HA run.
        domain_data["subsystems_stopped"] = True
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
