"""Embeddings for OpenAI-compatible providers."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    DOMAIN,
    ID_GROQ,
    ID_LMSTUDIO,
    ID_TOGETHER,
    OPENAI_COMPATIBLE,
    SUBENTRY_TYPE_EMBEDDINGS,
)
from custom_components.smartchain.tools.memory.embeddings import (
    EmbeddingsConfigError,
    create_embeddings_from_subentry,
)


def _subentry(model: str) -> ConfigSubentry:
    return ConfigSubentry(
        data={"model": model},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title="emb",
        unique_id=None,
    )


def _entry(hass, engine: str, data: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_ENGINE: engine, **data})
    entry.add_to_hass(hass)
    return entry


async def test_table_provider_uses_its_base_url(hass):
    entry = _entry(hass, ID_TOGETHER, {CONF_API_KEY: "k"})
    with patch("custom_components.smartchain.tools.memory.embeddings.OpenAIEmbeddings") as emb:
        create_embeddings_from_subentry(hass, entry, _subentry("bge-m3"))
    kwargs = emb.call_args.kwargs
    assert kwargs["model"] == "bge-m3"
    assert kwargs["base_url"] == OPENAI_COMPATIBLE[ID_TOGETHER].default_base_url
    assert kwargs["api_key"] == "k"


async def test_local_provider_gets_a_placeholder_key(hass):
    entry = _entry(hass, ID_LMSTUDIO, {CONF_BASE_URL: "http://localhost:1234/v1"})
    with patch("custom_components.smartchain.tools.memory.embeddings.OpenAIEmbeddings") as emb:
        create_embeddings_from_subentry(hass, entry, _subentry("nomic-embed-text"))
    assert emb.call_args.kwargs["api_key"] == "not-needed"
    assert emb.call_args.kwargs["base_url"] == "http://localhost:1234/v1"


async def test_provider_without_embeddings_is_refused(hass):
    entry = _entry(hass, ID_GROQ, {CONF_API_KEY: "k"})
    with pytest.raises(EmbeddingsConfigError, match="does not provide embeddings"):
        create_embeddings_from_subentry(hass, entry, _subentry("bge-m3"))


async def test_openai_still_builds_without_a_base_url_override(hass):
    from custom_components.smartchain.const import ID_OPENAI

    entry = _entry(hass, ID_OPENAI, {CONF_API_KEY: "k"})
    with patch("custom_components.smartchain.tools.memory.embeddings.OpenAIEmbeddings") as emb:
        create_embeddings_from_subentry(hass, entry, _subentry("text-embedding-3-small"))
    assert emb.call_args.kwargs["model"] == "text-embedding-3-small"
    assert emb.call_args.kwargs["api_key"] == "k"
