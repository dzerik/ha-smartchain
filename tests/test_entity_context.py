"""Skeleton plus what this turn is about, and what happens when either fails."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.memory.entity_context import (
    _RETRIEVED_HEADING,
    SkeletonCache,
    build_entity_context,
)
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.registry import MemoryRegistry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str, area: str = "Кухня") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _install_cache(hass: HomeAssistant, skeleton: str | None) -> MagicMock:
    cache = MagicMock(spec=SkeletonCache)
    cache.get.return_value = skeleton
    hass.data.setdefault(DOMAIN, {})["entity_skeleton"] = cache
    return cache


def _patch_ranking(ranked: list[EntityCandidate]):
    return patch(
        "custom_components.smartchain.tools.memory.entity_context.rank_entities",
        new=AsyncMock(return_value=ranked),
    )


def _patch_candidates(cands: list[EntityCandidate]):
    return patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        return_value={c.entity_id: c for c in cands},
    )


async def test_both_blocks_appear(hass: HomeAssistant) -> None:
    hass.states.async_set("light.a", "on", {})
    _install_cache(hass, "Кухня — light: Потолочный")
    cand = _cand("light.a", "Потолочный")

    with _patch_candidates([cand]), _patch_ranking([cand]):
        text = await build_entity_context(hass, preset="optimal", query="потолок")

    assert "Кухня — light: Потолочный" in text
    assert "light.a" in text
    assert "= on" in text


async def test_state_is_read_live_not_from_the_index(hass: HomeAssistant) -> None:
    hass.states.async_set("light.a", "off", {})
    _install_cache(hass, "Кухня — light: Потолочный")
    cand = _cand("light.a", "Потолочный")

    with _patch_candidates([cand]), _patch_ranking([cand]):
        text = await build_entity_context(hass, preset="optimal", query="потолок")

    assert "= off" in text


async def test_an_entity_with_no_state_reads_unavailable(hass: HomeAssistant) -> None:
    _install_cache(hass, "Кухня — light: Потолочный")
    cand = _cand("light.gone", "Пропавший")

    with _patch_candidates([cand]), _patch_ranking([cand]):
        text = await build_entity_context(hass, preset="optimal", query="пропавший")

    assert "unavailable" in text


async def test_no_matches_renders_no_heading(hass: HomeAssistant) -> None:
    _install_cache(hass, "Кухня — light: Потолочный")

    with _patch_candidates([]), _patch_ranking([]):
        text = await build_entity_context(hass, preset="optimal", query="ничего")

    assert "Кухня — light: Потолочный" in text
    # The brief's original assertion here was
    #   assert ":" not in text.split("\n")[-1] or "light." not in text
    # which is an `or` of two negatives that holds in almost every state,
    # including the ones this test exists to reject (e.g. it is satisfied
    # even when the retrieved heading IS present, as long as some other
    # line happens to be last). Replaced with a direct check that the
    # retrieved block's heading is absent from the output.
    assert _RETRIEVED_HEADING not in text


async def test_the_retrieval_is_capped(hass: HomeAssistant) -> None:
    from custom_components.smartchain.const import ENTITY_CONTEXT_MAX_ENTITIES

    _install_cache(hass, "skeleton")
    cands = [_cand(f"light.a{i}", f"Свет {i}") for i in range(40)]
    for c in cands:
        hass.states.async_set(c.entity_id, "on", {})

    captured = {}

    async def _fake_rank(hass_, registry, candidates, query, top_k, **kw):
        captured["top_k"] = top_k
        return cands[:top_k]

    with (
        _patch_candidates(cands),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=_fake_rank,
        ),
    ):
        await build_entity_context(hass, preset="optimal", query="свет")

    assert captured["top_k"] == ENTITY_CONTEXT_MAX_ENTITIES


async def test_a_failing_retrieval_leaves_the_skeleton(hass: HomeAssistant, caplog) -> None:
    """Layer one of the failure ladder."""
    _install_cache(hass, "Кухня — light: Потолочный")

    with (
        _patch_candidates([_cand("light.a", "Потолочный")]),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        text = await build_entity_context(hass, preset="optimal", query="потолок")

    assert text == "Кухня — light: Потолочный"
    assert "boom" not in text


async def test_a_failing_skeleton_returns_none(hass: HomeAssistant) -> None:
    """Layer two: the caller falls back to the full dump."""
    _install_cache(hass, None)

    with _patch_candidates([]), _patch_ranking([]):
        assert await build_entity_context(hass, preset="optimal", query="x") is None


async def test_a_missing_cache_returns_none(hass: HomeAssistant) -> None:
    """Nothing installed in hass.data must not raise into a conversation."""
    hass.data.setdefault(DOMAIN, {}).pop("entity_skeleton", None)
    assert await build_entity_context(hass, preset="optimal", query="x") is None


async def test_an_empty_home_is_not_a_failure(hass: HomeAssistant) -> None:
    _install_cache(hass, "")

    with _patch_candidates([]), _patch_ranking([]):
        assert await build_entity_context(hass, preset="optimal", query="x") == ""


async def test_a_russian_sentence_retrieves_the_entity_it_names(
    hass: HomeAssistant,
) -> None:
    """No store, no mocked ranking — the configuration the docs promote.

    Every other retrieval test here either mocks `rank_entities` or hands it
    a single word. Both hide the case that actually happens: the query this
    caller passes is the user's raw utterance, and matching it whole finds
    nothing, because no entity is called "включи свет на кухне".
    """
    hass.data.setdefault(DOMAIN, {}).pop("memory", None)
    _install_cache(hass, "Кухня — light: Свет")
    lamp = _cand("light.kitchen", "Свет")
    fridge = _cand("sensor.fridge", "Температура холодильника")
    hass.states.async_set("light.kitchen", "on", {})
    hass.states.async_set("sensor.fridge", "4", {})

    with _patch_candidates([lamp, fridge]):
        text = await build_entity_context(hass, preset="optimal", query="включи свет на кухне")

    assert _RETRIEVED_HEADING in text
    assert "light.kitchen" in text
    assert "sensor.fridge" not in text


async def test_an_english_sentence_retrieves_the_entity_it_names(
    hass: HomeAssistant,
) -> None:
    hass.data.setdefault(DOMAIN, {}).pop("memory", None)
    _install_cache(hass, "Kitchen — light: Kitchen Light")
    lamp = EntityCandidate(
        entity_id="light.kitchen",
        domain="light",
        name="Kitchen Light",
        area="Kitchen",
        device="",
        device_class="",
        aliases=(),
    )
    humidity = EntityCandidate(
        entity_id="sensor.humidity",
        domain="sensor",
        name="Humidity",
        area="Bedroom",
        device="",
        device_class="",
        aliases=(),
    )
    hass.states.async_set("light.kitchen", "on", {})
    hass.states.async_set("sensor.humidity", "51", {})

    with _patch_candidates([lamp, humidity]):
        text = await build_entity_context(hass, preset="optimal", query="is the kitchen light on")

    assert "light.kitchen" in text
    assert "sensor.humidity" not in text


async def test_the_vector_pass_is_used_only_with_exactly_one_entity_store(
    hass: HomeAssistant,
) -> None:
    """With several there is no non-arbitrary choice and nobody to ask."""
    _install_cache(hass, "skeleton")
    cand = _cand("light.a", "Потолочный")
    hass.states.async_set("light.a", "on", {})

    registry = MagicMock(spec=MemoryRegistry)
    registry.entity_store_names.return_value = ["a", "b"]
    hass.data[DOMAIN]["memory"] = registry

    captured = {}

    async def _fake_rank(hass_, reg, candidates, query, top_k, store_name=None, **kw):
        captured["store_name"] = store_name
        return [cand]

    with (
        _patch_candidates([cand]),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=_fake_rank,
        ),
    ):
        await build_entity_context(hass, preset="optimal", query="потолок")

    assert captured["store_name"] is None

    registry.entity_store_names.return_value = ["only"]
    with (
        _patch_candidates([cand]),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=_fake_rank,
        ),
    ):
        await build_entity_context(hass, preset="optimal", query="потолок")

    assert captured["store_name"] == "only"
