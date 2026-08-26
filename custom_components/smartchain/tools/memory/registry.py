"""MemoryRegistry — owns every configured store and its background tasks."""

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from ...const import DOMAIN, SUBENTRY_TYPE_EMBEDDINGS
from .backends import BackendInitError, create_backend
from .config import MemorySettings, StoreConfig
from .embeddings import EmbeddingsConfigError, create_embeddings_from_subentry
from .entity_index import EntityIndexer
from .ingest import MemoryLogbookPoller
from .retention import RetentionTask
from .store import MemoryStore

LOGGER = logging.getLogger(__name__)


def embeddings_subentries_by_title(
    hass: HomeAssistant,
) -> dict[str, tuple[ConfigEntry, ConfigSubentry] | None]:
    """Collect embeddings subentries by title across all SmartChain entries.

    A title claimed by more than one subentry maps to None, so the caller can
    refuse to bind rather than pick an arbitrary one.

    Module-level rather than a method because the store form needs the same
    answer before a MemoryRegistry exists — and because a second copy of this
    walk is a second place for the "duplicated title unbinds silently" rule to
    stop applying.
    """
    found: dict[str, tuple[ConfigEntry, ConfigSubentry] | None] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        for subentry in (entry.subentries or {}).values():
            if subentry.subentry_type != SUBENTRY_TYPE_EMBEDDINGS:
                continue
            if subentry.title in found:
                found[subentry.title] = None
            else:
                found[subentry.title] = (entry, subentry)
    return found


class MemoryRegistry:
    """Maps store names to live MemoryStore instances.

    A failure in one store is contained: it is logged, that store is skipped,
    and every other store still builds.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.stores: dict[str, MemoryStore] = {}
        self._configs: dict[str, StoreConfig] = {}
        self._retention: dict[str, RetentionTask] = {}
        self._pollers: dict[str, MemoryLogbookPoller] = {}
        self.indexers: dict[str, EntityIndexer] = {}
        # Store name -> why it is not live. Every `continue` in build() records
        # one. Without this nothing downstream could tell a *configured* store
        # from a *live* one, so `tools/save` reported success over a memory
        # subsystem that never came up and the only trace was a log line.
        #
        # Message text only, never an exception's repr: the catch-all handlers
        # below log the type alone because a pydantic ValidationError renders
        # `input_value`, which on these paths is the provider credential.
        self.failures: dict[str, str] = {}
        # Store name -> "yaml" | "subentry", supplied by the caller that merged
        # the two sources. Purely descriptive; the panel uses it to say which
        # stores it can edit.
        self.sources: dict[str, str] = {}

    # ----- construction -----

    def _embeddings_subentries(self) -> dict[str, tuple[ConfigEntry, ConfigSubentry] | None]:
        """Embeddings subentries by title — see `embeddings_subentries_by_title`."""
        return embeddings_subentries_by_title(self.hass)

    def stores_bound_to(self, title: str) -> list[str]:
        """Names of configured memory stores bound to this embeddings title.

        Stores bind by title, so renaming or duplicating a title silently
        unbinds them. The panel asks this before writing, never after.
        """
        return [name for name, config in self._configs.items() if config.embeddings == title]

    def _fail(self, name: str, reason: str) -> None:
        """Record why a store is configured but not live.

        `reason` is written by the caller and is always literal text or an
        already-scrubbed message — never `str(err)` for an unexpected
        exception, for the reason spelled out on `self.failures`.
        """
        self.failures[name] = reason

    async def build(
        self,
        settings: MemorySettings,
        storage_dir: Path,
        sources: dict[str, str] | None = None,
    ) -> None:
        """Construct every configured store. Never raises.

        `sources` is the optional store-name -> "yaml" / "subentry" map from
        whoever merged the two configuration sources; it is carried, not
        interpreted.
        """
        available = self._embeddings_subentries()
        self.failures.clear()
        self.sources = dict(sources or {})

        for config in settings.stores:
            binding = available.get(config.embeddings, "__missing__")

            if binding == "__missing__":
                LOGGER.error(
                    "Memory store %r references embeddings subentry %r, which does "
                    "not exist. Available: %s",
                    config.name,
                    config.embeddings,
                    sorted(available) or "none",
                )
                self._fail(
                    config.name,
                    f"no embeddings binding is named {config.embeddings!r}",
                )
                continue
            if binding is None:
                LOGGER.error(
                    "Memory store %r references embeddings subentry %r, but that "
                    "title is duplicated across config entries. Rename one of them.",
                    config.name,
                    config.embeddings,
                )
                self._fail(
                    config.name,
                    f"the embeddings title {config.embeddings!r} is claimed by more "
                    "than one binding; rename one of them",
                )
                continue

            entry, subentry = binding
            # Two handlers, not one. The expected errors carry messages that
            # earlier tasks scrubbed of credentials, so those are logged in full.
            # But create_embeddings_from_subentry indexes entry.data[CONF_API_KEY]
            # directly and constructs pydantic models, so a malformed entry can
            # raise KeyError / ValidationError instead — and anything escaping
            # here would propagate out of build() into _reload_registry, whose
            # handler discards the whole new registry, letting one bad entry kill
            # every configured store. Hence a catch-all that logs the type only.
            try:
                embeddings = create_embeddings_from_subentry(self.hass, entry, subentry)
            except EmbeddingsConfigError as err:
                LOGGER.error("Memory store %r disabled: %s", config.name, err)
                self._fail(config.name, str(err))
                continue
            except Exception as err:  # noqa: BLE001 — per-store isolation
                # Type only. An unexpected error here can be a pydantic
                # ValidationError, and pydantic renders `input_value` — which on
                # this call path is the provider credential.
                LOGGER.error(
                    "Memory store %r disabled: unexpected %s while building embeddings",
                    config.name,
                    type(err).__name__,
                )
                self._fail(
                    config.name,
                    f"unexpected {type(err).__name__} while building embeddings",
                )
                continue

            try:
                backend = create_backend(self.hass, config.backend, config.name, storage_dir)
            except BackendInitError as err:
                LOGGER.error("Memory store %r disabled: %s", config.name, err)
                self._fail(config.name, str(err))
                continue
            except Exception as err:  # noqa: BLE001 — per-store isolation
                # Type only, for the same reason: BackendConfig carries `dsn`
                # and `api_key`, and an unexpected error may render them.
                LOGGER.error(
                    "Memory store %r disabled: unexpected %s while building the backend",
                    config.name,
                    type(err).__name__,
                )
                self._fail(
                    config.name,
                    f"unexpected {type(err).__name__} while building the backend",
                )
                continue

            store = MemoryStore(self.hass, embeddings, backend)
            try:
                await store.async_setup()
                if not store.is_available:
                    LOGGER.error(
                        "Memory store %r did not come up; see earlier log lines.",
                        config.name,
                    )
                    self._fail(
                        config.name,
                        store.unavailable_reason or "the store did not come up",
                    )
                    continue

                self.stores[config.name] = store
                self._configs[config.name] = config

                if config.source is not None:
                    # An entity index has no conversation turns to retain and no
                    # logbook to poll; retention in particular would delete the
                    # index by age.
                    indexer = EntityIndexer(self.hass, store, config.source)
                    indexer.start()
                    self.indexers[config.name] = indexer
                    LOGGER.info(
                        "Entity index %r ready on backend %s (preset %s, states %s)",
                        config.name,
                        backend.name,
                        config.source.preset,
                        "on" if config.source.index_states else "off",
                    )
                    continue

                retention = RetentionTask(self.hass, store, config.retention_days)
                retention.start()
                self._retention[config.name] = retention

                poller = MemoryLogbookPoller(self.hass, store, config.logbook)
                poller.start()
                self._pollers[config.name] = poller

                LOGGER.info("Memory store %r ready on backend %s", config.name, backend.name)
            except Exception as err:  # noqa: BLE001 — per-store isolation
                # Type only, for the same reason as the embeddings/backend
                # steps above: an unexpected error here can be a pydantic
                # ValidationError, and pydantic renders `input_value`, which on
                # this call path can be the provider credential.
                LOGGER.error(
                    "Memory store %r disabled: unexpected %s while starting it",
                    config.name,
                    type(err).__name__,
                )
                self._fail(config.name, f"unexpected {type(err).__name__} while starting it")
                # This store was registered (and may have come up) before the
                # failure, so both the registration and any partially-started
                # tasks must be unwound — a `KeyError` in describe() or
                # stores_for_conversation_ingest() is not an acceptable outcome
                # of a single store failing to start.
                self.stores.pop(config.name, None)
                self._configs.pop(config.name, None)
                self.indexers.pop(config.name, None)
                self._retention.pop(config.name, None)
                self._pollers.pop(config.name, None)
                try:
                    await store.close()
                except Exception:  # noqa: BLE001
                    LOGGER.exception(
                        "Error closing memory store %r after a failed start", config.name
                    )
                continue

    async def shutdown(self) -> None:
        """Stop every task, then close every backend."""
        for indexer in self.indexers.values():
            await indexer.stop()
        for task in self._retention.values():
            await task.stop()
        for poller in self._pollers.values():
            await poller.stop()
        for store in self.stores.values():
            try:
                await store.close()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Error closing a memory store")

        self.stores.clear()
        self._configs.clear()
        self._retention.clear()
        self._pollers.clear()
        self.indexers.clear()
        self.failures.clear()
        self.sources.clear()

    # ----- lookup -----

    def get(self, name: str | None) -> MemoryStore | None:
        """Look up a store. `None` resolves only when exactly one is configured."""
        if name is None:
            if len(self.stores) == 1:
                return next(iter(self.stores.values()))
            return None
        return self.stores.get(name)

    def names(self) -> list[str]:
        return list(self.stores)

    def describe(self) -> list[tuple[str, str]]:
        """(name, description) pairs, for the search_memory tool schema."""
        return [(name, self._configs[name].description) for name in self.stores]

    def status(self) -> list[dict[str, object]]:
        """Every *configured* store and whether it is live.

        Live stores first, then the ones that failed — `self.stores` holds only
        the former, and a caller that read that alone (as everything did before
        `failures` existed) would report a healthy subsystem while none of it
        came up. `reason` is `None` for a live store and safe text otherwise.
        """
        rows: list[dict[str, object]] = [
            {
                "name": name,
                "ok": True,
                "reason": None,
                "source": self.sources.get(name),
                "entity_index": name in self.indexers,
            }
            for name in self.stores
        ]
        rows.extend(
            {
                "name": name,
                "ok": False,
                "reason": reason,
                "source": self.sources.get(name),
                "entity_index": False,
            }
            for name, reason in self.failures.items()
        )
        return rows

    def stores_for_conversation_ingest(self) -> list[MemoryStore]:
        return [
            store
            for name, store in self.stores.items()
            if self._configs[name].source is None and self._configs[name].ingest_conversation
        ]

    def config_for(self, name: str) -> StoreConfig | None:
        return self._configs.get(name)

    def entity_store_names(self) -> list[str]:
        return list(self.indexers)

    def indexer_for(self, name: str) -> EntityIndexer | None:
        return self.indexers.get(name)

    def __len__(self) -> int:
        return len(self.stores)
