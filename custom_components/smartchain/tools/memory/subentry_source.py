"""Memory stores that live in config subentries rather than in tools.yaml.

A store used to be configurable only by editing the `memory:` block of
`/config/smartchain/tools.yaml`. That file is served to the browser by
`smartchain/tools/get`, so a pgvector `dsn` or a qdrant `api_key` written there
is a credential sitting in a text box. A subentry keeps both in `.storage`,
where a form can accept a key without ever echoing it back.

The two sources produce the *same* dataclass: `store_config_from_subentry`
builds a `StoreConfig` field for field with `loader._memory_from_validated`, so
nothing downstream can tell where a store came from. `merge_store_sources` is
the one place that decides what happens when they both name the same store.
"""

import logging
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant

from ...const import (
    DOMAIN,
    ENTITY_DEFAULT_PRESET,
    ENTITY_SOURCE_TYPE,
    MEMORY_DEFAULT_BACKEND,
    MEMORY_DEFAULT_RETENTION_DAYS,
    SUBENTRY_TYPE_MEMORY_STORE,
)
from .config import BackendConfig, EntitySourceConfig, MemorySettings, StoreConfig

LOGGER = logging.getLogger(__name__)

# Where a merged store came from. Reported by `smartchain/store/status` so the
# Stores tab can say which ones it is able to edit.
SOURCE_SUBENTRY = "subentry"
SOURCE_YAML = "yaml"


def store_config_from_subentry(subentry: ConfigSubentry) -> StoreConfig:
    """Build a `StoreConfig` from one `memory_store` subentry.

    The subentry title is the store name — the same convention embeddings
    subentries use, and the one `MemoryRegistry.stores_bound_to` already
    depends on. Everything else is flat in `data`, because the form that
    writes it is flat.

    An entity-source store gets `retention_days` / `ingest_conversation` /
    `logbook` left at their defaults and never reads them: retention would
    delete the index by age, and either ingest would write non-entity
    documents into it. That mutual exclusion is enforced where the data is
    written (the subentry schema declares neither set at the same time); this
    function simply does not consult them.
    """
    data: dict[str, Any] = dict(subentry.data)
    source_type = data.get("source_type") or ""

    source = None
    if source_type == ENTITY_SOURCE_TYPE:
        source = EntitySourceConfig(
            type=ENTITY_SOURCE_TYPE,
            preset=data.get("preset") or ENTITY_DEFAULT_PRESET,
            index_states=bool(data.get("index_states", False)),
            include=list(data.get("include") or []),
            exclude=list(data.get("exclude") or []),
        )

    return StoreConfig(
        name=subentry.title,
        embeddings=data.get("embeddings") or "",
        description=data.get("description") or "",
        backend=BackendConfig(
            type=data.get("backend_type") or MEMORY_DEFAULT_BACKEND,
            path=data.get("path") or None,
            dsn=data.get("dsn") or None,
            table=data.get("table") or None,
            url=data.get("url") or None,
            api_key=data.get("api_key") or None,
            collection=data.get("collection") or None,
            verify_ssl=bool(data.get("verify_ssl", True)),
        ),
        retention_days=(
            MEMORY_DEFAULT_RETENTION_DAYS
            if source is not None
            else int(data.get("retention_days", MEMORY_DEFAULT_RETENTION_DAYS))
        ),
        # Left at the dataclass default for an entity store, which is exactly
        # what the YAML path produces for one — the schema rejects the key
        # there, so the default is all it ever carries. Two sources, one
        # dataclass; a different value here would make them compare unequal
        # while behaving identically, which is the worst of both.
        ingest_conversation=(
            True if source is not None else bool(data.get("ingest_conversation", True))
        ),
        source=source,
    )


def store_subentries(hass: HomeAssistant) -> list[tuple[Any, ConfigSubentry]]:
    """Every `memory_store` subentry across every SmartChain entry."""
    return [
        (entry, subentry)
        for entry in hass.config_entries.async_entries(DOMAIN)
        for subentry in (entry.subentries or {}).values()
        if subentry.subentry_type == SUBENTRY_TYPE_MEMORY_STORE
    ]


def stores_from_subentries(hass: HomeAssistant) -> list[StoreConfig]:
    """Every store configured as a subentry, first claimant wins on a name clash.

    Two subentries can hold the same title — nothing in Home Assistant stops
    it, and the panel shows every entry at once, so it is reachable. The
    registry keys stores by name, so the second would silently replace the
    first. Dropping it with an error instead means the user is told, and the
    store that was already working keeps working. `ws_store_save` refuses the
    clash up front; this is the backstop for one written any other way.
    """
    out: list[StoreConfig] = []
    seen: set[str] = set()
    for _entry, subentry in store_subentries(hass):
        if subentry.title in seen:
            LOGGER.error(
                "Two SmartChain memory-store subentries are both named %r. Only the first "
                "is used; rename one of them",
                subentry.title,
            )
            continue
        seen.add(subentry.title)
        out.append(store_config_from_subentry(subentry))
    return out


def merge_store_sources(
    yaml_stores: list[StoreConfig], subentry_stores: list[StoreConfig]
) -> tuple[MemorySettings, dict[str, str], list[str]]:
    """Combine the two sources of stores. The subentry wins a name collision.

    Returns `(settings, sources, shadowed)`:

    - `settings` — what `MemoryRegistry.build` consumes.
    - `sources` — store name to `SOURCE_YAML` / `SOURCE_SUBENTRY`, so the panel
      can say which stores it is able to edit and which live in the file.
    - `shadowed` — YAML store names a subentry took over. Reported, never
      silent: a user whose YAML store stopped taking effect otherwise has no
      way to find out except by noticing that edits to it do nothing.

    The subentry wins because it is the editable one. Losing to a file the
    panel cannot safely rewrite would make the UI a read-only display of
    something it appears to control.
    """
    subentry_names = {store.name for store in subentry_stores}
    shadowed = [store.name for store in yaml_stores if store.name in subentry_names]
    if shadowed:
        LOGGER.warning(
            "Memory store(s) %s are defined both in tools.yaml and as a config subentry. "
            "The subentry wins; the tools.yaml definition is ignored. Delete it from "
            "tools.yaml to silence this",
            ", ".join(sorted(shadowed)),
        )

    kept_yaml = [store for store in yaml_stores if store.name not in subentry_names]
    sources = {store.name: SOURCE_YAML for store in kept_yaml}
    sources.update({store.name: SOURCE_SUBENTRY for store in subentry_stores})
    return MemorySettings(stores=[*kept_yaml, *subentry_stores]), sources, shadowed
