"""One cached map per preset, invalidated by the registries."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.smartchain.tools.memory.entity_context import SkeletonCache
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str) -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name="Имя",
        area="Кухня",
        device="",
        device_class="",
        aliases=(),
    )


def _patched(entity_ids: list[str]):
    return patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        return_value={e: _cand(e) for e in entity_ids},
    )


async def test_a_second_get_does_not_recompute(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        first = cache.get("optimal")
        second = cache.get("optimal")
    assert first == second
    assert resolve.call_count == 1
    await cache.stop()


async def test_different_presets_are_cached_separately(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        cache.get("minimal")
    assert resolve.call_count == 2
    await cache.stop()


@pytest.mark.parametrize(
    "event",
    [
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        dr.EVENT_DEVICE_REGISTRY_UPDATED,
        ar.EVENT_AREA_REGISTRY_UPDATED,
    ],
)
async def test_a_registry_event_invalidates(hass: HomeAssistant, event: str) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        hass.bus.async_fire(event, {"action": "update", "entity_id": "light.a"})
        await hass.async_block_till_done()
        cache.get("optimal")
    assert resolve.call_count == 2
    await cache.stop()


async def test_stop_unsubscribes(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        await cache.stop()
        hass.bus.async_fire(
            er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
        )
        await hass.async_block_till_done()
        cache.get("optimal")
    assert resolve.call_count == 1


async def test_start_is_idempotent(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        hass.bus.async_fire(
            er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
        )
        await hass.async_block_till_done()
        cache.get("optimal")
    # One invalidation, not two — a doubled subscription would still give 2
    # here, so also assert the subscription count directly.
    assert resolve.call_count == 2
    assert len(cache._unsubs) == 3
    await cache.stop()


async def test_a_resolve_failure_returns_none_not_an_empty_map(hass: HomeAssistant, caplog) -> None:
    """None means "could not build" so the caller can fall back to the dump.

    An empty string would be indistinguishable from a genuinely empty home,
    and the spec's failure layering turns on exactly that distinction.
    """
    cache = SkeletonCache(hass)
    cache.start()
    with patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        side_effect=RuntimeError("boom"),
    ):
        assert cache.get("optimal") is None
    await cache.stop()


async def test_a_genuinely_empty_home_returns_an_empty_string(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        return_value={},
    ):
        assert cache.get("optimal") == ""
    await cache.stop()


async def test_a_failure_is_not_cached(hass: HomeAssistant) -> None:
    """A transient registry error must not blind the agent for five minutes."""
    cache = SkeletonCache(hass)
    cache.start()
    with patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        side_effect=RuntimeError("boom"),
    ):
        cache.get("optimal")
    with _patched(["light.a"]) as resolve:
        assert cache.get("optimal") != ""
    assert resolve.call_count == 1
    await cache.stop()
