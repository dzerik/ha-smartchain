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
    assert clause == " AND metadata->>'kind' = $3"
    assert params == ["logbook"]


def test_pg_empty() -> None:
    assert build_pg_where(None, start_index=1) == ("", [])


def test_qdrant_empty_is_none() -> None:
    assert build_qdrant_filter(None) is None
    assert build_qdrant_filter({}) is None


def test_qdrant_must_conditions() -> None:
    assert build_qdrant_filter({"kind": "logbook"}) == {
        "must": [{"key": "kind", "match": {"value": "logbook"}}]
    }


def test_all_dialects_handle_the_same_two_key_filter() -> None:
    where = {"kind": "conversation", "subentry_id": "s1"}
    sqlite_clause, sqlite_params = build_where_clause(where)
    pg_clause, pg_params = build_pg_where(where, start_index=1)
    qdrant = build_qdrant_filter(where)

    assert len(sqlite_params) == 2
    assert len(pg_params) == 2
    assert len(qdrant["must"]) == 2
    assert "kind" in sqlite_clause and "kind" in pg_clause
