"""Pluggable EmbeddingsProvider factory for the memory subsystem."""

import asyncio
import logging
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
from langchain_gigachat import GigaChatEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

from ...client_util import supports
from ...const import (
    CAPABILITY_EMBEDDINGS,
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
    MEMORY_EMBED_TIMEOUT_SECONDS,
)
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
        async with asyncio.timeout(MEMORY_EMBED_TIMEOUT_SECONDS):
            return await self._hass.async_add_executor_job(self._inner.embed_query, text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        async with asyncio.timeout(MEMORY_EMBED_TIMEOUT_SECONDS):
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
        from .embeddings_yandex import YandexEmbeddingsAdapter

        return _ExecutorBacked(
            hass,
            YandexEmbeddingsAdapter(
                api_key=entry.data[CONF_API_KEY],
                model=model,
                folder_id=entry.data.get(CONF_FOLDER_ID, ""),
            ),
        )

    raise EmbeddingsConfigError(f"unknown provider {engine!r}")
