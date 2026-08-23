"""Tests for the stdlib-sqlite + numpy vector backend."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorRecord,
)
from custom_components.smartchain.tools.memory.backends.sqlite_numpy import (
    SqliteNumpyBackend,
)


@pytest.fixture
async def backend(hass: HomeAssistant, tmp_path):
    be = SqliteNumpyBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    yield be
    await be.close()


def _rec(
    doc_id: str,
    vector: list[float],
    kind: str = "conversation",
    ts: str = "2026-01-01T00:00:00+00:00",
):
    return VectorRecord(
        doc_id=doc_id,
        vector=vector,
        text=f"text-{doc_id}",
        metadata={"kind": kind, "timestamp": ts},
    )


async def test_initialize_creates_db(hass: HomeAssistant, tmp_path) -> None:
    be = SqliteNumpyBackend(hass, tmp_path / "sub" / "memory.db")
    await be.initialize(4)
    assert be.is_available is True
    assert (tmp_path / "sub" / "memory.db").exists()
    await be.close()


async def test_upsert_then_query_returns_nearest_first(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0]),
            _rec("b", [0.0, 1.0, 0.0]),
            _rec("c", [0.9, 0.1, 0.0]),
        ]
    )
    hits = await backend.query([1.0, 0.0, 0.0], top_k=2, where=None)
    assert [h.doc_id for h in hits] == ["a", "c"]
    assert hits[0].distance < hits[1].distance
    assert hits[0].text == "text-a"


async def test_query_applies_metadata_filter(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0], kind="conversation"),
            _rec("b", [1.0, 0.0, 0.0], kind="logbook"),
        ]
    )
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where={"kind": "logbook"})
    assert [h.doc_id for h in hits] == ["b"]


async def test_upsert_is_idempotent_on_doc_id(backend) -> None:
    await backend.upsert([_rec("a", [1.0, 0.0, 0.0])])
    await backend.upsert([_rec("a", [0.0, 1.0, 0.0])])
    hits = await backend.query([0.0, 1.0, 0.0], top_k=5, where=None)
    assert len(hits) == 1
    assert hits[0].doc_id == "a"


async def test_delete_older_than(backend) -> None:
    await backend.upsert(
        [
            _rec("old", [1.0, 0.0, 0.0], ts="2026-01-01T00:00:00+00:00"),
            _rec("new", [1.0, 0.0, 0.0], ts="2026-06-01T00:00:00+00:00"),
        ]
    )
    deleted = await backend.delete_older_than("2026-03-01T00:00:00+00:00")
    assert deleted == 1
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where=None)
    assert [h.doc_id for h in hits] == ["new"]


async def test_delete_where_and_delete_all(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0], kind="conversation"),
            _rec("b", [1.0, 0.0, 0.0], kind="logbook"),
        ]
    )
    assert await backend.delete_where({"kind": "logbook"}) == 1
    assert await backend.delete_where(None) == 1
    assert await backend.query([1.0, 0.0, 0.0], top_k=5, where=None) == []


async def test_dimension_mismatch_raises(hass: HomeAssistant, tmp_path) -> None:
    path = tmp_path / "memory.db"
    be = SqliteNumpyBackend(hass, path)
    await be.initialize(3)
    await be.close()

    other = SqliteNumpyBackend(hass, path)
    with pytest.raises(BackendInitError, match="768"):
        await other.initialize(768)
    assert other.is_available is False


async def test_dimension_mismatch_names_the_file_to_delete(hass: HomeAssistant, tmp_path) -> None:
    """A dimension conflict makes the store unavailable, so clear_memory cannot
    reach it — and would not reset the recorded dimension even if it could."""
    path = tmp_path / "memory.db"
    be = SqliteNumpyBackend(hass, path)
    await be.initialize(3)
    await be.close()

    other = SqliteNumpyBackend(hass, path)
    with pytest.raises(BackendInitError) as exc:
        await other.initialize(768)

    message = str(exc.value)
    assert f"Delete the database file {path}" in message
    assert "smartchain.reload_tools" in message
    assert "clear_memory" not in message


async def test_query_on_empty_store_returns_empty(backend) -> None:
    assert await backend.query([1.0, 0.0, 0.0], top_k=5, where=None) == []
