"""Startup timing and registry-driven refreshes."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

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
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
    )
    await indexer.stop()
    await hass.async_block_till_done()

    assert sweep.await_count == 0


async def test_stop_is_idempotent(hass: HomeAssistant) -> None:
    indexer, _ = _indexer(hass)
    indexer.start()
    await indexer.stop()
    await indexer.stop()
