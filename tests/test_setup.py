"""Tests for SmartChain integration setup and unload."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
def mock_gigachat_entry(hass: HomeAssistant):
    """Create a mock GigaChat config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_openai_entry(hass: HomeAssistant):
    """Create a mock OpenAI config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "test-openai-key"},
        options={},
        unique_id="OpenAI",
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_entry_gigachat(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test successful setup of GigaChat entry."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        result = await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert mock_gigachat_entry.runtime_data is mock_llm_client


async def test_setup_entry_openai(
    hass: HomeAssistant, mock_openai_entry, mock_llm_client
) -> None:
    """Test successful setup of OpenAI entry."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        result = await hass.config_entries.async_setup(mock_openai_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert mock_openai_entry.runtime_data is mock_llm_client


async def test_unload_entry(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test unloading a config entry."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.async_unload(mock_gigachat_entry.entry_id)
    await hass.async_block_till_done()

    assert result is True


async def test_setup_creates_conversation_entity(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test that setup creates a conversation entity."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    states = [s for s in hass.states.async_all() if s.domain == "conversation"]
    assert len(states) >= 2
    entity_ids = [s.entity_id for s in states]
    assert any("smartchain" in eid for eid in entity_ids)
