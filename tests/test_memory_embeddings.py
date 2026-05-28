"""Tests for the EmbeddingsProvider factory."""

import asyncio
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


async def test_embed_query_raises_timeout_when_slow(hass: HomeAssistant) -> None:
    """embed_query raises TimeoutError when the embedding call exceeds the timeout."""
    import custom_components.smartchain.tools.memory.embeddings as emb_mod

    cfg = MemoryConfig(provider="ollama", model="nomic-embed-text")

    # Use a threading.Event-cancellable sleep so the executor thread exits
    # cleanly during pytest teardown. Plain time.sleep(10) leaves the thread
    # running and raises PytestUnhandledThreadExceptionWarning on teardown.
    import threading

    cancel = threading.Event()

    def _slow_embed(text: str) -> list[float]:
        # 200ms is well above the patched 1ms timeout but short enough that
        # the thread exits before pytest teardown noticeably runs.
        cancel.wait(timeout=0.2)
        return [0.0]

    fake_inner = MagicMock()
    fake_inner.embed_query = _slow_embed

    with patch(
        "custom_components.smartchain.tools.memory.embeddings.OllamaEmbeddings",
        return_value=fake_inner,
    ):
        provider = create_embeddings(hass, cfg)
        # Patch the timeout to a tiny value so the test runs fast
        with patch.object(emb_mod, "MEMORY_EMBED_TIMEOUT_SECONDS", 0.001):
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await provider.embed_query("slow")
        # Release the executor thread so it exits before teardown
        cancel.set()
