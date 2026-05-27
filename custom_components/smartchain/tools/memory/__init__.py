"""SmartChain long-term memory / RAG subsystem (v4.3.0+)."""

from .config import LogbookConfig, MemoryConfig
from .embeddings import EmbeddingsProvider, create_embeddings
from .store import MemorySnippet, MemoryStore

__all__ = [
    "EmbeddingsProvider",
    "LogbookConfig",
    "MemoryConfig",
    "MemorySnippet",
    "MemoryStore",
    "create_embeddings",
]
