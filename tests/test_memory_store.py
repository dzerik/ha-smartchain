"""Tests for MemoryStore over a real sqlite_numpy backend."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import MEMORY_MAX_TEXT_LEN
from custom_components.smartchain.tools.memory.backends.sqlite_numpy import (
    SqliteNumpyBackend,
)
from custom_components.smartchain.tools.memory.store import MemorySnippet, MemoryStore


class _FakeEmbeddings:
    """Deterministic mini-embedder: first 8 character codes, padded."""

    def __init__(self) -> None:
        self.embed_query = AsyncMock(side_effect=self._embed)
        self.embed_documents = AsyncMock(side_effect=lambda texts: [self._embed(t) for t in texts])

    @staticmethod
    def _embed(text: str) -> list[float]:
        vec = [float(ord(c)) for c in text[:8]]
        while len(vec) < 8:
            vec.append(0.0)
        return vec


@pytest.fixture
async def store(hass: HomeAssistant, tmp_path):
    backend = SqliteNumpyBackend(hass, tmp_path / "memory.db")
    st = MemoryStore(hass, _FakeEmbeddings(), backend)
    await st.async_setup()
    yield st
    await st.close()


async def test_add_and_search_returns_snippet(store) -> None:
    await store.add("hello world", {"kind": "conversation", "timestamp": "t1"})
    results = await store.search("hello world", top_k=1)
    assert len(results) == 1
    assert isinstance(results[0], MemorySnippet)
    assert results[0].text == "hello world"
    assert results[0].metadata["kind"] == "conversation"


async def test_search_with_where_filter(store) -> None:
    await store.add("foo", {"kind": "conversation", "timestamp": "t1"})
    await store.add("bar", {"kind": "logbook", "timestamp": "t2"})
    results = await store.search("foo", top_k=5, where={"kind": "logbook"})
    assert all(r.metadata["kind"] == "logbook" for r in results)


async def test_delete_older_than(store) -> None:
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    new = datetime.now(UTC).isoformat()
    await store.add("old", {"kind": "conversation", "timestamp": old})
    await store.add("new", {"kind": "conversation", "timestamp": new})

    deleted = await store.delete_older_than(datetime.now(UTC) - timedelta(days=5))
    assert deleted == 1
    remaining = await store.search("new", top_k=5)
    assert any(r.text == "new" for r in remaining)
    assert not any(r.text == "old" for r in remaining)


async def test_clear_removes_everything(store) -> None:
    await store.add("a", {"kind": "conversation", "timestamp": "t"})
    await store.add("b", {"kind": "logbook", "timestamp": "t"})
    assert await store.clear() == 2
    assert await store.search("a", top_k=5) == []


async def test_long_text_is_chunked(store) -> None:
    ids = await store.add(
        "a" * (MEMORY_MAX_TEXT_LEN + 200), {"kind": "conversation", "timestamp": "t"}
    )
    assert len(ids) >= 2


async def test_add_with_explicit_doc_id_is_idempotent(store) -> None:
    await store.add("alpha", {"kind": "logbook", "timestamp": "t"}, doc_id="fixed-1")
    await store.add("alpha", {"kind": "logbook", "timestamp": "t"}, doc_id="fixed-1")
    results = await store.search("alpha", top_k=10)
    assert len([r for r in results if r.text == "alpha"]) == 1


async def test_score_is_inverted_distance(store) -> None:
    await store.add("hello world", {"kind": "conversation", "timestamp": "t"})
    results = await store.search("hello world", top_k=1)
    assert results[0].score == pytest.approx(1.0, abs=1e-4)


async def test_store_list_metadata_round_trips(store) -> None:
    await store.add("hello", {"kind": "entity", "entity_id": "light.a"}, doc_id="entity:light.a")

    stored = await store.list_metadata({"kind": "entity"})

    assert set(stored) == {"entity:light.a"}
    assert stored["entity:light.a"]["entity_id"] == "light.a"


async def test_store_update_metadata_round_trips(store) -> None:
    await store.add("hello", {"kind": "entity", "entity_id": "light.a"}, doc_id="entity:light.a")

    assert (
        await store.update_metadata(
            "entity:light.a", {"kind": "entity", "entity_id": "light.a", "state": "on"}
        )
        is True
    )
    stored = await store.list_metadata({"kind": "entity"})
    assert stored["entity:light.a"]["state"] == "on"


async def test_store_metadata_helpers_are_safe_when_unavailable(store) -> None:
    store.is_available = False

    assert await store.list_metadata() is None
    assert await store.update_metadata("entity:light.a", {"kind": "entity"}) is False


async def test_store_metadata_helpers_swallow_backend_failures(store, caplog) -> None:
    store.backend.list_metadata = AsyncMock(side_effect=RuntimeError("boom"))
    store.backend.update_metadata = AsyncMock(side_effect=RuntimeError("boom"))

    assert await store.list_metadata() is None
    assert await store.update_metadata("x", {}) is False
    assert store.is_available is True


async def test_search_does_not_report_a_broken_store_as_no_memories(store) -> None:
    """A failed lookup and an empty store must not give the same answer.

    Every caller of `MemoryStore.search` is written around this: the
    `search_memory` tool wraps the call in `try/except` to render "Memory
    lookup failed; see logs." instead of "No memories matched the query.",
    and `rank_entities` wraps it to decide between degrading to lexical and
    propagating. Both handlers were unreachable while the store swallowed
    the failure and returned `[]` — the model was told, confidently, that
    nothing had been remembered.
    """
    store.backend.query = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await store.search("hello", top_k=3)

    assert store.is_available is True


async def test_search_reports_a_failed_embedding_too(store) -> None:
    """The query has to be embedded before the backend is ever asked.

    A provider that refuses is just as much a failed lookup as an
    unreachable database, and must not read as "nothing matched" either.
    """
    store.embeddings.embed_query = AsyncMock(side_effect=RuntimeError("provider down"))

    with pytest.raises(RuntimeError):
        await store.search("hello", top_k=3)


async def test_add_reports_a_failed_write_to_its_caller(store) -> None:
    """Nothing was written, and the caller has to be able to find that out.

    Three callers already assume it: conversation ingest catches per store
    so one bad store does not stop the others, the logbook poller counts a
    row as `written` only if `add` returned without raising, and the entity
    indexer relies on a failed write aborting the sweep *before* it deletes
    orphans. All three were tested against mocks that raise while the real
    store returned `[]` and let every one of those paths run on.
    """
    store.backend.upsert = AsyncMock(side_effect=RuntimeError("disk full"))

    with pytest.raises(RuntimeError):
        await store.add("hello", {"kind": "conversation", "timestamp": "t"})

    assert store.is_available is True


async def test_add_still_answers_quietly_when_the_store_is_switched_off(store) -> None:
    """The unavailable path is not a failure and must stay a silent no-op.

    Otherwise every conversation turn on an installation with a disabled
    store would raise on ingest.
    """
    store.is_available = False

    assert await store.add("hello", {"kind": "conversation"}) == []


async def test_an_embedder_that_answers_with_nothing_does_not_make_a_working_store(
    store, hass
) -> None:
    """A zero-length probe is a broken provider, not a zero-dimension store.

    `dim = len(probe)` accepted `[]` and set the store `is_available`, so a
    provider answering with an empty vector produced a store that looked
    healthy and could never match anything.
    """
    from custom_components.smartchain.tools.memory.store import MemoryStore

    embeddings = AsyncMock()
    embeddings.embed_query = AsyncMock(return_value=[])
    backend = AsyncMock()
    backend.name = "fake"

    empty = MemoryStore(hass, embeddings, backend)
    await empty.async_setup()

    assert empty.is_available is False
    assert empty.unavailable_reason is not None
    backend.initialize.assert_not_awaited()


async def test_a_failed_read_is_not_reported_as_an_empty_store(store) -> None:
    """`None` and `{}` must never collapse into one another.

    The entity indexer reads `{}` as "the store is empty, index the whole
    home". If a failed read returned `{}` too, one unreachable database would
    re-embed every entity in the house.
    """
    assert await store.list_metadata({"kind": "entity"}) == {}  # genuinely empty

    store.backend.list_metadata = AsyncMock(side_effect=RuntimeError("boom"))

    assert await store.list_metadata({"kind": "entity"}) is None
