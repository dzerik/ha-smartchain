"""Tests for GigaChain conversation entity."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation import ConversationInput, ConversationResult
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from custom_components.gigachain.conversation import (
    GigaChainConversationEntity,
    _chatlog_to_langchain,
)
from custom_components.gigachain.const import (
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    ID_GIGACHAT,
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


def _make_chat_log(conversation_id="test-conv-id", user_text="Hello, assistant!"):
    """Create a mock ChatLog with proper content list."""
    chat_log = MagicMock()
    chat_log.conversation_id = conversation_id
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content=user_text),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()
    return chat_log


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
    return _make_chat_log()


async def test_handle_message_basic(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test basic _async_handle_message returns a response."""
    result = await entity._async_handle_message(user_input, mock_chat_log)

    assert isinstance(result, ConversationResult)
    assert result.response.speech["plain"]["speech"] == "Test response from LLM"
    assert result.conversation_id == mock_chat_log.conversation_id
    mock_chat_log.async_add_assistant_content_without_tools.assert_called_once()


async def test_handle_message_sets_system_prompt(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test that system prompt is set in ChatLog."""
    await entity._async_handle_message(user_input, mock_chat_log)

    # content[0] should be replaced with the rendered system prompt
    assert isinstance(mock_chat_log.content[0], SystemContent)
    assert "test assistant" in mock_chat_log.content[0].content


async def test_handle_message_sends_correct_messages_to_llm(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test that LLM receives correct LangChain messages from ChatLog."""
    await entity._async_handle_message(user_input, mock_chat_log)

    # Check what was passed to client.invoke
    call_args = entity.entry.runtime_data.invoke.call_args[0][0]
    assert len(call_args) == 2  # system + human
    assert isinstance(call_args[0], SystemMessage)
    assert isinstance(call_args[1], HumanMessage)
    assert call_args[1].content == "Hello, assistant!"


async def test_handle_message_with_history(
    hass: HomeAssistant, entity, user_input
) -> None:
    """Test that ChatLog history is converted to LangChain messages."""
    chat_log = MagicMock()
    chat_log.conversation_id = "test-conv-id"
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content="First message"),
        AssistantContent(agent_id="test", content="First response"),
        UserContent(content="Hello, assistant!"),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    await entity._async_handle_message(user_input, chat_log)

    call_args = entity.entry.runtime_data.invoke.call_args[0][0]
    assert len(call_args) == 4  # system + human + ai + human
    assert isinstance(call_args[0], SystemMessage)
    assert isinstance(call_args[1], HumanMessage)
    assert call_args[1].content == "First message"
    assert isinstance(call_args[2], AIMessage)
    assert call_args[2].content == "First response"
    assert isinstance(call_args[3], HumanMessage)
    assert call_args[3].content == "Hello, assistant!"


async def test_handle_message_history_disabled(
    hass: HomeAssistant, mock_llm_client, user_input
) -> None:
    """Test that only current message is sent when history disabled."""
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

    # ChatLog has history, but history is disabled
    chat_log = MagicMock()
    chat_log.conversation_id = "test-conv-id"
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content="Old message"),
        AssistantContent(agent_id="test", content="Old response"),
        UserContent(content="Hello, assistant!"),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    await ent._async_handle_message(user_input, chat_log)

    # Only system + current user message (not old history)
    call_args = mock_llm_client.invoke.call_args[0][0]
    assert len(call_args) == 2  # system + human (no history)
    assert isinstance(call_args[0], SystemMessage)
    assert isinstance(call_args[1], HumanMessage)
    assert call_args[1].content == "Hello, assistant!"


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


def test_chatlog_to_langchain() -> None:
    """Test conversion of ChatLog content to LangChain messages."""
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="User message"),
        AssistantContent(agent_id="test", content="AI response"),
        UserContent(content="Follow-up"),
    ]

    messages = _chatlog_to_langchain(chat_log)

    assert len(messages) == 4
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "System prompt"
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "User message"
    assert isinstance(messages[2], AIMessage)
    assert messages[2].content == "AI response"
    assert isinstance(messages[3], HumanMessage)
    assert messages[3].content == "Follow-up"


def test_chatlog_to_langchain_skips_empty_assistant() -> None:
    """Test that assistant content without text is skipped."""
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="Prompt"),
        UserContent(content="Hello"),
        AssistantContent(agent_id="test", content=None),
    ]

    messages = _chatlog_to_langchain(chat_log)

    assert len(messages) == 2  # system + human (empty assistant skipped)
