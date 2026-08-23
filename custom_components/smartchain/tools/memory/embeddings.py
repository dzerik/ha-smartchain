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

LOGGER = logging.getLogger(__name__)


class EmbeddingsConfigError(Exception):
    """Raised when a config entry/subentry cannot be turned into a working provider."""


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
