"""Pluggable EmbeddingsProvider factory for the memory subsystem."""

import logging
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
from langchain_gigachat import GigaChatEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

from .config import MemoryConfig

LOGGER = logging.getLogger(__name__)


class EmbeddingsConfigError(Exception):
    """Raised when MemoryConfig cannot be turned into a working provider."""


class EmbeddingsProvider(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class _ExecutorBacked:
    """Generic wrapper turning a sync LangChain Embeddings into the async Protocol."""

    def __init__(self, hass: HomeAssistant, inner: Any) -> None:
        self._hass = hass
        self._inner = inner

    async def embed_query(self, text: str) -> list[float]:
        return await self._hass.async_add_executor_job(self._inner.embed_query, text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._hass.async_add_executor_job(self._inner.embed_documents, texts)


def create_embeddings(hass: HomeAssistant, config: MemoryConfig) -> EmbeddingsProvider:
    """Build an EmbeddingsProvider for the configured backend.

    Raises EmbeddingsConfigError when required credentials are missing or the
    provider name is unknown.
    """
    provider = config.provider
    if provider == "ollama":
        kwargs: dict[str, Any] = {"model": config.model}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        return _ExecutorBacked(hass, OllamaEmbeddings(**kwargs))
    if provider == "openai":
        if not config.api_key:
            raise EmbeddingsConfigError("openai embeddings require `api_key` in memory: block")
        return _ExecutorBacked(hass, OpenAIEmbeddings(model=config.model, api_key=config.api_key))
    if provider == "gigachat":
        if not config.api_key:
            raise EmbeddingsConfigError(
                "gigachat embeddings require `api_key` (credentials) in memory: block"
            )
        gc_kwargs: dict[str, Any] = {
            "credentials": config.api_key,
            "model": config.model,
            "verify_ssl_certs": False,
        }
        if config.base_url:
            gc_kwargs["base_url"] = config.base_url
        return _ExecutorBacked(hass, GigaChatEmbeddings(**gc_kwargs))
    if provider == "yandex":
        if not config.api_key:
            raise EmbeddingsConfigError(
                "yandex embeddings require `api_key` (IAM token) in memory: block"
            )
        # Lazy import — only when actually requested.
        from .embeddings_yandex import YandexEmbeddingsAdapter

        return _ExecutorBacked(
            hass, YandexEmbeddingsAdapter(api_key=config.api_key, model=config.model)
        )
    raise EmbeddingsConfigError(f"unknown provider {provider!r}")
