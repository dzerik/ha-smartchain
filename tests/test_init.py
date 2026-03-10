"""Tests for GigaChain conversation entity."""

from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation import ConversationInput, ConversationResult
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from custom_components.gigachain.conversation import GigaChainConversationEntity
from custom_components.gigachain.const import (
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DOMAIN,
    ID_GIGACHAT,
    MAX_HISTORY_CONVERSATIONS,
)


def _make_input(text="Hello, assistant!", conversation_id=None):
    """Create a ConversationInput with correct signature."""
    return ConversationInput(
        text=text,
        context=Context(),
        conversation_id=conversation_id,
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
    )


@pytest.fixture
def mock_entry(mock_llm_client):
    """Create a mock config entry with runtime_data."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "You are a test assistant.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
    }
    entry.runtime_data = mock_llm_client
    return entry


@pytest.fixture
def entity(hass: HomeAssistant, mock_entry):
    """Create a GigaChainConversationEntity."""
    ent = GigaChainConversationEntity(mock_entry)
    ent.hass = hass
    return ent


@pytest.fixture
def user_input():
    """Create a ConversationInput."""
    return _make_input()


@pytest.fixture
def mock_chat_log():
    """Create a mock ChatLog."""
    chat_log = MagicMock()
    chat_log.conversation_id = "test-conv-id"
    chat_log.async_add_assistant_content_without_tools = MagicMock()
    return chat_log


async def test_handle_message_basic(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test basic _async_handle_message returns a response."""
    result = await entity._async_handle_message(user_input, mock_chat_log)

    assert isinstance(result, ConversationResult)
    assert result.response.speech["plain"]["speech"] == "Test response from LLM"
    assert result.conversation_id == mock_chat_log.conversation_id
    mock_chat_log.async_add_assistant_content_without_tools.assert_called_once()


async def test_handle_message_saves_history(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test that _async_handle_message saves conversation history."""
    result = await entity._async_handle_message(user_input, mock_chat_log)
    conversation_id = result.conversation_id

    assert conversation_id in entity.history
    messages = entity.history[conversation_id]
    assert len(messages) == 3  # system + human + ai
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert isinstance(messages[2], AIMessage)


async def test_handle_message_continues_history(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test that subsequent messages use existing history."""
    await entity._async_handle_message(user_input, mock_chat_log)

    user_input2 = _make_input(text="Second message")
    await entity._async_handle_message(user_input2, mock_chat_log)

    messages = entity.history[mock_chat_log.conversation_id]
    assert len(messages) == 5  # system + human + ai + human + ai


async def test_handle_message_history_disabled(
    hass: HomeAssistant, mock_llm_client, user_input, mock_chat_log
) -> None:
    """Test that history is not used when disabled."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "Test prompt.",
        CONF_CHAT_HISTORY: False,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
    }
    entry.runtime_data = mock_llm_client

    ent = GigaChainConversationEntity(entry)
    ent.hass = hass

    await ent._async_handle_message(user_input, mock_chat_log)

    # Call again with same conversation_id - should start fresh (new system message)
    mock_chat_log2 = MagicMock()
    mock_chat_log2.conversation_id = mock_chat_log.conversation_id
    mock_chat_log2.async_add_assistant_content_without_tools = MagicMock()

    user_input2 = _make_input(text="Second")
    await ent._async_handle_message(user_input2, mock_chat_log2)

    # Messages should be fresh (3, not 5)
    messages = ent.history[mock_chat_log.conversation_id]
    assert len(messages) == 3  # system + human + ai (fresh)


async def test_history_eviction(
    hass: HomeAssistant, entity
) -> None:
    """Test that history evicts oldest entries beyond MAX_HISTORY_CONVERSATIONS."""
    for i in range(MAX_HISTORY_CONVERSATIONS + 10):
        conv_id = f"conv_{i}"
        entity._save_history(conv_id, [SystemMessage(content=f"msg {i}")])

    assert len(entity.history) == MAX_HISTORY_CONVERSATIONS
    assert "conv_0" not in entity.history
    assert "conv_9" not in entity.history
    assert f"conv_{MAX_HISTORY_CONVERSATIONS + 9}" in entity.history


async def test_handle_message_llm_error(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test _async_handle_message handles LLM errors gracefully."""
    entity.entry.runtime_data.invoke.side_effect = RuntimeError("API Error")

    result = await entity._async_handle_message(user_input, mock_chat_log)

    assert isinstance(result, ConversationResult)
    assert result.response.error_code == intent.IntentResponseErrorCode.UNKNOWN
    assert "API Error" in result.response.speech["plain"]["speech"]


async def test_handle_message_with_builtin_not_recognized(
    hass: HomeAssistant, mock_llm_client, user_input, mock_chat_log
) -> None:
    """Test delegates to HA default agent, falls back to LLM when not recognized."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "Test prompt.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: True,
    }
    entry.runtime_data = mock_llm_client

    mock_default_response = MagicMock(spec=ConversationResult)
    mock_default_response.response = MagicMock()
    mock_default_response.response.intent = None  # Not recognized

    mock_default_agent = AsyncMock()
    mock_default_agent.async_process.return_value = mock_default_response

    ent = GigaChainConversationEntity(entry)
    ent.hass = hass

    with patch(
        "homeassistant.components.conversation.agent_manager.async_get_agent",
        return_value=mock_default_agent,
    ):
        result = await ent._async_handle_message(user_input, mock_chat_log)

    mock_default_agent.async_process.assert_called_once()
    assert result.response.speech["plain"]["speech"] == "Test response from LLM"


async def test_handle_message_builtin_recognized(
    hass: HomeAssistant, mock_llm_client, user_input, mock_chat_log
) -> None:
    """Test returns HA response when builtin sentence recognized."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "Test prompt.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: True,
    }
    entry.runtime_data = mock_llm_client

    mock_intent_response = MagicMock()
    mock_intent_response.intent = MagicMock()  # Truthy = recognized
    mock_intent_response.speech = {"plain": {"speech": "HA handled this"}}

    mock_default_response = MagicMock(spec=ConversationResult)
    mock_default_response.response = mock_intent_response

    mock_default_agent = AsyncMock()
    mock_default_agent.async_process.return_value = mock_default_response

    ent = GigaChainConversationEntity(entry)
    ent.hass = hass

    with patch(
        "homeassistant.components.conversation.agent_manager.async_get_agent",
        return_value=mock_default_agent,
    ):
        result = await ent._async_handle_message(user_input, mock_chat_log)

    mock_llm_client.invoke.assert_not_called()
    assert result.response is mock_intent_response


async def test_supported_languages(
    hass: HomeAssistant, entity
) -> None:
    """Test that supported_languages returns a list."""
    languages = entity.supported_languages
    assert isinstance(languages, list)
    assert len(languages) > 0
