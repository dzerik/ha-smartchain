"""Tests for the EmbeddingsProvider factory."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant


async def test_create_from_subentry_uses_entry_credentials(hass: HomeAssistant) -> None:
    """Credentials come from the config entry, the model from the subentry."""
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_API_KEY, CONF_ENGINE, ID_GIGACHAT
    from custom_components.smartchain.tools.memory.embeddings import (
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "creds-from-entry"})
    subentry = SimpleNamespace(title="GigaChat Embeddings", data={"model": "Embeddings"})

    with patch("custom_components.smartchain.tools.memory.embeddings.GigaChatEmbeddings") as gc:
        create_embeddings_from_subentry(hass, entry, subentry)

    kwargs = gc.call_args.kwargs
    assert kwargs["credentials"] == "creds-from-entry"
    assert kwargs["model"] == "Embeddings"


async def test_create_from_subentry_ollama_uses_base_url(hass: HomeAssistant) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_BASE_URL, CONF_ENGINE, ID_OLLAMA
    from custom_components.smartchain.tools.memory.embeddings import (
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(data={CONF_ENGINE: ID_OLLAMA, CONF_BASE_URL: "http://box:11434"})
    subentry = SimpleNamespace(title="Ollama nomic", data={"model": "nomic-embed-text"})

    with patch("custom_components.smartchain.tools.memory.embeddings.OllamaEmbeddings") as ollama:
        create_embeddings_from_subentry(hass, entry, subentry)

    ollama.assert_called_once_with(model="nomic-embed-text", base_url="http://box:11434")


async def test_create_from_subentry_rejects_incapable_provider(hass: HomeAssistant) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_API_KEY, CONF_ENGINE, ID_ANTHROPIC
    from custom_components.smartchain.tools.memory.embeddings import (
        EmbeddingsConfigError,
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(data={CONF_ENGINE: ID_ANTHROPIC, CONF_API_KEY: "k"})
    subentry = SimpleNamespace(title="Nope", data={"model": "whatever"})

    with pytest.raises(EmbeddingsConfigError, match="does not provide embeddings"):
        create_embeddings_from_subentry(hass, entry, subentry)


async def test_create_from_subentry_requires_a_model(hass: HomeAssistant) -> None:
    from types import SimpleNamespace

    from custom_components.smartchain.const import CONF_API_KEY, CONF_ENGINE, ID_OPENAI
    from custom_components.smartchain.tools.memory.embeddings import (
        EmbeddingsConfigError,
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"})
    subentry = SimpleNamespace(title="Empty", data={"model": ""})

    with pytest.raises(EmbeddingsConfigError, match="no model"):
        create_embeddings_from_subentry(hass, entry, subentry)


async def test_create_from_subentry_yandex_uses_folder_id(hass: HomeAssistant) -> None:
    """Deliberate addition beyond the brief: covers the YandexGPT branch, asserting
    that folder_id from the entry, the api_key, and the subentry's model all reach
    YandexEmbeddingsAdapter."""
    from types import SimpleNamespace

    from custom_components.smartchain.const import (
        CONF_API_KEY,
        CONF_ENGINE,
        CONF_FOLDER_ID,
        ID_YANDEX_GPT,
    )
    from custom_components.smartchain.tools.memory.embeddings import (
        create_embeddings_from_subentry,
    )

    entry = SimpleNamespace(
        data={
            CONF_ENGINE: ID_YANDEX_GPT,
            CONF_API_KEY: "yandex-key",
            CONF_FOLDER_ID: "b1gfolder",
        }
    )
    subentry = SimpleNamespace(title="Yandex Embeddings", data={"model": "text-search-doc"})

    with patch(
        "custom_components.smartchain.tools.memory.embeddings_yandex.YandexEmbeddingsAdapter"
    ) as adapter:
        create_embeddings_from_subentry(hass, entry, subentry)

    adapter.assert_called_once_with(
        api_key="yandex-key", model="text-search-doc", folder_id="b1gfolder"
    )
