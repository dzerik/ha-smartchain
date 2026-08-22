"""Vector backend using the sqlite-vec extension for native KNN.

Optional. `sqlite-vec` loads as a SQLite extension, which requires a Python
build with `enable_load_extension` compiled in — not universally true. Both
failure modes raise BackendInitError naming sqlite_numpy as the drop-in
replacement.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .base import BackendInitError, Filter, VectorHit, VectorRecord
from .sqlite_numpy import build_where_clause

LOGGER = logging.getLogger(__name__)

_GUIDANCE = (
    "The sqlite_vec backend is unavailable on this installation. Switch the "
    "store's backend type to sqlite_numpy, which needs no extension."
)


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into an open connection.

    Split out so tests can patch it to simulate both failure modes.
    """
    import sqlite_vec  # noqa: PLC0415

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


class SqliteVecBackend:
    """Same file layout as sqlite_numpy but with a vec0 virtual table."""

    name = "sqlite_vec"

    def __init__(self, hass: HomeAssistant, db_path: Path) -> None:
        self.hass = hass
        self.db_path = db_path
        self.is_available = False
        self._dim: int | None = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        _load_sqlite_vec(conn)
        return conn

    async def initialize(self, dim: int) -> None:
        def _run() -> str | None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS docs ("
                    "doc_id TEXT PRIMARY KEY, text TEXT NOT NULL, "
                    "metadata TEXT NOT NULL, timestamp TEXT NOT NULL DEFAULT '', "
                    "rowid_ref INTEGER)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_docs "
                    f"USING vec0(embedding float[{dim}])"
                )
                row = conn.execute("SELECT value FROM _meta WHERE key = 'dim'").fetchone()
                if row is None:
                    conn.execute("INSERT INTO _meta (key, value) VALUES ('dim', ?)", (str(dim),))
                    return None
                return str(row["value"])

        try:
            stored = await self.hass.async_add_executor_job(_run)
        except (ImportError, AttributeError) as err:
            self.is_available = False
            raise BackendInitError(f"{_GUIDANCE} Cause: {err}") from err
        except sqlite3.Error as err:
            self.is_available = False
            raise BackendInitError(f"sqlite_vec could not open {self.db_path}: {err}") from err

        if stored is not None and int(stored) != dim:
            self.is_available = False
            raise BackendInitError(
                f"stored embedding dimension is {stored} but the configured model "
                f"produces {dim}. Clear this store with smartchain.clear_memory, "
                "then call smartchain.reload_tools."
            )

        self._dim = dim
        self.is_available = True

    async def upsert(self, records: list[VectorRecord]) -> None:
        if not self.is_available or not records:
            return

        def _run() -> None:
            with self._connect() as conn:
                for rec in records:
                    existing = conn.execute(
                        "SELECT rowid_ref FROM docs WHERE doc_id = ?", (rec.doc_id,)
                    ).fetchone()
                    if existing is not None and existing["rowid_ref"] is not None:
                        conn.execute(
                            "DELETE FROM vec_docs WHERE rowid = ?", (existing["rowid_ref"],)
                        )
                    cur = conn.execute(
                        "INSERT INTO vec_docs (embedding) VALUES (?)",
                        (json.dumps(rec.vector),),
                    )
                    conn.execute(
                        "INSERT INTO docs (doc_id, text, metadata, timestamp, rowid_ref) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(doc_id) DO UPDATE SET text=excluded.text, "
                        "metadata=excluded.metadata, timestamp=excluded.timestamp, "
                        "rowid_ref=excluded.rowid_ref",
                        (
                            rec.doc_id,
                            rec.text,
                            json.dumps(rec.metadata, ensure_ascii=False),
                            str(rec.metadata.get("timestamp", "")),
                            cur.lastrowid,
                        ),
                    )

        await self.hass.async_add_executor_job(_run)

    async def query(self, vector: list[float], top_k: int, where: Filter | None) -> list[VectorHit]:
        if not self.is_available:
            return []
        clause, params = build_where_clause(where)

        def _run() -> list[Any]:
            with self._connect() as conn:
                return conn.execute(
                    "SELECT d.doc_id, d.text, d.metadata, v.distance "
                    "FROM vec_docs v "
                    "JOIN docs d ON d.rowid_ref = v.rowid "
                    "WHERE v.embedding MATCH ? AND k = ?" + clause + " "
                    "ORDER BY v.distance",
                    [json.dumps(vector), top_k, *params],
                ).fetchall()

        rows = await self.hass.async_add_executor_job(_run)
        return [
            VectorHit(
                doc_id=r["doc_id"],
                text=r["text"],
                metadata=json.loads(r["metadata"]),
                distance=float(r["distance"]),
            )
            for r in rows
        ]

    async def delete_older_than(self, cutoff_iso: str) -> int:
        if not self.is_available:
            return 0

        def _run() -> int:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT rowid_ref FROM docs WHERE timestamp != '' AND timestamp < ?",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    if row["rowid_ref"] is not None:
                        conn.execute("DELETE FROM vec_docs WHERE rowid = ?", (row["rowid_ref"],))
                cur = conn.execute(
                    "DELETE FROM docs WHERE timestamp != '' AND timestamp < ?", (cutoff_iso,)
                )
                return cur.rowcount

        return await self.hass.async_add_executor_job(_run)

    async def delete_where(self, where: Filter | None) -> int:
        if not self.is_available:
            return 0
        clause, params = build_where_clause(where)

        def _run() -> int:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT rowid_ref FROM docs WHERE 1=1{clause}", params
                ).fetchall()
                for row in rows:
                    if row["rowid_ref"] is not None:
                        conn.execute("DELETE FROM vec_docs WHERE rowid = ?", (row["rowid_ref"],))
                cur = conn.execute(f"DELETE FROM docs WHERE 1=1{clause}", params)
                return cur.rowcount

        return await self.hass.async_add_executor_job(_run)

    async def close(self) -> None:
        self.is_available = False
