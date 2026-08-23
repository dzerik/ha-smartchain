"""Keeps an entity store in step with the home, embedding only what changed."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ...const import (
    ENTITY_INDEX_BATCH_PAUSE_SECONDS,
    ENTITY_INDEX_BATCH_SIZE,
    ENTITY_REGISTRY_DEBOUNCE_SECONDS,
    ENTITY_STATE_FLUSH_SECONDS,
)
from .config import EntitySourceConfig
from .entity_doc import build_metadata, doc_id_for, render_catalogue
from .entity_filter import EntityCandidate, resolve_candidates
from .store import MemoryStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepResult:
    new: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0


class EntityIndexer:
    """One entity-source store's view of the home.

    Failures are logged and swallowed: a broken sweep leaves the previous
    index in place rather than emptying it.
    """

    def __init__(self, hass: HomeAssistant, store: MemoryStore, config: EntitySourceConfig) -> None:
        self.hass = hass
        self.store = store
        self.config = config
        self._lock = asyncio.Lock()
        self._unsubs: list = []
        self._task: asyncio.Task | None = None
        self._unsub_debounce = None
        self._removal_tasks: set[asyncio.Task] = set()
        self._pending_states: dict[str, str] = {}
        self._indexed_metadata: dict[str, dict[str, str]] = {}

    def _state_of(self, entity_id: str) -> str | None:
        if not self.config.index_states:
            return None
        state = self.hass.states.get(entity_id)
        return state.state if state else "unavailable"

    async def reconcile(self, *, full: bool = False) -> SweepResult:
        """Bring the store in line with the home. Never raises."""
        if not self.store.is_available:
            return SweepResult()

        async with self._lock:
            try:
                return await self._reconcile(full)
            except Exception:  # noqa: BLE001 — a sweep must never break setup
                LOGGER.exception("entity index sweep failed")
                return SweepResult()

    async def _reconcile(self, full: bool = False) -> SweepResult:
        candidates = resolve_candidates(self.hass, self.config)
        stored = await self.store.list_metadata({"kind": "entity"})

        pending: list[tuple[EntityCandidate, str, dict[str, str]]] = []
        new = changed = unchanged = 0

        for entity_id, cand in candidates.items():
            text = render_catalogue(cand)
            metadata = build_metadata(cand, text, state=self._state_of(entity_id))
            existing = stored.get(doc_id_for(entity_id))
            if existing is None:
                new += 1
            elif full or existing.get("fingerprint") != metadata["fingerprint"]:
                changed += 1
            else:
                unchanged += 1
                continue
            pending.append((cand, text, metadata))

        await self._write(pending)

        orphans: list[str] = []
        seen: set[str] = set()
        for meta in stored.values():
            entity_id = meta.get("entity_id", "")
            if entity_id and entity_id not in candidates and entity_id not in seen:
                seen.add(entity_id)
                orphans.append(entity_id)
        removed = await self._remove(orphans)

        LOGGER.info(
            "entity index: %d new, %d changed, %d removed, %d unchanged",
            new,
            changed,
            removed,
            unchanged,
        )
        return SweepResult(new=new, changed=changed, removed=removed, unchanged=unchanged)

    async def _write(self, pending: list[tuple[EntityCandidate, str, dict[str, str]]]) -> None:
        """Embed and store in batches, yielding between them.

        A first sweep over a large home is hundreds of embedding calls; it must
        not monopolise the executor while HA is still coming up.
        """
        for index in range(0, len(pending), ENTITY_INDEX_BATCH_SIZE):
            batch = pending[index : index + ENTITY_INDEX_BATCH_SIZE]
            for cand, text, metadata in batch:
                await self.store.add(text, metadata, doc_id=doc_id_for(cand.entity_id))
                self._indexed_metadata[doc_id_for(cand.entity_id)] = metadata
            if index + ENTITY_INDEX_BATCH_SIZE < len(pending):
                await asyncio.sleep(ENTITY_INDEX_BATCH_PAUSE_SECONDS)

    async def _remove(self, orphans: list[str]) -> int:
        """Delete orphans in batches, yielding between them like `_write`.

        A preset narrowed from `maximal` to `minimal` can orphan hundreds of
        entities at once; that must not fire as one uninterrupted run of
        backend round-trips while HA is still coming up.

        Counts only what `MemoryStore.clear` reports as actually deleted —
        it swallows backend failures and returns 0, so `removed` must never
        claim more than that.
        """
        removed = 0
        for index in range(0, len(orphans), ENTITY_INDEX_BATCH_SIZE):
            batch = orphans[index : index + ENTITY_INDEX_BATCH_SIZE]
            for entity_id in batch:
                removed += await self.store.clear({"kind": "entity", "entity_id": entity_id})
                self._indexed_metadata.pop(doc_id_for(entity_id), None)
                self._pending_states.pop(entity_id, None)
            if index + ENTITY_INDEX_BATCH_SIZE < len(orphans):
                await asyncio.sleep(ENTITY_INDEX_BATCH_PAUSE_SECONDS)
        return removed

    def start(self) -> None:
        """Subscribe and schedule the first sweep. Never sweeps inline."""
        if self._unsubs:
            return

        self._unsubs.append(
            self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_entity_registry)
        )
        for event in (dr.EVENT_DEVICE_REGISTRY_UPDATED, ar.EVENT_AREA_REGISTRY_UPDATED):
            self._unsubs.append(self.hass.bus.async_listen(event, self._on_broad_change))

        if self.hass.state is CoreState.running:
            self._schedule_sweep()
        else:
            self._unsubs.append(
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_hass_started)
            )

        if self.config.index_states:
            tracked = list(resolve_candidates(self.hass, self.config))
            if tracked:
                self._unsubs.append(
                    async_track_state_change_event(self.hass, tracked, self._on_state)
                )
            self._unsubs.append(
                async_track_time_interval(
                    self.hass,
                    self._on_flush_interval,
                    timedelta(seconds=ENTITY_STATE_FLUSH_SECONDS),
                )
            )

    async def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_debounce()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        pending_removals = list(self._removal_tasks)
        for task in pending_removals:
            task.cancel()
        for task in pending_removals:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._removal_tasks.clear()

    @callback
    def _on_hass_started(self, _event: Event) -> None:
        self._schedule_sweep()

    @callback
    def _schedule_sweep(self, *, full: bool = False) -> None:
        self._task = self.hass.async_create_background_task(
            self.reconcile(full=full), name="smartchain_entity_index"
        )

    @callback
    def _on_entity_registry(self, event: Event) -> None:
        data = event.data
        if data.get("action") == "remove":
            entity_id = data.get("entity_id")
            if entity_id:
                self._indexed_metadata.pop(doc_id_for(entity_id), None)
                self._pending_states.pop(entity_id, None)
                task = self.hass.async_create_background_task(
                    self.store.clear({"kind": "entity", "entity_id": entity_id}),
                    name="smartchain_entity_index_remove",
                )
                self._removal_tasks.add(task)
                task.add_done_callback(self._removal_tasks.discard)
            return
        self._debounce()

    @callback
    def _on_broad_change(self, _event: Event) -> None:
        self._debounce()

    @callback
    def _debounce(self) -> None:
        self._cancel_debounce()
        self._unsub_debounce = async_call_later(
            self.hass,
            ENTITY_REGISTRY_DEBOUNCE_SECONDS,
            self._on_debounce_elapsed,
        )

    @callback
    def _on_debounce_elapsed(self, _now: datetime) -> None:
        self._schedule_sweep()

    @callback
    def _cancel_debounce(self) -> None:
        if self._unsub_debounce is not None:
            self._unsub_debounce()
            self._unsub_debounce = None

    async def _flush_debounce(self) -> None:
        """Run a pending debounced sweep now. Test seam — production waits."""
        if self._unsub_debounce is None:
            return
        self._cancel_debounce()
        await self.reconcile()

    @callback
    def _on_state(self, event: Event) -> None:
        """Coalesce by entity_id — a flapping sensor must not cost a write per event."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            self._pending_states[new_state.entity_id] = new_state.state

    @callback
    def _on_flush_interval(self, _now: datetime) -> None:
        self.hass.async_create_background_task(
            self._flush_states(), name="smartchain_entity_state_flush"
        )

    async def _flush_states(self) -> None:
        """Write coalesced states as metadata. Issues no embedding call at all.

        An entity is only known to have a document once this indexer has swept
        it: `list_metadata` is the source of truth, but a store double used in
        tests (or a backend with eventual consistency) may not yet reflect a
        write this same process just made, so the sweep's own record of what
        it wrote (`_indexed_metadata`) is consulted as a fallback rather than
        writing blind.
        """
        if not self._pending_states or not self.store.is_available:
            return
        batch, self._pending_states = self._pending_states, {}

        stored = await self.store.list_metadata({"kind": "entity"})
        now = dt_util.utcnow().isoformat()
        for entity_id, state in batch.items():
            doc_id = doc_id_for(entity_id)
            metadata = stored.get(doc_id) or self._indexed_metadata.get(doc_id)
            if metadata is None:
                continue
            try:
                await self.store.update_metadata(
                    doc_id, {**metadata, "state": state, "state_updated": now}
                )
            except Exception:  # noqa: BLE001 — one entity must not stop the flush
                LOGGER.exception("entity state flush failed for %s", entity_id)
