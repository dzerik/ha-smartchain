"""MemoryStore (Chroma facade) + text-chunking helpers (stub — Task 5)."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemorySnippet:
    text: str
    score: float
    metadata: dict[str, Any]


class MemoryStore:
    """Stub — full implementation in Task 5."""
