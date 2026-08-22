"""MemoryStore probes the embedding dimension and reacts to a mismatch."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import MEMORY_DIM_PROBE_TEXT
from custom_components.smartchain.tools.memory.backends.base import BackendInitError
from custom_components.smartchain.tools.memory.store import MemoryStore


def _embeddings(dim: int) -> MagicMock:
    emb = MagicMock()
    emb.embed_query = AsyncMock(return_value=[0.1] * dim)
    emb.embed_documents = AsyncMock(side_effect=lambda texts: [[0.1] * dim for _ in texts])
    return emb


def _backend() -> MagicMock:
    be = MagicMock()
    be.name = "fake"
    be.is_available = True
    be.initialize = AsyncMock()
    be.upsert = AsyncMock()
    be.query = AsyncMock(return_value=[])
    be.delete_older_than = AsyncMock(return_value=0)
    be.delete_where = AsyncMock(return_value=0)
    be.close = AsyncMock()
    return be


async def test_setup_probes_and_passes_dimension(hass: HomeAssistant) -> None:
    emb = _embeddings(768)
    be = _backend()
    store = MemoryStore(hass, emb, be)
    await store.async_setup()

    emb.embed_query.assert_awaited_once_with(MEMORY_DIM_PROBE_TEXT)
    be.initialize.assert_awaited_once_with(768)
    assert store.is_available is True


async def test_backend_init_error_disables_store(hass: HomeAssistant) -> None:
    be = _backend()
    be.initialize = AsyncMock(side_effect=BackendInitError("dimension is 768 but model gives 1536"))
    store = MemoryStore(hass, _embeddings(1536), be)
    await store.async_setup()
    assert store.is_available is False


async def test_probe_failure_disables_store(hass: HomeAssistant) -> None:
    emb = _embeddings(768)
    emb.embed_query = AsyncMock(side_effect=RuntimeError("ollama is down"))
    store = MemoryStore(hass, emb, _backend())
    await store.async_setup()
    assert store.is_available is False


async def test_operations_noop_when_unavailable(hass: HomeAssistant) -> None:
    be = _backend()
    be.initialize = AsyncMock(side_effect=BackendInitError("nope"))
    store = MemoryStore(hass, _embeddings(3), be)
    await store.async_setup()

    assert await store.add("text", {"kind": "conversation"}) == []
    assert await store.search("q") == []
    assert await store.clear() == 0
    be.upsert.assert_not_awaited()
    be.query.assert_not_awaited()
