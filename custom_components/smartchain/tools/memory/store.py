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
        except Exception:  # noqa: BLE001 — runtime, store stays up
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
        except Exception:  # noqa: BLE001 — runtime, store stays up
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

    async def close(self) -> None:
        self.is_available = False
        await self.backend.close()
