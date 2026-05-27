"""MemoryStore (Chroma facade) + text-chunking helpers."""

from dataclasses import dataclass
from typing import Any

from ...const import (
    MEMORY_CHUNK_OVERLAP,
    MEMORY_CHUNK_SIZE,
    MEMORY_MAX_TEXT_LEN,
)


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
    """Stub — full implementation in Task 5."""
