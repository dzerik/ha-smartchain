"""Pluggable EmbeddingsProvider factory for the memory subsystem (stub — Task 3)."""

from typing import Protocol


class EmbeddingsProvider(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


def create_embeddings(hass, config):  # type: ignore[no-untyped-def]
    raise NotImplementedError("embeddings not yet implemented — see Task 3")
