"""The neutral filter must translate correctly into every backend dialect."""

from custom_components.smartchain.tools.memory.backends.pgvector import build_pg_where
from custom_components.smartchain.tools.memory.backends.qdrant import build_qdrant_filter
from custom_components.smartchain.tools.memory.backends.sqlite_numpy import (
    build_where_clause,
)


def test_sqlite_empty() -> None:
    assert build_where_clause(None) == ("", [])
    assert build_where_clause({}) == ("", [])


def test_sqlite_single_condition() -> None:
    clause, params = build_where_clause({"kind": "logbook"})
    assert clause == " AND json_extract(metadata, '$.kind') = ?"
    assert params == ["logbook"]


def test_sqlite_two_conditions_are_anded() -> None:
    clause, params = build_where_clause({"kind": "logbook", "agent_id": "a1"})
    assert clause.count("AND") == 2
    assert params == ["logbook", "a1"]


def test_pg_placeholders_start_where_told() -> None:
    clause, params = build_pg_where({"kind": "logbook"}, start_index=3)
    assert clause == " AND metadata->'kind' = $3::jsonb"
    assert params == ['"logbook"']


def test_pg_empty() -> None:
    assert build_pg_where(None, start_index=1) == ("", [])


def test_qdrant_empty_is_none() -> None:
    assert build_qdrant_filter(None) is None
    assert build_qdrant_filter({}) is None


def test_qdrant_must_conditions() -> None:
    # Qdrant filter keys are JSON paths into the payload, and `upsert` nests
    # the neutral metadata under a "metadata" key — so the path prefix is
    # mandatory. Without it every filtered query and delete matches nothing.
    assert build_qdrant_filter({"kind": "logbook"}) == {
        "must": [{"key": "metadata.kind", "match": {"value": "logbook"}}]
    }


def test_qdrant_keys_are_payload_paths_not_bare_names() -> None:
    flt = build_qdrant_filter({"kind": "logbook", "subentry_id": "s1"})
    keys = [cond["key"] for cond in flt["must"]]
    assert keys == ["metadata.kind", "metadata.subentry_id"]


def test_all_dialects_handle_the_same_two_key_filter() -> None:
    where = {"kind": "conversation", "subentry_id": "s1"}
    sqlite_clause, sqlite_params = build_where_clause(where)
    pg_clause, pg_params = build_pg_where(where, start_index=1)
    qdrant = build_qdrant_filter(where)

    # Arity alone proves nothing: a dialect can emit the right number of
    # clauses against entirely wrong keys. Assert on key semantics too.
    assert sqlite_params == ["conversation", "s1"]
    assert pg_params == ['"conversation"', '"s1"']
    for key in where:
        assert f"json_extract(metadata, '$.{key}')" in sqlite_clause
        assert f"metadata->'{key}'" in pg_clause

    assert [cond["key"] for cond in qdrant["must"]] == ["metadata.kind", "metadata.subentry_id"]
    assert [cond["match"]["value"] for cond in qdrant["must"]] == ["conversation", "s1"]
