"""MemoryRegistry — owns every configured store and its background tasks."""

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from ...const import DOMAIN, SUBENTRY_TYPE_EMBEDDINGS
from .backends import BackendInitError, create_backend
from .config import MemorySettings, StoreConfig
from .embeddings import EmbeddingsConfigError, create_embeddings_from_subentry
from .ingest import MemoryLogbookPoller
from .retention import RetentionTask
from .store import MemoryStore

LOGGER = logging.getLogger(__name__)


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

    # ----- construction -----

    def _embeddings_subentries(self) -> dict[str, tuple[ConfigEntry, ConfigSubentry] | None]:
        """Collect embeddings subentries by title across all SmartChain entries.

        A title claimed by more than one subentry maps to None, so the caller
        can refuse to bind rather than pick an arbitrary one.
        """
        found: dict[str, tuple[ConfigEntry, ConfigSubentry] | None] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for subentry in (entry.subentries or {}).values():
                if subentry.subentry_type != SUBENTRY_TYPE_EMBEDDINGS:
                    continue
                if subentry.title in found:
                    found[subentry.title] = None
                else:
                    found[subentry.title] = (entry, subentry)
        return found

    async def build(self, settings: MemorySettings, storage_dir: Path) -> None:
        """Construct every configured store. Never raises."""
        available = self._embeddings_subentries()

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
                continue
            if binding is None:
                LOGGER.error(
                    "Memory store %r references embeddings subentry %r, but that "
                    "title is duplicated across config entries. Rename one of them.",
                    config.name,
                    config.embeddings,
                )
                continue

            entry, subentry = binding
            try:
                embeddings = create_embeddings_from_subentry(self.hass, entry, subentry)
            except EmbeddingsConfigError as err:
                LOGGER.error("Memory store %r disabled: %s", config.name, err)
                continue

            try:
                backend = create_backend(self.hass, config.backend, config.name, storage_dir)
            except BackendInitError as err:
                LOGGER.error("Memory store %r disabled: %s", config.name, err)
                continue

            store = MemoryStore(self.hass, embeddings, backend)
            await store.async_setup()
            if not store.is_available:
                LOGGER.error(
                    "Memory store %r did not come up; see earlier log lines.",
                    config.name,
                )
                continue

            self.stores[config.name] = store
            self._configs[config.name] = config

            retention = RetentionTask(self.hass, store, config.retention_days)
            retention.start()
            self._retention[config.name] = retention

            poller = MemoryLogbookPoller(self.hass, store, config.logbook)
            poller.start()
            self._pollers[config.name] = poller

            LOGGER.info("Memory store %r ready on backend %s", config.name, backend.name)

    async def shutdown(self) -> None:
        """Stop every task, then close every backend."""
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

    def stores_for_conversation_ingest(self) -> list[MemoryStore]:
        return [
            store for name, store in self.stores.items() if self._configs[name].ingest_conversation
        ]

    def config_for(self, name: str) -> StoreConfig | None:
        return self._configs.get(name)

    def __len__(self) -> int:
        return len(self.stores)
