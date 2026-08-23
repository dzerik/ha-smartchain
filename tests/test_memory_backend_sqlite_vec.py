"""Tests for the sqlite-vec backend, including the extension-missing path."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.sqlite_vec import (
    SqliteVecBackend,
)

sqlite_vec = pytest.importorskip(
    "sqlite_vec", reason="sqlite-vec is optional and not installed in CI"
)


async def test_initialize_creates_virtual_table(hass: HomeAssistant, tmp_path) -> None:
    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    assert be.is_available is True
    await be.close()


async def test_upsert_then_query(hass: HomeAssistant, tmp_path) -> None:
    from custom_components.smartchain.tools.memory.backends.base import VectorRecord

    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    await be.upsert(
        [
            VectorRecord("a", [1.0, 0.0, 0.0], "text-a", {"kind": "conversation"}),
            VectorRecord("b", [0.0, 1.0, 0.0], "text-b", {"kind": "conversation"}),
        ]
    )
    hits = await be.query([1.0, 0.0, 0.0], top_k=1, where=None)
    assert [h.doc_id for h in hits] == ["a"]
    await be.close()


async def test_filtered_query_over_fetches_past_nearer_non_matches(
    hass: HomeAssistant, tmp_path
) -> None:
    """vec0 applies `k` inside the index, before the metadata conditions run.

    Asking it for exactly top_k neighbours and filtering afterwards returns
    nothing whenever the nearest rows all belong to another kind.
    """
    from custom_components.smartchain.tools.memory.backends.base import VectorRecord

    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    await be.upsert(
        [
            VectorRecord(f"log{i}", [1.0, i / 1000, 0.0], f"t{i}", {"kind": "logbook"})
            for i in range(30)
        ]
        + [
            VectorRecord(f"conv{i}", [0.2, 1.0, i / 1000], f"c{i}", {"kind": "conversation"})
            for i in range(3)
        ]
    )

    hits = await be.query([1.0, 0.0, 0.0], top_k=2, where={"kind": "conversation"})
    assert [h.doc_id for h in hits] == ["conv0", "conv1"]
    await be.close()


async def test_filtered_query_still_honours_top_k(hass: HomeAssistant, tmp_path) -> None:
    """Over-fetching must not leak extra rows past the caller's top_k."""
    from custom_components.smartchain.tools.memory.backends.base import VectorRecord

    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    await be.upsert(
        [
            VectorRecord(f"d{i}", [1.0, i / 100, 0.0], f"t{i}", {"kind": "logbook"})
            for i in range(10)
        ]
    )
    hits = await be.query([1.0, 0.0, 0.0], top_k=3, where={"kind": "logbook"})
    assert len(hits) == 3
    await be.close()


async def test_dimension_mismatch_names_the_file_to_delete(hass: HomeAssistant, tmp_path) -> None:
    from custom_components.smartchain.tools.memory.backends.base import BackendInitError

    path = tmp_path / "memory.db"
    be = SqliteVecBackend(hass, path)
    await be.initialize(3)
    await be.close()

    other = SqliteVecBackend(hass, path)
    with pytest.raises(BackendInitError) as exc:
        await other.initialize(768)

    message = str(exc.value)
    assert f"Delete the database file {path}" in message
    assert "smartchain.reload_tools" in message
    assert "clear_memory" not in message
