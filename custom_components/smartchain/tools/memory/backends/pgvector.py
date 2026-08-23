"""PostgreSQL + pgvector backend.

`asyncpg` is an optional dependency, lazy-imported in `initialize()`. The DSN
is a credential: it must never reach an exception message that a caller might
surface, so every failure raises a scrubbed BackendInitError while the full
cause goes to the log.
"""

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .base import BackendInitError, Filter, VectorHit, VectorRecord

LOGGER = logging.getLogger(__name__)


def build_pg_where(where: Filter | None, start_index: int) -> tuple[str, list[Any]]:
    """Translate the neutral filter into a jsonb WHERE fragment.

    `start_index` is the first positional placeholder number to use, so the
    caller can reserve $1/$2 for the query vector and limit.

    The comparison is jsonb-to-jsonb (`metadata->'key' = $n::jsonb`), not
    text-to-text. `metadata->>'key'` renders every value as text, where a
    Python `True` stringifies to "True" and can never equal the "true" JSON
    stores; floats are similarly at the mercy of repr. Encoding the value with
    json.dumps and letting Postgres compare jsonb keeps str, int, float and
    bool — the whole of `Filter` — matching what `upsert` wrote.
    """
    if not where:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    for offset, (key, value) in enumerate(where.items()):
        clauses.append(f"metadata->'{key}' = ${start_index + offset}::jsonb")
        params.append(json.dumps(value))
    return " AND " + " AND ".join(clauses), params


class PgVectorBackend:
    """Vectors in a `vector(N)` column with an HNSW cosine index."""

    name = "pgvector"

    def __init__(self, hass: HomeAssistant, dsn: str, table: str) -> None:
        self.hass = hass
        self._dsn = dsn
        self.table = table
        self.is_available = False
        self._pool: Any = None
        self._dim: int | None = None

    async def initialize(self, dim: int) -> None:
        try:
            import asyncpg  # noqa: PLC0415
        except ImportError as err:
            self.is_available = False
            raise BackendInitError(
                "The pgvector backend needs the `asyncpg` package. Install it in "
                "the Home Assistant environment, or switch this store to the "
                "sqlite_numpy backend."
            ) from err

        try:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        except Exception:  # noqa: BLE001 — cause is logged, message is scrubbed
            self.is_available = False
            LOGGER.exception("pgvector could not connect")
            raise BackendInitError(
                "pgvector could not connect to the configured database; see the "
                "Home Assistant log for details."
            ) from None

        try:
            async with self._pool.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

                # to_regclass resolves the name through the session search_path
                # and yields the one OID this connection would actually read.
                # Matching on pg_class.relname alone would happily pick up a
                # same-named table in an unrelated schema.
                existing_dim = await conn.fetchval(
                    "SELECT a.atttypmod FROM pg_attribute a "
                    "WHERE a.attrelid = to_regclass($1) AND a.attname = 'embedding'",
                    self.table,
                )
                if existing_dim is not None and int(existing_dim) != dim:
                    self.is_available = False
                    # Clearing the store cannot fix this: the vector(N) column
                    # type outlives a row delete, and a store with a dimension
                    # conflict never becomes available for smartchain.clear_memory
                    # to act on. Only dropping the table does it.
                    raise BackendInitError(
                        f"table {self.table} stores {existing_dim}-dimensional vectors "
                        f"but the configured model produces {dim}. Drop the table "
                        f"{self.table} in the configured database, then call "
                        "smartchain.reload_tools."
                    )

                await conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {self.table} ("
                    "doc_id text PRIMARY KEY, "
                    "text text NOT NULL, "
                    "metadata jsonb NOT NULL DEFAULT '{}'::jsonb, "
                    f"embedding vector({dim}), "
                    "timestamp timestamptz)"
                )
                try:
                    await conn.execute(
                        f"CREATE INDEX IF NOT EXISTS {self.table}_embedding_hnsw "
                        f"ON {self.table} USING hnsw (embedding vector_cosine_ops)"
                    )
                except Exception:  # noqa: BLE001 — pre-0.5 pgvector has no HNSW
                    LOGGER.warning(
                        "pgvector on this server does not support HNSW; continuing "
                        "without a vector index. Queries still work but will be "
                        "slower on large stores."
                    )
        except BackendInitError:
            await self._discard_pool()
            raise
        except Exception:  # noqa: BLE001
            self.is_available = False
            LOGGER.exception("pgvector schema setup failed")
            await self._discard_pool()
            raise BackendInitError(
                "pgvector could not create its table or extension. The database "
                "user likely lacks privileges; see the Home Assistant log."
            ) from None

        self._dim = dim
        self.is_available = True

    async def upsert(self, records: list[VectorRecord]) -> None:
        if not self.is_available or not records:
            return
        rows = [
            (
                r.doc_id,
                r.text,
                json.dumps(r.metadata, ensure_ascii=False),
                _vector_literal(r.vector),
                str(r.metadata.get("timestamp") or "") or None,
            )
            for r in records
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                f"INSERT INTO {self.table} (doc_id, text, metadata, embedding, timestamp) "
                "VALUES ($1, $2, $3::jsonb, $4::vector, $5::timestamptz) "
                "ON CONFLICT (doc_id) DO UPDATE SET "
                "text = EXCLUDED.text, metadata = EXCLUDED.metadata, "
                "embedding = EXCLUDED.embedding, timestamp = EXCLUDED.timestamp",
                rows,
            )

    async def query(self, vector: list[float], top_k: int, where: Filter | None) -> list[VectorHit]:
        if not self.is_available:
            return []
        clause, params = build_pg_where(where, start_index=3)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT doc_id, text, metadata::text AS metadata, "
                f"embedding <=> $1::vector AS distance "
                f"FROM {self.table} WHERE embedding IS NOT NULL{clause} "
                f"ORDER BY embedding <=> $1::vector LIMIT $2",
                _vector_literal(vector),
                top_k,
                *params,
            )
        return [
            VectorHit(
                doc_id=r["doc_id"],
                text=r["text"],
                metadata=json.loads(r["metadata"]),
                distance=float(r["distance"]),
            )
            for r in rows
        ]

    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        if not self.is_available:
            return False
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                f"UPDATE {self.table} SET metadata = $1::jsonb WHERE doc_id = $2",
                json.dumps(metadata, ensure_ascii=False),
                doc_id,
            )
        return _rowcount(status) > 0

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        if not self.is_available:
            return {}
        clause, params = build_pg_where(where, start_index=1)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT doc_id, metadata FROM {self.table} WHERE TRUE{clause}", *params
            )
        return {row["doc_id"]: json.loads(row["metadata"]) for row in rows}

    async def delete_older_than(self, cutoff_iso: str) -> int:
        if not self.is_available:
            return 0
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                f"DELETE FROM {self.table} WHERE timestamp IS NOT NULL "
                "AND timestamp < $1::timestamptz",
                cutoff_iso,
            )
        return _rowcount(status)

    async def delete_where(self, where: Filter | None) -> int:
        if not self.is_available:
            return 0
        clause, params = build_pg_where(where, start_index=1)
        async with self._pool.acquire() as conn:
            status = await conn.execute(f"DELETE FROM {self.table} WHERE TRUE{clause}", *params)
        return _rowcount(status)

    async def _discard_pool(self) -> None:
        """Close and drop the pool, tolerating a pool that is already broken.

        `initialize` must not leave a pool behind when it fails: reload_tools
        re-runs it, so every reload against an unreachable or unprivileged
        database would otherwise strand another set of live connections.
        """
        pool, self._pool = self._pool, None
        if pool is None:
            return
        try:
            await pool.close()
        except Exception:  # noqa: BLE001 — teardown must not mask the real cause
            LOGGER.debug("pgvector pool close failed during cleanup")

    async def close(self) -> None:
        self.is_available = False
        await self._discard_pool()


def _vector_literal(vector: list[float]) -> str:
    """pgvector accepts its text form: '[1,2,3]'."""
    return "[" + ",".join(str(float(v)) for v in vector) + "]"


def _rowcount(status: Any) -> int:
    """asyncpg returns a command tag like 'DELETE 3'."""
    try:
        return int(str(status).rsplit(" ", 1)[-1])
    except (ValueError, AttributeError):
        return 0
