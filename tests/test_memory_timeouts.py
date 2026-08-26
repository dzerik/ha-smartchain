"""The nine `asyncio.timeout` guards around the store and the embeddings.

Every guard here exists for one promise: a slow or wedged provider must not
be able to hold a conversation turn open forever. Until this file the promise
was written down and never watched — no test in the repository so much as
named `MEMORY_BACKEND_TIMEOUT_SECONDS` or `MEMORY_EMBED_TIMEOUT_SECONDS`.

Two rules shape the tests below.

*The timeout is never mocked.* Patching `asyncio.timeout` would only prove
the mock works. Instead the budget constant is patched down to a few
milliseconds and the operation underneath is made genuinely slower than it —
by an `asyncio.sleep` for the backends, by a blocking `threading.Event.wait`
in an executor thread for the embeddings. Each test also asserts the wall
clock, because "raised the right error" and "came back in time" are two
different claims and only the second one is the guarantee.

*What the caller is told matters as much as when.* A guard that turns a
wedged backend into an empty result list is not a guard, it is a way of
losing the news. The `_returns_...` tests pin the answer each call gives.
"""

import asyncio
import threading
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import (
    MEMORY_BACKEND_TIMEOUT_SECONDS,
    MEMORY_EMBED_TIMEOUT_SECONDS,
)
from custom_components.smartchain.tools.memory.backends import VectorHit
from custom_components.smartchain.tools.memory.embeddings import _ExecutorBacked
from custom_components.smartchain.tools.memory.store import MemoryStore

# The patched budget, and how much slower than it the wedged operation is.
# 60x apart, so a guard that fails to fire cannot be mistaken for a slow test
# machine — and the operation is bounded rather than infinite, so a missing
# guard fails the run instead of hanging it.
BUDGET = 0.05
WEDGED = 3.0
# Anything under this proves the call came back on the budget, not on the
# operation. Generous enough not to flake on a loaded CI box.
CAME_BACK_FAST = 1.0

STORE_BUDGET = "custom_components.smartchain.tools.memory.store.MEMORY_BACKEND_TIMEOUT_SECONDS"
EMBED_BUDGET = "custom_components.smartchain.tools.memory.embeddings.MEMORY_EMBED_TIMEOUT_SECONDS"


class WedgedBackend:
    """A VectorBackend whose every call outlives any sane budget.

    `initialize` answers instantly: the store has to reach `is_available`
    before the operations under test are allowed to run at all.
    """

    name = "wedged"
    is_available = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def _wedge(self, what: str) -> Any:
        self.calls.append(what)
        await asyncio.sleep(WEDGED)
        raise AssertionError(f"{what} was allowed to run to completion")

    async def initialize(self, dim: int) -> None:
        return None

    async def upsert(self, records: list[Any]) -> None:
        await self._wedge("upsert")

    async def query(self, vector: list[float], top_k: int, where: Any) -> list[VectorHit]:
        return await self._wedge("query")

    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        return await self._wedge("update_metadata")

    async def list_metadata(self, where: Any = None) -> dict[str, dict[str, Any]]:
        return await self._wedge("list_metadata")

    async def delete_older_than(self, cutoff_iso: str) -> int:
        return await self._wedge("delete_older_than")

    async def delete_where(self, where: Any) -> int:
        return await self._wedge("delete_where")

    async def close(self) -> None:
        return None


def _embeddings(dim: int = 4) -> MagicMock:
    emb = MagicMock()
    emb.embed_query = AsyncMock(return_value=[0.1] * dim)
    emb.embed_documents = AsyncMock(side_effect=lambda texts: [[0.1] * dim for _ in texts])
    return emb


@pytest.fixture
async def wedged_store(hass: HomeAssistant):
    """A live store — `is_available` True — over a backend that never answers."""
    backend = WedgedBackend()
    store = MemoryStore(hass, _embeddings(), backend)
    await store.async_setup()
    assert store.is_available is True
    return store


class Stopwatch:
    """Wall-clock around the call under test."""

    def __enter__(self) -> "Stopwatch":
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed = time.monotonic() - self._start


# ---------------------------------------------------------------------------
# The six guards in store.py, all on MEMORY_BACKEND_TIMEOUT_SECONDS
# ---------------------------------------------------------------------------


async def test_add_gives_up_on_a_wedged_upsert(wedged_store) -> None:
    with patch(STORE_BUDGET, BUDGET), Stopwatch() as watch, pytest.raises(TimeoutError):
        await wedged_store.add("hello", {"kind": "conversation", "timestamp": "t"})

    assert watch.elapsed < CAME_BACK_FAST
    assert wedged_store.backend.calls == ["upsert"]


async def test_search_gives_up_on_a_wedged_query(wedged_store) -> None:
    with patch(STORE_BUDGET, BUDGET), Stopwatch() as watch, pytest.raises(TimeoutError):
        await wedged_store.search("hello", top_k=3)

    assert watch.elapsed < CAME_BACK_FAST
    assert wedged_store.backend.calls == ["query"]


async def test_delete_older_than_gives_up_on_a_wedged_backend(wedged_store, caplog) -> None:
    with patch(STORE_BUDGET, BUDGET), Stopwatch() as watch:
        deleted = await wedged_store.delete_older_than(datetime.now(UTC))

    assert watch.elapsed < CAME_BACK_FAST
    assert deleted == 0
    assert "retention" in caplog.text.lower()
    assert wedged_store.is_available is True


async def test_clear_gives_up_on_a_wedged_backend(wedged_store, caplog) -> None:
    with patch(STORE_BUDGET, BUDGET), Stopwatch() as watch:
        deleted = await wedged_store.clear({"kind": "entity"})

    assert watch.elapsed < CAME_BACK_FAST
    assert deleted == 0
    assert "clear" in caplog.text.lower()
    assert wedged_store.is_available is True


async def test_list_metadata_gives_up_on_a_wedged_backend(wedged_store) -> None:
    """A timed-out read answers `None`, never `{}`.

    `{}` is the entity indexer's signal to index the whole home from scratch;
    a backend that simply took too long must never be able to send it.
    """
    with patch(STORE_BUDGET, BUDGET), Stopwatch() as watch:
        result = await wedged_store.list_metadata({"kind": "entity"})

    assert watch.elapsed < CAME_BACK_FAST
    assert result is None


async def test_update_metadata_gives_up_on_a_wedged_backend(wedged_store) -> None:
    with patch(STORE_BUDGET, BUDGET), Stopwatch() as watch:
        result = await wedged_store.update_metadata("entity:light.a", {"state": "on"})

    assert watch.elapsed < CAME_BACK_FAST
    assert result is False


# ---------------------------------------------------------------------------
# The two guards in embeddings.py, on MEMORY_EMBED_TIMEOUT_SECONDS
# ---------------------------------------------------------------------------


class WedgedEmbeddings:
    """A synchronous LangChain-shaped embedder that blocks a worker thread.

    The block is a real one — `_ExecutorBacked` hands the call to HA's thread
    pool, and cancelling the awaiting task cannot stop a running thread. That
    is precisely why the guarantee is worth testing: the promise is that the
    *caller* is released, not that the work is stopped. `release()` lets the
    stranded thread finish so the test does not leave HA's executor blocked
    at teardown.
    """

    def __init__(self) -> None:
        self._gate = threading.Event()
        self.entered = threading.Event()

    def release(self) -> None:
        self._gate.set()

    def _block(self) -> Any:
        self.entered.set()
        self._gate.wait(timeout=WEDGED)
        raise AssertionError("the embeddings call was allowed to run to completion")

    def embed_query(self, text: str) -> list[float]:
        return self._block()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._block()


async def test_embed_query_gives_up_on_a_wedged_provider(hass: HomeAssistant) -> None:
    inner = WedgedEmbeddings()
    provider = _ExecutorBacked(hass, inner)
    try:
        with patch(EMBED_BUDGET, BUDGET), Stopwatch() as watch, pytest.raises(TimeoutError):
            await provider.embed_query("hello")
        assert watch.elapsed < CAME_BACK_FAST
        assert inner.entered.is_set()
    finally:
        inner.release()


async def test_embed_documents_gives_up_on_a_wedged_provider(hass: HomeAssistant) -> None:
    inner = WedgedEmbeddings()
    provider = _ExecutorBacked(hass, inner)
    try:
        with patch(EMBED_BUDGET, BUDGET), Stopwatch() as watch, pytest.raises(TimeoutError):
            await provider.embed_documents(["a", "b"])
        assert watch.elapsed < CAME_BACK_FAST
        assert inner.entered.is_set()
    finally:
        inner.release()


async def test_a_wedged_provider_disables_the_store_instead_of_hanging_setup(
    hass: HomeAssistant,
) -> None:
    """End-to-end: the embed guard is what keeps `async_setup` bounded.

    A provider that never answers the dimension probe would otherwise wedge
    the whole config-entry setup; the store must come back disabled, with a
    reason a user can read.
    """
    inner = WedgedEmbeddings()
    backend = MagicMock()
    backend.name = "fake"
    backend.initialize = AsyncMock()
    backend.close = AsyncMock()
    store = MemoryStore(hass, _ExecutorBacked(hass, inner), backend)
    try:
        with patch(EMBED_BUDGET, BUDGET), Stopwatch() as watch:
            await store.async_setup()
        assert watch.elapsed < CAME_BACK_FAST
        assert store.is_available is False
        assert store.unavailable_reason is not None
        assert "dimension probe" in store.unavailable_reason
        backend.initialize.assert_not_awaited()
    finally:
        inner.release()


# ---------------------------------------------------------------------------
# The budgets themselves
# ---------------------------------------------------------------------------


def test_the_budgets_are_finite_and_bounded() -> None:
    """A budget is only a guarantee while it is small enough to matter.

    Both constants are read by name here, which is the thing the audit found
    missing: `tests/` never mentioned either of them, so nothing objected if
    one drifted to an hour or to `None`.
    """
    for budget in (MEMORY_BACKEND_TIMEOUT_SECONDS, MEMORY_EMBED_TIMEOUT_SECONDS):
        assert isinstance(budget, (int, float))
        assert 0 < budget <= 120
