"""One contract test suite, executed against every VectorBackend.

Backends that need an unavailable dependency or an external server are skipped
rather than mocked here: mocks would test the mock, not the contract. Their
per-backend files cover the mocked paths.
"""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import (
    VectorBackend,
    VectorRecord,
)
from custom_components.smartchain.tools.memory.backends.sqlite_numpy import (
    SqliteNumpyBackend,
)


def _sqlite_numpy(hass, tmp_path):
    return SqliteNumpyBackend(hass, tmp_path / "conformance.db")


def _sqlite_vec(hass, tmp_path):
    pytest.importorskip("sqlite_vec", reason="sqlite-vec is optional")
    from custom_components.smartchain.tools.memory.backends.sqlite_vec import (
        SqliteVecBackend,
    )

    return SqliteVecBackend(hass, tmp_path / "conformance_vec.db")


BACKEND_FACTORIES = {
    "sqlite_numpy": _sqlite_numpy,
    "sqlite_vec": _sqlite_vec,
}


@pytest.fixture(params=sorted(BACKEND_FACTORIES))
async def backend(request, hass: HomeAssistant, tmp_path):
    be = BACKEND_FACTORIES[request.param](hass, tmp_path)
    await be.initialize(3)
    yield be
    await be.close()


def _rec(doc_id, vector, kind="conversation", ts="2026-01-01T00:00:00+00:00"):
    return VectorRecord(
        doc_id=doc_id,
        vector=vector,
        text=f"text-{doc_id}",
        metadata={"kind": kind, "timestamp": ts},
    )


async def test_satisfies_protocol(backend) -> None:
    assert isinstance(backend, VectorBackend)
    assert backend.is_available is True
    assert isinstance(backend.name, str) and backend.name


async def test_upsert_then_query_finds_the_record(backend) -> None:
    await backend.upsert([_rec("a", [1.0, 0.0, 0.0])])
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where=None)
    assert [h.doc_id for h in hits] == ["a"]
    assert hits[0].text == "text-a"
    assert hits[0].metadata["kind"] == "conversation"


async def test_nearest_comes_first(backend) -> None:
    await backend.upsert([_rec("far", [0.0, 1.0, 0.0]), _rec("near", [1.0, 0.0, 0.0])])
    hits = await backend.query([1.0, 0.0, 0.0], top_k=2, where=None)
    assert hits[0].doc_id == "near"
    assert hits[0].distance <= hits[1].distance


async def test_top_k_is_respected(backend) -> None:
    await backend.upsert([_rec(f"d{i}", [1.0, float(i) / 10, 0.0]) for i in range(5)])
    assert len(await backend.query([1.0, 0.0, 0.0], top_k=2, where=None)) == 2


async def test_metadata_filter_narrows_results(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0], kind="conversation"),
            _rec("b", [1.0, 0.0, 0.0], kind="logbook"),
        ]
    )
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where={"kind": "logbook"})
    assert [h.doc_id for h in hits] == ["b"]


async def test_filter_is_applied_before_the_top_k_cut(backend) -> None:
    """Matching records ranked below non-matching ones must still be returned.

    A backend that asks its index for `top_k` neighbours and only then applies
    the metadata filter returns nothing here: the ten `logbook` rows are all
    nearer the query than the three `conversation` rows.
    """
    near = [_rec(f"log{i}", [1.0, float(i) / 1000, 0.0], kind="logbook") for i in range(10)]
    far = [_rec(f"conv{i}", [0.2, 1.0, float(i) / 1000], kind="conversation") for i in range(3)]
    await backend.upsert(near + far)

    hits = await backend.query([1.0, 0.0, 0.0], top_k=3, where={"kind": "conversation"})
    assert sorted(h.doc_id for h in hits) == ["conv0", "conv1", "conv2"]


async def test_upsert_same_doc_id_replaces(backend) -> None:
    await backend.upsert([_rec("a", [1.0, 0.0, 0.0])])
    await backend.upsert([_rec("a", [0.0, 0.0, 1.0])])
    hits = await backend.query([0.0, 0.0, 1.0], top_k=5, where=None)
    assert len([h for h in hits if h.doc_id == "a"]) == 1


async def test_delete_older_than_removes_only_older(backend) -> None:
    await backend.upsert(
        [
            _rec("old", [1.0, 0.0, 0.0], ts="2026-01-01T00:00:00+00:00"),
            _rec("new", [1.0, 0.0, 0.0], ts="2026-06-01T00:00:00+00:00"),
        ]
    )
    assert await backend.delete_older_than("2026-03-01T00:00:00+00:00") == 1
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where=None)
    assert [h.doc_id for h in hits] == ["new"]


async def test_delete_where_filters(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0], kind="conversation"),
            _rec("b", [1.0, 0.0, 0.0], kind="logbook"),
        ]
    )
    await backend.delete_where({"kind": "logbook"})
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where=None)
    assert [h.doc_id for h in hits] == ["a"]


async def test_delete_where_none_clears_everything(backend) -> None:
    await backend.upsert([_rec("a", [1.0, 0.0, 0.0]), _rec("b", [0.0, 1.0, 0.0])])
    await backend.delete_where(None)
    assert await backend.query([1.0, 0.0, 0.0], top_k=5, where=None) == []


async def test_query_on_empty_backend_is_empty(backend) -> None:
    assert await backend.query([1.0, 0.0, 0.0], top_k=5, where=None) == []


async def test_operations_are_noops_after_close(backend) -> None:
    await backend.upsert([_rec("a", [1.0, 0.0, 0.0])])
    await backend.close()
    assert backend.is_available is False
    assert await backend.query([1.0, 0.0, 0.0], top_k=5, where=None) == []
    assert await backend.delete_where(None) == 0
    assert await backend.list_metadata() == {}
    assert await backend.update_metadata("a", {"kind": "tampered"}) is False

    # the attempted update after close must not have actually written:
    # reopen and confirm the original metadata is still there.
    backend.is_available = True
    stored = await backend.list_metadata()
    assert stored["a"]["kind"] == "conversation"


async def test_list_metadata_returns_every_stored_doc(backend) -> None:
    await backend.initialize(3)
    await backend.upsert(
        [
            VectorRecord(doc_id="a", vector=[1.0, 0.0, 0.0], text="a", metadata={"kind": "x"}),
            VectorRecord(doc_id="b", vector=[0.0, 1.0, 0.0], text="b", metadata={"kind": "y"}),
        ]
    )
    everything = await backend.list_metadata()
    assert set(everything) == {"a", "b"}
    assert everything["a"]["kind"] == "x"


async def test_list_metadata_honours_the_filter(backend) -> None:
    await backend.initialize(3)
    await backend.upsert(
        [
            VectorRecord(doc_id="a", vector=[1.0, 0.0, 0.0], text="a", metadata={"kind": "x"}),
            VectorRecord(doc_id="b", vector=[0.0, 1.0, 0.0], text="b", metadata={"kind": "y"}),
        ]
    )
    assert set(await backend.list_metadata({"kind": "x"})) == {"a"}


async def test_update_metadata_replaces_without_touching_the_vector(backend) -> None:
    await backend.initialize(3)
    await backend.upsert(
        [VectorRecord(doc_id="a", vector=[1.0, 0.0, 0.0], text="a", metadata={"kind": "x"})]
    )
    assert await backend.update_metadata("a", {"kind": "x", "state": "on"}) is True

    stored = await backend.list_metadata({"kind": "x"})
    assert stored["a"]["state"] == "on"

    # the vector survived: an identical query still finds the document
    hits = await backend.query([1.0, 0.0, 0.0], top_k=1, where=None)
    assert hits[0].doc_id == "a"


async def test_update_metadata_reports_a_missing_doc(backend) -> None:
    await backend.initialize(3)
    assert await backend.update_metadata("nope", {"kind": "x"}) is False


def test_factory_builds_each_type(hass: HomeAssistant, tmp_path) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.tools.memory.backends import create_backend

    sn = create_backend(
        hass, SimpleNamespace(type="sqlite_numpy", path=None), "conversations", tmp_path
    )
    assert sn.name == "sqlite_numpy"
    assert sn.db_path == tmp_path / "conversations.db"

    pg = create_backend(
        hass,
        SimpleNamespace(type="pgvector", dsn="postgresql://x/y", table=None),
        "entities",
        tmp_path,
    )
    assert pg.name == "pgvector"
    assert pg.table == "smartchain_memory"

    qd = create_backend(
        hass,
        SimpleNamespace(
            type="qdrant", url="http://q:6333/", collection=None, api_key=None, verify_ssl=True
        ),
        "entities",
        tmp_path,
    )
    assert qd.name == "qdrant"
    assert qd.url == "http://q:6333"
    assert qd.collection == "smartchain_memory"


def test_factory_rejects_unknown_type(hass: HomeAssistant, tmp_path) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.tools.memory.backends import (
        BackendInitError,
        create_backend,
    )

    with pytest.raises(BackendInitError, match="unknown backend type"):
        create_backend(hass, SimpleNamespace(type="milvus"), "s", tmp_path)


def test_explicit_path_overrides_store_name(hass: HomeAssistant, tmp_path) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.tools.memory.backends import create_backend

    be = create_backend(
        hass,
        SimpleNamespace(type="sqlite_numpy", path=str(tmp_path / "custom.db")),
        "conversations",
        tmp_path,
    )
    assert be.db_path == tmp_path / "custom.db"
