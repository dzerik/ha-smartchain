"""Fixtures for SmartChain tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from langchain_core.messages import AIMessage, AIMessageChunk

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
)

MOCK_GIGACHAT_DATA = {
    CONF_ENGINE: ID_GIGACHAT,
    CONF_API_KEY: "test-credentials",
}

MOCK_YANDEXGPT_DATA = {
    CONF_ENGINE: ID_YANDEX_GPT,
    CONF_API_KEY: "test-api-key",
    "folder_id": "test-folder-id",
}

MOCK_OPENAI_DATA = {
    CONF_ENGINE: ID_OPENAI,
    CONF_API_KEY: "test-openai-key",
}

MOCK_OLLAMA_DATA = {
    CONF_ENGINE: ID_OLLAMA,
    CONF_BASE_URL: "http://localhost:11434",
}

MOCK_DEEPSEEK_DATA = {
    CONF_ENGINE: ID_DEEPSEEK,
    CONF_API_KEY: "test-deepseek-key",
}

MOCK_ANTHROPIC_DATA = {
    CONF_ENGINE: ID_ANTHROPIC,
    CONF_API_KEY: "test-anthropic-key",
}


@pytest.fixture(autouse=True)
async def setup_ha_components(hass: HomeAssistant) -> None:
    """Set up required HA components for all tests."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    await hass.async_block_till_done()


async def _mock_astream(messages):
    """Async generator that yields a single AIMessageChunk."""
    yield AIMessageChunk(content="Test response from LLM")


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client with astream support."""
    client = MagicMock()
    client.invoke.return_value = AIMessage(content="Test response from LLM")
    client.astream = MagicMock(side_effect=_mock_astream)
    return client


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.options = {}
    entry.runtime_data = None
    entry.unique_id = "GigaChat"
    entry.add_update_listener = MagicMock(return_value=lambda: None)
    entry.async_on_unload = MagicMock()
    return entry


@pytest.fixture
def mock_validate_client():
    """Mock validate_client to skip actual API calls."""
    with patch(
        "custom_components.smartchain.config_flow.validate_client",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture
def mock_get_client(mock_llm_client):
    """Mock get_client to return a fake LLM client."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ) as mock:
        yield mock
