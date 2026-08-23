"""Default vector backend: stdlib sqlite3 for storage, numpy for cosine search.

Requires no dependency beyond what Home Assistant already ships, which makes
it the one backend guaranteed to work on every installation.
"""

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
from homeassistant.core import HomeAssistant

from ....const import MEMORY_SQLITE_SOFT_LIMIT
from .base import BackendInitError, Filter, VectorHit, VectorRecord

LOGGER = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    doc_id    TEXT PRIMARY KEY,
    text      TEXT NOT NULL,
    metadata  TEXT NOT NULL,
    embedding BLOB NOT NULL,
    timestamp TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_timestamp ON docs(timestamp);
"""


def build_where_clause(where: Filter | None) -> tuple[str, list[Any]]:
    """Translate the neutral filter into a SQL WHERE fragment.

    Returns ("", []) when there is nothing to filter on, otherwise
    (" AND json_extract(metadata, '$.k') = ?", [value, ...]).
    """
    if not where:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    for key, value in where.items():
        clauses.append(f"json_extract(metadata, '$.{key}') = ?")
        params.append(value)
    return " AND " + " AND ".join(clauses), params


class SqliteNumpyBackend:
    """Vectors as float32 BLOBs in SQLite; similarity computed with numpy."""

    name = "sqlite_numpy"

    def __init__(self, hass: HomeAssistant, db_path: Path) -> None:
        self.hass = hass
        self.db_path = db_path
        self.is_available = False
        self._dim: int | None = None
        self._warned_soft_limit = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(self, dim: int) -> None:
        def _run() -> str | None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn, conn:
                conn.executescript(_SCHEMA)
                row = conn.execute("SELECT value FROM _meta WHERE key = 'dim'").fetchone()
                if row is None:
                    conn.execute("INSERT INTO _meta (key, value) VALUES ('dim', ?)", (str(dim),))
                    return None
                return str(row["value"])

        try:
            stored = await self.hass.async_add_executor_job(_run)
        except sqlite3.Error as err:
            self.is_available = False
            raise BackendInitError(f"sqlite_numpy could not open {self.db_path}: {err}") from err

        if stored is not None and int(stored) != dim:
            self.is_available = False
            # Clearing the store cannot fix this: the recorded dimension
            # outlives a delete, and a store with a dimension conflict never
            # becomes available for smartchain.clear_memory to act on. Only
            # removing the file does it.
            raise BackendInitError(
                f"stored embedding dimension is {stored} but the configured model "
                f"produces {dim}. Delete the database file {self.db_path}, then "
                "call smartchain.reload_tools."
            )

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
                np.asarray(r.vector, dtype=np.float32).tobytes(),
                str(r.metadata.get("timestamp", "")),
            )
            for r in records
        ]

        def _run() -> int:
            with closing(self._connect()) as conn, conn:
                conn.executemany(
                    "INSERT INTO docs (doc_id, text, metadata, embedding, timestamp) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(doc_id) DO UPDATE SET "
                    "text=excluded.text, metadata=excluded.metadata, "
                    "embedding=excluded.embedding, timestamp=excluded.timestamp",
                    rows,
                )
                return int(conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0])

        total = await self.hass.async_add_executor_job(_run)
        if total > MEMORY_SQLITE_SOFT_LIMIT and not self._warned_soft_limit:
            self._warned_soft_limit = True
            LOGGER.warning(
                "SmartChain memory store at %s holds %d records, above the "
                "recommended %d for the sqlite_numpy backend. Consider switching "
                "to pgvector or qdrant.",
                self.db_path,
                total,
                MEMORY_SQLITE_SOFT_LIMIT,
            )

    async def query(self, vector: list[float], top_k: int, where: Filter | None) -> list[VectorHit]:
        if not self.is_available:
            return []
        clause, params = build_where_clause(where)

        def _run() -> list[sqlite3.Row]:
            with closing(self._connect()) as conn, conn:
                return conn.execute(
                    f"SELECT doc_id, text, metadata, embedding FROM docs WHERE 1=1{clause}",
                    params,
                ).fetchall()

        rows = await self.hass.async_add_executor_job(_run)
        if not rows:
            return []

        matrix = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        q = np.asarray(vector, dtype=np.float32)

        # Cosine similarity as a normalised dot product. eps guards the
        # degenerate all-zero vector rather than emitting a RuntimeWarning.
        eps = 1e-12
        norms = np.linalg.norm(matrix, axis=1) * float(np.linalg.norm(q))
        sims = (matrix @ q) / np.maximum(norms, eps)

        k = min(top_k, len(rows))
        top_idx = np.argpartition(-sims, k - 1)[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        return [
            VectorHit(
                doc_id=rows[i]["doc_id"],
                text=rows[i]["text"],
                metadata=json.loads(rows[i]["metadata"]),
                distance=float(1.0 - sims[i]),
            )
            for i in top_idx
        ]

    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        if not self.is_available:
            return False

        def _run() -> bool:
            with closing(self._connect()) as conn, conn:
                cur = conn.execute(
                    "UPDATE docs SET metadata = ? WHERE doc_id = ?",
                    (json.dumps(metadata, ensure_ascii=False), doc_id),
                )
                return cur.rowcount > 0

        return await self.hass.async_add_executor_job(_run)

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        if not self.is_available:
            return {}
        clause, params = build_where_clause(where)

        def _run() -> dict[str, dict[str, Any]]:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    f"SELECT doc_id, metadata FROM docs WHERE 1=1{clause}", params
                ).fetchall()
            return {row["doc_id"]: json.loads(row["metadata"]) for row in rows}

        return await self.hass.async_add_executor_job(_run)

    async def delete_older_than(self, cutoff_iso: str) -> int:
        if not self.is_available:
            return 0

        def _run() -> int:
            with closing(self._connect()) as conn, conn:
                cur = conn.execute(
                    "DELETE FROM docs WHERE timestamp != '' AND timestamp < ?",
                    (cutoff_iso,),
                )
                return cur.rowcount

        return await self.hass.async_add_executor_job(_run)

    async def delete_where(self, where: Filter | None) -> int:
        if not self.is_available:
            return 0
        clause, params = build_where_clause(where)

        def _run() -> int:
            with closing(self._connect()) as conn, conn:
                cur = conn.execute(f"DELETE FROM docs WHERE 1=1{clause}", params)
                return cur.rowcount

        return await self.hass.async_add_executor_job(_run)

    async def close(self) -> None:
        # Connections are opened per operation and closed by contextlib.closing,
        # so there is nothing long-lived to release.
        self.is_available = False
