"""Built-in tools clamp `top_k` themselves.

The jsonschema pass in `dispatcher.dispatch` only ever sees YAML tools. A
built-in's schema — `minimum: 1`, `maximum: 20/50` — is advisory text sent to
the model and nothing enforces it, so whatever integer the model wrote lands
in the executor unchanged. A local model that ignores the schema can ask for
`top_k=10000` (the whole store, rendered at 400 characters an entry, parked in
`chat_log` and re-sent to the provider on every later turn) or for a negative
one (which reaches the backend, where it silently yields nothing instead of
failing).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import (
    BUILTIN_SEARCH_MIN_TOP_K,
    DOMAIN,
    ENTITY_SEARCH_MAX_TOP_K,
    MEMORY_SEARCH_MAX_TOP_K,
)
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer
from custom_components.smartchain.tools.memory.entity_tool import execute_entity_search
from custom_components.smartchain.tools.memory.registry import MemoryRegistry
from custom_components.smartchain.tools.memory.search_tool import execute_memory_search
from custom_components.smartchain.tools.memory.store import MemorySnippet, MemoryStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _memory_registry(hass: HomeAssistant, snippets: list[MemorySnippet]) -> MagicMock:
    store = MagicMock(spec=MemoryStore)
    store.is_available = True
    store.search = AsyncMock(return_value=snippets)
    reg = MagicMock()
    reg.names.return_value = ["only"]
    reg.describe.return_value = [("only", "")]
    reg.__len__.return_value = 1
    reg.get.return_value = store
    hass.data.setdefault(DOMAIN, {})["memory"] = reg
    return store


def _entity_cand(entity_id: str) -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name="Свет",
        area="Кухня",
        device="",
        device_class="",
        aliases=(),
    )


def _entity_registry(hass: HomeAssistant, candidates: dict[str, EntityCandidate]):
    store = MagicMock(spec=MemoryStore)
    store.is_available = True
    store.search = AsyncMock(return_value=[])

    indexer = MagicMock(spec=EntityIndexer)
    indexer.config = MagicMock(index_states=False)

    reg = MagicMock(spec=MemoryRegistry)
    reg.entity_store_names.return_value = ["entities"]
    reg.indexer_for.return_value = indexer
    reg.get.return_value = store
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    patcher = patch(
        "custom_components.smartchain.tools.memory.entity_tool.resolve_candidates",
        return_value=candidates,
    )
    patcher.start()
    return store, patcher


async def test_memory_search_clamps_a_huge_top_k(hass: HomeAssistant) -> None:
    """`top_k=10000` must not reach the backend."""
    store = _memory_registry(hass, [])

    await execute_memory_search(hass, query="x", top_k=10_000)

    assert store.search.await_args.kwargs["top_k"] == MEMORY_SEARCH_MAX_TOP_K


async def test_memory_search_clamps_a_negative_top_k(hass: HomeAssistant) -> None:
    """A negative `top_k` reaches numpy's slicing as garbage and returns
    nothing, with `MemoryStore.search` swallowing whatever it raises — a
    silent empty result rather than a search."""
    store = _memory_registry(hass, [])

    await execute_memory_search(hass, query="x", top_k=-5)

    assert store.search.await_args.kwargs["top_k"] == BUILTIN_SEARCH_MIN_TOP_K


async def test_memory_search_renders_at_most_the_capped_number_of_hits(
    hass: HomeAssistant,
) -> None:
    """The store may hand back more than the cap (sqlite_numpy has no SQL
    LIMIT at all); the rendered result still has to stay bounded."""
    snippets = [
        MemorySnippet(text=f"m{i}", score=0.5, metadata={"kind": "conversation", "timestamp": "t"})
        for i in range(100)
    ]
    _memory_registry(hass, snippets)

    result = await execute_memory_search(hass, query="x", top_k=10_000)

    assert len(result.splitlines()) == MEMORY_SEARCH_MAX_TOP_K + 1  # + the header line


async def test_entity_search_clamps_a_huge_top_k(hass: HomeAssistant) -> None:
    cands = {}
    for i in range(ENTITY_SEARCH_MAX_TOP_K + 20):
        entity_id = f"light.l{i}"
        hass.states.async_set(entity_id, "on", {})
        cands[entity_id] = _entity_cand(entity_id)
    _, patcher = _entity_registry(hass, cands)

    result = await execute_entity_search(hass, query="Свет", top_k=10_000)

    patcher.stop()
    assert result.count("light.l") == ENTITY_SEARCH_MAX_TOP_K


async def test_entity_search_clamps_a_negative_top_k(hass: HomeAssistant) -> None:
    """A negative `top_k` becomes a negative `fetch_k`, and `_MAX_STORE_FETCH_K`
    is an upper bound only — `min(-4, 200)` keeps the negative. sqlite's
    `LIMIT -1` means "no limit"; numpy's `[:−4]` means something else again.
    Neither is a search."""
    hass.states.async_set("light.a", "on", {})
    store, patcher = _entity_registry(hass, {"light.a": _entity_cand("light.a")})

    result = await execute_entity_search(hass, query="Свет", top_k=-1)

    patcher.stop()
    assert store.search.await_args.kwargs["top_k"] >= BUILTIN_SEARCH_MIN_TOP_K
    # Clamped to the floor, not to zero: one result still comes back.
    assert "light.a" in result
