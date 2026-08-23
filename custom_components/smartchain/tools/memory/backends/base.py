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

    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        """Replace one document's metadata without touching its vector.

        Returns True when the document existed. Never re-embeds — being able
        to refresh metadata cheaply is the entire reason this method exists.
        """
        ...

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        """Every stored document's metadata, keyed by doc_id.

        For reconciliation, not for serving queries: callers must pass a
        `where` narrow enough to keep the result bounded.
        """
        ...

    async def delete_older_than(self, cutoff_iso: str) -> int: ...

    async def delete_where(self, where: Filter | None) -> int: ...

    async def close(self) -> None: ...
