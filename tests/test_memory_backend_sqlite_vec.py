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


async def test_filtered_query_reaches_matches_behind_any_number_of_non_matches(
    hass: HomeAssistant, tmp_path
) -> None:
    """vec0 applies `k` inside the index, before the metadata conditions run.

    Asking it for a page of neighbours and filtering afterwards returns nothing
    whenever the nearest rows all belong to another kind. The count here is far
    past the 200-row window this backend used to over-fetch, so no widening of
    that window would rescue it — only ranking the matching rows directly does.
    """
    from custom_components.smartchain.tools.memory.backends.base import VectorRecord

    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    await be.upsert(
        [
            VectorRecord(f"log{i}", [1.0, i / 100000, 0.0], f"t{i}", {"kind": "logbook"})
            for i in range(400)
        ]
        + [
            VectorRecord(f"conv{i}", [0.2, 1.0, i / 1000], f"c{i}", {"kind": "conversation"})
            for i in range(3)
        ]
    )

    hits = await be.query([1.0, 0.0, 0.0], top_k=2, where={"kind": "conversation"})
    assert [h.doc_id for h in hits] == ["conv0", "conv1"]
    await be.close()


async def test_filtered_query_agrees_with_sqlite_numpy_on_the_same_data(
    hass: HomeAssistant, tmp_path
) -> None:
    """Same records, same call, same answer — ids, order and distances alike.

    The two backends share a VectorBackend Protocol, and this is what that is
    supposed to buy: switching `backend.type` in tools.yaml must not change
    which memories an agent can recall. Distances are compared too, because
    equal ids with different distances would still change the ordering the
    moment a caller merges hits from more than one store.

    The distance tolerance is absolute, not relative: vec0 computes the cosine
    in C and sqlite_numpy in numpy, so they disagree in the last bits (~1e-7
    here), and a distance near zero turns that into a large *relative* gap
    while remaining a meaningless one. 1e-6 is still far tighter than any
    difference that could reorder results.
    """
    from custom_components.smartchain.tools.memory.backends.base import VectorRecord
    from custom_components.smartchain.tools.memory.backends.sqlite_numpy import (
        SqliteNumpyBackend,
    )

    records = [
        VectorRecord(
            f"d{i}",
            [1.0 - i / 500, i / 500, (i % 7) / 10],
            f"t{i}",
            {"kind": "logbook" if i % 3 else "conversation", "subentry_id": "sub-a"},
        )
        for i in range(300)
    ]
    query = [0.4, 0.6, 0.2]
    where = {"kind": "conversation", "subentry_id": "sub-a"}

    vec = SqliteVecBackend(hass, tmp_path / "vec.db")
    num = SqliteNumpyBackend(hass, tmp_path / "num.db")
    for be in (vec, num):
        await be.initialize(3)
        await be.upsert(records)

    vec_hits = await vec.query(query, top_k=5, where=where)
    num_hits = await num.query(query, top_k=5, where=where)

    assert [h.doc_id for h in vec_hits] == [h.doc_id for h in num_hits]
    assert len(vec_hits) == 5
    assert [h.distance for h in vec_hits] == pytest.approx(
        [h.distance for h in num_hits], abs=1e-6, rel=0
    )

    await vec.close()
    await num.close()


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


async def test_probe_confirms_this_installation_pushes_the_filter_down(
    hass: HomeAssistant, tmp_path
) -> None:
    """The capability the filtered path depends on, checked against the real extension."""
    import sqlite3

    from custom_components.smartchain.tools.memory.backends.sqlite_vec import (
        _load_sqlite_vec,
        _probe_filtered_knn,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _load_sqlite_vec(conn)
    try:
        assert _probe_filtered_knn(conn) is True
    finally:
        conn.close()


async def test_initialize_refuses_when_the_filter_is_not_pushed_down(
    hass: HomeAssistant, tmp_path, monkeypatch
) -> None:
    """An extension that cannot pre-filter must disable the store, not answer wrongly.

    Without this the backend degrades exactly into the defect it was fixed for:
    `rowid IN` quietly stops narrowing the candidate set, vec0 goes back to
    filtering after its own `k` cut, and every filtered search loses matches
    with nothing in the log. `store.search` turns query exceptions into an
    empty list, so failing later is barely louder. Fail at startup instead.
    """
    from custom_components.smartchain.tools.memory.backends import sqlite_vec as mod
    from custom_components.smartchain.tools.memory.backends.base import BackendInitError

    monkeypatch.setattr(mod, "_probe_filtered_knn", lambda conn: False)

    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    with pytest.raises(BackendInitError) as exc:
        await be.initialize(3)

    assert be.is_available is False
    assert "sqlite_numpy" in str(exc.value)


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
