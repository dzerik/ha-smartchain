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
