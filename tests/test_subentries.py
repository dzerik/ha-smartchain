"""Tests for SmartChain sub-entries (multiple agents per provider)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _make_subentry_data(
    model: str = "GigaChat",
    title: str = "Test Agent",
) -> dict:
    """Create a ConfigSubentryData dict for MockConfigEntry."""
    return {
        "data": {
            CONF_CHAT_MODEL: model,
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
        },
        "subentry_type": SUBENTRY_TYPE_CONVERSATION,
        "title": title,
        "unique_id": None,
    }


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


# --- SubentryFlow Tests ---


async def test_subentry_flow_shows_form(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test that subentry flow shows form for adding an agent."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (mock_gigachat_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": "user"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_subentry_flow_creates_agent(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test that subentry flow creates a conversation agent."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (mock_gigachat_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "GigaChat",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GigaChat"


async def test_subentry_flow_model_required_error(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test subentry flow shows error when no model provided."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (mock_gigachat_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "",
            CONF_CHAT_MODEL_USER: "",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "model_required"}


async def test_subentry_flow_custom_model(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test subentry flow accepts custom model name."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (mock_gigachat_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "",
            CONF_CHAT_MODEL_USER: "GigaChat-Max-2",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: 0.5,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GigaChat-Max-2"


# --- Setup with subentries ---


async def test_setup_with_subentries(hass: HomeAssistant, mock_llm_client) -> None:
    """Test that setup creates entities from subentries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id="GigaChat",
        subentries_data=[_make_subentry_data()],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert isinstance(entry.runtime_data, dict)
    assert len(entry.runtime_data) == 1

    # Check conversation entity was created (entity_id may include subentry ID)
    states = [s for s in hass.states.async_all() if s.domain == "conversation"]
    # Exclude the default HA conversation entity
    custom_entities = [s for s in states if s.entity_id != "conversation.home_assistant"]
    assert len(custom_entities) >= 1


async def test_setup_with_multiple_subentries(hass: HomeAssistant, mock_llm_client) -> None:
    """Test that setup creates separate entities for each subentry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            _make_subentry_data(model="GigaChat", title="Agent 1"),
            _make_subentry_data(model="GigaChat-Pro", title="Agent 2"),
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert isinstance(entry.runtime_data, dict)
    assert len(entry.runtime_data) == 2

    # Check two conversation entities were created
    states = [s for s in hass.states.async_all() if s.domain == "conversation"]
    custom_entities = [s for s in states if s.entity_id != "conversation.home_assistant"]
    assert len(custom_entities) >= 2


async def test_setup_legacy_without_subentries(
    hass: HomeAssistant, mock_gigachat_entry, mock_llm_client
) -> None:
    """Test that setup still works in legacy mode (no subentries)."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        result = await hass.config_entries.async_setup(mock_gigachat_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    # Legacy: runtime_data is a client, not a dict
    assert not isinstance(mock_gigachat_entry.runtime_data, dict)


# --- Conversation entity with subentry ---


async def test_conversation_entity_subentry_options(hass: HomeAssistant, mock_llm_client) -> None:
    """Test that conversation entity uses subentry options."""
    from homeassistant.config_entries import ConfigSubentry

    from custom_components.smartchain.conversation import SmartChainConversationEntity

    subentry = ConfigSubentry(
        data=_make_subentry_data()["data"],
        subentry_id="sub_1",
        subentry_type=SUBENTRY_TYPE_CONVERSATION,
        title="Test Agent",
        unique_id=None,
    )
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.subentries = {"sub_1": subentry}
    entry.runtime_data = {"sub_1": mock_llm_client}

    entity = SmartChainConversationEntity(entry, subentry_id="sub_1", options=dict(subentry.data))
    entity.hass = hass

    assert entity._attr_unique_id == "test_entry_sub_1"
    assert entity._attr_name == "Test Agent"
    assert entity._agent_options[CONF_CHAT_MODEL] == "GigaChat"
    assert entity._client is mock_llm_client
