"""Startup timing and registry-driven refreshes."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.smartchain.const import ENTITY_REGISTRY_DEBOUNCE_SECONDS
from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer
from custom_components.smartchain.tools.memory.store import MemoryStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _indexer(hass: HomeAssistant, **cfg) -> tuple[EntityIndexer, AsyncMock]:
    store = MagicMock(spec=MemoryStore)
    store.is_available = True
    indexer = EntityIndexer(hass, store, EntitySourceConfig(**cfg))
    sweep = AsyncMock(return_value=None)
    indexer.reconcile = sweep
    return indexer, sweep


async def test_start_defers_the_sweep_until_hass_is_up(hass: HomeAssistant) -> None:
    """A thousand embeddings must not delay HA's startup."""
    indexer, sweep = _indexer(hass)

    hass.set_state(CoreState.not_running)
    try:
        indexer.start()
        assert sweep.await_count == 0

        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED, {})
        await hass.async_block_till_done()
    finally:
        hass.set_state(CoreState.running)

    assert sweep.await_count == 1
    await indexer.stop()


async def test_running_hass_sweeps_in_the_background(hass: HomeAssistant) -> None:
    """On reload_tools HA is already up, so waiting for the event would hang."""
    indexer, sweep = _indexer(hass)

    indexer.start()
    await hass.async_block_till_done()

    assert sweep.await_count == 1
    await indexer.stop()


async def test_entity_removal_deletes_immediately(hass: HomeAssistant) -> None:
    indexer, _ = _indexer(hass)
    indexer.store.clear = AsyncMock(return_value=1)
    indexer.start()
    await hass.async_block_till_done()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        {"action": "remove", "entity_id": "light.gone"},
    )
    await hass.async_block_till_done()

    indexer.store.clear.assert_awaited_with({"kind": "entity", "entity_id": "light.gone"})
    await indexer.stop()


async def test_entity_removal_also_schedules_a_reconciling_sweep(hass: HomeAssistant) -> None:
    """The immediate clear can be overtaken by a sweep already in flight.

    If that sweep's `_write` lands after the clear, the document comes back —
    and without a debounced sweep behind it, nothing would ever remove it
    again. It stays invisible in results but wastes storage indefinitely.
    """
    indexer, sweep = _indexer(hass)
    indexer.store.clear = AsyncMock(return_value=1)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        {"action": "remove", "entity_id": "light.gone"},
    )
    await hass.async_block_till_done()

    assert indexer._unsub_debounce is not None
    await indexer._flush_debounce()

    assert sweep.await_count == 1
    await indexer.stop()


async def test_registry_changes_are_debounced_into_one_sweep(hass: HomeAssistant) -> None:
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    for name in ("a", "b", "c"):
        hass.bus.async_fire(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            {"action": "update", "entity_id": f"light.{name}"},
        )
    await hass.async_block_till_done()
    await indexer._flush_debounce()

    assert sweep.await_count == 1
    await indexer.stop()


async def test_debounced_sweep_fires_on_its_own_after_the_window_elapses(
    hass: HomeAssistant,
) -> None:
    """The real timer, not just the `_flush_debounce` test seam, must fire the sweep."""
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
    )
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=ENTITY_REGISTRY_DEBOUNCE_SECONDS + 1)
    )
    await hass.async_block_till_done()

    assert sweep.await_count == 1
    await indexer.stop()


@pytest.mark.parametrize(
    "event",
    [dr.EVENT_DEVICE_REGISTRY_UPDATED, ar.EVENT_AREA_REGISTRY_UPDATED],
)
async def test_device_and_area_changes_schedule_a_sweep(hass: HomeAssistant, event: str) -> None:
    """Renaming an area touches every entity in it, so the sweep is the cheap
    way to catch it — fingerprints keep it incremental."""
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    hass.bus.async_fire(event, {"action": "update", "device_id": "d1"})
    await hass.async_block_till_done()
    await indexer._flush_debounce()

    assert sweep.await_count == 1
    await indexer.stop()


async def test_stop_cancels_pending_work(hass: HomeAssistant) -> None:
    """A debounce timer that outlives `stop()` would sweep against a closed store.

    Real time must actually elapse past the debounce window for this to prove
    anything — `ENTITY_REGISTRY_DEBOUNCE_SECONDS` never passes on its own during
    a test, so without `async_fire_time_changed` this assertion would hold
    whether or not `stop()` cancels the timer at all.
    """
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
    )
    await indexer.stop()

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=ENTITY_REGISTRY_DEBOUNCE_SECONDS + 1)
    )
    await hass.async_block_till_done()

    assert sweep.await_count == 0


async def test_stop_cancels_a_sweep_in_flight(hass: HomeAssistant) -> None:
    """A shutdown must not wait on a sweep that could take minutes."""
    indexer, _ = _indexer(hass)
    blocker = asyncio.Event()

    async def _blocking_sweep(*, full: bool = False):
        await blocker.wait()

    indexer.reconcile = _blocking_sweep
    indexer.start()
    await hass.async_block_till_done()

    task = indexer._task
    assert task is not None
    assert not task.done()

    await indexer.stop()

    assert task.cancelled()
    assert indexer._task is None


async def test_stop_cancels_an_in_flight_removal(hass: HomeAssistant) -> None:
    """A removal still running when `stop()` is called must not outlive it."""
    indexer, _ = _indexer(hass)
    blocker = asyncio.Event()

    async def _blocking_clear(_where):
        await blocker.wait()
        return 1

    indexer.store.clear = AsyncMock(side_effect=_blocking_clear)
    indexer.start()
    await hass.async_block_till_done()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        {"action": "remove", "entity_id": "light.gone"},
    )

    assert len(indexer._removal_tasks) == 1
    task = next(iter(indexer._removal_tasks))
    assert not task.done()

    await indexer.stop()

    assert task.cancelled()
    assert indexer._removal_tasks == set()


async def test_stop_is_idempotent(hass: HomeAssistant) -> None:
    """A second `stop()` must not raise — and must not tear down twice.

    HA unsub callables are not safe to call again, so "idempotent" has to mean
    the second call does no work, not merely that it survived.
    """
    indexer, _ = _indexer(hass)
    indexer.start()
    teardowns: list[int] = []
    indexer._unsubs.append(lambda: teardowns.append(1))

    await indexer.stop()
    await indexer.stop()

    assert teardowns == [1]
    assert indexer._unsubs == []
    assert indexer._unsub_debounce is None
    assert indexer._unsub_states is None
    assert indexer._task is None
    assert indexer._removal_tasks == set()
