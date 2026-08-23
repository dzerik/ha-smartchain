"""Lexical and vector matching, merged; the tool must survive a dead store."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN, ENTITY_TOOL_NAME
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_tool import (
    execute_entity_search,
    get_entity_tool_definition,
)
from custom_components.smartchain.tools.memory.store import MemorySnippet

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str, area: str = "Кухня", aliases=()) -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=tuple(aliases),
    )


def _registry(hass, candidates, *, hits=None, store_available=True):
    store = MagicMock()
    store.is_available = store_available
    store.search = AsyncMock(return_value=hits or [])

    indexer = MagicMock()
    indexer.config = MagicMock(index_states=False)

    reg = MagicMock()
    reg.entity_store_names.return_value = ["entities"]
    reg.indexer_for.side_effect = lambda n: indexer if n == "entities" else None
    reg.get.side_effect = lambda n: store if n in ("entities", None) else None
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    patcher = patch(
        "custom_components.smartchain.tools.memory.entity_tool.resolve_candidates",
        return_value={c.entity_id: c for c in candidates},
    )
    patcher.start()
    return reg, store, patcher


def test_definition_names_the_tool_and_requires_a_query() -> None:
    reg = MagicMock()
    reg.entity_store_names.return_value = ["entities"]
    spec = get_entity_tool_definition(reg)
    assert spec["name"] == ENTITY_TOOL_NAME
    assert spec["parameters"]["required"] == ["query"]
    assert "store" not in spec["parameters"].get("required", [])


def test_definition_requires_store_with_two_entity_stores() -> None:
    reg = MagicMock()
    reg.entity_store_names.return_value = ["a", "b"]
    spec = get_entity_tool_definition(reg)
    assert spec["parameters"]["properties"]["store"]["enum"] == ["a", "b"]
    assert "store" in spec["parameters"]["required"]


async def test_lexical_match_finds_by_name(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолочный свет")])

    result = await execute_entity_search(hass, query="потолочный")

    assert "light.ceiling" in result
    patcher.stop()


async def test_lexical_match_finds_by_alias(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолок", aliases=("люстра",))])

    assert "light.ceiling" in await execute_entity_search(hass, query="люстра")
    patcher.stop()


async def test_exact_lexical_outranks_a_better_vector_hit(hass: HomeAssistant) -> None:
    """The whole reason lexical stays in the loop."""
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "off", {})
    hit = MemorySnippet(
        text="switch.socket — Кофеварка",
        score=0.99,
        metadata={"kind": "entity", "entity_id": "switch.socket"},
    )
    _, _, patcher = _registry(
        hass,
        [_cand("light.ceiling", "Кофеварка"), _cand("switch.socket", "Розетка")],
        hits=[hit],
    )

    result = await execute_entity_search(hass, query="Кофеварка")

    assert result.index("light.ceiling") < result.index("switch.socket")
    patcher.stop()


async def test_results_are_deduplicated_by_entity_id(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    hit = MemorySnippet(
        text="…", score=0.9, metadata={"kind": "entity", "entity_id": "light.ceiling"}
    )
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолок")], hits=[hit])

    result = await execute_entity_search(hass, query="потолок")

    assert result.count("light.ceiling") == 1
    patcher.stop()


async def test_state_comes_from_hass_not_from_stale_metadata(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "off", {})
    hit = MemorySnippet(
        text="…",
        score=0.9,
        metadata={"kind": "entity", "entity_id": "light.ceiling", "state": "on"},
    )
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолок")], hits=[hit])

    result = await execute_entity_search(hass, query="потолок")

    assert "= off" in result
    patcher.stop()


async def test_it_still_works_with_the_store_unavailable(hass: HomeAssistant) -> None:
    """No indexer ever ran; resolve_candidates is what saves the fallback."""
    hass.states.async_set("light.ceiling", "on", {})
    _, store, patcher = _registry(hass, [_cand("light.ceiling", "Потолок")], store_available=False)

    result = await execute_entity_search(hass, query="потолок")

    assert "light.ceiling" in result
    assert store.search.await_count == 0
    patcher.stop()


async def test_domain_and_area_filter_the_result(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "on", {})
    _, _, patcher = _registry(
        hass,
        [_cand("light.ceiling", "Свет"), _cand("switch.socket", "Свет", area="Спальня")],
    )

    result = await execute_entity_search(hass, query="свет", domain="light")
    assert "switch.socket" not in result

    result = await execute_entity_search(hass, query="свет", area="Спальня")
    assert "light.ceiling" not in result
    patcher.stop()


async def test_state_filter_works_without_index_states(hass: HomeAssistant) -> None:
    """Applied after enrichment rather than as a metadata filter — not an error."""
    hass.states.async_set("cover.a", "open", {})
    hass.states.async_set("cover.b", "closed", {})
    _, _, patcher = _registry(hass, [_cand("cover.a", "Штора A"), _cand("cover.b", "Штора B")])

    result = await execute_entity_search(hass, query="штора", state="open")

    assert "cover.a" in result
    assert "cover.b" not in result
    patcher.stop()


async def test_no_match_names_the_filters(hass: HomeAssistant) -> None:
    _, _, patcher = _registry(hass, [])
    result = await execute_entity_search(hass, query="ничего", domain="light")
    assert "light" in result
    patcher.stop()


async def test_unknown_store_is_reported_back(hass: HomeAssistant) -> None:
    _, _, patcher = _registry(hass, [])
    result = await execute_entity_search(hass, query="x", store="ghost")
    assert "ghost" in result
    assert "entities" in result
    patcher.stop()


async def test_no_entity_store_configured(hass: HomeAssistant) -> None:
    reg = MagicMock()
    reg.entity_store_names.return_value = []
    hass.data.setdefault(DOMAIN, {})["memory"] = reg
    result = await execute_entity_search(hass, query="x")
    assert "not configured" in result.lower()


async def test_failures_return_a_fixed_string(hass: HomeAssistant) -> None:
    _, store, patcher = _registry(hass, [_cand("light.a", "A")])
    store.search = AsyncMock(side_effect=RuntimeError("boom"))

    result = await execute_entity_search(hass, query="a")

    assert "boom" not in result
    patcher.stop()
