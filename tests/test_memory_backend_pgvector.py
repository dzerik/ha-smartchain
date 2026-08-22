"""Tests for the pgvector backend against a mocked asyncpg pool."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorRecord,
)
from custom_components.smartchain.tools.memory.backends.pgvector import (
    PgVectorBackend,
    build_pg_where,
)


def test_build_pg_where_empty() -> None:
    clause, params = build_pg_where(None, start_index=1)
    assert clause == ""
    assert params == []


def test_build_pg_where_single() -> None:
    clause, params = build_pg_where({"kind": "logbook"}, start_index=2)
    assert clause == " AND metadata->>'kind' = $2"
    assert params == ["logbook"]


def test_build_pg_where_multiple_numbers_placeholders_sequentially() -> None:
    clause, params = build_pg_where({"kind": "logbook", "agent_id": "a1"}, start_index=3)
    assert clause == " AND metadata->>'kind' = $3 AND metadata->>'agent_id' = $4"
    assert params == ["logbook", "a1"]


def test_build_pg_where_casts_non_string_values() -> None:
    clause, params = build_pg_where({"chunk_index": 2}, start_index=1)
    assert clause == " AND metadata->>'chunk_index' = $1"
    assert params == ["2"]


@pytest.fixture
def fake_pool():
    """A mocked asyncpg pool whose acquired connection records every call."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=None)

    acquire_ctx = MagicMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    pool.close = AsyncMock()
    return pool, conn


@pytest.fixture
def fake_asyncpg(fake_pool):
    """Install a fake `asyncpg` module so the lazy import resolves."""
    pool, _conn = fake_pool
    module = SimpleNamespace(create_pool=AsyncMock(return_value=pool))
    with patch.dict(sys.modules, {"asyncpg": module}):
        yield module


async def test_initialize_creates_extension_table_and_index(
    hass: HomeAssistant, fake_asyncpg, fake_pool
) -> None:
    _pool, conn = fake_pool
    be = PgVectorBackend(hass, dsn="postgresql://x/y", table="smartchain_memory")
    await be.initialize(768)

    assert be.is_available is True
    statements = " ".join(call.args[0] for call in conn.execute.call_args_list)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in statements
    assert "vector(768)" in statements
    assert "USING hnsw" in statements


async def test_initialize_creates_valid_json_default(
    hass: HomeAssistant, fake_asyncpg, fake_pool
) -> None:
    _pool, conn = fake_pool
    be = PgVectorBackend(hass, dsn="postgresql://x/y", table="t")
    await be.initialize(3)

    statements = " ".join(call.args[0] for call in conn.execute.call_args_list)
    assert "DEFAULT '{}'::jsonb" in statements
    assert "{{" not in statements


async def test_initialize_falls_back_when_hnsw_unsupported(
    hass: HomeAssistant, fake_asyncpg, fake_pool
) -> None:
    _pool, conn = fake_pool

    async def _execute(sql: str, *args):
        if "USING hnsw" in sql:
            raise RuntimeError('access method "hnsw" does not exist')
        return None

    conn.execute = AsyncMock(side_effect=_execute)
    be = PgVectorBackend(hass, dsn="postgresql://x/y", table="t")
    await be.initialize(768)
    assert be.is_available is True


async def test_initialize_dimension_mismatch_raises(
    hass: HomeAssistant, fake_asyncpg, fake_pool
) -> None:
    _pool, conn = fake_pool
    conn.fetchval = AsyncMock(return_value=768)
    be = PgVectorBackend(hass, dsn="postgresql://x/y", table="t")
    with pytest.raises(BackendInitError, match="1536"):
        await be.initialize(1536)
    assert be.is_available is False


async def test_connection_failure_raises_without_leaking_dsn(
    hass: HomeAssistant, fake_pool
) -> None:
    module = SimpleNamespace(
        create_pool=AsyncMock(side_effect=OSError("connection refused to secret-host"))
    )
    be = PgVectorBackend(hass, dsn="postgresql://user:hunter2@secret-host/db", table="t")
    with patch.dict(sys.modules, {"asyncpg": module}):
        with pytest.raises(BackendInitError) as exc:
            await be.initialize(768)
    assert "hunter2" not in str(exc.value)
    assert "secret-host" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert be.is_available is False


async def test_query_orders_by_cosine_distance(
    hass: HomeAssistant, fake_asyncpg, fake_pool
) -> None:
    _pool, conn = fake_pool
    conn.fetch = AsyncMock(
        return_value=[
            {"doc_id": "a", "text": "ta", "metadata": '{"kind":"conversation"}', "distance": 0.1}
        ]
    )
    be = PgVectorBackend(hass, dsn="postgresql://x/y", table="t")
    await be.initialize(3)
    hits = await be.query([1.0, 0.0, 0.0], top_k=5, where={"kind": "conversation"})

    assert [h.doc_id for h in hits] == ["a"]
    assert hits[0].distance == 0.1
    sql = conn.fetch.call_args.args[0]
    assert "<=>" in sql
    assert "metadata->>'kind'" in sql


async def test_upsert_uses_on_conflict(hass: HomeAssistant, fake_asyncpg, fake_pool) -> None:
    _pool, conn = fake_pool
    be = PgVectorBackend(hass, dsn="postgresql://x/y", table="t")
    await be.initialize(3)
    await be.upsert([VectorRecord("a", [1.0, 0.0, 0.0], "ta", {"kind": "conversation"})])

    sql = conn.executemany.call_args.args[0]
    assert "ON CONFLICT (doc_id) DO UPDATE" in sql
