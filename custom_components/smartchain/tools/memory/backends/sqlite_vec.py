"""Vector backend using the sqlite-vec extension for native KNN.

Optional. `sqlite-vec` loads as a SQLite extension, which requires a Python
build with `enable_load_extension` compiled in — not universally true. Both
failure modes raise BackendInitError naming sqlite_numpy as the drop-in
replacement.
"""

import json
import logging
import sqlite3
from contextlib import closing
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


class _FilteredKnnUnsupported(Exception):
    """Raised inside the executor job; translated into BackendInitError by initialize."""


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into an open connection.

    Split out so tests can patch it to simulate both failure modes.
    """
    import sqlite_vec  # noqa: PLC0415

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def _probe_filtered_knn(conn: sqlite3.Connection) -> bool:
    """Check that `rowid IN (...)` narrows a vec0 KNN *before* its `k` cut.

    `_query_filtered` is only correct if the extension and the query planner
    push that constraint into the vec0 scan. Older sqlite-vec builds do not,
    and a build that quietly stops pushing it down does not raise — it just
    starts losing matches again, which is the defect this backend was fixed
    for. So prove the property instead of assuming it: two rows in a throwaway
    in-memory database, the wanted one deliberately the *further* of the pair.
    A backend filtering after the cut asks for k=1, gets the near row, drops it
    on the metadata condition and returns nothing.
    """
    conn.execute("CREATE TABLE p (rid INTEGER, kind TEXT)")
    conn.execute("CREATE VIRTUAL TABLE pv USING vec0(embedding float[2] distance_metric=cosine)")
    for vector, kind in (([1.0, 0.0], "near"), ([0.0, 1.0], "wanted")):
        cur = conn.execute("INSERT INTO pv (embedding) VALUES (?)", (json.dumps(vector),))
        conn.execute("INSERT INTO p VALUES (?, ?)", (cur.lastrowid, kind))

    rows = conn.execute(
        "SELECT p.kind FROM pv v JOIN p ON p.rid = v.rowid "
        "WHERE v.embedding MATCH ? AND k = 1 "
        "AND v.rowid IN (SELECT rid FROM p WHERE kind = 'wanted')",
        (json.dumps([1.0, 0.0]),),
    ).fetchall()
    return [r["kind"] for r in rows] == ["wanted"]


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
            # Probe on a throwaway in-memory database, never the user's store:
            # the check has to insert rows, and it must not leave any behind.
            with closing(sqlite3.connect(":memory:")) as probe:
                probe.row_factory = sqlite3.Row
                _load_sqlite_vec(probe)
                if not _probe_filtered_knn(probe):
                    raise _FilteredKnnUnsupported

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn, conn:
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
                    f"USING vec0(embedding float[{dim}] distance_metric=cosine)"
                )
                row = conn.execute("SELECT value FROM _meta WHERE key = 'dim'").fetchone()
                if row is None:
                    conn.execute("INSERT INTO _meta (key, value) VALUES ('dim', ?)", (str(dim),))
                    return None
                return str(row["value"])

        try:
            stored = await self.hass.async_add_executor_job(_run)
        except _FilteredKnnUnsupported as err:
            self.is_available = False
            raise BackendInitError(
                "this sqlite-vec build does not narrow a KNN search by rowid before "
                "applying its k limit, so filtered searches would silently lose "
                f"matches. Upgrade sqlite-vec, or switch the store's backend type to "
                f"sqlite_numpy, which needs no extension. Store: {self.db_path}"
            ) from err
        except (ImportError, AttributeError) as err:
            self.is_available = False
            raise BackendInitError(f"{_GUIDANCE} Cause: {err}") from err
        except sqlite3.Error as err:
            self.is_available = False
            raise BackendInitError(f"sqlite_vec could not open {self.db_path}: {err}") from err

        if stored is not None and int(stored) != dim:
            self.is_available = False
            # Clearing the store cannot fix this: the recorded dimension and
            # the vec0 table survive a delete, and a store with a dimension
            # conflict never becomes available for smartchain.clear_memory to
            # act on. Only removing the file does it.
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

        def _run() -> None:
            with closing(self._connect()) as conn, conn:
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
        if clause:
            return await self._query_filtered(vector, top_k, clause, params)

        def _run() -> list[Any]:
            with closing(self._connect()) as conn:
                return conn.execute(
                    "SELECT d.doc_id, d.text, d.metadata, v.distance "
                    "FROM vec_docs v "
                    "JOIN docs d ON d.rowid_ref = v.rowid "
                    "WHERE v.embedding MATCH ? AND k = ? "
                    "ORDER BY v.distance LIMIT ?",
                    [json.dumps(vector), top_k, top_k],
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

    async def _query_filtered(
        self, vector: list[float], top_k: int, clause: str, params: list[Any]
    ) -> list[VectorHit]:
        """Narrow the candidate rowids *before* vec0 picks its `k` neighbours.

        vec0 honours `k` inside the virtual table, before any condition on the
        joined `docs` row can run, so a metadata condition in the outer query
        can only narrow the page vec0 already chose — never widen it. Every
        match ranked below `k` non-matches was silently lost, and a filtered
        search returned nothing at all when the nearest rows all belonged to
        another kind. Over-fetching a fixed window (this backend used to fetch
        200) moved that cliff instead of removing it, and left `sqlite_vec`
        answering differently from its three siblings on identical data — the
        divergence the VectorBackend Protocol exists to forbid.

        `rowid IN (<subquery>)` is the constraint vec0 *does* accept and push
        down into its own scan, so the KNN runs over exactly the rows the
        filter keeps. There is no window left to fall out of, and it is also
        cheaper than the over-fetch it replaces: vec0 stops computing distances
        for rows that were going to be discarded. Measured on 50 000 rows of
        1536 dimensions, half of them matching, a filtered search went from
        ~1.7 s to ~0.15 s.
        """

        def _run() -> list[Any]:
            with closing(self._connect()) as conn:
                return conn.execute(
                    "SELECT d.doc_id, d.text, d.metadata, v.distance "
                    "FROM vec_docs v "
                    "JOIN docs d ON d.rowid_ref = v.rowid "
                    "WHERE v.embedding MATCH ? AND k = ? AND v.rowid IN "
                    f"(SELECT rowid_ref FROM docs WHERE 1=1{clause}) "
                    "ORDER BY v.distance LIMIT ?",
                    [json.dumps(vector), top_k, *params, top_k],
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
            with closing(self._connect()) as conn, conn:
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
