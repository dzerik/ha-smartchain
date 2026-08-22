# Vector Backends + Embedding Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded Chroma store with four pluggable vector backends (default requiring no new dependency), turn embeddings into a provider capability expressed as a subentry type, and support multiple named memory stores each binding one embeddings subentry to one backend.

**Architecture:** Three sequential phases. Phase 1 introduces a `VectorBackend` Protocol with four implementations behind it, entirely inside `tools/memory/backends/`; `MemoryStore` keeps embeddings, chunking and the dimension probe and delegates raw vector operations. Phase 2 adds a `PROVIDER_CAPABILITIES` matrix, purpose-filtered model discovery and an `EmbeddingsSubentryFlow`, without any consumer yet. Phase 3 replaces the flat `memory:` block with `memory.stores[]`, introduces `MemoryRegistry`, and threads a `store` parameter through the tool and the service.

**Tech Stack:** Python 3.13, Home Assistant 2024.12+, stdlib `sqlite3`, numpy (already in HA), optional `sqlite-vec` / `asyncpg`, Qdrant REST over HA's shared aiohttp session.

**Spec:** [`docs/superpowers/specs/2026-08-23-vector-backends-and-embedding-providers-design.md`](../specs/2026-08-23-vector-backends-and-embedding-providers-design.md)

## Global Constraints

- `requires-python >= 3.13`; HA 2024.12.0+.
- **No new required dependency.** `sqlite-vec` and `asyncpg` are lazy-imported inside their backend's `initialize()` and must never appear in `manifest.json`. This is the lesson of v4.4.1, where `chromadb` in the manifest blocked the whole integration from loading.
- `chromadb` and `langchain-chroma` are removed from `manifest.json` and `pyproject.toml` and must not be imported anywhere.
- Credentials (`dsn`, `api_key`) never appear in strings returned to the LLM or in service-response errors — the v4.0.2 security boundary. Full detail goes to `LOGGER.exception` only.
- Every blocking call is wrapped in `hass.async_add_executor_job`; every backend operation is bounded by `MEMORY_BACKEND_TIMEOUT_SECONDS = 30`.
- Initialization failure disables a store (`is_available = False`); a runtime failure logs, returns empty, and leaves the store available.
- ruff: `line-length = 100`, `select = ["E", "F", "W", "I", "UP"]`.
- Test runner: `uv run --prerelease=allow pytest tests/ -q`
- Lint: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`

---

## File map

### New files

| Path | Responsibility |
|---|---|
| `custom_components/smartchain/tools/memory/backends/__init__.py` | Re-exports + `create_backend()` factory |
| `custom_components/smartchain/tools/memory/backends/base.py` | `VectorBackend` Protocol, `VectorRecord`, `VectorHit`, `Filter` |
| `custom_components/smartchain/tools/memory/backends/sqlite_numpy.py` | Default backend — stdlib `sqlite3` + numpy cosine |
| `custom_components/smartchain/tools/memory/backends/sqlite_vec.py` | `sqlite-vec` extension backend |
| `custom_components/smartchain/tools/memory/backends/pgvector.py` | PostgreSQL + pgvector via `asyncpg` |
| `custom_components/smartchain/tools/memory/backends/qdrant.py` | Qdrant REST over HA's aiohttp session |
| `custom_components/smartchain/tools/memory/registry.py` | `MemoryRegistry` — `name -> MemoryStore` map and per-store tasks |

### Modified files

| Path | Change |
|---|---|
| `tools/memory/store.py` | Chroma removed; delegates to a `VectorBackend`; owns the dimension probe |
| `tools/memory/config.py` | `MemoryConfig` → `BackendConfig` + `StoreConfig` + `MemorySettings` |
| `tools/memory/embeddings.py` | Built from (entry, subentry) instead of YAML credentials |
| `tools/memory/search_tool.py` | `store` parameter; flat filter; per-store descriptions |
| `tools/memory/ingest.py` | Conversation ingest fans out across stores |
| `tools/memory/retention.py` | One task per store |
| `tools/schema.py` | `memory.backend:` (phase 1) then `memory.stores[]` (phase 3) |
| `tools/loader.py` | Parses the new shapes |
| `config_flow.py` | `EmbeddingsSubentryFlow`; capability-filtered subentry types |
| `client_util.py` | `PROVIDER_CAPABILITIES`; `supports()`; `purpose` filter; `is_embedding_model()` |
| `__init__.py` | `_build_memory` → registry; `clear_memory` gains `store` |
| `const.py` | New constants |
| `manifest.json`, `pyproject.toml` | Chroma removed; version bump in the final task |

### Test files

`test_memory_backend_conformance.py`, `test_memory_backend_sqlite_numpy.py`, `test_memory_backend_sqlite_vec.py`, `test_memory_backend_pgvector.py`, `test_memory_backend_qdrant.py`, `test_memory_dimension_probe.py`, `test_memory_filter_translation.py`, `test_provider_capabilities.py`, `test_embeddings_model_discovery.py`, `test_embeddings_subentry_flow.py`, `test_memory_registry.py`, `test_memory_multi_store.py` — plus updates to the existing memory tests.

---

## Phase boundaries

**Phase 1 (Tasks 1–8)** is self-contained. At its end `main` is green and shippable: memory works out of the box on `sqlite_numpy`, and all four backends are selectable through a new optional `memory.backend:` sub-block inside the *existing* flat `memory:` block. This sub-block is an intentional intermediate step — Phase 3 moves it under each entry of `memory.stores[]`.

**Phase 2 (Tasks 9–12)** adds the embeddings capability with no consumer. `main` stays green; nothing user-visible changes except that a new subentry type appears for providers that support it.

**Phase 3 (Tasks 13–18)** rewrites the config plumbing exactly once and carries the BREAKING change plus the version bump.

---

# Phase 1 — Vector backends

### Task 1: Protocol, shared types and constants

**Files:**
- Create: `custom_components/smartchain/tools/memory/backends/__init__.py`
- Create: `custom_components/smartchain/tools/memory/backends/base.py`
- Modify: `custom_components/smartchain/const.py`
- Test: `tests/test_memory_backend_base.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `VectorRecord(doc_id: str, vector: list[float], text: str, metadata: dict)`, `VectorHit(doc_id: str, text: str, metadata: dict, distance: float)`, `Filter = dict[str, str | int | float | bool]`, `VectorBackend` Protocol, `BackendInitError`. Every later backend task implements this Protocol.

- [ ] **Step 1: Add constants**

Append to `custom_components/smartchain/const.py`:

```python

# Vector backends (v4.5.0)
MEMORY_BACKEND_TYPES = ["sqlite_numpy", "sqlite_vec", "pgvector", "qdrant"]
MEMORY_DEFAULT_BACKEND = "sqlite_numpy"
MEMORY_BACKEND_TIMEOUT_SECONDS = 30
MEMORY_DIM_PROBE_TEXT = "smartchain dimension probe"
MEMORY_SQLITE_SOFT_LIMIT = 50_000
MEMORY_DEFAULT_QDRANT_COLLECTION = "smartchain_memory"
MEMORY_DEFAULT_PG_TABLE = "smartchain_memory"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_memory_backend_base.py`:

```python
"""Tests for the VectorBackend shared types."""

import pytest

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorHit,
    VectorRecord,
)


def test_vector_record_fields() -> None:
    rec = VectorRecord(
        doc_id="d1",
        vector=[0.1, 0.2],
        text="hello",
        metadata={"kind": "conversation"},
    )
    assert rec.doc_id == "d1"
    assert rec.vector == [0.1, 0.2]
    assert rec.text == "hello"
    assert rec.metadata["kind"] == "conversation"


def test_vector_hit_fields() -> None:
    hit = VectorHit(doc_id="d1", text="hello", metadata={"kind": "logbook"}, distance=0.25)
    assert hit.doc_id == "d1"
    assert hit.distance == 0.25
    assert hit.metadata["kind"] == "logbook"


def test_records_are_frozen() -> None:
    rec = VectorRecord(doc_id="d1", vector=[0.0], text="t", metadata={})
    with pytest.raises(AttributeError):
        rec.doc_id = "other"  # type: ignore[misc]


def test_backend_init_error_is_exception() -> None:
    assert issubclass(BackendInitError, Exception)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.smartchain.tools.memory.backends'`.

- [ ] **Step 4: Implement `base.py`**

Create `custom_components/smartchain/tools/memory/backends/base.py`:

```python
"""Shared types and the VectorBackend Protocol."""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# A conjunction of equality conditions over metadata keys. This is the
# backend-neutral filter dialect: every backend translates it into its own
# query language. It covers every filter SmartChain builds (kind,
# subentry_id, agent_id).
type Filter = dict[str, str | int | float | bool]


class BackendInitError(Exception):
    """Raised when a backend cannot be initialised.

    Callers treat this as fatal for the store: `is_available` goes False and
    every operation becomes a no-op. Runtime errors are NOT this exception —
    they are logged and the store stays available.
    """


@dataclass(frozen=True)
class VectorRecord:
    """One row to write into a backend."""

    doc_id: str
    vector: list[float]
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorHit:
    """One search result. `distance` is cosine distance — lower is closer."""

    doc_id: str
    text: str
    metadata: dict[str, Any]
    distance: float


@runtime_checkable
class VectorBackend(Protocol):
    """Raw vector storage. Embedding and chunking live in MemoryStore."""

    name: str
    is_available: bool

    async def initialize(self, dim: int) -> None:
        """Create structures for `dim`-dimensional vectors.

        Raises BackendInitError when the backend cannot be used at all, or
        when `dim` conflicts with a previously stored dimension.
        """
        ...

    async def upsert(self, records: list[VectorRecord]) -> None: ...

    async def query(
        self, vector: list[float], top_k: int, where: Filter | None
    ) -> list[VectorHit]: ...

    async def delete_older_than(self, cutoff_iso: str) -> int: ...

    async def delete_where(self, where: Filter | None) -> int: ...

    async def close(self) -> None: ...
```

- [ ] **Step 5: Implement the package marker**

Create `custom_components/smartchain/tools/memory/backends/__init__.py`:

```python
"""Pluggable vector storage backends for the SmartChain memory subsystem."""

from .base import BackendInitError, Filter, VectorBackend, VectorHit, VectorRecord

__all__ = [
    "BackendInitError",
    "Filter",
    "VectorBackend",
    "VectorHit",
    "VectorRecord",
]
```

The `create_backend()` factory is added in Task 6, once all four implementations exist.

- [ ] **Step 6: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_base.py -v`
Expected: 4 passed.

- [ ] **Step 7: Lint and commit**

```bash
uv run --prerelease=allow ruff check custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_base.py
uv run --prerelease=allow ruff format custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_base.py
git add custom_components/smartchain/tools/memory/backends/ custom_components/smartchain/const.py tests/test_memory_backend_base.py
git commit -m "feat(memory): VectorBackend Protocol and shared types"
```

---

### Task 2: `sqlite_numpy` backend — the zero-dependency default

**Files:**
- Create: `custom_components/smartchain/tools/memory/backends/sqlite_numpy.py`
- Test: `tests/test_memory_backend_sqlite_numpy.py`

**Interfaces:**
- Consumes: `VectorRecord`, `VectorHit`, `Filter`, `BackendInitError` from `backends.base`.
- Produces: `SqliteNumpyBackend(hass: HomeAssistant, db_path: Path)`. Task 6 registers it in the factory under the key `"sqlite_numpy"`; Task 7 makes it the store's default.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_backend_sqlite_numpy.py`:

```python
"""Tests for the stdlib-sqlite + numpy vector backend."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorRecord,
)
from custom_components.smartchain.tools.memory.backends.sqlite_numpy import (
    SqliteNumpyBackend,
)


@pytest.fixture
async def backend(hass: HomeAssistant, tmp_path):
    be = SqliteNumpyBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    yield be
    await be.close()


def _rec(doc_id: str, vector: list[float], kind: str = "conversation", ts: str = "2026-01-01T00:00:00+00:00"):
    return VectorRecord(
        doc_id=doc_id,
        vector=vector,
        text=f"text-{doc_id}",
        metadata={"kind": kind, "timestamp": ts},
    )


async def test_initialize_creates_db(hass: HomeAssistant, tmp_path) -> None:
    be = SqliteNumpyBackend(hass, tmp_path / "sub" / "memory.db")
    await be.initialize(4)
    assert be.is_available is True
    assert (tmp_path / "sub" / "memory.db").exists()
    await be.close()


async def test_upsert_then_query_returns_nearest_first(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0]),
            _rec("b", [0.0, 1.0, 0.0]),
            _rec("c", [0.9, 0.1, 0.0]),
        ]
    )
    hits = await backend.query([1.0, 0.0, 0.0], top_k=2, where=None)
    assert [h.doc_id for h in hits] == ["a", "c"]
    assert hits[0].distance < hits[1].distance
    assert hits[0].text == "text-a"


async def test_query_applies_metadata_filter(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0], kind="conversation"),
            _rec("b", [1.0, 0.0, 0.0], kind="logbook"),
        ]
    )
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where={"kind": "logbook"})
    assert [h.doc_id for h in hits] == ["b"]


async def test_upsert_is_idempotent_on_doc_id(backend) -> None:
    await backend.upsert([_rec("a", [1.0, 0.0, 0.0])])
    await backend.upsert([_rec("a", [0.0, 1.0, 0.0])])
    hits = await backend.query([0.0, 1.0, 0.0], top_k=5, where=None)
    assert len(hits) == 1
    assert hits[0].doc_id == "a"


async def test_delete_older_than(backend) -> None:
    await backend.upsert(
        [
            _rec("old", [1.0, 0.0, 0.0], ts="2026-01-01T00:00:00+00:00"),
            _rec("new", [1.0, 0.0, 0.0], ts="2026-06-01T00:00:00+00:00"),
        ]
    )
    deleted = await backend.delete_older_than("2026-03-01T00:00:00+00:00")
    assert deleted == 1
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where=None)
    assert [h.doc_id for h in hits] == ["new"]


async def test_delete_where_and_delete_all(backend) -> None:
    await backend.upsert(
        [
            _rec("a", [1.0, 0.0, 0.0], kind="conversation"),
            _rec("b", [1.0, 0.0, 0.0], kind="logbook"),
        ]
    )
    assert await backend.delete_where({"kind": "logbook"}) == 1
    assert await backend.delete_where(None) == 1
    assert await backend.query([1.0, 0.0, 0.0], top_k=5, where=None) == []


async def test_dimension_mismatch_raises(hass: HomeAssistant, tmp_path) -> None:
    path = tmp_path / "memory.db"
    be = SqliteNumpyBackend(hass, path)
    await be.initialize(3)
    await be.close()

    other = SqliteNumpyBackend(hass, path)
    with pytest.raises(BackendInitError, match="768"):
        await other.initialize(768)
    assert other.is_available is False


async def test_query_on_empty_store_returns_empty(backend) -> None:
    assert await backend.query([1.0, 0.0, 0.0], top_k=5, where=None) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_sqlite_numpy.py -v`
Expected: FAIL with `ModuleNotFoundError` for `backends.sqlite_numpy`.

- [ ] **Step 3: Implement `sqlite_numpy.py`**

Create `custom_components/smartchain/tools/memory/backends/sqlite_numpy.py`:

```python
"""Default vector backend: stdlib sqlite3 for storage, numpy for cosine search.

Requires no dependency beyond what Home Assistant already ships, which makes
it the one backend guaranteed to work on every installation.
"""

import json
import logging
import sqlite3
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
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
                row = conn.execute("SELECT value FROM _meta WHERE key = 'dim'").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO _meta (key, value) VALUES ('dim', ?)", (str(dim),)
                    )
                    return None
                return str(row["value"])

        try:
            stored = await self.hass.async_add_executor_job(_run)
        except sqlite3.Error as err:
            self.is_available = False
            raise BackendInitError(f"sqlite_numpy could not open {self.db_path}: {err}") from err

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
            with self._connect() as conn:
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

    async def query(
        self, vector: list[float], top_k: int, where: Filter | None
    ) -> list[VectorHit]:
        if not self.is_available:
            return []
        clause, params = build_where_clause(where)

        def _run() -> list[sqlite3.Row]:
            with self._connect() as conn:
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

    async def delete_older_than(self, cutoff_iso: str) -> int:
        if not self.is_available:
            return 0

        def _run() -> int:
            with self._connect() as conn:
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
            with self._connect() as conn:
                cur = conn.execute(f"DELETE FROM docs WHERE 1=1{clause}", params)
                return cur.rowcount

        return await self.hass.async_add_executor_job(_run)

    async def close(self) -> None:
        # Connections are opened per operation and closed by the context
        # manager, so there is nothing long-lived to release.
        self.is_available = False
```

- [ ] **Step 4: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_sqlite_numpy.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --prerelease=allow ruff check custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_sqlite_numpy.py
uv run --prerelease=allow ruff format custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_sqlite_numpy.py
git add custom_components/smartchain/tools/memory/backends/sqlite_numpy.py tests/test_memory_backend_sqlite_numpy.py
git commit -m "feat(memory): sqlite_numpy backend — zero-dependency default"
```

---

### Task 3: `sqlite_vec` backend

**Files:**
- Create: `custom_components/smartchain/tools/memory/backends/sqlite_vec.py`
- Test: `tests/test_memory_backend_sqlite_vec.py`

**Interfaces:**
- Consumes: `VectorRecord`, `VectorHit`, `Filter`, `BackendInitError`; `build_where_clause` from `backends.sqlite_numpy` (the SQL dialect is identical).
- Produces: `SqliteVecBackend(hass: HomeAssistant, db_path: Path)`, registered in Task 6 under `"sqlite_vec"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_backend_sqlite_vec.py`:

```python
"""Tests for the sqlite-vec backend, including the extension-missing path."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import BackendInitError
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
```

Create a second test file section for the unavailable path — it must run even when `sqlite-vec` *is* installed, so it lives outside the `importorskip` guard. Append to the same file, above the `importorskip` call is not possible, so instead put this test in `tests/test_memory_backend_sqlite_vec_missing.py`:

```python
"""The sqlite_vec backend must fail loudly and name its replacement."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import BackendInitError
from custom_components.smartchain.tools.memory.backends.sqlite_vec import (
    SqliteVecBackend,
)


async def test_missing_package_raises_with_guidance(hass: HomeAssistant, tmp_path) -> None:
    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    with patch(
        "custom_components.smartchain.tools.memory.backends.sqlite_vec._load_sqlite_vec",
        side_effect=ImportError("no module named sqlite_vec"),
    ):
        with pytest.raises(BackendInitError, match="sqlite_numpy"):
            await be.initialize(3)
    assert be.is_available is False


async def test_extension_loading_disabled_raises_with_guidance(
    hass: HomeAssistant, tmp_path
) -> None:
    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    with patch(
        "custom_components.smartchain.tools.memory.backends.sqlite_vec._load_sqlite_vec",
        side_effect=AttributeError("enable_load_extension"),
    ):
        with pytest.raises(BackendInitError, match="sqlite_numpy"):
            await be.initialize(3)
    assert be.is_available is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_sqlite_vec.py tests/test_memory_backend_sqlite_vec_missing.py -v`
Expected: `ModuleNotFoundError` for `backends.sqlite_vec` (the `importorskip` file skips, the `_missing` file errors).

- [ ] **Step 3: Implement `sqlite_vec.py`**

Create `custom_components/smartchain/tools/memory/backends/sqlite_vec.py`:

```python
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
                    conn.execute(
                        "INSERT INTO _meta (key, value) VALUES ('dim', ?)", (str(dim),)
                    )
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

    async def query(
        self, vector: list[float], top_k: int, where: Filter | None
    ) -> list[VectorHit]:
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
```

- [ ] **Step 4: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_sqlite_vec.py tests/test_memory_backend_sqlite_vec_missing.py -v`
Expected: the `_missing` file passes 2 tests; the main file is skipped with the `importorskip` reason unless `sqlite-vec` happens to be installed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --prerelease=allow ruff check custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_sqlite_vec*.py
uv run --prerelease=allow ruff format custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_sqlite_vec*.py
git add custom_components/smartchain/tools/memory/backends/sqlite_vec.py tests/test_memory_backend_sqlite_vec.py tests/test_memory_backend_sqlite_vec_missing.py
git commit -m "feat(memory): sqlite_vec backend with explicit unavailable path"
```

---

### Task 4: `pgvector` backend

**Files:**
- Create: `custom_components/smartchain/tools/memory/backends/pgvector.py`
- Test: `tests/test_memory_backend_pgvector.py`

**Interfaces:**
- Consumes: `VectorRecord`, `VectorHit`, `Filter`, `BackendInitError`.
- Produces: `PgVectorBackend(hass, dsn: str, table: str)` and module-level `build_pg_where(where, start_index) -> tuple[str, list]`, registered in Task 6 under `"pgvector"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_backend_pgvector.py`. `asyncpg` is not installed in CI, so the module is faked in `sys.modules` and the pool is a mock — this exercises the SQL we generate and the control flow, which is what can actually regress.

```python
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


async def test_initialize_falls_back_when_hnsw_unsupported(
    hass: HomeAssistant, fake_asyncpg, fake_pool
) -> None:
    _pool, conn = fake_pool

    async def _execute(sql: str, *args):
        if "USING hnsw" in sql:
            raise RuntimeError("access method \"hnsw\" does not exist")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_pgvector.py -v`
Expected: FAIL with `ModuleNotFoundError` for `backends.pgvector`.

- [ ] **Step 3: Implement `pgvector.py`**

Create `custom_components/smartchain/tools/memory/backends/pgvector.py`:

```python
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
    caller can reserve $1/$2 for the query vector and limit. Values are cast to
    str because `metadata->>'key'` yields text.
    """
    if not where:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    for offset, (key, value) in enumerate(where.items()):
        clauses.append(f"metadata->>'{key}' = ${start_index + offset}")
        params.append(str(value))
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
        except Exception as err:  # noqa: BLE001 — cause is logged, message is scrubbed
            self.is_available = False
            LOGGER.exception("pgvector could not connect")
            raise BackendInitError(
                "pgvector could not connect to the configured database; see the "
                "Home Assistant log for details."
            ) from err

        try:
            async with self._pool.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

                existing_dim = await conn.fetchval(
                    "SELECT a.atttypmod FROM pg_attribute a "
                    "JOIN pg_class c ON c.oid = a.attrelid "
                    "WHERE c.relname = $1 AND a.attname = 'embedding'",
                    self.table,
                )
                if existing_dim is not None and int(existing_dim) != dim:
                    self.is_available = False
                    raise BackendInitError(
                        f"table {self.table} stores {existing_dim}-dimensional vectors "
                        f"but the configured model produces {dim}. Clear this store "
                        "with smartchain.clear_memory, then call smartchain.reload_tools."
                    )

                await conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {self.table} ("
                    "doc_id text PRIMARY KEY, "
                    "text text NOT NULL, "
                    "metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb, "
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
            raise
        except Exception as err:  # noqa: BLE001
            self.is_available = False
            LOGGER.exception("pgvector schema setup failed")
            raise BackendInitError(
                "pgvector could not create its table or extension. The database "
                "user likely lacks privileges; see the Home Assistant log."
            ) from err

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

    async def query(
        self, vector: list[float], top_k: int, where: Filter | None
    ) -> list[VectorHit]:
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
            status = await conn.execute(
                f"DELETE FROM {self.table} WHERE TRUE{clause}", *params
            )
        return _rowcount(status)

    async def close(self) -> None:
        self.is_available = False
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


def _vector_literal(vector: list[float]) -> str:
    """pgvector accepts its text form: '[1,2,3]'."""
    return "[" + ",".join(str(float(v)) for v in vector) + "]"


def _rowcount(status: Any) -> int:
    """asyncpg returns a command tag like 'DELETE 3'."""
    try:
        return int(str(status).rsplit(" ", 1)[-1])
    except (ValueError, AttributeError):
        return 0
```

- [ ] **Step 4: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_pgvector.py -v`
Expected: 10 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --prerelease=allow ruff check custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_pgvector.py
uv run --prerelease=allow ruff format custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_pgvector.py
git add custom_components/smartchain/tools/memory/backends/pgvector.py tests/test_memory_backend_pgvector.py
git commit -m "feat(memory): pgvector backend with HNSW index and scrubbed errors"
```

---

### Task 5: `qdrant` backend

**Files:**
- Create: `custom_components/smartchain/tools/memory/backends/qdrant.py`
- Test: `tests/test_memory_backend_qdrant.py`

**Interfaces:**
- Consumes: `VectorRecord`, `VectorHit`, `Filter`, `BackendInitError`.
- Produces: `QdrantBackend(hass, url: str, collection: str, api_key: str | None, verify_ssl: bool)` and module-level `build_qdrant_filter(where) -> dict | None`, `point_id_for(doc_id: str) -> str`. Registered in Task 6 under `"qdrant"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_backend_qdrant.py`:

```python
"""Tests for the Qdrant REST backend against a mocked aiohttp session."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorRecord,
)
from custom_components.smartchain.tools.memory.backends.qdrant import (
    QdrantBackend,
    build_qdrant_filter,
    point_id_for,
)


def test_point_id_is_deterministic_uuid() -> None:
    a = point_id_for("logbook_abc123")
    b = point_id_for("logbook_abc123")
    c = point_id_for("logbook_other")
    assert a == b
    assert a != c
    assert len(a) == 36 and a.count("-") == 4


def test_build_qdrant_filter_empty() -> None:
    assert build_qdrant_filter(None) is None
    assert build_qdrant_filter({}) is None


def test_build_qdrant_filter_conditions() -> None:
    flt = build_qdrant_filter({"kind": "logbook", "agent_id": "a1"})
    assert flt == {
        "must": [
            {"key": "kind", "match": {"value": "logbook"}},
            {"key": "agent_id", "match": {"value": "a1"}},
        ]
    }


def _response(status: int = 200, payload: dict | None = None):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload or {})
    resp.text = AsyncMock(return_value="")
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


@pytest.fixture
def session_and_calls():
    """A mocked aiohttp session recording (method, url, json) per request."""
    calls: list[tuple[str, str, dict | None]] = []
    responses: dict[str, object] = {}

    def _request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        for suffix, resp in responses.items():
            if url.endswith(suffix):
                return resp
        return _response(200, {"result": {}})

    session = MagicMock()
    session.request = MagicMock(side_effect=_request)
    return session, calls, responses


async def test_initialize_creates_collection_with_dimension(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["/collections/mem"] = _response(404, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(768)

    assert be.is_available is True
    creates = [c for c in calls if c[0] == "PUT" and c[1].endswith("/collections/mem")]
    assert creates
    assert creates[0][2]["vectors"] == {"size": 768, "distance": "Cosine"}


async def test_initialize_dimension_mismatch_raises(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, _calls, responses = session_and_calls
    responses["/collections/mem"] = _response(
        200, {"result": {"config": {"params": {"vectors": {"size": 768}}}}}
    )

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        with pytest.raises(BackendInitError, match="1536"):
            await be.initialize(1536)
    assert be.is_available is False


async def test_api_key_travels_in_header(hass: HomeAssistant, session_and_calls) -> None:
    session, _calls, responses = session_and_calls
    responses["/collections/mem"] = _response(404, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", "secret-key", True)
        await be.initialize(3)

    headers = session.request.call_args.kwargs["headers"]
    assert headers["api-key"] == "secret-key"


async def test_upsert_maps_doc_id_and_keeps_original_in_payload(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["/collections/mem"] = _response(404, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(3)
        await be.upsert(
            [VectorRecord("logbook_abc", [1.0, 0.0, 0.0], "ta", {"kind": "logbook"})]
        )

    points_calls = [c for c in calls if c[1].endswith("/points") and c[0] == "PUT"]
    assert points_calls
    point = points_calls[0][2]["points"][0]
    assert point["id"] == point_id_for("logbook_abc")
    assert point["payload"]["doc_id"] == "logbook_abc"
    assert point["payload"]["text"] == "ta"


async def test_query_translates_filter_and_maps_score(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["/collections/mem"] = _response(404, {})
    responses["/points/search"] = _response(
        200,
        {
            "result": [
                {
                    "score": 0.75,
                    "payload": {
                        "doc_id": "a",
                        "text": "ta",
                        "metadata": {"kind": "logbook"},
                    },
                }
            ]
        },
    )

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(3)
        hits = await be.query([1.0, 0.0, 0.0], top_k=5, where={"kind": "logbook"})

    assert [h.doc_id for h in hits] == ["a"]
    # Qdrant returns cosine similarity; the Protocol wants distance.
    assert hits[0].distance == pytest.approx(0.25)

    search = [c for c in calls if c[1].endswith("/points/search")][0]
    assert search[2]["filter"] == {"must": [{"key": "kind", "match": {"value": "logbook"}}]}


async def test_unreachable_server_raises_without_leaking_api_key(
    hass: HomeAssistant,
) -> None:
    session = MagicMock()
    session.request = MagicMock(side_effect=OSError("cannot connect to secret-host"))

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://secret-host:6333", "mem", "hunter2", True)
        with pytest.raises(BackendInitError) as exc:
            await be.initialize(3)

    assert "hunter2" not in str(exc.value)
    assert be.is_available is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_qdrant.py -v`
Expected: FAIL with `ModuleNotFoundError` for `backends.qdrant`.

- [ ] **Step 3: Implement `qdrant.py`**

Create `custom_components/smartchain/tools/memory/backends/qdrant.py`:

```python
"""Qdrant backend over its REST API.

Deliberately avoids `qdrant-client`: Home Assistant already ships aiohttp, so
this backend costs no new dependency. Same reasoning as the MCP SSE transport.

Qdrant point IDs must be unsigned integers or UUIDs, while SmartChain document
IDs are strings such as `logbook_<sha1>` or `<uuid>_chunk0`. They are mapped
with uuid5, which is deterministic — so re-upserting the same document ID
overwrites rather than duplicates — and the original is kept in the payload.
"""

import asyncio
import logging
import uuid
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ....const import MEMORY_BACKEND_TIMEOUT_SECONDS
from .base import BackendInitError, Filter, VectorHit, VectorRecord

LOGGER = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL


def point_id_for(doc_id: str) -> str:
    """Map a SmartChain document ID onto a deterministic Qdrant point UUID."""
    return str(uuid.uuid5(_NAMESPACE, doc_id))


def build_qdrant_filter(where: Filter | None) -> dict[str, Any] | None:
    """Translate the neutral filter into Qdrant's filter object."""
    if not where:
        return None
    return {
        "must": [{"key": key, "match": {"value": value}} for key, value in where.items()]
    }


class QdrantBackend:
    """Vectors in a Qdrant collection, addressed over REST."""

    name = "qdrant"

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        collection: str,
        api_key: str | None,
        verify_ssl: bool,
    ) -> None:
        self.hass = hass
        self.url = url.rstrip("/")
        self.collection = collection
        self._api_key = api_key
        self.verify_ssl = verify_ssl
        self.is_available = False
        self._dim: int | None = None

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["api-key"] = self._api_key
        return headers

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        session = async_get_clientsession(self.hass, verify_ssl=self.verify_ssl)
        async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
            async with session.request(
                method,
                f"{self.url}{path}",
                json=payload,
                headers=self._headers,
            ) as resp:
                if resp.status >= 400 and resp.status != 404:
                    body = await resp.text()
                    LOGGER.warning("qdrant %s %s -> %s: %s", method, path, resp.status, body)
                    return resp.status, {}
                if resp.status == 404:
                    return 404, {}
                return resp.status, await resp.json()

    async def initialize(self, dim: int) -> None:
        try:
            status, body = await self._request("GET", f"/collections/{self.collection}")
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            self.is_available = False
            LOGGER.exception("qdrant is unreachable")
            raise BackendInitError(
                "The configured Qdrant server is unreachable; see the Home "
                "Assistant log for details."
            ) from err

        if status == 200:
            existing = (
                body.get("result", {})
                .get("config", {})
                .get("params", {})
                .get("vectors", {})
                .get("size")
            )
            if existing is not None and int(existing) != dim:
                self.is_available = False
                raise BackendInitError(
                    f"collection {self.collection} stores {existing}-dimensional "
                    f"vectors but the configured model produces {dim}. Clear this "
                    "store with smartchain.clear_memory, then call "
                    "smartchain.reload_tools."
                )
        else:
            try:
                await self._request(
                    "PUT",
                    f"/collections/{self.collection}",
                    {"vectors": {"size": dim, "distance": "Cosine"}},
                )
            except (aiohttp.ClientError, OSError, TimeoutError) as err:
                self.is_available = False
                LOGGER.exception("qdrant collection creation failed")
                raise BackendInitError(
                    "Could not create the Qdrant collection; see the Home "
                    "Assistant log for details."
                ) from err

        self._dim = dim
        self.is_available = True

    async def upsert(self, records: list[VectorRecord]) -> None:
        if not self.is_available or not records:
            return
        points = [
            {
                "id": point_id_for(r.doc_id),
                "vector": list(r.vector),
                "payload": {"doc_id": r.doc_id, "text": r.text, "metadata": r.metadata},
            }
            for r in records
        ]
        try:
            await self._request(
                "PUT", f"/collections/{self.collection}/points", {"points": points}
            )
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant upsert failed")

    async def query(
        self, vector: list[float], top_k: int, where: Filter | None
    ) -> list[VectorHit]:
        if not self.is_available:
            return []
        payload: dict[str, Any] = {
            "vector": list(vector),
            "limit": top_k,
            "with_payload": True,
        }
        flt = build_qdrant_filter(where)
        if flt is not None:
            payload["filter"] = flt

        try:
            _status, body = await self._request(
                "POST", f"/collections/{self.collection}/points/search", payload
            )
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant search failed")
            return []

        hits: list[VectorHit] = []
        for item in body.get("result") or []:
            data = item.get("payload") or {}
            hits.append(
                VectorHit(
                    doc_id=data.get("doc_id", ""),
                    text=data.get("text", ""),
                    metadata=data.get("metadata") or {},
                    # Qdrant reports cosine similarity; the Protocol wants distance.
                    distance=1.0 - float(item.get("score", 0.0)),
                )
            )
        return hits

    async def delete_older_than(self, cutoff_iso: str) -> int:
        if not self.is_available:
            return 0
        # Qdrant range matching works on numbers, not ISO strings, so the
        # timestamp filter is applied by scrolling and comparing client-side.
        # Home-scale stores make this acceptable; pgvector is the documented
        # choice when retention volume grows.
        to_delete: list[str] = []
        offset: Any = None
        try:
            while True:
                payload: dict[str, Any] = {"limit": 256, "with_payload": True}
                if offset is not None:
                    payload["offset"] = offset
                _status, body = await self._request(
                    "POST", f"/collections/{self.collection}/points/scroll", payload
                )
                result = body.get("result") or {}
                for point in result.get("points") or []:
                    meta = (point.get("payload") or {}).get("metadata") or {}
                    ts = str(meta.get("timestamp", ""))
                    if ts and ts < cutoff_iso:
                        to_delete.append(point["id"])
                offset = result.get("next_page_offset")
                if offset is None:
                    break

            if to_delete:
                await self._request(
                    "POST",
                    f"/collections/{self.collection}/points/delete",
                    {"points": to_delete},
                )
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant retention sweep failed")
            return 0
        return len(to_delete)

    async def delete_where(self, where: Filter | None) -> int:
        if not self.is_available:
            return 0
        flt = build_qdrant_filter(where)
        body_payload: dict[str, Any] = (
            {"filter": flt} if flt is not None else {"filter": {"must": []}}
        )
        try:
            _status, body = await self._request(
                "POST", f"/collections/{self.collection}/points/delete", body_payload
            )
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant delete failed")
            return 0
        # Qdrant does not report a deleted count; report the operation status.
        return int(bool((body.get("result") or {}).get("status") == "completed"))

    async def close(self) -> None:
        # The aiohttp session is owned by Home Assistant and must not be closed.
        self.is_available = False
```

- [ ] **Step 4: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_qdrant.py -v`
Expected: 9 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --prerelease=allow ruff check custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_qdrant.py
uv run --prerelease=allow ruff format custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_qdrant.py
git add custom_components/smartchain/tools/memory/backends/qdrant.py tests/test_memory_backend_qdrant.py
git commit -m "feat(memory): qdrant REST backend with no new dependency"
```

---

### Task 6: Backend factory and the conformance suite

**Files:**
- Modify: `custom_components/smartchain/tools/memory/backends/__init__.py`
- Create: `tests/test_memory_backend_conformance.py`
- Create: `tests/test_memory_filter_translation.py`

**Interfaces:**
- Consumes: all four backend classes.
- Produces: `create_backend(hass, config: BackendConfig, store_name: str, storage_dir: Path) -> VectorBackend`. Task 7 calls it from `MemoryStore`; Task 8 supplies `BackendConfig`.

> `BackendConfig` is introduced in Task 8. To keep this task independently testable, `create_backend` accepts any object exposing `.type`, `.path`, `.dsn`, `.table`, `.url`, `.api_key`, `.collection`, `.verify_ssl` — the conformance tests pass a `SimpleNamespace`.

- [ ] **Step 1: Write the conformance suite**

Create `tests/test_memory_backend_conformance.py`. One contract, every backend — this is what stops the Protocol drifting between implementations.

```python
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
        [_rec("a", [1.0, 0.0, 0.0], kind="conversation"), _rec("b", [1.0, 0.0, 0.0], kind="logbook")]
    )
    hits = await backend.query([1.0, 0.0, 0.0], top_k=5, where={"kind": "logbook"})
    assert [h.doc_id for h in hits] == ["b"]


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
        [_rec("a", [1.0, 0.0, 0.0], kind="conversation"), _rec("b", [1.0, 0.0, 0.0], kind="logbook")]
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
```

- [ ] **Step 2: Write the filter-translation test**

Create `tests/test_memory_filter_translation.py`. Each backend's translator is a pure function, so this is fast and covers the dialects the conformance suite cannot reach without live servers.

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_conformance.py tests/test_memory_filter_translation.py -v`
Expected: the conformance suite passes for `sqlite_numpy` (its backend already exists) and skips `sqlite_vec`; filter translation passes. Both files exist to lock the contract before the factory lands — if everything already passes, that is the correct state and you proceed to Step 4.

- [ ] **Step 4: Implement the factory**

Replace `custom_components/smartchain/tools/memory/backends/__init__.py` with:

```python
"""Pluggable vector storage backends for the SmartChain memory subsystem."""

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ....const import (
    MEMORY_DEFAULT_PG_TABLE,
    MEMORY_DEFAULT_QDRANT_COLLECTION,
)
from .base import BackendInitError, Filter, VectorBackend, VectorHit, VectorRecord

LOGGER = logging.getLogger(__name__)

__all__ = [
    "BackendInitError",
    "Filter",
    "VectorBackend",
    "VectorHit",
    "VectorRecord",
    "create_backend",
]


def create_backend(
    hass: HomeAssistant,
    config: Any,
    store_name: str,
    storage_dir: Path,
) -> VectorBackend:
    """Build the backend named by `config.type`.

    `storage_dir` is where file-based backends put their database; the file is
    named after the store so several stores can coexist.

    Raises BackendInitError for an unknown type — a value the schema should
    have rejected, so reaching this is a bug rather than user error.
    """
    backend_type = getattr(config, "type", None) or "sqlite_numpy"

    if backend_type == "sqlite_numpy":
        from .sqlite_numpy import SqliteNumpyBackend  # noqa: PLC0415

        return SqliteNumpyBackend(hass, _db_path(config, storage_dir, store_name))

    if backend_type == "sqlite_vec":
        from .sqlite_vec import SqliteVecBackend  # noqa: PLC0415

        return SqliteVecBackend(hass, _db_path(config, storage_dir, store_name))

    if backend_type == "pgvector":
        from .pgvector import PgVectorBackend  # noqa: PLC0415

        return PgVectorBackend(
            hass,
            dsn=getattr(config, "dsn", "") or "",
            table=getattr(config, "table", None) or MEMORY_DEFAULT_PG_TABLE,
        )

    if backend_type == "qdrant":
        from .qdrant import QdrantBackend  # noqa: PLC0415

        return QdrantBackend(
            hass,
            url=getattr(config, "url", "") or "",
            collection=(
                getattr(config, "collection", None) or MEMORY_DEFAULT_QDRANT_COLLECTION
            ),
            api_key=getattr(config, "api_key", None),
            verify_ssl=bool(getattr(config, "verify_ssl", True)),
        )

    raise BackendInitError(f"unknown backend type {backend_type!r}")


def _db_path(config: Any, storage_dir: Path, store_name: str) -> Path:
    """Resolve the on-disk path for a file-based backend."""
    configured = getattr(config, "path", None)
    if configured:
        return Path(configured)
    return storage_dir / f"{store_name}.db"
```

- [ ] **Step 5: Add factory tests**

Append to `tests/test_memory_backend_conformance.py`:

```python


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
```

- [ ] **Step 6: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_conformance.py tests/test_memory_filter_translation.py -v`
Expected: all pass; `sqlite_vec` parametrisations skip unless the package is installed.

- [ ] **Step 7: Lint and commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/backends/__init__.py tests/test_memory_backend_conformance.py tests/test_memory_filter_translation.py
git commit -m "feat(memory): backend factory + cross-backend conformance suite"
```

---

### Task 7: `MemoryStore` switches from Chroma to a backend

**Files:**
- Modify: `custom_components/smartchain/tools/memory/store.py`
- Create: `tests/test_memory_dimension_probe.py`
- Modify: `tests/test_memory_store.py`

**Interfaces:**
- Consumes: `create_backend`, `VectorBackend`, `VectorRecord`, `VectorHit`, `BackendInitError`.
- Produces: `MemoryStore(hass, embeddings, backend: VectorBackend)` with `async_setup() -> None`, `add(text, metadata, doc_id=None) -> list[str]`, `search(query, top_k=5, where=None) -> list[MemorySnippet]`, `delete_older_than(cutoff: datetime) -> int`, `clear(where=None) -> int`, `close() -> None`, and the `is_available` flag. `chunk_text` and `MemorySnippet` keep their current signatures. Task 8 constructs it; Task 15 puts instances into the registry.

> The constructor signature changes: `persist_dir: Path` is replaced by `backend: VectorBackend`, and initialization moves out of `__init__` into the async `async_setup()` because the dimension probe is asynchronous. Every caller is updated in Task 8.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_dimension_probe.py`:

```python
"""MemoryStore probes the embedding dimension and reacts to a mismatch."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import MEMORY_DIM_PROBE_TEXT
from custom_components.smartchain.tools.memory.backends.base import BackendInitError
from custom_components.smartchain.tools.memory.store import MemoryStore


def _embeddings(dim: int) -> MagicMock:
    emb = MagicMock()
    emb.embed_query = AsyncMock(return_value=[0.1] * dim)
    emb.embed_documents = AsyncMock(side_effect=lambda texts: [[0.1] * dim for _ in texts])
    return emb


def _backend() -> MagicMock:
    be = MagicMock()
    be.name = "fake"
    be.is_available = True
    be.initialize = AsyncMock()
    be.upsert = AsyncMock()
    be.query = AsyncMock(return_value=[])
    be.delete_older_than = AsyncMock(return_value=0)
    be.delete_where = AsyncMock(return_value=0)
    be.close = AsyncMock()
    return be


async def test_setup_probes_and_passes_dimension(hass: HomeAssistant) -> None:
    emb = _embeddings(768)
    be = _backend()
    store = MemoryStore(hass, emb, be)
    await store.async_setup()

    emb.embed_query.assert_awaited_once_with(MEMORY_DIM_PROBE_TEXT)
    be.initialize.assert_awaited_once_with(768)
    assert store.is_available is True


async def test_backend_init_error_disables_store(hass: HomeAssistant) -> None:
    be = _backend()
    be.initialize = AsyncMock(side_effect=BackendInitError("dimension is 768 but model gives 1536"))
    store = MemoryStore(hass, _embeddings(1536), be)
    await store.async_setup()
    assert store.is_available is False


async def test_probe_failure_disables_store(hass: HomeAssistant) -> None:
    emb = _embeddings(768)
    emb.embed_query = AsyncMock(side_effect=RuntimeError("ollama is down"))
    store = MemoryStore(hass, emb, _backend())
    await store.async_setup()
    assert store.is_available is False


async def test_operations_noop_when_unavailable(hass: HomeAssistant) -> None:
    be = _backend()
    be.initialize = AsyncMock(side_effect=BackendInitError("nope"))
    store = MemoryStore(hass, _embeddings(3), be)
    await store.async_setup()

    assert await store.add("text", {"kind": "conversation"}) == []
    assert await store.search("q") == []
    assert await store.clear() == 0
    be.upsert.assert_not_awaited()
    be.query.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_memory_dimension_probe.py -v`
Expected: FAIL — `MemoryStore.__init__` still takes `persist_dir` and has no `async_setup`.

- [ ] **Step 3: Rewrite `store.py`**

Replace `custom_components/smartchain/tools/memory/store.py` with the following. `chunk_text` and `MemorySnippet` are unchanged; everything Chroma-specific is gone.

```python
"""MemoryStore — embeddings, chunking and orchestration over a VectorBackend."""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import (
    MEMORY_BACKEND_TIMEOUT_SECONDS,
    MEMORY_CHUNK_OVERLAP,
    MEMORY_CHUNK_SIZE,
    MEMORY_DIM_PROBE_TEXT,
    MEMORY_MAX_TEXT_LEN,
)
from .backends import BackendInitError, VectorBackend, VectorRecord

LOGGER = logging.getLogger(__name__)


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks for embedding.

    Short text (≤ MEMORY_MAX_TEXT_LEN) is returned as a single chunk. Longer
    text is split into MEMORY_CHUNK_SIZE-character pieces with
    MEMORY_CHUNK_OVERLAP characters of overlap between consecutive chunks.
    """
    if not text:
        return []
    if len(text) <= MEMORY_MAX_TEXT_LEN:
        return [text]

    chunks: list[str] = []
    start = 0
    step = MEMORY_CHUNK_SIZE - MEMORY_CHUNK_OVERLAP
    while start < len(text):
        end = start + MEMORY_CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return chunks


@dataclass(frozen=True)
class MemorySnippet:
    text: str
    score: float
    metadata: dict[str, Any]


class MemoryStore:
    """Owns embeddings and chunking; delegates vector storage to a backend."""

    def __init__(
        self,
        hass: HomeAssistant,
        embeddings: Any,
        backend: VectorBackend,
    ) -> None:
        self.hass = hass
        self.embeddings = embeddings
        self.backend = backend
        self.is_available = False
        self.dim: int | None = None

    async def async_setup(self) -> None:
        """Probe the embedding dimension and initialise the backend.

        Any failure here disables the store rather than raising: one broken
        store must not prevent the others from starting.
        """
        try:
            probe = await self.embeddings.embed_query(MEMORY_DIM_PROBE_TEXT)
        except Exception:  # noqa: BLE001
            LOGGER.exception(
                "SmartChain memory: the embeddings provider did not answer the "
                "dimension probe; this store is disabled"
            )
            self.is_available = False
            return

        dim = len(probe)
        try:
            await self.backend.initialize(dim)
        except BackendInitError as err:
            LOGGER.error("SmartChain memory backend %s disabled: %s", self.backend.name, err)
            self.is_available = False
            return
        except Exception:  # noqa: BLE001
            LOGGER.exception("SmartChain memory backend %s failed to start", self.backend.name)
            self.is_available = False
            return

        self.dim = dim
        self.is_available = True

    async def add(
        self,
        text: str,
        metadata: dict[str, Any],
        doc_id: str | None = None,
    ) -> list[str]:
        """Embed and store a text. Returns the list of doc_ids written."""
        if not self.is_available:
            return []
        chunks = chunk_text(text)
        if not chunks:
            return []

        vectors = await self.embeddings.embed_documents(chunks)
        records: list[VectorRecord] = []
        for index, chunk in enumerate(chunks):
            this_id = (
                doc_id
                if doc_id is not None and len(chunks) == 1
                else f"{doc_id or uuid.uuid4().hex}_chunk{index}"
            )
            records.append(
                VectorRecord(
                    doc_id=this_id,
                    vector=vectors[index],
                    text=chunk,
                    metadata={**metadata, "chunk_index": index},
                )
            )

        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                await self.backend.upsert(records)
        except (TimeoutError, Exception):  # noqa: BLE001 — runtime, store stays up
            LOGGER.exception("memory upsert failed on backend %s", self.backend.name)
            return []
        return [r.doc_id for r in records]

    async def search(
        self,
        query: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[MemorySnippet]:
        if not self.is_available:
            return []
        try:
            vector = await self.embeddings.embed_query(query)
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                hits = await self.backend.query(vector, top_k, where)
        except (TimeoutError, Exception):  # noqa: BLE001 — runtime, store stays up
            LOGGER.exception("memory search failed on backend %s", self.backend.name)
            return []

        return [
            MemorySnippet(
                text=hit.text,
                score=1.0 - hit.distance,
                metadata=hit.metadata,
            )
            for hit in hits
        ]

    async def delete_older_than(self, cutoff: datetime) -> int:
        if not self.is_available:
            return 0
        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                return await self.backend.delete_older_than(cutoff.isoformat())
        except (TimeoutError, Exception):  # noqa: BLE001
            LOGGER.exception("memory retention failed on backend %s", self.backend.name)
            return 0

    async def clear(self, where: dict[str, Any] | None = None) -> int:
        if not self.is_available:
            return 0
        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                return await self.backend.delete_where(where)
        except (TimeoutError, Exception):  # noqa: BLE001
            LOGGER.exception("memory clear failed on backend %s", self.backend.name)
            return 0

    async def close(self) -> None:
        self.is_available = False
        await self.backend.close()
```

- [ ] **Step 4: Rewrite `tests/test_memory_store.py`**

The old file faked a `chromadb` module in `sys.modules`. Replace it entirely — the store is now tested against a real `sqlite_numpy` backend, which is both simpler and closer to production:

```python
"""Tests for MemoryStore over a real sqlite_numpy backend."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import MEMORY_MAX_TEXT_LEN
from custom_components.smartchain.tools.memory.backends.sqlite_numpy import (
    SqliteNumpyBackend,
)
from custom_components.smartchain.tools.memory.store import MemorySnippet, MemoryStore


class _FakeEmbeddings:
    """Deterministic mini-embedder: first 8 character codes, padded."""

    def __init__(self) -> None:
        self.embed_query = AsyncMock(side_effect=self._embed)
        self.embed_documents = AsyncMock(
            side_effect=lambda texts: [self._embed(t) for t in texts]
        )

    @staticmethod
    def _embed(text: str) -> list[float]:
        vec = [float(ord(c)) for c in text[:8]]
        while len(vec) < 8:
            vec.append(0.0)
        return vec


@pytest.fixture
async def store(hass: HomeAssistant, tmp_path):
    backend = SqliteNumpyBackend(hass, tmp_path / "memory.db")
    st = MemoryStore(hass, _FakeEmbeddings(), backend)
    await st.async_setup()
    yield st
    await st.close()


async def test_add_and_search_returns_snippet(store) -> None:
    await store.add("hello world", {"kind": "conversation", "timestamp": "t1"})
    results = await store.search("hello world", top_k=1)
    assert len(results) == 1
    assert isinstance(results[0], MemorySnippet)
    assert results[0].text == "hello world"
    assert results[0].metadata["kind"] == "conversation"


async def test_search_with_where_filter(store) -> None:
    await store.add("foo", {"kind": "conversation", "timestamp": "t1"})
    await store.add("bar", {"kind": "logbook", "timestamp": "t2"})
    results = await store.search("foo", top_k=5, where={"kind": "logbook"})
    assert all(r.metadata["kind"] == "logbook" for r in results)


async def test_delete_older_than(store) -> None:
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    new = datetime.now(UTC).isoformat()
    await store.add("old", {"kind": "conversation", "timestamp": old})
    await store.add("new", {"kind": "conversation", "timestamp": new})

    deleted = await store.delete_older_than(datetime.now(UTC) - timedelta(days=5))
    assert deleted == 1
    remaining = await store.search("new", top_k=5)
    assert any(r.text == "new" for r in remaining)
    assert not any(r.text == "old" for r in remaining)


async def test_clear_removes_everything(store) -> None:
    await store.add("a", {"kind": "conversation", "timestamp": "t"})
    await store.add("b", {"kind": "logbook", "timestamp": "t"})
    assert await store.clear() == 2
    assert await store.search("a", top_k=5) == []


async def test_long_text_is_chunked(store) -> None:
    ids = await store.add(
        "a" * (MEMORY_MAX_TEXT_LEN + 200), {"kind": "conversation", "timestamp": "t"}
    )
    assert len(ids) >= 2


async def test_add_with_explicit_doc_id_is_idempotent(store) -> None:
    await store.add("alpha", {"kind": "logbook", "timestamp": "t"}, doc_id="fixed-1")
    await store.add("alpha", {"kind": "logbook", "timestamp": "t"}, doc_id="fixed-1")
    results = await store.search("alpha", top_k=10)
    assert len([r for r in results if r.text == "alpha"]) == 1


async def test_score_is_inverted_distance(store) -> None:
    await store.add("hello world", {"kind": "conversation", "timestamp": "t"})
    results = await store.search("hello world", top_k=1)
    assert results[0].score == pytest.approx(1.0, abs=1e-4)
```

- [ ] **Step 5: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_dimension_probe.py tests/test_memory_store.py -v`
Expected: 4 + 7 passed.

Other memory tests still reference the old constructor and will fail; they are fixed in Task 8. Do not run the whole suite yet.

- [ ] **Step 6: Commit**

```bash
uv run --prerelease=allow ruff check custom_components/smartchain/tools/memory/ tests/test_memory_dimension_probe.py tests/test_memory_store.py
uv run --prerelease=allow ruff format custom_components/smartchain/tools/memory/ tests/test_memory_dimension_probe.py tests/test_memory_store.py
git add custom_components/smartchain/tools/memory/store.py tests/test_memory_dimension_probe.py tests/test_memory_store.py
git commit -m "refactor(memory): MemoryStore delegates to VectorBackend, Chroma removed"
```

---

### Task 8: Wire backend selection through config; drop Chroma; Phase 1 checkpoint

**Files:**
- Modify: `custom_components/smartchain/tools/memory/config.py`
- Modify: `custom_components/smartchain/tools/schema.py`
- Modify: `custom_components/smartchain/tools/loader.py`
- Modify: `custom_components/smartchain/__init__.py`
- Modify: `custom_components/smartchain/manifest.json`, `pyproject.toml`
- Modify: `tests/test_memory_schema.py`, `tests/test_memory_loader.py`, `tests/test_memory_integration.py`, `tests/test_memory_clear_service.py`

**Interfaces:**
- Consumes: `create_backend`, `MemoryStore.async_setup`.
- Produces: `BackendConfig(type, path, dsn, table, url, api_key, collection, verify_ssl)` and `MemoryConfig.backend: BackendConfig`. Task 13 reuses `BackendConfig` verbatim inside `StoreConfig`.

- [ ] **Step 1: Add `BackendConfig` to `config.py`**

Insert above `MemoryConfig` in `custom_components/smartchain/tools/memory/config.py`:

```python
@dataclass(frozen=True)
class BackendConfig:
    """Vector backend selection and its per-type settings.

    One dataclass carries every backend's options rather than a union: the
    schema already rejects irrelevant combinations, and a flat shape keeps the
    factory a simple attribute read.
    """

    type: str = "sqlite_numpy"
    # sqlite_numpy / sqlite_vec
    path: str | None = None
    # pgvector
    dsn: str | None = None
    table: str | None = None
    # qdrant
    url: str | None = None
    api_key: str | None = None
    collection: str | None = None
    verify_ssl: bool = True
```

And add the field to `MemoryConfig`:

```python
    backend: BackendConfig = field(default_factory=BackendConfig)
```

- [ ] **Step 2: Extend the schema**

In `custom_components/smartchain/tools/schema.py`, add `MEMORY_BACKEND_TYPES` to the `..const` import, then define the sub-schema above `MEMORY_SCHEMA`:

```python
_BACKEND_SCHEMA = vol.Schema(
    {
        vol.Optional("type", default="sqlite_numpy"): vol.In(MEMORY_BACKEND_TYPES),
        vol.Optional("path"): vol.Any(None, str),
        vol.Optional("dsn"): vol.Any(None, str),
        vol.Optional("table"): vol.Any(None, str),
        vol.Optional("url"): vol.Any(None, str),
        vol.Optional("api_key"): vol.Any(None, str),
        vol.Optional("collection"): vol.Any(None, str),
        vol.Optional("verify_ssl", default=True): bool,
    }
)
```

Add one key to `MEMORY_SCHEMA`:

```python
        vol.Optional("backend", default=dict): _BACKEND_SCHEMA,
```

- [ ] **Step 3: Parse it in the loader**

In `custom_components/smartchain/tools/loader.py`, import `BackendConfig` alongside the existing memory config imports and extend `_memory_from_validated` so the returned `MemoryConfig` carries:

```python
        backend=BackendConfig(
            type=(raw.get("backend") or {}).get("type", "sqlite_numpy"),
            path=(raw.get("backend") or {}).get("path"),
            dsn=(raw.get("backend") or {}).get("dsn"),
            table=(raw.get("backend") or {}).get("table"),
            url=(raw.get("backend") or {}).get("url"),
            api_key=(raw.get("backend") or {}).get("api_key"),
            collection=(raw.get("backend") or {}).get("collection"),
            verify_ssl=(raw.get("backend") or {}).get("verify_ssl", True),
        ),
```

- [ ] **Step 4: Update `_build_memory` in `__init__.py`**

Replace the body of `_build_memory` so it constructs a backend and awaits `async_setup()`:

```python
async def _build_memory(
    hass: HomeAssistant, cfg
) -> tuple[MemoryStore | None, RetentionTask | None, MemoryLogbookPoller | None]:
    """Construct MemoryStore + auxiliary tasks for a MemoryConfig.

    Returns (None, None, None) when cfg is None/disabled, the embeddings
    provider could not be constructed, or the backend refused to start.
    """
    if cfg is None or not cfg.enabled:
        return None, None, None
    try:
        embeddings = create_embeddings(hass, cfg)
    except EmbeddingsConfigError as err:
        LOGGER.error("SmartChain memory disabled: %s", err)
        return None, None, None

    try:
        backend = create_backend(hass, cfg.backend, "default", _memory_persist_dir(hass))
    except BackendInitError as err:
        LOGGER.error("SmartChain memory disabled: %s", err)
        return None, None, None

    store = _memory_store_mod.MemoryStore(hass, embeddings, backend)
    await store.async_setup()
    if not store.is_available:
        return None, None, None

    retention = RetentionTask(hass, store, cfg.retention_days)
    poller = MemoryLogbookPoller(hass, store, cfg.logbook)
    return store, retention, poller
```

Update the imports at the top of `__init__.py`: add `from .tools.memory.backends import BackendInitError, create_backend`, and remove the now-unused `Path`-based persist-dir argument from the old call site. `_memory_persist_dir` stays — it is the directory file-based backends write into.

- [ ] **Step 5: Remove Chroma from the manifests**

In `custom_components/smartchain/manifest.json`, delete the `"chromadb>=0.5,<2"` entry if present. In `pyproject.toml`, delete `"chromadb>=0.5,<2"` from the dev group. Then:

```bash
uv lock --prerelease=allow
```

- [ ] **Step 6: Update the affected existing tests**

`tests/test_memory_integration.py` and `tests/test_memory_clear_service.py` patch `MemoryStore` and assert on `hass.data[DOMAIN]["memory"]`. Their stubs must now also expose `async_setup` and `close`. In both files, extend the stub class with:

```python
        async_setup = AsyncMock()
        close = AsyncMock()
```

`tests/test_memory_schema.py` — add:

```python
def test_memory_accepts_backend_block() -> None:
    MEMORY_SCHEMA(
        {
            "provider": "ollama",
            "model": "nomic-embed-text",
            "backend": {"type": "pgvector", "dsn": "postgresql://x/y"},
        }
    )


def test_memory_rejects_unknown_backend_type() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {"provider": "ollama", "model": "x", "backend": {"type": "milvus"}}
        )


def test_memory_backend_defaults_to_sqlite_numpy() -> None:
    result = MEMORY_SCHEMA({"provider": "ollama", "model": "x"})
    assert result["backend"]["type"] == "sqlite_numpy"
```

`tests/test_memory_loader.py` — add:

```python
def test_loader_parses_backend_block(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text(
        "memory:\n"
        "  provider: ollama\n"
        "  model: nomic-embed-text\n"
        "  backend:\n"
        "    type: qdrant\n"
        "    url: http://localhost:6333\n"
        "    collection: mem\n"
    )
    result = load_tools_file(target)
    assert result.memory_config.backend.type == "qdrant"
    assert result.memory_config.backend.url == "http://localhost:6333"
    assert result.memory_config.backend.collection == "mem"


def test_loader_backend_defaults_when_absent(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text("memory:\n  provider: ollama\n  model: nomic-embed-text\n")
    result = load_tools_file(target)
    assert result.memory_config.backend.type == "sqlite_numpy"
```

- [ ] **Step 7: Full suite and lint — the Phase 1 checkpoint**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
```
Expected: everything green. Confirm no import of `chromadb` survives:

```bash
grep -rn "chromadb\|langchain_chroma\|langchain-chroma" custom_components/ tests/ pyproject.toml || echo "clean"
```
Expected: `clean`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(memory): select backend from YAML, drop chromadb entirely

Phase 1 checkpoint: memory now works out of the box on sqlite_numpy,
which needs no dependency beyond what HA already ships. All four
backends are selectable through the new optional memory.backend block."
```

---

# Phase 2 — Embeddings as a provider capability

### Task 9: Provider capability matrix

**Files:**
- Modify: `custom_components/smartchain/const.py`
- Modify: `custom_components/smartchain/client_util.py`
- Test: `tests/test_provider_capabilities.py`

**Interfaces:**
- Consumes: existing `ID_*` provider constants.
- Produces: `CAPABILITY_CHAT`, `CAPABILITY_EMBEDDINGS`, `SUBENTRY_TYPE_EMBEDDINGS` in `const.py`; `PROVIDER_CAPABILITIES: dict[str, frozenset[str]]` and `supports(engine: str, capability: str) -> bool` in `client_util.py`. Task 11 gates the subentry type on `supports`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_provider_capabilities.py`:

```python
"""The capability matrix decides which providers can host embeddings."""

from custom_components.smartchain.client_util import PROVIDER_CAPABILITIES, supports
from custom_components.smartchain.const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
)


def test_every_provider_supports_chat() -> None:
    for engine in (ID_GIGACHAT, ID_YANDEX_GPT, ID_OPENAI, ID_OLLAMA, ID_DEEPSEEK, ID_ANTHROPIC):
        assert supports(engine, CAPABILITY_CHAT) is True


def test_four_providers_support_embeddings() -> None:
    for engine in (ID_GIGACHAT, ID_YANDEX_GPT, ID_OPENAI, ID_OLLAMA):
        assert supports(engine, CAPABILITY_EMBEDDINGS) is True


def test_deepseek_and_anthropic_have_no_embeddings() -> None:
    assert supports(ID_DEEPSEEK, CAPABILITY_EMBEDDINGS) is False
    assert supports(ID_ANTHROPIC, CAPABILITY_EMBEDDINGS) is False


def test_unknown_engine_supports_nothing() -> None:
    assert supports("mistral", CAPABILITY_CHAT) is False
    assert supports("mistral", CAPABILITY_EMBEDDINGS) is False


def test_matrix_covers_every_known_provider() -> None:
    known = {ID_GIGACHAT, ID_YANDEX_GPT, ID_OPENAI, ID_OLLAMA, ID_DEEPSEEK, ID_ANTHROPIC}
    assert set(PROVIDER_CAPABILITIES) == known
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_provider_capabilities.py -v`
Expected: `ImportError` for `CAPABILITY_CHAT`.

- [ ] **Step 3: Add the constants**

Append to `custom_components/smartchain/const.py`:

```python

# Provider capabilities (v4.5.0)
CAPABILITY_CHAT = "chat"
CAPABILITY_EMBEDDINGS = "embeddings"
SUBENTRY_TYPE_EMBEDDINGS = "embeddings"
```

- [ ] **Step 4: Add the matrix**

In `custom_components/smartchain/client_util.py`, add `CAPABILITY_CHAT` and `CAPABILITY_EMBEDDINGS` to the existing `.const` imports, then insert after the `LOGGER` definition:

```python
# Which providers can serve which purpose. DeepSeek exposes no embeddings
# endpoint; Anthropic directs users to Voyage. Neither offers the embeddings
# subentry in the UI.
PROVIDER_CAPABILITIES: dict[str, frozenset[str]] = {
    ID_GIGACHAT: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_YANDEX_GPT: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_OPENAI: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_OLLAMA: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_DEEPSEEK: frozenset({CAPABILITY_CHAT}),
    ID_ANTHROPIC: frozenset({CAPABILITY_CHAT}),
}


def supports(engine: str, capability: str) -> bool:
    """Whether `engine` can serve `capability`. Unknown engines support nothing."""
    return capability in PROVIDER_CAPABILITIES.get(engine, frozenset())
```

- [ ] **Step 5: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_provider_capabilities.py -v`
Expected: 5 passed.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/const.py custom_components/smartchain/client_util.py tests/test_provider_capabilities.py
git commit -m "feat(providers): capability matrix for chat and embeddings"
```

---

### Task 10: Purpose-filtered model discovery

**Files:**
- Modify: `custom_components/smartchain/client_util.py`
- Modify: `custom_components/smartchain/const.py`
- Test: `tests/test_embeddings_model_discovery.py`

**Interfaces:**
- Consumes: `CAPABILITY_CHAT`, `CAPABILITY_EMBEDDINGS`, existing `_fetch_*_models` helpers.
- Produces: `async_fetch_models(hass, engine, data, purpose=CAPABILITY_CHAT)` — a new keyword-only-in-effect third argument with a default, so every existing call site keeps working unchanged. Also `is_embedding_model(engine, name) -> bool`. Task 11 calls it with `purpose=CAPABILITY_EMBEDDINGS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_embeddings_model_discovery.py`:

```python
"""Model discovery splits a provider's catalogue by purpose."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.client_util import (
    async_fetch_models,
    is_embedding_model,
)
from custom_components.smartchain.const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    ID_ANTHROPIC,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
)


@pytest.mark.parametrize(
    ("engine", "name", "expected"),
    [
        (ID_OPENAI, "text-embedding-3-small", True),
        (ID_OPENAI, "gpt-4.1", False),
        (ID_GIGACHAT, "Embeddings", True),
        (ID_GIGACHAT, "EmbeddingsGigaR", True),
        (ID_GIGACHAT, "GigaChat-Pro", False),
        (ID_OLLAMA, "nomic-embed-text", True),
        (ID_OLLAMA, "bge-m3", True),
        (ID_OLLAMA, "mxbai-embed-large", True),
        (ID_OLLAMA, "llama3.3", False),
        (ID_ANTHROPIC, "claude-sonnet-4-6", False),
    ],
)
def test_is_embedding_model(engine: str, name: str, expected: bool) -> None:
    assert is_embedding_model(engine, name) is expected


async def test_openai_embeddings_purpose_filters_catalogue(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1", "gpt-4o", "text-embedding-3-small", "text-embedding-3-large"],
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert "text-embedding-3-small" in models
    assert "gpt-4.1" not in models


async def test_openai_chat_purpose_excludes_embeddings(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1", "text-embedding-3-small"],
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_CHAT
        )
    assert "gpt-4.1" in models
    assert "text-embedding-3-small" not in models


async def test_default_purpose_is_chat(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1", "text-embedding-3-small"],
    ):
        models = await async_fetch_models(hass, ID_OPENAI, {"api_key": "k"})
    assert "gpt-4.1" in models
    assert "text-embedding-3-small" not in models


async def test_gigachat_embeddings_purpose(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_gigachat_models",
        new_callable=AsyncMock,
        return_value=["GigaChat-Pro", "GigaChat-Max", "Embeddings", "EmbeddingsGigaR"],
    ):
        models = await async_fetch_models(
            hass, ID_GIGACHAT, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert set(models) >= {"Embeddings", "EmbeddingsGigaR"}
    assert "GigaChat-Pro" not in models


async def test_yandex_uses_static_embedding_list(hass: HomeAssistant) -> None:
    models = await async_fetch_models(
        hass, ID_YANDEX_GPT, {}, purpose=CAPABILITY_EMBEDDINGS
    )
    assert "text-search-doc" in models
    assert "text-search-query" in models


async def test_fetch_failure_falls_back_to_static_embedding_list(
    hass: HomeAssistant,
) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network down"),
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert "text-embedding-3-small" in models


async def test_empty_result_keeps_the_blank_custom_option(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1"],
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert models[0] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_embeddings_model_discovery.py -v`
Expected: `ImportError` for `is_embedding_model`.

- [ ] **Step 3: Add the static embedding lists**

Append to `custom_components/smartchain/const.py`:

```python

# Static fallback embedding-model lists, used when a provider's API is
# unreachable or has no list endpoint (YandexGPT).
EMBEDDING_MODELS_GIGACHAT = ["", "Embeddings", "EmbeddingsGigaR"]
EMBEDDING_MODELS_YANDEX_GPT = ["", "text-search-doc", "text-search-query"]
EMBEDDING_MODELS_OPENAI = ["", "text-embedding-3-small", "text-embedding-3-large"]
EMBEDDING_MODELS_OLLAMA = ["", "nomic-embed-text", "mxbai-embed-large", "bge-m3"]

ENGINE_EMBEDDING_MODELS = {
    UNIQUE_ID_GIGACHAT: EMBEDDING_MODELS_GIGACHAT,
    UNIQUE_ID_YANDEX_GPT: EMBEDDING_MODELS_YANDEX_GPT,
    UNIQUE_ID_OPENAI: EMBEDDING_MODELS_OPENAI,
    UNIQUE_ID_OLLAMA: EMBEDDING_MODELS_OLLAMA,
}
```

- [ ] **Step 4: Add the classifier and the `purpose` argument**

In `custom_components/smartchain/client_util.py`, add above `async_fetch_models`:

```python
# Ollama's /api/tags does not report purpose, so names are classified by a
# heuristic covering the embedding families in common use.
_OLLAMA_EMBEDDING_HINT = re.compile(r"embed|bge-|gte-|e5-|minilm", re.IGNORECASE)


def is_embedding_model(engine: str, name: str) -> bool:
    """Whether `name` is an embedding model for `engine`."""
    if engine == ID_OPENAI:
        return name.startswith("text-embedding-")
    if engine == ID_GIGACHAT:
        return name.startswith("Embeddings")
    if engine == ID_OLLAMA:
        return bool(_OLLAMA_EMBEDDING_HINT.search(name))
    if engine == ID_YANDEX_GPT:
        return name.startswith("text-search-")
    return False
```

Add `import re` to the module imports.

Then change the `async_fetch_models` signature and its two return paths:

```python
async def async_fetch_models(
    hass: HomeAssistant,
    engine: str,
    data: dict,
    purpose: str = CAPABILITY_CHAT,
) -> list[str]:
    """Fetch available models from provider API, filtered by purpose.

    Returns a list of model names with an empty string first (the 'custom'
    option). Falls back to the static list for `purpose` on any error.
    """
    from .const import (  # noqa: PLC0415
        ENGINE_EMBEDDING_MODELS,
        ENGINE_MODELS,
        UNIQUE_ID,
    )

    want_embeddings = purpose == CAPABILITY_EMBEDDINGS
    static = (
        ENGINE_EMBEDDING_MODELS.get(UNIQUE_ID.get(engine, ""), [""])
        if want_embeddings
        else ENGINE_MODELS.get(UNIQUE_ID.get(engine, ""), [""])
    )

    try:
        if engine == ID_OLLAMA:
            models = await _fetch_ollama_models(hass, data)
        elif engine == ID_OPENAI:
            models = await _fetch_openai_compatible_models(
                hass, data, "https://api.openai.com/v1/models"
            )
        elif engine == ID_DEEPSEEK:
            models = await _fetch_openai_compatible_models(
                hass, data, f"{DEFAULT_DEEPSEEK_BASE_URL}/models"
            )
        elif engine == ID_ANTHROPIC:
            models = await _fetch_anthropic_models(hass, data)
        elif engine == ID_GIGACHAT:
            models = await _fetch_gigachat_models(hass, data)
        else:
            # YandexGPT has no list endpoint.
            return static

        models = [m for m in models if is_embedding_model(engine, m) == want_embeddings]
        if models:
            return [""] + models
        raise ValueError("Empty model list")
    except Exception:
        LOGGER.debug(
            "Failed to fetch %s models for %s, using static list", purpose, engine
        )
        return static
```

Add `CAPABILITY_CHAT` and `CAPABILITY_EMBEDDINGS` to the `.const` imports at the top of the file.

- [ ] **Step 5: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_embeddings_model_discovery.py tests/test_fetch_models.py -v`
Expected: all pass. `test_fetch_models.py` covers the existing chat path and must stay green — the `purpose` default preserves its behaviour.

- [ ] **Step 6: Commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/client_util.py custom_components/smartchain/const.py tests/test_embeddings_model_discovery.py
git commit -m "feat(providers): filter model discovery by purpose"
```

---

### Task 11: `EmbeddingsSubentryFlow`

**Files:**
- Modify: `custom_components/smartchain/config_flow.py`
- Modify: `custom_components/smartchain/strings.json`, `translations/en.json`, `translations/ru.json`
- Test: `tests/test_embeddings_subentry_flow.py`

**Interfaces:**
- Consumes: `supports`, `async_fetch_models(purpose=...)`, `SUBENTRY_TYPE_EMBEDDINGS`, `CAPABILITY_EMBEDDINGS`.
- Produces: `EmbeddingsSubentryFlow`, registered in `async_get_supported_subentry_types`. Subentry data shape is `{"model": str, "model_user": str}`; the subentry title is the reference key used by Task 14's YAML.

- [ ] **Step 1: Write the failing test**

Create `tests/test_embeddings_subentry_flow.py`:

```python
"""The embeddings subentry type appears only for capable providers."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import SmartChainConfigFlow
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry(hass: HomeAssistant, engine: str, unique_id: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: engine, CONF_API_KEY: "k"},
        options={},
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    return entry


async def test_capable_provider_offers_embeddings(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_GIGACHAT, "GigaChat")
    types = SmartChainConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_CONVERSATION in types
    assert SUBENTRY_TYPE_EMBEDDINGS in types


async def test_deepseek_does_not_offer_embeddings(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_DEEPSEEK, "DeepSeek")
    types = SmartChainConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_CONVERSATION in types
    assert SUBENTRY_TYPE_EMBEDDINGS not in types


async def test_anthropic_does_not_offer_embeddings(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_ANTHROPIC, "Anthropic")
    types = SmartChainConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_EMBEDDINGS not in types


async def test_flow_creates_subentry_with_selected_model(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_GIGACHAT, "GigaChat")

    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        new_callable=AsyncMock,
        return_value=["", "Embeddings", "EmbeddingsGigaR"],
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_EMBEDDINGS),
            context={"source": "user"},
        )
        assert result["type"] == "form"
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"name": "GigaChat Embeddings", "model": "Embeddings", "model_user": ""},
        )

    assert result["type"] == "create_entry"
    assert result["title"] == "GigaChat Embeddings"
    assert result["data"]["model"] == "Embeddings"


async def test_custom_model_name_wins_over_selection(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_GIGACHAT, "GigaChat")

    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        new_callable=AsyncMock,
        return_value=["", "Embeddings"],
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_EMBEDDINGS),
            context={"source": "user"},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"name": "Custom", "model": "Embeddings", "model_user": "EmbeddingsGigaR"},
        )

    assert result["data"]["model"] == "EmbeddingsGigaR"


async def test_fetch_is_called_with_embeddings_purpose(hass: HomeAssistant) -> None:
    from custom_components.smartchain.const import CAPABILITY_EMBEDDINGS

    entry = _entry(hass, ID_GIGACHAT, "GigaChat")
    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        new_callable=AsyncMock,
        return_value=["", "Embeddings"],
    ) as fetch:
        await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_EMBEDDINGS),
            context={"source": "user"},
        )
    assert fetch.await_args.kwargs["purpose"] == CAPABILITY_EMBEDDINGS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_embeddings_subentry_flow.py -v`
Expected: `ImportError` for `SUBENTRY_TYPE_EMBEDDINGS` in `config_flow`, or `KeyError` on the unregistered subentry type.

- [ ] **Step 3: Implement the flow**

In `custom_components/smartchain/config_flow.py`, add to the `.const` imports: `CAPABILITY_EMBEDDINGS`, `SUBENTRY_TYPE_EMBEDDINGS`; and to the `.client_util` imports: `supports`.

Replace `async_get_supported_subentry_types`:

```python
    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry types, filtered by provider capability."""
        types: dict[str, type[ConfigSubentryFlow]] = {
            SUBENTRY_TYPE_CONVERSATION: ConversationSubentryFlow,
        }
        engine = config_entry.data.get(CONF_ENGINE) or ID_GIGACHAT
        if supports(engine, CAPABILITY_EMBEDDINGS):
            types[SUBENTRY_TYPE_EMBEDDINGS] = EmbeddingsSubentryFlow
        return types
```

Append the flow class at the end of the file:

```python
def _embeddings_subentry_schema(
    models: list[str], defaults: dict[str, Any] | None = None
) -> vol.Schema:
    """Schema for an embeddings binding: a name and a model, nothing more.

    An embeddings subentry has no prompt, no tools and no temperature — it
    exists purely to bind provider credentials to one embedding model.
    """
    current = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                "name",
                description={"suggested_value": current.get("name", "")},
            ): str,
            vol.Optional(
                "model",
                description={"suggested_value": current.get("model")},
                default="",
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    mode=SelectSelectorMode("dropdown"),
                    options=models,
                ),
            ),
            vol.Optional(
                "model_user",
                description={"suggested_value": current.get("model_user")},
            ): str,
        }
    )


class EmbeddingsSubentryFlow(ConfigSubentryFlow):
    """Handle adding or reconfiguring an embeddings binding."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a new embeddings binding."""
        entry = self._get_entry()
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(
            self.hass, engine, entry.data, purpose=CAPABILITY_EMBEDDINGS
        )
        schema = _embeddings_subentry_schema(models)

        if user_input is not None:
            return self._create(user_input, schema)
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an existing embeddings binding."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(
            self.hass, engine, entry.data, purpose=CAPABILITY_EMBEDDINGS
        )
        defaults = {**subentry.data, "name": subentry.title}
        schema = _embeddings_subentry_schema(models, defaults)

        if user_input is not None:
            model = _resolve_embeddings_model(user_input)
            if not model:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=schema,
                    errors={"base": "model_required"},
                )
            return self.async_update_and_abort(
                entry,
                subentry,
                title=user_input["name"],
                data={"model": model, "model_user": user_input.get("model_user", "")},
            )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    def _create(self, user_input: dict[str, Any], schema: vol.Schema) -> SubentryFlowResult:
        model = _resolve_embeddings_model(user_input)
        if not model:
            return self.async_show_form(
                step_id="user", data_schema=schema, errors={"base": "model_required"}
            )
        return self.async_create_entry(
            title=user_input["name"],
            data={"model": model, "model_user": user_input.get("model_user", "")},
        )


def _resolve_embeddings_model(user_input: dict[str, Any]) -> str:
    """A non-empty custom name wins over the dropdown selection."""
    custom = (user_input.get("model_user") or "").strip()
    if custom:
        return custom
    return (user_input.get("model") or "").strip()
```

- [ ] **Step 4: Add translation strings**

In `custom_components/smartchain/strings.json`, `translations/en.json` and `translations/ru.json`, add a sibling of the existing `config_subentries.conversation` block:

```json
    "embeddings": {
      "entry_type": "Embeddings binding",
      "initiate_flow": {
        "user": "Add embeddings binding",
        "reconfigure": "Reconfigure embeddings binding"
      },
      "step": {
        "user": {
          "title": "Add embeddings binding",
          "data": {
            "name": "Name",
            "model": "Embedding model",
            "model_user": "Custom model name (leave empty to use the list above)"
          }
        },
        "reconfigure": {
          "title": "Reconfigure embeddings binding",
          "data": {
            "name": "Name",
            "model": "Embedding model",
            "model_user": "Custom model name (leave empty to use the list above)"
          }
        }
      },
      "error": {
        "model_required": "Select a model or enter a custom name"
      }
    }
```

For `translations/ru.json` use: `entry_type` — `"Связка embeddings"`, `user` — `"Добавить связку embeddings"`, `reconfigure` — `"Изменить связку embeddings"`, `name` — `"Название"`, `model` — `"Модель эмбеддингов"`, `model_user` — `"Своё имя модели (оставьте пустым, чтобы взять из списка выше)"`, `model_required` — `"Выберите модель или введите своё имя"`.

- [ ] **Step 5: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_embeddings_subentry_flow.py tests/test_config_flow.py tests/test_subentries.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/config_flow.py custom_components/smartchain/strings.json custom_components/smartchain/translations/ tests/test_embeddings_subentry_flow.py
git commit -m "feat(providers): EmbeddingsSubentryFlow gated on capability"
```

---

### Task 12: Build embeddings from a subentry

**Files:**
- Modify: `custom_components/smartchain/tools/memory/embeddings.py`
- Test: `tests/test_memory_embeddings.py`

**Interfaces:**
- Consumes: `PROVIDER_CAPABILITIES`, `supports`, provider `ID_*` constants.
- Produces: `create_embeddings_from_subentry(hass, entry: ConfigEntry, subentry: ConfigSubentry) -> EmbeddingsProvider`. The existing `create_embeddings(hass, config)` stays until Task 16 removes its last caller. `_ExecutorBacked` and `EmbeddingsConfigError` are unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory_embeddings.py`:

```python


async def test_create_from_subentry_uses_entry_credentials(hass: HomeAssistant) -> None:
    """Credentials come from the config entry, the model from the subentry."""
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_API_KEY, CONF_ENGINE, ID_GIGACHAT
    from custom_components.smartchain.tools.memory.embeddings import (
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "creds-from-entry"})
    subentry = SimpleNamespace(title="GigaChat Embeddings", data={"model": "Embeddings"})

    with patch(
        "custom_components.smartchain.tools.memory.embeddings.GigaChatEmbeddings"
    ) as gc:
        create_embeddings_from_subentry(hass, entry, subentry)

    kwargs = gc.call_args.kwargs
    assert kwargs["credentials"] == "creds-from-entry"
    assert kwargs["model"] == "Embeddings"


async def test_create_from_subentry_ollama_uses_base_url(hass: HomeAssistant) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_BASE_URL, CONF_ENGINE, ID_OLLAMA
    from custom_components.smartchain.tools.memory.embeddings import (
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(
        data={CONF_ENGINE: ID_OLLAMA, CONF_BASE_URL: "http://box:11434"}
    )
    subentry = SimpleNamespace(title="Ollama nomic", data={"model": "nomic-embed-text"})

    with patch(
        "custom_components.smartchain.tools.memory.embeddings.OllamaEmbeddings"
    ) as ollama:
        create_embeddings_from_subentry(hass, entry, subentry)

    ollama.assert_called_once_with(model="nomic-embed-text", base_url="http://box:11434")


async def test_create_from_subentry_rejects_incapable_provider(hass: HomeAssistant) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_API_KEY, CONF_ENGINE, ID_ANTHROPIC
    from custom_components.smartchain.tools.memory.embeddings import (
        EmbeddingsConfigError,
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(data={CONF_ENGINE: ID_ANTHROPIC, CONF_API_KEY: "k"})
    subentry = SimpleNamespace(title="Nope", data={"model": "whatever"})

    with pytest.raises(EmbeddingsConfigError, match="does not provide embeddings"):
        create_embeddings_from_subentry(hass, entry, subentry)


async def test_create_from_subentry_requires_a_model(hass: HomeAssistant) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_API_KEY, CONF_ENGINE, ID_OPENAI
    from custom_components.smartchain.tools.memory.embeddings import (
        EmbeddingsConfigError,
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"})
    subentry = SimpleNamespace(title="Empty", data={"model": ""})

    with pytest.raises(EmbeddingsConfigError, match="no model"):
        create_embeddings_from_subentry(hass, entry, subentry)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_embeddings.py -v`
Expected: `ImportError` for `create_embeddings_from_subentry`.

- [ ] **Step 3: Implement it**

Append to `custom_components/smartchain/tools/memory/embeddings.py`, adding the needed imports (`CONF_API_KEY`, `CONF_BASE_URL`, `CONF_ENGINE`, `CONF_FOLDER_ID`, `CAPABILITY_EMBEDDINGS`, `ID_*` from `...const`; `supports` from `...client_util`):

```python
def create_embeddings_from_subentry(
    hass: HomeAssistant,
    entry: Any,
    subentry: Any,
) -> EmbeddingsProvider:
    """Build an embeddings provider from a config entry and its subentry.

    Credentials come from the entry, the model from the subentry. This is what
    removes the duplicate credential declaration the flat YAML block required.
    """
    engine = entry.data.get(CONF_ENGINE) or ID_GIGACHAT
    if not supports(engine, CAPABILITY_EMBEDDINGS):
        raise EmbeddingsConfigError(
            f"provider {engine!r} does not provide embeddings; "
            f"subentry {subentry.title!r} cannot be used for memory"
        )

    model = (subentry.data.get("model") or "").strip()
    if not model:
        raise EmbeddingsConfigError(
            f"embeddings subentry {subentry.title!r} has no model configured"
        )

    if engine == ID_OLLAMA:
        kwargs: dict[str, Any] = {"model": model}
        base_url = entry.data.get(CONF_BASE_URL)
        if base_url:
            kwargs["base_url"] = base_url
        return _ExecutorBacked(hass, OllamaEmbeddings(**kwargs))

    if engine == ID_OPENAI:
        return _ExecutorBacked(
            hass, OpenAIEmbeddings(model=model, api_key=entry.data[CONF_API_KEY])
        )

    if engine == ID_GIGACHAT:
        return _ExecutorBacked(
            hass,
            GigaChatEmbeddings(
                credentials=entry.data[CONF_API_KEY],
                model=model,
                verify_ssl_certs=False,
            ),
        )

    if engine == ID_YANDEX_GPT:
        from .embeddings_yandex import YandexEmbeddingsAdapter  # noqa: PLC0415

        return _ExecutorBacked(
            hass,
            YandexEmbeddingsAdapter(
                api_key=entry.data[CONF_API_KEY],
                model=model,
                folder_id=entry.data.get(CONF_FOLDER_ID, ""),
            ),
        )

    raise EmbeddingsConfigError(f"unknown provider {engine!r}")
```

Extend `YandexEmbeddingsAdapter.__init__` in `embeddings_yandex.py` to accept `folder_id: str = ""` and pass it to `YCloudML(folder_id=self._folder_id, auth=self._api_key)`.

- [ ] **Step 4: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_embeddings.py -v`
Expected: all pass — the four new tests plus the existing ones.

- [ ] **Step 5: Full suite and commit — the Phase 2 checkpoint**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
git add custom_components/smartchain/tools/memory/embeddings.py custom_components/smartchain/tools/memory/embeddings_yandex.py tests/test_memory_embeddings.py
git commit -m "feat(providers): build embeddings from entry + subentry

Phase 2 checkpoint: the embeddings capability exists end to end but has
no consumer yet — the flat memory: block still drives the single store."
```

---

# Phase 3 — Named multi-stores

### Task 13: `StoreConfig` and `MemorySettings`

**Files:**
- Modify: `custom_components/smartchain/tools/memory/config.py`
- Test: `tests/test_memory_config.py`

**Interfaces:**
- Consumes: `BackendConfig`, `LogbookConfig` from Task 8.
- Produces: `StoreConfig(name, description, embeddings, backend, retention_days, ingest_conversation, logbook)` and `MemorySettings(stores: list[StoreConfig])`. Task 14 produces them from YAML; Task 15 consumes them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory_config.py`:

```python


def test_store_config_defaults() -> None:
    from custom_components.smartchain.tools.memory.config import (
        BackendConfig,
        LogbookConfig,
        StoreConfig,
    )

    cfg = StoreConfig(name="conversations", embeddings="GigaChat Embeddings")
    assert cfg.description == ""
    assert cfg.retention_days == 90
    assert cfg.ingest_conversation is True
    assert cfg.backend == BackendConfig()
    assert cfg.logbook == LogbookConfig()


def test_store_config_full() -> None:
    from custom_components.smartchain.tools.memory.config import (
        BackendConfig,
        StoreConfig,
    )

    cfg = StoreConfig(
        name="entities",
        description="Devices and sensors",
        embeddings="Ollama nomic",
        backend=BackendConfig(type="pgvector", dsn="postgresql://x/y"),
        retention_days=0,
        ingest_conversation=False,
    )
    assert cfg.backend.type == "pgvector"
    assert cfg.retention_days == 0
    assert cfg.ingest_conversation is False


def test_memory_settings_defaults_to_no_stores() -> None:
    from custom_components.smartchain.tools.memory.config import MemorySettings

    assert MemorySettings().stores == []


def test_memory_settings_names() -> None:
    from custom_components.smartchain.tools.memory.config import (
        MemorySettings,
        StoreConfig,
    )

    settings = MemorySettings(
        stores=[
            StoreConfig(name="a", embeddings="E1"),
            StoreConfig(name="b", embeddings="E2"),
        ]
    )
    assert settings.names() == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_config.py -v`
Expected: `ImportError` for `StoreConfig`.

- [ ] **Step 3: Add the dataclasses**

Append to `custom_components/smartchain/tools/memory/config.py`:

```python
@dataclass(frozen=True)
class StoreConfig:
    """One named memory store: an embeddings binding plus a vector backend."""

    name: str
    embeddings: str = ""
    description: str = ""
    backend: BackendConfig = field(default_factory=BackendConfig)
    retention_days: int = 90
    ingest_conversation: bool = True
    logbook: LogbookConfig = field(default_factory=LogbookConfig)


@dataclass(frozen=True)
class MemorySettings:
    """The parsed `memory:` block — a list of named stores."""

    stores: list[StoreConfig] = field(default_factory=list)

    def names(self) -> list[str]:
        return [s.name for s in self.stores]
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_memory_config.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/config.py tests/test_memory_config.py
git commit -m "feat(memory): StoreConfig and MemorySettings dataclasses"
```

---

### Task 14: `memory.stores[]` schema and loader

**Files:**
- Modify: `custom_components/smartchain/tools/schema.py`
- Modify: `custom_components/smartchain/tools/loader.py`
- Modify: `tests/test_memory_schema.py`, `tests/test_memory_loader.py`
- Modify: `tests/fixtures/memory_basic.yaml`

**Interfaces:**
- Consumes: `StoreConfig`, `MemorySettings`, `BackendConfig`, `LogbookConfig`.
- Produces: `LoaderResult.memory_settings: MemorySettings` replacing `LoaderResult.memory_config`. Task 15 and Task 16 read it.

- [ ] **Step 1: Replace the fixture**

Rewrite `tests/fixtures/memory_basic.yaml`:

```yaml
tools: []
memory:
  stores:
    - name: conversations
      description: "Past conversations"
      embeddings: "GigaChat Embeddings"
      backend:
        type: sqlite_numpy
      retention_days: 30
      ingest_conversation: true
      ingest_logbook:
        enabled: true
        domains: [light, lock]
        poll_interval_minutes: 30

    - name: entities
      description: "Devices and sensors"
      embeddings: "Ollama nomic"
      backend:
        type: pgvector
        dsn: "postgresql://user:pass@host/db"
        table: smartchain_entities
      retention_days: 0
      ingest_conversation: false
```

- [ ] **Step 2: Write the failing tests**

Replace the memory-specific tests in `tests/test_memory_schema.py` with:

```python
def test_stores_block_validates() -> None:
    TOOLS_FILE_SCHEMA(
        {
            "memory": {
                "stores": [
                    {"name": "conversations", "embeddings": "GigaChat Embeddings"}
                ]
            }
        }
    )


def test_store_requires_name_and_embeddings() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"name": "a"}]})
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"embeddings": "E"}]})


def test_store_name_pattern_is_enforced() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"name": "Bad Name", "embeddings": "E"}]})


def test_duplicate_store_names_rejected() -> None:
    with pytest.raises(vol.Invalid, match="duplicate"):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {"name": "a", "embeddings": "E1"},
                    {"name": "a", "embeddings": "E2"},
                ]
            }
        )


def test_store_backend_defaults_to_sqlite_numpy() -> None:
    result = MEMORY_SCHEMA({"stores": [{"name": "a", "embeddings": "E"}]})
    assert result["stores"][0]["backend"]["type"] == "sqlite_numpy"


def test_store_rejects_unknown_backend_type() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {"stores": [{"name": "a", "embeddings": "E", "backend": {"type": "milvus"}}]}
        )


def test_legacy_flat_block_is_rejected() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"provider": "ollama", "model": "nomic-embed-text"})
```

Replace the memory tests in `tests/test_memory_loader.py` with:

```python
def test_loader_parses_stores(tmp_path: Path) -> None:
    from custom_components.smartchain.tools.memory.config import MemorySettings

    target = tmp_path / "tools.yaml"
    target.write_text((FIXTURE_DIR / "memory_basic.yaml").read_text())
    result = load_tools_file(target)

    assert isinstance(result.memory_settings, MemorySettings)
    assert result.memory_settings.names() == ["conversations", "entities"]

    conv = result.memory_settings.stores[0]
    assert conv.embeddings == "GigaChat Embeddings"
    assert conv.description == "Past conversations"
    assert conv.backend.type == "sqlite_numpy"
    assert conv.retention_days == 30
    assert conv.ingest_conversation is True
    assert conv.logbook.enabled is True
    assert conv.logbook.domains == ["light", "lock"]

    ent = result.memory_settings.stores[1]
    assert ent.backend.type == "pgvector"
    assert ent.backend.table == "smartchain_entities"
    assert ent.retention_days == 0
    assert ent.ingest_conversation is False


def test_loader_without_memory_block_yields_no_stores(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text("tools: []\n")
    result = load_tools_file(target)
    assert result.memory_settings.stores == []


def test_loader_rejects_legacy_flat_block_with_guidance(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text(
        "memory:\n  provider: ollama\n  model: nomic-embed-text\n  api_key: k\n"
    )
    with pytest.raises(LoaderError) as exc:
        load_tools_file(target)

    message = str(exc.value)
    assert "embeddings subentry" in message
    assert "stores:" in message
    assert "reload_tools" in message
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_schema.py tests/test_memory_loader.py -v`
Expected: failures — the schema still accepts the flat shape and there is no `memory_settings`.

- [ ] **Step 4: Rewrite the schema**

In `custom_components/smartchain/tools/schema.py`, add `MEMORY_STORE_NAME_PATTERN` to the `..const` import and replace `MEMORY_SCHEMA` (keep `_LOGBOOK_SCHEMA` and `_BACKEND_SCHEMA` as they are):

```python
_STORE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): vol.All(str, vol.Match(MEMORY_STORE_NAME_PATTERN)),
        vol.Required("embeddings"): _NON_EMPTY_STR,
        vol.Optional("description", default=""): str,
        vol.Optional("backend", default=dict): _BACKEND_SCHEMA,
        vol.Optional("retention_days", default=90): vol.All(int, vol.Range(min=0, max=3650)),
        vol.Optional("ingest_conversation", default=True): bool,
        vol.Optional("ingest_logbook", default=dict): _LOGBOOK_SCHEMA,
    }
)


def _validate_memory(value: object) -> dict:
    """Validate the memory block and reject the pre-4.5.0 flat shape.

    Credentials no longer live in YAML, so a block carrying `provider` or
    `api_key` cannot be migrated automatically — there is no subentry to point
    at until the user creates one. Fail loudly with the exact steps.
    """
    if not isinstance(value, dict):
        raise vol.Invalid("memory must be a mapping")

    legacy_keys = {"provider", "model", "api_key", "base_url"} & set(value)
    if legacy_keys:
        raise vol.Invalid(
            "the flat memory: block was replaced in v4.5.0. Create an embeddings "
            "subentry on the provider's config entry, then rewrite the block as a "
            "stores: list referencing it by name, then call smartchain.reload_tools. "
            f"Offending keys: {sorted(legacy_keys)}"
        )

    validated = vol.Schema({vol.Optional("stores", default=list): [_STORE_SCHEMA]})(value)

    seen: set[str] = set()
    for store in validated["stores"]:
        if store["name"] in seen:
            raise vol.Invalid(f"duplicate store name {store['name']!r}")
        seen.add(store["name"])
    return validated


MEMORY_SCHEMA = _validate_memory
```

Add the constant to `const.py`:

```python
MEMORY_STORE_NAME_PATTERN = r"^[a-z_][a-z0-9_]*$"
```

- [ ] **Step 5: Rewrite the loader helper**

In `custom_components/smartchain/tools/loader.py`, change the `LoaderResult` field from `memory_config: MemoryConfig | None = None` to:

```python
    memory_settings: MemorySettings = field(default_factory=MemorySettings)
```

Update the import to bring in `BackendConfig`, `LogbookConfig`, `MemorySettings`, `StoreConfig`, and replace `_memory_from_validated`:

```python
def _memory_from_validated(validated: dict) -> MemorySettings:
    """Build MemorySettings from the validated `memory:` block."""
    raw = validated.get("memory") or {}
    stores: list[StoreConfig] = []
    for entry in raw.get("stores") or []:
        backend_raw = entry.get("backend") or {}
        logbook_raw = entry.get("ingest_logbook") or {}
        stores.append(
            StoreConfig(
                name=entry["name"],
                embeddings=entry["embeddings"],
                description=entry.get("description", ""),
                backend=BackendConfig(
                    type=backend_raw.get("type", "sqlite_numpy"),
                    path=backend_raw.get("path"),
                    dsn=backend_raw.get("dsn"),
                    table=backend_raw.get("table"),
                    url=backend_raw.get("url"),
                    api_key=backend_raw.get("api_key"),
                    collection=backend_raw.get("collection"),
                    verify_ssl=backend_raw.get("verify_ssl", True),
                ),
                retention_days=entry.get("retention_days", 90),
                ingest_conversation=entry.get("ingest_conversation", True),
                logbook=LogbookConfig(
                    enabled=logbook_raw.get("enabled", False),
                    domains=list(logbook_raw.get("domains") or []),
                    poll_interval_minutes=logbook_raw.get("poll_interval_minutes", 60),
                ),
            )
        )
    return MemorySettings(stores=stores)
```

Update the `load_tools_file` return to pass `memory_settings=_memory_from_validated(validated)`, and the missing-file early return to `LoaderResult()`.

Because the schema now raises `vol.Invalid` for the legacy shape and `load_tools_file` already wraps `vol.Invalid` into `LoaderError`, the guidance message reaches the user unchanged.

- [ ] **Step 6: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_schema.py tests/test_memory_loader.py tests/test_tools_schema.py tests/test_tools_loader.py tests/test_mcp_loader.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/schema.py custom_components/smartchain/tools/loader.py custom_components/smartchain/const.py tests/test_memory_schema.py tests/test_memory_loader.py tests/fixtures/memory_basic.yaml
git commit -m "feat(memory): memory.stores[] schema and loader, legacy shape rejected"
```

---

### Task 15: `MemoryRegistry`

**Files:**
- Create: `custom_components/smartchain/tools/memory/registry.py`
- Test: `tests/test_memory_registry.py`

**Interfaces:**
- Consumes: `MemorySettings`, `StoreConfig`, `create_backend`, `MemoryStore`, `create_embeddings_from_subentry`, `RetentionTask`, `MemoryLogbookPoller`, `SUBENTRY_TYPE_EMBEDDINGS`.
- Produces: `MemoryRegistry(hass)` with `async build(settings, storage_dir) -> None`, `async shutdown() -> None`, `get(name: str | None) -> MemoryStore | None`, `names() -> list[str]`, `describe() -> list[tuple[str, str]]`, `stores_for_conversation_ingest() -> list[MemoryStore]`, and the `stores: dict[str, MemoryStore]` attribute. Tasks 16 and 17 consume all of these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_registry.py`:

```python
"""MemoryRegistry resolves embeddings references and owns per-store tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
)
from custom_components.smartchain.tools.memory.config import (
    BackendConfig,
    MemorySettings,
    StoreConfig,
)
from custom_components.smartchain.tools.memory.registry import MemoryRegistry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry_with_embeddings(hass: HomeAssistant, titles: list[str]) -> MockConfigEntry:
    from homeassistant.config_entries import ConfigSubentryData

    from custom_components.smartchain.const import SUBENTRY_TYPE_EMBEDDINGS

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "Embeddings"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title=title,
                unique_id=None,
            )
            for title in titles
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def patched_store():
    """Patch MemoryStore so no real backend or embeddings provider is needed."""
    made: list[MagicMock] = []

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.backend = backend
        made.append(st)
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry."
            "create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield made


async def test_build_resolves_reference_by_title(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["GigaChat Embeddings"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[StoreConfig(name="conversations", embeddings="GigaChat Embeddings")]
        ),
        tmp_path,
    )
    assert registry.names() == ["conversations"]
    assert registry.get("conversations") is not None
    await registry.shutdown()


async def test_missing_reference_skips_only_that_store(
    hass: HomeAssistant, tmp_path, patched_store, caplog
) -> None:
    _entry_with_embeddings(hass, ["GigaChat Embeddings"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="good", embeddings="GigaChat Embeddings"),
                StoreConfig(name="bad", embeddings="Does Not Exist"),
            ]
        ),
        tmp_path,
    )
    assert registry.names() == ["good"]
    assert "Does Not Exist" in caplog.text
    assert "GigaChat Embeddings" in caplog.text  # available titles are listed
    await registry.shutdown()


async def test_duplicate_titles_skip_the_store(
    hass: HomeAssistant, tmp_path, patched_store, caplog
) -> None:
    _entry_with_embeddings(hass, ["Dup", "Dup"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="s", embeddings="Dup")]), tmp_path
    )
    assert registry.names() == []
    assert "duplicate" in caplog.text.lower()
    await registry.shutdown()


async def test_get_none_returns_single_store(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="only", embeddings="E")]), tmp_path
    )
    assert registry.get(None) is registry.get("only")
    await registry.shutdown()


async def test_get_none_is_ambiguous_with_two_stores(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="a", embeddings="E"),
                StoreConfig(name="b", embeddings="E"),
            ]
        ),
        tmp_path,
    )
    assert registry.get(None) is None
    await registry.shutdown()


async def test_unavailable_store_is_not_registered(
    hass: HomeAssistant, tmp_path
) -> None:
    _entry_with_embeddings(hass, ["E"])

    def _factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = False
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry."
            "create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(stores=[StoreConfig(name="s", embeddings="E")]), tmp_path
        )
    assert registry.names() == []
    await registry.shutdown()


async def test_describe_returns_names_and_descriptions(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[StoreConfig(name="a", embeddings="E", description="First store")]
        ),
        tmp_path,
    )
    assert registry.describe() == [("a", "First store")]
    await registry.shutdown()


async def test_conversation_ingest_targets_respect_the_flag(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="yes", embeddings="E", ingest_conversation=True),
                StoreConfig(name="no", embeddings="E", ingest_conversation=False),
            ]
        ),
        tmp_path,
    )
    targets = registry.stores_for_conversation_ingest()
    assert len(targets) == 1
    assert targets[0] is registry.get("yes")
    await registry.shutdown()


async def test_shutdown_closes_every_store(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="a", embeddings="E"),
                StoreConfig(name="b", embeddings="E"),
            ]
        ),
        tmp_path,
    )
    await registry.shutdown()

    assert registry.names() == []
    for store in patched_store:
        store.close.assert_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_registry.py -v`
Expected: `ModuleNotFoundError` for `tools.memory.registry`.

- [ ] **Step 3: Implement `registry.py`**

Create `custom_components/smartchain/tools/memory/registry.py`:

```python
"""MemoryRegistry — owns every configured store and its background tasks."""

import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from ...const import DOMAIN, SUBENTRY_TYPE_EMBEDDINGS
from .backends import BackendInitError, create_backend
from .config import MemorySettings, StoreConfig
from .embeddings import EmbeddingsConfigError, create_embeddings_from_subentry
from .ingest import MemoryLogbookPoller
from .retention import RetentionTask
from .store import MemoryStore

LOGGER = logging.getLogger(__name__)


class MemoryRegistry:
    """Maps store names to live MemoryStore instances.

    A failure in one store is contained: it is logged, that store is skipped,
    and every other store still builds.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.stores: dict[str, MemoryStore] = {}
        self._configs: dict[str, StoreConfig] = {}
        self._retention: dict[str, RetentionTask] = {}
        self._pollers: dict[str, MemoryLogbookPoller] = {}

    # ----- construction -----

    def _embeddings_subentries(self) -> dict[str, tuple[ConfigEntry, ConfigSubentry] | None]:
        """Collect embeddings subentries by title across all SmartChain entries.

        A title claimed by more than one subentry maps to None, so the caller
        can refuse to bind rather than pick an arbitrary one.
        """
        found: dict[str, tuple[ConfigEntry, ConfigSubentry] | None] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for subentry in (entry.subentries or {}).values():
                if subentry.subentry_type != SUBENTRY_TYPE_EMBEDDINGS:
                    continue
                if subentry.title in found:
                    found[subentry.title] = None
                else:
                    found[subentry.title] = (entry, subentry)
        return found

    async def build(self, settings: MemorySettings, storage_dir: Path) -> None:
        """Construct every configured store. Never raises."""
        available = self._embeddings_subentries()

        for config in settings.stores:
            binding = available.get(config.embeddings, "__missing__")

            if binding == "__missing__":
                LOGGER.error(
                    "Memory store %r references embeddings subentry %r, which does "
                    "not exist. Available: %s",
                    config.name,
                    config.embeddings,
                    sorted(available) or "none",
                )
                continue
            if binding is None:
                LOGGER.error(
                    "Memory store %r references embeddings subentry %r, but that "
                    "title is duplicated across config entries. Rename one of them.",
                    config.name,
                    config.embeddings,
                )
                continue

            entry, subentry = binding
            try:
                embeddings = create_embeddings_from_subentry(self.hass, entry, subentry)
            except EmbeddingsConfigError as err:
                LOGGER.error("Memory store %r disabled: %s", config.name, err)
                continue

            try:
                backend = create_backend(
                    self.hass, config.backend, config.name, storage_dir
                )
            except BackendInitError as err:
                LOGGER.error("Memory store %r disabled: %s", config.name, err)
                continue

            store = MemoryStore(self.hass, embeddings, backend)
            await store.async_setup()
            if not store.is_available:
                LOGGER.error(
                    "Memory store %r did not come up; see earlier log lines.",
                    config.name,
                )
                continue

            self.stores[config.name] = store
            self._configs[config.name] = config

            retention = RetentionTask(self.hass, store, config.retention_days)
            retention.start()
            self._retention[config.name] = retention

            poller = MemoryLogbookPoller(self.hass, store, config.logbook)
            poller.start()
            self._pollers[config.name] = poller

            LOGGER.info(
                "Memory store %r ready on backend %s", config.name, backend.name
            )

    async def shutdown(self) -> None:
        """Stop every task, then close every backend."""
        for task in self._retention.values():
            await task.stop()
        for poller in self._pollers.values():
            await poller.stop()
        for store in self.stores.values():
            try:
                await store.close()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Error closing a memory store")

        self.stores.clear()
        self._configs.clear()
        self._retention.clear()
        self._pollers.clear()

    # ----- lookup -----

    def get(self, name: str | None) -> MemoryStore | None:
        """Look up a store. `None` resolves only when exactly one is configured."""
        if name is None:
            if len(self.stores) == 1:
                return next(iter(self.stores.values()))
            return None
        return self.stores.get(name)

    def names(self) -> list[str]:
        return list(self.stores)

    def describe(self) -> list[tuple[str, str]]:
        """(name, description) pairs, for the search_memory tool schema."""
        return [(name, self._configs[name].description) for name in self.stores]

    def stores_for_conversation_ingest(self) -> list[MemoryStore]:
        return [
            store
            for name, store in self.stores.items()
            if self._configs[name].ingest_conversation
        ]

    def config_for(self, name: str) -> StoreConfig | None:
        return self._configs.get(name)

    def __len__(self) -> int:
        return len(self.stores)
```

- [ ] **Step 4: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_registry.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/registry.py tests/test_memory_registry.py
git commit -m "feat(memory): MemoryRegistry with per-store isolation"
```

---

### Task 16: Wire the registry into `__init__.py`

**Files:**
- Modify: `custom_components/smartchain/__init__.py`
- Modify: `custom_components/smartchain/tools/memory/ingest.py`
- Modify: `custom_components/smartchain/conversation.py`
- Modify: `tests/test_memory_integration.py`
- Create: `tests/test_memory_multi_store.py`

**Interfaces:**
- Consumes: `MemoryRegistry`, `LoaderResult.memory_settings`.
- Produces: `hass.data[DOMAIN]["memory"]` now holds a `MemoryRegistry` rather than a `MemoryStore | None`. `ingest_conversation_turn(stores: list[MemoryStore], user_text, assistant_text, metadata)` takes a list. Task 17 reads the registry from `hass.data`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_multi_store.py`:

```python
"""End-to-end multi-store wiring through hass.data."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_EMBEDDINGS,
)
from custom_components.smartchain.tools.memory.registry import MemoryRegistry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_YAML = """
tools: []
memory:
  stores:
    - name: conversations
      description: "Dialogue history"
      embeddings: "GigaChat Embeddings"
      ingest_conversation: true
    - name: entities
      description: "Devices"
      embeddings: "GigaChat Embeddings"
      ingest_conversation: false
"""


@pytest.fixture
def patched_store():
    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.add = AsyncMock(return_value=["id"])
        st.search = AsyncMock(return_value=[])
        st.clear = AsyncMock(return_value=3)
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry."
            "create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield


async def _setup(hass: HomeAssistant, tmp_path_factory, mock_llm_client):
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(_YAML)
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "Embeddings"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="GigaChat Embeddings",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_registry_lands_in_hass_data(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory, patched_store
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client)
    registry = hass.data[DOMAIN]["memory"]
    assert isinstance(registry, MemoryRegistry)
    assert sorted(registry.names()) == ["conversations", "entities"]


async def test_only_flagged_stores_receive_conversation_ingest(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory, patched_store
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client)
    registry = hass.data[DOMAIN]["memory"]
    targets = registry.stores_for_conversation_ingest()
    assert len(targets) == 1
    assert targets[0] is registry.get("conversations")


async def test_no_memory_block_yields_empty_registry(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory
) -> None:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text("tools: []\n")
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == []


async def test_ingest_fans_out_to_every_flagged_store(hass: HomeAssistant) -> None:
    from custom_components.smartchain.tools.memory.ingest import (
        ingest_conversation_turn,
    )

    a = MagicMock()
    a.is_available = True
    a.add = AsyncMock(return_value=["1"])
    b = MagicMock()
    b.is_available = True
    b.add = AsyncMock(return_value=["2"])

    await ingest_conversation_turn(
        [a, b],
        user_text="q",
        assistant_text="a",
        metadata={"kind": "conversation", "timestamp": "t"},
    )
    a.add.assert_awaited_once()
    b.add.assert_awaited_once()


async def test_ingest_continues_when_one_store_fails(hass: HomeAssistant, caplog) -> None:
    from custom_components.smartchain.tools.memory.ingest import (
        ingest_conversation_turn,
    )

    bad = MagicMock()
    bad.is_available = True
    bad.add = AsyncMock(side_effect=RuntimeError("provider down"))
    good = MagicMock()
    good.is_available = True
    good.add = AsyncMock(return_value=["1"])

    await ingest_conversation_turn(
        [bad, good],
        user_text="q",
        assistant_text="a",
        metadata={"kind": "conversation", "timestamp": "t"},
    )
    good.add.assert_awaited_once()
    assert "memory" in caplog.text.lower()


async def test_ingest_with_no_stores_is_a_noop(hass: HomeAssistant) -> None:
    from custom_components.smartchain.tools.memory.ingest import (
        ingest_conversation_turn,
    )

    await ingest_conversation_turn(
        [], user_text="q", assistant_text="a", metadata={"kind": "conversation"}
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_multi_store.py -v`
Expected: failures — `hass.data[DOMAIN]["memory"]` is still a store, and `ingest_conversation_turn` still takes a single store.

- [ ] **Step 3: Make ingest take a list**

In `custom_components/smartchain/tools/memory/ingest.py`, replace `ingest_conversation_turn`:

```python
async def ingest_conversation_turn(
    stores: list[MemoryStore],
    user_text: str,
    assistant_text: str,
    metadata: dict[str, Any],
) -> None:
    """Embed and persist one user+assistant exchange into every given store.

    Failures are logged at WARNING and never propagated — ingestion must not
    affect the user-facing conversation response. One failing store does not
    prevent the others from being written.
    """
    if not stores or not assistant_text:
        return

    combined = f"User: {user_text or ''}\n\nAssistant: {assistant_text}"
    for store in stores:
        if not store.is_available:
            continue
        try:
            await store.add(combined, metadata)
        except Exception:  # noqa: BLE001
            LOGGER.warning("smartchain memory ingest failed for a store", exc_info=True)
```

- [ ] **Step 4: Update `__init__.py`**

Replace the memory portion of `_reload_registry` and delete `_build_memory` entirely — the registry now owns construction:

```python
async def _reload_registry(hass: HomeAssistant) -> int:
    """Re-read tools.yaml into the registry. Raises LoaderError on failure."""
    path = _tools_yaml_path(hass)
    result = await hass.async_add_executor_job(load_tools_file, path)
    registry: ToolRegistry = hass.data[DOMAIN]["tools"]
    registry.replace_all(result.yaml_tools)

    manager: MCPManager | None = hass.data[DOMAIN].get("mcp_manager")
    if manager is not None:
        await manager.stop()
        manager.configure(result.mcp_servers)
        await manager.start()

    # --- Memory subsystem: build first, swap only on success ---
    try:
        new_memory = MemoryRegistry(hass)
        await new_memory.build(result.memory_settings, _memory_persist_dir(hass))
    except Exception:  # noqa: BLE001
        LOGGER.exception("memory rebuild failed; keeping the previous registry")
    else:
        old_memory: MemoryRegistry | None = hass.data[DOMAIN].get("memory")
        if old_memory is not None:
            await old_memory.shutdown()
        hass.data[DOMAIN]["memory"] = new_memory

    return len(result.yaml_tools)
```

In `async_setup`, seed an empty registry next to the tool registry so the key always exists:

```python
    if "memory" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["memory"] = MemoryRegistry(hass)
```

Replace the `_handle_clear_memory` body:

```python
    async def _handle_clear_memory(call: ServiceCall) -> None:
        registry: MemoryRegistry | None = hass.data.get(DOMAIN, {}).get("memory")
        if registry is None or not len(registry):
            raise HomeAssistantError("smartchain memory is not configured")

        requested = call.data.get("store")
        if requested is not None and requested not in registry.names():
            raise HomeAssistantError(
                f"unknown memory store {requested!r}; configured: {registry.names()}"
            )
        targets = [requested] if requested else registry.names()

        kind = call.data.get("kind", "any")
        agent_id = call.data.get("agent_id")
        where: dict[str, Any] = {}
        if kind != "any":
            where["kind"] = kind
        if agent_id:
            where["agent_id"] = agent_id

        deleted = 0
        for name in targets:
            store = registry.get(name)
            if store is not None:
                deleted += await store.clear(where or None)

        hass.bus.async_fire(
            EVENT_MEMORY_CLEARED, {"deleted": deleted, "stores": targets}
        )
```

Extend its schema with `vol.Optional("store"): str`.

In `async_unload_entry`, replace the retention/poller teardown with a single registry shutdown:

```python
    if not remaining:
        memory: MemoryRegistry | None = hass.data.get(DOMAIN, {}).get("memory")
        if memory is not None:
            await memory.shutdown()
```

Update imports: add `from .tools.memory.registry import MemoryRegistry`; drop the now-unused `RetentionTask`, `MemoryLogbookPoller`, `MemoryStore`, `create_embeddings`, `EmbeddingsConfigError`, `create_backend`, `BackendInitError` and `_memory_store_mod` — the registry owns all of it. Keep `_memory_persist_dir`.

- [ ] **Step 5: Update `conversation.py`**

The ingest call site now reads the registry. Replace the `memory_store` lookup and the ingest block:

```python
        memory_registry: MemoryRegistry | None = self.hass.data.get(DOMAIN, {}).get("memory")
        memory_enabled = memory_registry is not None and len(memory_registry) > 0
```

and, at the end of `_async_handle_message`:

```python
        if memory_enabled:
            ingest_targets = memory_registry.stores_for_conversation_ingest()
            assistant_text = ""
            for content in reversed(chat_log.content):
                if isinstance(content, AssistantContent) and content.content:
                    assistant_text = content.content
                    break
            if assistant_text and ingest_targets:
                self.hass.async_create_background_task(
                    ingest_conversation_turn(
                        ingest_targets,
                        user_text=user_input.text or "",
                        assistant_text=assistant_text,
                        metadata={
                            "kind": "conversation",
                            "timestamp": dt_util.utcnow().isoformat(),
                            "agent_id": user_input.agent_id,
                            "subentry_id": self._subentry_id or "",
                            "conversation_id": chat_log.conversation_id,
                        },
                    ),
                    name="smartchain_memory_ingest",
                )
```

The per-store `ingest_conversation` flag replaces the old `memory_config.ingest_conversation` check, so the `memory_config` lookup added in v4.3.0 is removed along with its `hass.data[DOMAIN]["memory_config"]` key.

Update imports: `from .tools.memory.registry import MemoryRegistry` replaces `from .tools.memory import MemoryStore`.

- [ ] **Step 6: Update `tests/test_memory_integration.py`**

Its two tests assert on `hass.data[DOMAIN]["memory"]` being a store or `None`, and its fixture patches the old `MemoryStore` import site. Replace the whole file:

```python
"""End-to-end: memory YAML -> registry in hass.data."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_EMBEDDINGS,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_YAML_WITH_STORE = """
tools: []
memory:
  stores:
    - name: conversations
      embeddings: "GigaChat Embeddings"
"""


@pytest.fixture
def fake_memory_store():
    """Patch the registry's collaborators so no real backend is opened."""

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry."
            "create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield


async def _setup(hass: HomeAssistant, tmp_path_factory, mock_llm_client, yaml: str):
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(yaml)
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "Embeddings"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="GigaChat Embeddings",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_memory_enabled_via_yaml_lands_in_registry(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory, fake_memory_store
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client, _YAML_WITH_STORE)
    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == ["conversations"]


async def test_memory_disabled_when_yaml_lacks_block(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client, "tools: []\n")
    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == []
```

- [ ] **Step 7: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_multi_store.py tests/test_memory_integration.py tests/test_memory_clear_service.py tests/test_tools_reload.py tests/test_mcp_reload.py -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add -A
git commit -m "feat(memory): registry replaces the single store in hass.data"
```

---

### Task 17: `store` parameter on the tool and the service

**Files:**
- Modify: `custom_components/smartchain/tools/memory/search_tool.py`
- Modify: `custom_components/smartchain/conversation.py`
- Modify: `tests/test_memory_search_tool.py`, `tests/test_memory_clear_service.py`

**Interfaces:**
- Consumes: `MemoryRegistry.get`, `.names`, `.describe`.
- Produces: `get_memory_tool_definition(registry: MemoryRegistry) -> dict` — now takes the registry so the schema can carry the store enum and descriptions. `execute_memory_search(hass, query, top_k=5, kind="any", subentry_id=None, store=None) -> str`.

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_memory_search_tool.py`:

```python
"""search_memory routes to a named store and describes what each one holds."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN, MEMORY_TOOL_NAME
from custom_components.smartchain.tools.memory.search_tool import (
    execute_memory_search,
    get_memory_tool_definition,
)
from custom_components.smartchain.tools.memory.store import MemorySnippet


def _registry(entries: dict[str, str], stores: dict[str, MagicMock] | None = None):
    """A stub registry: {name: description} plus optional store mocks."""
    made = stores or {name: MagicMock() for name in entries}
    reg = MagicMock()
    reg.names.return_value = list(entries)
    reg.describe.return_value = list(entries.items())
    reg.__len__.return_value = len(entries)
    reg.get.side_effect = lambda name: (
        made.get(name)
        if name is not None
        else (next(iter(made.values())) if len(made) == 1 else None)
    )
    return reg, made


def _store_returning(snippets: list[MemorySnippet]) -> MagicMock:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(return_value=snippets)
    return store


def test_definition_has_no_store_enum_for_a_single_store() -> None:
    reg, _ = _registry({"only": "The one store"})
    spec = get_memory_tool_definition(reg)
    assert spec["name"] == MEMORY_TOOL_NAME
    assert "store" not in spec["parameters"].get("required", [])


def test_definition_requires_store_when_several_exist() -> None:
    reg, _ = _registry({"a": "First", "b": "Second"})
    spec = get_memory_tool_definition(reg)
    assert spec["parameters"]["properties"]["store"]["enum"] == ["a", "b"]
    assert "store" in spec["parameters"]["required"]


def test_definition_embeds_store_descriptions() -> None:
    reg, _ = _registry({"a": "Dialogue history", "b": "Devices and sensors"})
    spec = get_memory_tool_definition(reg)
    text = spec["description"] + spec["parameters"]["properties"]["store"]["description"]
    assert "Dialogue history" in text
    assert "Devices and sensors" in text


async def test_execute_routes_to_the_named_store(hass: HomeAssistant) -> None:
    hit = MemorySnippet(text="from B", score=0.9, metadata={"kind": "logbook", "timestamp": "t"})
    store_a = _store_returning([])
    store_b = _store_returning([hit])
    reg, _ = _registry({"a": "", "b": ""}, {"a": store_a, "b": store_b})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x", store="b")
    assert "from B" in result
    store_a.search.assert_not_awaited()
    store_b.search.assert_awaited_once()


async def test_execute_defaults_to_the_only_store(hass: HomeAssistant) -> None:
    hit = MemorySnippet(text="only", score=0.9, metadata={"kind": "conversation", "timestamp": "t"})
    store = _store_returning([hit])
    reg, _ = _registry({"only": ""}, {"only": store})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x")
    assert "only" in result


async def test_execute_rejects_unknown_store_by_name(hass: HomeAssistant) -> None:
    reg, _ = _registry({"a": ""})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x", store="ghost")
    assert "ghost" in result
    assert "a" in result  # the available names are listed back to the model


async def test_execute_asks_for_a_store_when_ambiguous(hass: HomeAssistant) -> None:
    reg, _ = _registry({"a": "", "b": ""})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x")
    assert "store" in result.lower()


async def test_execute_returns_not_configured_for_empty_registry(
    hass: HomeAssistant,
) -> None:
    reg, _ = _registry({})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg
    assert "not configured" in (await execute_memory_search(hass, query="x")).lower()


async def test_execute_still_filters_by_kind_and_subentry(hass: HomeAssistant) -> None:
    store = _store_returning([])
    reg, _ = _registry({"only": ""}, {"only": store})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    await execute_memory_search(hass, query="x", kind="logbook", subentry_id="s1")
    where = store.search.call_args.kwargs["where"]
    assert where == {"kind": "logbook", "subentry_id": "s1"}


async def test_execute_returns_failure_string_on_exception(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(side_effect=RuntimeError("boom"))
    reg, _ = _registry({"only": ""}, {"only": store})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x")
    assert "lookup failed" in result.lower()
    assert "boom" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_search_tool.py -v`
Expected: failures — the definition takes no argument and the executor has no `store`.

- [ ] **Step 3: Rewrite `search_tool.py`**

Replace `custom_components/smartchain/tools/memory/search_tool.py`:

```python
"""Built-in `search_memory` LLM tool, routed across named stores."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import DOMAIN, MEMORY_TOOL_NAME

LOGGER = logging.getLogger(__name__)


def get_memory_tool_definition(registry: Any) -> dict[str, Any]:
    """Build the tool schema from the live registry.

    Store names and their descriptions go into the schema so the model can
    choose the right one instead of guessing.
    """
    described = registry.describe()
    names = [name for name, _desc in described]

    catalogue = "; ".join(
        f"{name}: {desc}" if desc else name for name, desc in described
    )
    description = (
        "Search long-term memory for past conversations and home events. Use "
        "this when the user asks about something said earlier or events from "
        "the past."
    )
    if catalogue:
        description += f" Available stores — {catalogue}."

    properties: dict[str, Any] = {
        "query": {"type": "string", "description": "Natural-language query."},
        "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        "kind": {
            "type": "string",
            "enum": ["conversation", "logbook", "any"],
            "default": "any",
        },
    }
    required = ["query"]

    if names:
        properties["store"] = {
            "type": "string",
            "enum": names,
            "description": f"Which memory store to search. {catalogue}",
        }
        # With one store the parameter is inferable, so leave it optional.
        if len(names) > 1:
            required.append("store")

    return {
        "name": MEMORY_TOOL_NAME,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


async def execute_memory_search(
    hass: HomeAssistant,
    query: str,
    top_k: int = 5,
    kind: str = "any",
    subentry_id: str | None = None,
    store: str | None = None,
) -> str:
    domain_data = hass.data.get(DOMAIN) or {}
    registry = domain_data.get("memory")
    if registry is None or not len(registry):
        return "Memory is not configured for this installation."

    if store is not None and store not in registry.names():
        return (
            f"Unknown memory store {store!r}. Configured stores: "
            f"{', '.join(registry.names())}."
        )

    target = registry.get(store)
    if target is None:
        return (
            "Several memory stores are configured — pass the `store` parameter. "
            f"Available: {', '.join(registry.names())}."
        )

    where: dict[str, Any] = {}
    if kind != "any":
        where["kind"] = kind
    if subentry_id:
        where["subentry_id"] = subentry_id

    try:
        snippets = await target.search(query, top_k=top_k, where=where or None)
    except Exception:  # noqa: BLE001
        LOGGER.exception("memory search failed")
        return "Memory lookup failed; see logs."

    if not snippets:
        return "No memories matched the query."

    lines = [f"Found {len(snippets)} memories:"]
    for index, snip in enumerate(snippets, start=1):
        ts = (snip.metadata or {}).get("timestamp", "?")
        kind_label = (snip.metadata or {}).get("kind", "?")
        first_line = snip.text.replace("\n", " ").strip()
        if len(first_line) > 400:
            first_line = first_line[:400] + "…"
        lines.append(f"{index}. [{ts}, {kind_label}] {first_line}")
    return "\n".join(lines)
```

- [ ] **Step 4: Update the `conversation.py` call sites**

`get_memory_tool_definition` now needs the registry, and the dispatcher passes `store`:

```python
        if memory_enabled:
            tools.append(get_memory_tool_definition(memory_registry))
```

and in the tool-call handler:

```python
                            result_text = await execute_memory_search(
                                self.hass,
                                query=args.get("query", ""),
                                top_k=int(args.get("top_k", 5)),
                                kind=str(args.get("kind", "any")),
                                subentry_id=self._subentry_id,
                                store=args.get("store"),
                            )
```

- [ ] **Step 5: Update the clear-service tests**

Append to `tests/test_memory_clear_service.py`. The existing "not configured" test stays as it is; these cover the new parameter:

```python
_TWO_STORES_YAML = """
tools: []
memory:
  stores:
    - name: conversations
      embeddings: "GigaChat Embeddings"
    - name: entities
      embeddings: "GigaChat Embeddings"
"""


@pytest.fixture
def two_stores(hass: HomeAssistant, tools_dir):
    """Two configured stores, each backed by a mock that reports 3 deletions."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from homeassistant.config_entries import ConfigSubentryData
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.smartchain.const import (
        CONF_API_KEY,
        CONF_ENGINE,
        ID_GIGACHAT,
        SUBENTRY_TYPE_EMBEDDINGS,
    )

    (tools_dir / "tools.yaml").write_text(_TWO_STORES_YAML)

    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "Embeddings"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="GigaChat Embeddings",
                unique_id=None,
            )
        ],
    ).add_to_hass(hass)

    def _factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.clear = AsyncMock(return_value=3)
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry."
            "create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield


async def test_clear_memory_targets_one_store(
    hass: HomeAssistant, two_stores
) -> None:
    """Passing `store` clears only that store."""
    await async_setup(hass, {})

    events: list = []
    hass.bus.async_listen(EVENT_MEMORY_CLEARED, lambda e: events.append(e))

    await hass.services.async_call(
        DOMAIN, SERVICE_CLEAR_MEMORY, {"store": "conversations"}, blocking=True
    )
    await hass.async_block_till_done()

    assert events[0].data["stores"] == ["conversations"]
    assert events[0].data["deleted"] == 3


async def test_clear_memory_without_store_clears_all(
    hass: HomeAssistant, two_stores
) -> None:
    await async_setup(hass, {})

    events: list = []
    hass.bus.async_listen(EVENT_MEMORY_CLEARED, lambda e: events.append(e))

    await hass.services.async_call(DOMAIN, SERVICE_CLEAR_MEMORY, {}, blocking=True)
    await hass.async_block_till_done()

    assert sorted(events[0].data["stores"]) == ["conversations", "entities"]
    assert events[0].data["deleted"] == 6


async def test_clear_memory_unknown_store_raises(
    hass: HomeAssistant, two_stores
) -> None:
    await async_setup(hass, {})
    with pytest.raises(HomeAssistantError, match="ghost"):
        await hass.services.async_call(
            DOMAIN, SERVICE_CLEAR_MEMORY, {"store": "ghost"}, blocking=True
        )
```

- [ ] **Step 6: Run tests**

Run: `uv run --prerelease=allow pytest tests/test_memory_search_tool.py tests/test_memory_clear_service.py -v`
Expected: all pass.

- [ ] **Step 7: Full suite and commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
git add -A
git commit -m "feat(memory): store parameter on search_memory and clear_memory"
```

---

### Task 18: Version bump, CHANGELOG and documentation

**Files:**
- Modify: `custom_components/smartchain/manifest.json`, `pyproject.toml`, `uv.lock`
- Modify: `CHANGELOG.md`
- Modify: `docs/USAGE.md`, `docs/USAGE-ru.md`
- Modify: `README.md`, `README-ru.md`

**Interfaces:**
- Consumes: everything.
- Produces: the v4.5.0 release.

- [ ] **Step 1: Bump the version**

`custom_components/smartchain/manifest.json`: `"version": "4.4.2"` → `"version": "4.5.0"`.
`pyproject.toml`: `version = "4.4.2"` → `version = "4.5.0"`.

Run: `uv lock --prerelease=allow`

- [ ] **Step 2: Prepend the CHANGELOG entry**

Insert above the existing `## [4.4.2]` heading:

```markdown
## [4.5.0] - 2026-08-23

### ⚠ BREAKING CHANGES

**Chroma is removed.** `chromadb` and `langchain-chroma` are gone from the manifest and the codebase. If `<config>/.storage/smartchain_memory/` exists from an earlier version it is now orphaned and can be deleted — no data is converted. In practice the directory is empty on most installations, because HA's pip step could not install `chromadb` (which is why v4.4.1 had to make it optional).

**The `memory:` block has a new shape.** Credentials no longer live in `tools.yaml`, so the flat block with `provider` / `model` / `api_key` is rejected with an error naming the migration steps. There is no automatic migration: until you create an embeddings subentry there is nothing for the config to point at.

Migration:
1. Open the provider's config entry and add an **embeddings** subentry, giving it a name and choosing an embedding model.
2. Replace the `memory:` block with a `stores:` list whose `embeddings:` field holds that name.
3. Call `smartchain.reload_tools`.

### Added
- **Four pluggable vector backends** behind one `VectorBackend` Protocol: `sqlite_numpy` (default), `sqlite_vec`, `pgvector` and `qdrant`. The default needs **no dependency beyond what Home Assistant already ships** — stdlib `sqlite3` for storage and numpy for cosine similarity — so long-term memory now works out of the box on every installation. `qdrant` also adds no dependency: it speaks REST over HA's shared aiohttp session.
- **Embeddings as a provider capability.** A new `embeddings` subentry type sits alongside `conversation` and reuses the config entry's credentials, ending the duplicate credential declaration the flat YAML block required. It is offered only where the provider supports it — DeepSeek and Anthropic expose no embeddings API and do not show the option.
- **Purpose-filtered model discovery.** The existing provider model APIs are now split by purpose, so the embeddings form lists `text-embedding-*` for OpenAI, `Embeddings*` for GigaChat and the embedding families for Ollama, while chat forms stop offering embedding models by mistake.
- **Named memory stores.** `memory.stores[]` binds one embeddings subentry to one backend, each with its own retention, logbook polling and conversation-ingest flag. `search_memory` and `smartchain.clear_memory` take a `store` parameter; with a single store it stays optional.
- **Dimension probing.** The embedding dimension is measured at startup and persisted per store. Changing to a model of a different dimension is detected and reported with exact remediation steps instead of corrupting the index.

### Changed
- `hass.data[DOMAIN]["memory"]` now holds a `MemoryRegistry` rather than a single `MemoryStore`.
- `smartchain_memory_cleared` now carries `{"deleted": <int>, "stores": [<names>]}`.
- The Chroma `$and` filter dialect is replaced by a flat backend-neutral filter, translated per backend.

### Tests
- ~345 passing (was 289). The centrepiece is a conformance suite executed against every backend, so the Protocol cannot drift between implementations.
```

- [ ] **Step 3: Rewrite the memory section of `docs/USAGE.md`**

Replace §9 with content covering: creating an embeddings subentry (with the capability caveat), the `stores:` YAML shape with both examples from the spec, a backend comparison table, dimension-change remediation, and the `store` parameter on the tool and the service. State plainly that `sqlite_numpy` needs no installation step, and that `pgvector` needs `asyncpg` plus a database whose user may run `CREATE EXTENSION`.

Delete the v4.3.0 note instructing users to `pip install chromadb`; replace it with the backend table:

| Backend | Extra install | When to use |
|---|---|---|
| `sqlite_numpy` | none | Default. Every installation. Up to ~50 000 records per store. |
| `sqlite_vec` | `pip install sqlite-vec` | Same file layout, native KNN. Needs a Python build with extension loading. |
| `pgvector` | `pip install asyncpg` + PostgreSQL | Large stores; natural if HA's recorder already runs on PostgreSQL. |
| `qdrant` | a Qdrant server | Large stores without PostgreSQL. No Python dependency. |

- [ ] **Step 4: Mirror the section in `docs/USAGE-ru.md`**

Same structure and the same table, in Russian. Keep the YAML examples byte-identical to the English file so they can be copied either way.

- [ ] **Step 5: Update the README feature lists**

In `README.md` and `README-ru.md`, replace the memory bullet with one naming the four backends and the embeddings subentry, and add the v4.5.0 row to the "What's new" table:

```markdown
| **v4.5.0** | Pluggable vector backends (sqlite_numpy / sqlite_vec / pgvector / qdrant), embeddings as a provider capability, named multi-stores |
```

Update the tests badge in both files from `289+` to `345+`.

- [ ] **Step 6: Final smoke**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
grep -rn "chromadb\|langchain_chroma\|langchain-chroma" custom_components/ tests/ pyproject.toml manifest.json 2>/dev/null || echo "no chroma references"
```
Expected: all green; the grep prints `no chroma references`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: bump version to 4.5.0 and document vector backends"
```

---

## Out of scope (deferred)

- Cross-store federated search in a single `search_memory` call.
- Automatic re-embedding when a store's embeddings subentry changes.
- Further backends — Milvus, Weaviate, Redis, Elasticsearch.
- Vision as a declared provider capability.
- Managing stores and embeddings subentries from the SmartChain panel — roadmap subsystem **D**.
- Entity indexing consuming a dedicated store — roadmap subsystem **B**.
