"""Lexical and vector matching, merged; the tool must survive a dead store."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN, ENTITY_TOOL_NAME
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer
from custom_components.smartchain.tools.memory.entity_tool import (
    execute_entity_search,
    get_entity_tool_definition,
)
from custom_components.smartchain.tools.memory.registry import MemoryRegistry
from custom_components.smartchain.tools.memory.store import MemorySnippet, MemoryStore

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


def _registry(hass, candidates, *, hits=None, store_available=True, store_names=("entities",)):
    store = MagicMock(spec=MemoryStore)
    store.is_available = store_available
    store.search = AsyncMock(return_value=hits or [])

    indexer = MagicMock(spec=EntityIndexer)
    indexer.config = MagicMock(index_states=False)

    reg = MagicMock(spec=MemoryRegistry)
    reg.entity_store_names.return_value = list(store_names)
    reg.indexer_for.side_effect = lambda n: indexer if n in store_names else None
    reg.get.side_effect = lambda n: store if n in store_names else None
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    patcher = patch(
        "custom_components.smartchain.tools.memory.entity_tool.resolve_candidates",
        return_value={c.entity_id: c for c in candidates},
    )
    patcher.start()
    return reg, store, patcher


def test_definition_names_the_tool_and_requires_a_query() -> None:
    reg = MagicMock(spec=MemoryRegistry)
    reg.entity_store_names.return_value = ["entities"]
    spec = get_entity_tool_definition(reg)
    assert spec["name"] == ENTITY_TOOL_NAME
    assert spec["parameters"]["required"] == ["query"]
    assert "store" not in spec["parameters"].get("required", [])


def test_definition_requires_store_with_two_entity_stores() -> None:
    reg = MagicMock(spec=MemoryRegistry)
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


async def test_exact_lexical_match_merges_with_a_lower_scored_vector_hit(
    hass: HomeAssistant,
) -> None:
    """Exact-tier candidates still surface correctly once a vector hit is
    merged into the ranking.

    This does NOT pin the tier-over-score ordering: the exact tier is
    hardcoded to score 1.0, the ceiling for any cosine score, and this
    fixture's vector hit is 0.99 — strictly lower. A naive score-only sort
    with the tier dropped from the key produces the identical order, so this
    test passes either way. See
    test_prefix_lexical_outranks_a_higher_scored_vector_hit for the test that
    actually exercises the tier.
    """
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


async def test_prefix_lexical_outranks_a_higher_scored_vector_hit(hass: HomeAssistant) -> None:
    """The whole reason lexical stays in the loop.

    The exact tier's hardcoded 1.0 can never lose to a cosine score, so it
    proves nothing about the tier itself. The prefix tier (hardcoded 0.5) is
    where the ordering has bite: a prefix lexical match must still beat a
    vector hit that scores higher on cosine similarity alone. A naive
    score-only sort gets this one wrong.
    """
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "off", {})
    hit = MemorySnippet(
        text="switch.socket — Кофеварка",
        score=0.9,
        metadata={"kind": "entity", "entity_id": "switch.socket"},
    )
    _, _, patcher = _registry(
        hass,
        [_cand("light.ceiling", "Кофеварка на кухне"), _cand("switch.socket", "Розетка")],
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


async def test_area_filter_is_case_insensitive(hass: HomeAssistant) -> None:
    """A model writes the area as the user said it, not as the registry spells it.

    Every other comparison in this module goes through `_fold`; the filters
    were the exception and compared bytes, so `area="кухня"` against an area
    named "Кухня" threw away every match.
    """
    hass.states.async_set("light.ceiling", "on", {})
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Свет", area="Кухня")])

    result = await execute_entity_search(hass, query="свет", area="кухня")

    patcher.stop()
    assert "light.ceiling" in result


async def test_area_filter_still_excludes_a_different_area(hass: HomeAssistant) -> None:
    """Folding must not turn the filter into a no-op."""
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "on", {})
    _, _, patcher = _registry(
        hass,
        [
            _cand("light.ceiling", "Свет", area="Кухня"),
            _cand("switch.socket", "Свет", area="Спальня"),
        ],
    )

    result = await execute_entity_search(hass, query="свет", area="кухня")

    patcher.stop()
    assert "light.ceiling" in result
    assert "switch.socket" not in result


async def test_area_reaches_the_store_as_the_registry_spells_it(hass: HomeAssistant) -> None:
    """The store-side filter is the other half of the same bug.

    `area` goes into the vector query's `where`, and the indexed metadata
    carries the registry's spelling. Passing the model's casing there drops
    every vector hit before the folded post-filter ever sees it, so the
    semantic arm goes silently dead for exactly the queries this tool exists
    to answer.
    """
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "off", {})
    hit = MemorySnippet(
        text="…",
        score=0.9,
        metadata={"kind": "entity", "entity_id": "switch.socket", "area": "Кухня"},
    )
    _, store, patcher = _registry(
        hass,
        [_cand("light.ceiling", "Потолок", area="Кухня"), _cand("switch.socket", "Розетка")],
    )

    async def _search(_query, *, top_k, where):
        """A backend that really applies the metadata filter it is handed."""
        return [hit] if all(hit.metadata.get(k) == v for k, v in where.items()) else []

    store.search = AsyncMock(side_effect=_search)

    result = await execute_entity_search(hass, query="кофеварка", area="кухня")

    patcher.stop()
    assert store.search.await_args.kwargs["where"]["area"] == "Кухня"
    assert "switch.socket" in result


async def test_state_filter_is_case_insensitive(hass: HomeAssistant) -> None:
    hass.states.async_set("cover.a", "open", {})
    hass.states.async_set("cover.b", "closed", {})
    _, _, patcher = _registry(hass, [_cand("cover.a", "Штора A"), _cand("cover.b", "Штора B")])

    result = await execute_entity_search(hass, query="штора", state="OPEN")

    patcher.stop()
    assert "cover.a" in result
    assert "cover.b" not in result


async def test_domain_filter_is_case_insensitive(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "on", {})
    _, store, patcher = _registry(
        hass,
        [_cand("light.ceiling", "Свет"), _cand("switch.socket", "Свет", area="Спальня")],
    )

    result = await execute_entity_search(hass, query="свет", domain="Light")

    patcher.stop()
    assert "light.ceiling" in result
    assert "switch.socket" not in result
    # …and the store-side filter gets the canonical spelling, not "Light".
    assert store.search.await_args.kwargs["where"]["domain"] == "light"


async def test_state_filter_works_without_index_states(hass: HomeAssistant) -> None:
    """Applied after enrichment rather than as a metadata filter — not an error."""
    hass.states.async_set("cover.a", "open", {})
    hass.states.async_set("cover.b", "closed", {})
    _, _, patcher = _registry(hass, [_cand("cover.a", "Штора A"), _cand("cover.b", "Штора B")])

    result = await execute_entity_search(hass, query="штора", state="open")

    assert "cover.a" in result
    assert "cover.b" not in result
    patcher.stop()


async def test_state_filter_never_prunes_on_stale_stored_state(hass: HomeAssistant) -> None:
    """With `index_states: true` the stored state can be half a minute old.

    Filtering vector hits against it inside the store would discard exactly
    the semantic-only matches this tool exists to find — a cover that opened
    since the last flush would be invisible to `state="open"`, while the live
    post-filter that runs afterwards would have kept it. So `state` must never
    reach the store-side `where`.
    """
    hass.states.async_set("cover.a", "open", {})
    hit = MemorySnippet(
        text="…",
        score=0.9,
        metadata={"kind": "entity", "entity_id": "cover.a", "state": "closed"},
    )
    _, store, patcher = _registry(hass, [_cand("cover.a", "Штора")])

    async def _search(_query, *, top_k, where):
        """A backend that really applies the metadata filter it is handed."""
        return [hit] if all(hit.metadata.get(k) == v for k, v in where.items()) else []

    store.search = AsyncMock(side_effect=_search)
    # The store this time really does index states.
    reg_indexer = MagicMock(spec=EntityIndexer)
    reg_indexer.config = MagicMock(index_states=True)
    hass.data[DOMAIN]["memory"].indexer_for.side_effect = lambda n: reg_indexer

    result = await execute_entity_search(hass, query="жалюзи в спальне", state="open")

    assert "state" not in store.search.await_args.kwargs["where"]
    assert "cover.a" in result
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


async def test_ambiguous_store_is_reported_without_a_store_arg(hass: HomeAssistant) -> None:
    """Several entity stores, no `store` argument: the tool must not guess."""
    _, _, patcher = _registry(hass, [], store_names=("a", "b"))

    result = await execute_entity_search(hass, query="x")

    assert "pass `store`" in result
    assert "Available: a, b" in result
    patcher.stop()


async def test_a_valid_store_name_bypasses_the_ambiguous_branch(hass: HomeAssistant) -> None:
    """Passing `store` explicitly against a multi-store registry must resolve
    directly rather than falling into the ambiguous branch."""
    hass.states.async_set("light.ceiling", "on", {})
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолок")], store_names=("a", "b"))

    result = await execute_entity_search(hass, query="потолок", store="a")

    assert "light.ceiling" in result
    assert "pass `store`" not in result
    patcher.stop()


async def test_no_entity_store_configured(hass: HomeAssistant) -> None:
    reg = MagicMock(spec=MemoryRegistry)
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
