"""State tracking must cost embeddings nothing at all."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.smartchain.const import ENTITY_STATE_FLUSH_SECONDS
from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer
from custom_components.smartchain.tools.memory.store import MemoryStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str) -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name="Name",
        area="",
        device="",
        device_class="",
        aliases=(),
    )


def _make(hass: HomeAssistant, *, index_states: bool):
    store = MagicMock(spec=MemoryStore)
    store.is_available = True
    store.add = AsyncMock(return_value=["id"])
    store.list_metadata = AsyncMock(return_value={})
    store.update_metadata = AsyncMock(return_value=True)
    store.clear = AsyncMock(return_value=0)
    indexer = EntityIndexer(hass, store, EntitySourceConfig(index_states=index_states))
    patcher = patch(
        "custom_components.smartchain.tools.memory.entity_index.resolve_candidates",
        return_value={"light.a": _cand("light.a")},
    )
    patcher.start()
    return indexer, store, patcher


async def test_toggle_off_registers_no_state_listener(hass: HomeAssistant) -> None:
    indexer, _, patcher = _make(hass, index_states=False)
    with patch(
        "custom_components.smartchain.tools.memory.entity_index.async_track_state_change_event"
    ) as track:
        indexer.start()
        await hass.async_block_till_done()
    assert track.call_count == 0
    await indexer.stop()
    patcher.stop()


async def test_toggle_on_tracks_only_the_candidate_set(hass: HomeAssistant) -> None:
    indexer, _, patcher = _make(hass, index_states=True)
    with patch(
        "custom_components.smartchain.tools.memory.entity_index.async_track_state_change_event"
    ) as track:
        indexer.start()
        await hass.async_block_till_done()
    assert track.call_count == 1
    assert list(track.call_args.args[1]) == ["light.a"]
    await indexer.stop()
    patcher.stop()


async def test_flush_coalesces_and_never_embeds(hass: HomeAssistant) -> None:
    """Three events for one entity produce one metadata write and zero adds."""
    indexer, store, patcher = _make(hass, index_states=True)
    indexer.start()
    await hass.async_block_till_done()
    store.add.reset_mock()

    for value in ("on", "off", "on"):
        hass.states.async_set("light.a", value, {})
        await hass.async_block_till_done()

    await indexer._flush_states()

    assert store.update_metadata.await_count == 1
    assert store.update_metadata.await_args.args[0] == "entity:light.a"
    assert store.update_metadata.await_args.args[1]["state"] == "on"
    assert store.add.await_count == 0
    await indexer.stop()
    patcher.stop()


async def test_flush_with_nothing_pending_is_a_noop(hass: HomeAssistant) -> None:
    indexer, store, patcher = _make(hass, index_states=True)
    indexer.start()
    await hass.async_block_till_done()

    await indexer._flush_states()

    assert store.update_metadata.await_count == 0
    await indexer.stop()
    patcher.stop()


async def test_a_failing_flush_does_not_raise(hass: HomeAssistant, caplog) -> None:
    indexer, store, patcher = _make(hass, index_states=True)
    store.update_metadata = AsyncMock(side_effect=RuntimeError("boom"))
    indexer.start()
    await hass.async_block_till_done()
    hass.states.async_set("light.a", "on", {})
    await hass.async_block_till_done()

    await indexer._flush_states()

    await indexer.stop()
    patcher.stop()


async def test_stop_cancels_the_flush_timer(hass: HomeAssistant) -> None:
    """A flush timer that outlives `stop()` would write into a closing store.

    Real time must actually elapse past the flush interval for this to prove
    anything — without `async_fire_time_changed` this assertion would hold
    whether or not `stop()` cancels the timer at all.
    """
    indexer, store, patcher = _make(hass, index_states=True)
    indexer.start()
    await hass.async_block_till_done()

    hass.states.async_set("light.a", "on", {})
    await hass.async_block_till_done()

    await indexer.stop()

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=ENTITY_STATE_FLUSH_SECONDS + 1)
    )
    await hass.async_block_till_done()

    assert store.update_metadata.await_count == 0
    patcher.stop()
