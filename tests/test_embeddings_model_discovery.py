"""Model discovery splits a provider's catalogue by purpose."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.client_util import (
    async_fetch_models,
    is_embedding_model,
)
from custom_components.smartchain.const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    ID_ANTHROPIC,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
)


@pytest.mark.parametrize(
    ("engine", "name", "expected"),
    [
        (ID_OPENAI, "text-embedding-3-small", True),
        (ID_OPENAI, "gpt-4.1", False),
        (ID_GIGACHAT, "Embeddings", True),
        (ID_GIGACHAT, "EmbeddingsGigaR", True),
        (ID_GIGACHAT, "GigaChat-Pro", False),
        (ID_OLLAMA, "nomic-embed-text", True),
        (ID_OLLAMA, "bge-m3", True),
        (ID_OLLAMA, "mxbai-embed-large", True),
        (ID_OLLAMA, "llama3.3", False),
        (ID_ANTHROPIC, "claude-sonnet-4-6", False),
    ],
)
def test_is_embedding_model(engine: str, name: str, expected: bool) -> None:
    assert is_embedding_model(engine, name) is expected


async def test_openai_embeddings_purpose_filters_catalogue(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1", "gpt-4o", "text-embedding-3-small", "text-embedding-3-large"],
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert "text-embedding-3-small" in models
    assert "gpt-4.1" not in models


async def test_openai_chat_purpose_excludes_embeddings(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1", "text-embedding-3-small"],
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_CHAT
        )
    assert "gpt-4.1" in models
    assert "text-embedding-3-small" not in models


async def test_default_purpose_is_chat(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1", "text-embedding-3-small"],
    ):
        models = await async_fetch_models(hass, ID_OPENAI, {"api_key": "k"})
    assert "gpt-4.1" in models
    assert "text-embedding-3-small" not in models


async def test_gigachat_embeddings_purpose(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_gigachat_models",
        new_callable=AsyncMock,
        return_value=["GigaChat-Pro", "GigaChat-Max", "Embeddings", "EmbeddingsGigaR"],
    ):
        models = await async_fetch_models(
            hass, ID_GIGACHAT, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert set(models) >= {"Embeddings", "EmbeddingsGigaR"}
    assert "GigaChat-Pro" not in models


async def test_yandex_uses_static_embedding_list(hass: HomeAssistant) -> None:
    models = await async_fetch_models(hass, ID_YANDEX_GPT, {}, purpose=CAPABILITY_EMBEDDINGS)
    assert "text-search-doc" in models
    assert "text-search-query" in models


async def test_fetch_failure_falls_back_to_static_embedding_list(
    hass: HomeAssistant,
) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network down"),
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert "text-embedding-3-small" in models


async def test_empty_result_keeps_the_blank_custom_option(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models",
        new_callable=AsyncMock,
        return_value=["gpt-4.1"],
    ):
        models = await async_fetch_models(
            hass, ID_OPENAI, {"api_key": "k"}, purpose=CAPABILITY_EMBEDDINGS
        )
    assert models[0] == ""


def test_gigachat_recognises_the_gigaembedding_family() -> None:
    """GigaChat names embedding models two ways, and only one starts with
    `Embeddings`. A prefix test hid GigaEmbedding from the embeddings list and
    offered it as a chat model instead."""
    for name in ("Embeddings", "EmbeddingsGigaR", "GigaEmbedding", "GigaEmbeddingPlus"):
        assert is_embedding_model(ID_GIGACHAT, name) is True, name


def test_gigachat_chat_models_are_not_mistaken_for_embeddings() -> None:
    for name in ("GigaChat", "GigaChat-Pro", "GigaChat-Max", "GigaChat-2"):
        assert is_embedding_model(ID_GIGACHAT, name) is False, name
