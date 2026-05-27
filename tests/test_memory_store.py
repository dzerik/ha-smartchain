"""Tests for MemoryStore (Chroma facade).

Dev-env caveat: chromadb requires pydantic v1 which is broken on Python 3.14.
Instead of using a real Chroma client, all tests inject a _FakeCollection that
mimics the subset of the chromadb.Collection API used by MemoryStore, and patch
`chromadb` in sys.modules so that _init_collection succeeds.
"""

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.store import (
    MemorySnippet,
    MemoryStore,
)

# ---------------------------------------------------------------------------
# Fake in-memory chromadb collection
# ---------------------------------------------------------------------------


class _FakeCollection:
    """Minimal in-memory replica of chromadb.Collection used by MemoryStore."""

    def __init__(self) -> None:
        # rows: {id: {"embedding": list[float], "document": str, "metadata": dict}}
        self._rows: dict[str, dict] = {}

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        for ident, emb, meta, doc in zip(ids, embeddings, metadatas, documents):
            self._rows[ident] = {"embedding": emb, "document": doc, "metadata": meta}

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 5,
        where: dict | None = None,
    ) -> dict:
        qvec = query_embeddings[0]
        rows = list(self._rows.values())
        # Apply where filter
        if where:
            rows = [r for r in rows if all(r["metadata"].get(k) == v for k, v in where.items())]

        # Cosine-like distance (Euclidean for simplicity — tests only need ranking)
        def _dist(row: dict) -> float:
            rvec = row["embedding"]
            dim = max(len(qvec), len(rvec))
            a = qvec + [0.0] * (dim - len(qvec))
            b = rvec + [0.0] * (dim - len(rvec))
            return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

        rows.sort(key=_dist)
        top = rows[:n_results]
        return {
            "documents": [[r["document"] for r in top]],
            "metadatas": [[r["metadata"] for r in top]],
            "distances": [[_dist(r) for r in top]],
        }

    def get(
        self,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> dict:
        rows = list(self._rows.items())
        if where:
            rows = [
                (ident, r)
                for ident, r in rows
                if all(r["metadata"].get(k) == v for k, v in where.items())
            ]
        return {
            "ids": [ident for ident, _ in rows],
            "metadatas": [r["metadata"] for _, r in rows],
        }

    def delete(self, ids: list[str]) -> None:
        for ident in ids:
            self._rows.pop(ident, None)


def _make_fake_chromadb(collection: _FakeCollection) -> ModuleType:
    """Build a minimal fake chromadb module that returns our fake collection."""
    chroma = ModuleType("chromadb")
    config_mod = ModuleType("chromadb.config")

    class FakeSettings:
        def __init__(self, **kwargs: object) -> None:
            pass

    config_mod.Settings = FakeSettings  # type: ignore[attr-defined]

    class FakeClient:
        def get_or_create_collection(self, name: str) -> _FakeCollection:
            return collection

    def PersistentClient(path: str, settings: object = None) -> FakeClient:  # noqa: N802
        return FakeClient()

    chroma.PersistentClient = PersistentClient  # type: ignore[attr-defined]
    chroma.config = config_mod  # type: ignore[attr-defined]
    return chroma


# ---------------------------------------------------------------------------
# Fake embeddings
# ---------------------------------------------------------------------------


class _FakeEmbeddings:
    """Deterministic mini-embedder so search returns predictable results."""

    def __init__(self) -> None:
        self.embed_query = AsyncMock(side_effect=self._embed)
        self.embed_documents = AsyncMock(side_effect=lambda texts: [self._embed(t) for t in texts])

    @staticmethod
    def _embed(text: str) -> list[float]:
        # Pseudo-embedding: first 8 character codes, zero-padded.
        vec = [float(ord(c)) for c in text[:8]]
        while len(vec) < 8:
            vec.append(0.0)
        return vec


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def store(hass: HomeAssistant, tmp_path):
    """MemoryStore backed by a _FakeCollection, not real Chroma."""
    collection = _FakeCollection()
    fake_chroma = _make_fake_chromadb(collection)
    fake_config = fake_chroma.config

    saved_chroma = sys.modules.get("chromadb")
    saved_config = sys.modules.get("chromadb.config")
    sys.modules["chromadb"] = fake_chroma
    sys.modules["chromadb.config"] = fake_config

    try:
        s = MemoryStore(hass, _FakeEmbeddings(), tmp_path / "chroma")
    finally:
        if saved_chroma is None:
            sys.modules.pop("chromadb", None)
        else:
            sys.modules["chromadb"] = saved_chroma
        if saved_config is None:
            sys.modules.pop("chromadb.config", None)
        else:
            sys.modules["chromadb.config"] = saved_config

    assert s.is_available, "MemoryStore should be available with fake chromadb"
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_add_and_search_returns_snippet(hass: HomeAssistant, store) -> None:
    await store.add("hello world", {"kind": "conversation", "timestamp": "t1"})
    results = await store.search("hello world", top_k=1)
    assert len(results) == 1
    assert isinstance(results[0], MemorySnippet)
    assert results[0].text == "hello world"
    assert results[0].metadata["kind"] == "conversation"


async def test_search_with_where_filter(hass: HomeAssistant, store) -> None:
    await store.add("foo", {"kind": "conversation", "timestamp": "t1"})
    await store.add("bar", {"kind": "logbook", "timestamp": "t2"})
    results = await store.search("foo", top_k=5, where={"kind": "logbook"})
    assert all(r.metadata["kind"] == "logbook" for r in results)


async def test_delete_older_than(hass: HomeAssistant, store) -> None:
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    new = datetime.now(UTC).isoformat()
    await store.add("old", {"kind": "conversation", "timestamp": old})
    await store.add("new", {"kind": "conversation", "timestamp": new})

    cutoff = datetime.now(UTC) - timedelta(days=5)
    deleted = await store.delete_older_than(cutoff)
    assert deleted == 1
    remaining = await store.search("new", top_k=5)
    assert any(r.text == "new" for r in remaining)
    assert not any(r.text == "old" for r in remaining)


async def test_clear_removes_everything(hass: HomeAssistant, store) -> None:
    await store.add("a", {"kind": "conversation", "timestamp": "t"})
    await store.add("b", {"kind": "logbook", "timestamp": "t"})
    deleted = await store.clear()
    assert deleted == 2
    assert await store.search("a", top_k=5) == []


async def test_long_text_is_chunked(hass: HomeAssistant, store) -> None:
    """Adding text > MEMORY_MAX_TEXT_LEN stores multiple docs sharing metadata."""
    from custom_components.smartchain.const import MEMORY_MAX_TEXT_LEN

    text = "a" * (MEMORY_MAX_TEXT_LEN + 200)
    ids = await store.add(text, {"kind": "conversation", "timestamp": "t"})
    assert len(ids) >= 2


async def test_add_with_explicit_doc_id(hass: HomeAssistant, store) -> None:
    """Re-adding the same explicit doc_id is idempotent (overwrite, not duplicate)."""
    await store.add("alpha", {"kind": "logbook", "timestamp": "t"}, doc_id="fixed-1")
    await store.add("alpha", {"kind": "logbook", "timestamp": "t"}, doc_id="fixed-1")
    results = await store.search("alpha", top_k=10)
    assert len([r for r in results if r.text == "alpha"]) == 1
