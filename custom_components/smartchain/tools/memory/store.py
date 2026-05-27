"""MemoryStore (Chroma facade) + text-chunking helpers."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import (
    MEMORY_CHUNK_OVERLAP,
    MEMORY_CHUNK_SIZE,
    MEMORY_MAX_TEXT_LEN,
)

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
    """Persistent vector store backed by ChromaDB.

    All Chroma calls are blocking; this class wraps them via
    `hass.async_add_executor_job` to keep the HA loop responsive.
    """

    _COLLECTION = "smartchain_memory"

    def __init__(self, hass: HomeAssistant, embeddings: Any, persist_dir: Path) -> None:
        self.hass = hass
        self.embeddings = embeddings
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None
        self.is_available = False
        self._init_collection()

    def _init_collection(self) -> None:
        try:
            import chromadb  # noqa: PLC0415
            from chromadb.config import Settings  # noqa: PLC0415

            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(self._COLLECTION)
            self.is_available = True
        except Exception:  # noqa: BLE001
            LOGGER.exception(
                "Failed to initialise Chroma persistent client at %s; memory subsystem disabled",
                self.persist_dir,
            )
            self.is_available = False

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
        embeddings = await self.embeddings.embed_documents(chunks)
        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for index, _chunk in enumerate(chunks):
            this_id = (
                doc_id
                if doc_id is not None and len(chunks) == 1
                else f"{doc_id or uuid.uuid4().hex}_chunk{index}"
            )
            ids.append(this_id)
            metadatas.append({**metadata, "chunk_index": index})

        await self.hass.async_add_executor_job(
            self._collection.upsert,
            ids,
            embeddings,
            metadatas,
            chunks,
        )
        return ids

    async def search(
        self,
        query: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[MemorySnippet]:
        if not self.is_available:
            return []
        query_vec = await self.embeddings.embed_query(query)

        def _run() -> Any:
            return self._collection.query(
                query_embeddings=[query_vec],
                n_results=top_k,
                where=where,
            )

        result = await self.hass.async_add_executor_job(_run)
        snippets: list[MemorySnippet] = []
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0] or [0.0] * len(documents)
        for text, meta, dist in zip(documents, metadatas, distances, strict=False):
            snippets.append(
                MemorySnippet(text=text, score=1.0 - float(dist), metadata=dict(meta or {}))
            )
        return snippets

    async def delete_older_than(self, cutoff: datetime) -> int:
        if not self.is_available:
            return 0
        cutoff_iso = cutoff.isoformat()

        def _run() -> int:
            existing = self._collection.get(include=["metadatas"])
            ids = existing.get("ids") or []
            metas = existing.get("metadatas") or []
            to_delete = [
                ident
                for ident, meta in zip(ids, metas, strict=False)
                if (meta or {}).get("timestamp", "") < cutoff_iso
            ]
            if to_delete:
                self._collection.delete(ids=to_delete)
            return len(to_delete)

        return await self.hass.async_add_executor_job(_run)

    async def clear(self, where: dict[str, Any] | None = None) -> int:
        if not self.is_available:
            return 0

        def _run() -> int:
            existing = self._collection.get(where=where, include=["metadatas"])
            ids = existing.get("ids") or []
            if ids:
                self._collection.delete(ids=ids)
            return len(ids)

        return await self.hass.async_add_executor_job(_run)
