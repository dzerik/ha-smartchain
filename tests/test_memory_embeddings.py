"""Tests for the EmbeddingsProvider factory."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.config import MemoryConfig
from custom_components.smartchain.tools.memory.embeddings import (
    EmbeddingsConfigError,
    create_embeddings,
)


async def test_ollama_factory_builds_provider(hass: HomeAssistant) -> None:
    cfg = MemoryConfig(provider="ollama", model="nomic-embed-text", base_url="http://x:11434")
    with patch("custom_components.smartchain.tools.memory.embeddings.OllamaEmbeddings") as ollama:
        provider = create_embeddings(hass, cfg)
        ollama.assert_called_once_with(model="nomic-embed-text", base_url="http://x:11434")
    assert provider is not None


async def test_openai_factory_requires_api_key(hass: HomeAssistant) -> None:
    cfg = MemoryConfig(provider="openai", model="text-embedding-3-small")
    with pytest.raises(EmbeddingsConfigError, match="api_key"):
        create_embeddings(hass, cfg)


async def test_openai_factory_with_key(hass: HomeAssistant) -> None:
    cfg = MemoryConfig(provider="openai", model="text-embedding-3-small", api_key="sk-xx")
    with patch("custom_components.smartchain.tools.memory.embeddings.OpenAIEmbeddings") as oai:
        create_embeddings(hass, cfg)
        oai.assert_called_once_with(model="text-embedding-3-small", api_key="sk-xx")


async def test_gigachat_factory_with_credentials(hass: HomeAssistant) -> None:
    cfg = MemoryConfig(provider="gigachat", model="Embeddings", api_key="creds")
    with patch("custom_components.smartchain.tools.memory.embeddings.GigaChatEmbeddings") as gc:
        create_embeddings(hass, cfg)
        gc.assert_called_once()


async def test_unknown_provider_raises(hass: HomeAssistant) -> None:
    cfg = MemoryConfig(provider="bogus", model="x")
    with pytest.raises(EmbeddingsConfigError, match="unknown provider"):
        create_embeddings(hass, cfg)


async def test_embed_query_offloads_to_executor(hass: HomeAssistant) -> None:
    """embed_query wraps the sync SDK call via async_add_executor_job."""
    cfg = MemoryConfig(provider="ollama", model="nomic-embed-text")
    fake_inner = MagicMock()
    fake_inner.embed_query = MagicMock(return_value=[0.1, 0.2, 0.3])
    with patch(
        "custom_components.smartchain.tools.memory.embeddings.OllamaEmbeddings",
        return_value=fake_inner,
    ):
        provider = create_embeddings(hass, cfg)
        vec = await provider.embed_query("hello")
    assert vec == [0.1, 0.2, 0.3]
    fake_inner.embed_query.assert_called_once_with("hello")
