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
        # Why `async_setup` gave up, in text safe to show a user: a
        # BackendInitError message (already scrubbed by every backend that
        # raises one) or a bare exception type. Never `str(err)` for an
        # unexpected exception — an embeddings provider's error can carry the
        # API key. `None` until a setup has actually failed.
        self.unavailable_reason: str | None = None

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
            self.unavailable_reason = (
                "the embeddings provider did not answer the dimension probe; "
                "see the Home Assistant log"
            )
            return

        dim = len(probe)
        if dim <= 0:
            # An empty vector is a provider that failed politely, not a
            # zero-dimension store. Accepting it built a store that reported
            # itself healthy and could never match anything.
            LOGGER.error(
                "SmartChain memory: the embeddings provider answered the dimension "
                "probe with an empty vector; this store is disabled"
            )
            self.unavailable_reason = (
                "the embeddings provider answered the dimension probe with an "
                "empty vector; check the configured embeddings model"
            )
            self.is_available = False
            return

        try:
            await self.backend.initialize(dim)
        except BackendInitError as err:
            LOGGER.error("SmartChain memory backend %s disabled: %s", self.backend.name, err)
            # Safe to carry: every backend that raises BackendInitError builds
            # its message from literal text, never from a dsn or an api_key.
            self.unavailable_reason = str(err)
            self.is_available = False
            return
        except Exception as err:  # noqa: BLE001
            LOGGER.exception("SmartChain memory backend %s failed to start", self.backend.name)
            self.unavailable_reason = (
                f"the {self.backend.name} backend raised {type(err).__name__} while "
                "starting; see the Home Assistant log"
            )
            self.is_available = False
            return

        self.dim = dim
        self.unavailable_reason = None
        self.is_available = True

    async def add(
        self,
        text: str,
        metadata: dict[str, Any],
        doc_id: str | None = None,
    ) -> list[str]:
        """Embed and store a text. Returns the list of doc_ids written.

        Raises when the write fails, so a caller can tell "nothing to write"
        from "the write did not happen". `[]` means only the first: an empty
        text, or a store switched off.
        """
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
        except Exception as err:
            # Raised, not swallowed. Returning `[]` here read as "wrote
            # nothing" to a caller that checked, and as nothing at all to the
            # three callers that do not: conversation ingest, whose per-store
            # `except` exists so one dead store does not silence the others;
            # the logbook poller, which counts a row `written` when `add`
            # returns; and the entity indexer, whose sweep must abort before
            # deleting orphans if a write failed. All three were written
            # against a store that raises — and tested against mocks that do.
            #
            # The store itself stays available: this is a runtime failure, not
            # a broken configuration. `type(err).__name__` and never
            # `str(err)`, which for a provider error can carry an API key.
            LOGGER.warning(
                "memory upsert failed on backend %s: %s", self.backend.name, type(err).__name__
            )
            raise
        return [r.doc_id for r in records]

    async def search(
        self,
        query: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[MemorySnippet]:
        """Nearest snippets to `query`.

        Raises when the lookup fails. An empty list is an answer about the
        stored memories — never about the store's health — because both
        callers turn the two cases into different words for the user.
        """
        if not self.is_available:
            return []
        try:
            vector = await self.embeddings.embed_query(query)
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                hits = await self.backend.query(vector, top_k, where)
        except Exception as err:
            # Raised, not swallowed. `[]` from here is indistinguishable from
            # an empty store, and that is exactly what the callers must be
            # able to tell apart: `execute_memory_search` renders "Memory
            # lookup failed; see logs." rather than letting the model report
            # "No memories matched the query.", and `rank_entities` chooses
            # between degrading to lexical hits and failing its own caller.
            # Both handlers were unreachable while this returned `[]`.
            LOGGER.warning(
                "memory search failed on backend %s: %s", self.backend.name, type(err).__name__
            )
            raise

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
        except Exception:  # noqa: BLE001
            LOGGER.exception("memory retention failed on backend %s", self.backend.name)
            return 0

    async def clear(self, where: dict[str, Any] | None = None) -> int:
        if not self.is_available:
            return 0
        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                return await self.backend.delete_where(where)
        except Exception:  # noqa: BLE001
            LOGGER.exception("memory clear failed on backend %s", self.backend.name)
            return 0

    async def list_metadata(
        self, where: dict[str, Any] | None = None
    ) -> dict[str, dict[str, Any]] | None:
        """Stored metadata by doc_id, or `None` when it could not be read.

        `None` and `{}` must stay distinguishable. The entity indexer is the
        only caller, and it reads `{}` as "the store is empty, index the whole
        home" — so collapsing a transport failure, a locked database or a
        closed store into `{}` would make the next sweep re-embed every entity
        in the home, which is the exact cost incremental sweeps exist to avoid.
        """
        if not self.is_available:
            return None
        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                return await self.backend.list_metadata(where)
        except Exception:  # noqa: BLE001 — runtime, store stays up
            LOGGER.exception("memory list_metadata failed")
            return None

    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        """Refresh one document's metadata. Returns False on any failure."""
        if not self.is_available:
            return False
        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                return await self.backend.update_metadata(doc_id, metadata)
        except Exception:  # noqa: BLE001 — runtime, store stays up
            LOGGER.exception("memory update_metadata failed")
            return False

    async def close(self) -> None:
        self.is_available = False
        await self.backend.close()
