"""Tests for SmartChain ask service."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from langchain_core.messages import AIMessage

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import DOMAIN

from .conftest import MOCK_GIGACHAT_DATA


async def test_ask_service_registered(hass: HomeAssistant):
    """Test that smartchain.ask service is registered after setup."""
    assert await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "ask")


async def test_ask_service_no_agent(hass: HomeAssistant):
    """Test ask service when no agent is available."""
    await async_setup(hass, {})

    result = await hass.services.async_call(
        DOMAIN,
        "ask",
        {"message": "Hello"},
        blocking=True,
        return_response=True,
    )

    assert "No SmartChain agent" in result["response"]


async def test_ask_service_with_client(hass: HomeAssistant):
    """Test ask service returns LLM response."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="The kitchen is 22°C")

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.options = {}
    entry.unique_id = "GigaChat"
    entry.subentries = {}
    entry.runtime_data = mock_client

    hass.config_entries._entries[entry.entry_id] = entry

    result = await hass.services.async_call(
        DOMAIN,
        "ask",
        {"message": "What's the temperature?"},
        blocking=True,
        return_response=True,
    )

    assert result["response"] == "The kitchen is 22°C"
    mock_client.ainvoke.assert_called_once()


async def test_ask_service_with_subentry_client(hass: HomeAssistant):
    """Test ask service with subentry-based clients."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="Sunny weather")

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.unique_id = "GigaChat"
    entry.runtime_data = {"sub1": mock_client}

    hass.config_entries._entries[entry.entry_id] = entry

    result = await hass.services.async_call(
        DOMAIN,
        "ask",
        {"message": "What's the weather?"},
        blocking=True,
        return_response=True,
    )

    assert result["response"] == "Sunny weather"
