"""Tests for SmartChain conversation entity."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation import ConversationInput, ConversationResult
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent, llm
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from custom_components.smartchain.const import (
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_LLM_HASS_API,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import (
    SmartChainConversationEntity,
    _async_langchain_stream,
    _chatlog_to_langchain,
    _ha_tool_to_dict,
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
    """Create a mock ChatLog with proper content list and streaming support."""
    chat_log = MagicMock()
    chat_log.conversation_id = conversation_id
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content=user_text),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()
    chat_log.llm_api = None
    chat_log.unresponded_tool_results = False

    async def _mock_add_delta_stream(agent_id, stream):
        collected = ""
        async for delta in stream:
            if "content" in delta:
                collected += delta["content"]
        content = AssistantContent(agent_id=agent_id, content=collected)
        chat_log.content.append(content)
        yield content

    chat_log.async_add_delta_content_stream = _mock_add_delta_stream
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
    """Create a SmartChainConversationEntity."""
    ent = SmartChainConversationEntity(mock_entry)
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


async def test_handle_message_basic(hass: HomeAssistant, entity, user_input, mock_chat_log) -> None:
    """Test basic _async_handle_message returns a response."""
    result = await entity._async_handle_message(user_input, mock_chat_log)

    assert isinstance(result, ConversationResult)
    assert result.response.speech["plain"]["speech"] == "Test response from LLM"
    assert result.conversation_id == mock_chat_log.conversation_id


async def test_handle_message_sets_system_prompt(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test that system prompt is set in ChatLog."""
    await entity._async_handle_message(user_input, mock_chat_log)

    assert isinstance(mock_chat_log.content[0], SystemContent)
    assert "test assistant" in mock_chat_log.content[0].content


async def test_handle_message_sends_correct_messages_to_llm(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test that LLM receives correct LangChain messages from ChatLog."""
    await entity._async_handle_message(user_input, mock_chat_log)

    call_args = entity.entry.runtime_data.astream.call_args[0][0]
    assert len(call_args) == 2  # system + human
    assert isinstance(call_args[0], SystemMessage)
    assert isinstance(call_args[1], HumanMessage)
    assert call_args[1].content == "Hello, assistant!"


async def test_handle_message_with_history(hass: HomeAssistant, entity, user_input) -> None:
    """Test that ChatLog history is converted to LangChain messages."""
    chat_log = _make_chat_log()
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content="First message"),
        AssistantContent(agent_id="test", content="First response"),
        UserContent(content="Hello, assistant!"),
    ]

    await entity._async_handle_message(user_input, chat_log)

    call_args = entity.entry.runtime_data.astream.call_args[0][0]
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

    ent = SmartChainConversationEntity(entry)
    ent.hass = hass

    chat_log = _make_chat_log()
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content="Old message"),
        AssistantContent(agent_id="test", content="Old response"),
        UserContent(content="Hello, assistant!"),
    ]

    await ent._async_handle_message(user_input, chat_log)

    call_args = mock_llm_client.astream.call_args[0][0]
    assert len(call_args) == 2
    assert isinstance(call_args[0], SystemMessage)
    assert isinstance(call_args[1], HumanMessage)
    assert call_args[1].content == "Hello, assistant!"


async def test_handle_message_llm_error(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test _async_handle_message handles LLM errors gracefully."""

    async def _error_stream(messages):
        raise RuntimeError("API Error")
        yield  # noqa: F841

    entity.entry.runtime_data.astream = MagicMock(side_effect=_error_stream)

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
    mock_default_response.response.intent = None

    mock_default_agent = AsyncMock()
    mock_default_agent.async_process.return_value = mock_default_response

    ent = SmartChainConversationEntity(entry)
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
    mock_intent_response.intent = MagicMock()
    mock_intent_response.speech = {"plain": {"speech": "HA handled this"}}

    mock_default_response = MagicMock(spec=ConversationResult)
    mock_default_response.response = mock_intent_response

    mock_default_agent = AsyncMock()
    mock_default_agent.async_process.return_value = mock_default_response

    ent = SmartChainConversationEntity(entry)
    ent.hass = hass

    with patch(
        "homeassistant.components.conversation.agent_manager.async_get_agent",
        return_value=mock_default_agent,
    ):
        result = await ent._async_handle_message(user_input, mock_chat_log)

    mock_llm_client.astream.assert_not_called()
    assert result.response is mock_intent_response


async def test_supported_languages(hass: HomeAssistant, entity) -> None:
    """Test that supported_languages returns a list."""
    languages = entity.supported_languages
    assert isinstance(languages, list)
    assert len(languages) > 0


async def test_supports_streaming(entity) -> None:
    """Test that entity declares streaming support."""
    assert entity._attr_supports_streaming is True


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

    assert len(messages) == 2


async def test_async_langchain_stream() -> None:
    """Test that _async_langchain_stream converts LangChain chunks to HA deltas."""
    client = MagicMock()

    async def _fake_astream(messages):
        yield AIMessageChunk(content="Hello")
        yield AIMessageChunk(content=" world")

    client.astream = _fake_astream

    deltas = []
    async for delta in _async_langchain_stream(client, []):
        deltas.append(delta)

    assert len(deltas) == 2
    assert deltas[0] == {"role": "assistant", "content": "Hello"}
    assert deltas[1] == {"content": " world"}


async def test_async_langchain_stream_skips_empty_chunks() -> None:
    """Test that empty chunks are skipped in stream conversion."""
    client = MagicMock()

    async def _fake_astream(messages):
        yield AIMessageChunk(content="")
        yield AIMessageChunk(content="data")

    client.astream = _fake_astream

    deltas = []
    async for delta in _async_langchain_stream(client, []):
        deltas.append(delta)

    assert len(deltas) == 2
    assert deltas[0] == {"role": "assistant"}
    assert deltas[1] == {"content": "data"}


def test_chatlog_to_langchain_with_tool_calls() -> None:
    """Test conversion of ChatLog with tool calls and tool results."""
    tool_input = llm.ToolInput(
        tool_name="HassTurnOn",
        tool_args={"entity_id": "light.kitchen"},
        id="call_123",
    )
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="Turn on kitchen light"),
        AssistantContent(
            agent_id="test",
            content="",
            tool_calls=[tool_input],
        ),
        ToolResultContent(
            agent_id="test",
            tool_call_id="call_123",
            tool_name="HassTurnOn",
            tool_result={"success": True},
        ),
        AssistantContent(agent_id="test", content="Done!"),
    ]

    messages = _chatlog_to_langchain(chat_log)

    assert len(messages) == 5
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert isinstance(messages[2], AIMessage)
    assert len(messages[2].tool_calls) == 1
    assert messages[2].tool_calls[0]["name"] == "HassTurnOn"
    assert messages[2].tool_calls[0]["id"] == "call_123"
    assert isinstance(messages[3], ToolMessage)
    assert messages[3].tool_call_id == "call_123"
    assert json.loads(messages[3].content) == {"success": True}
    assert isinstance(messages[4], AIMessage)
    assert messages[4].content == "Done!"


def test_ha_tool_to_dict() -> None:
    """Test conversion of HA llm.Tool to dict for LangChain."""
    import voluptuous as vol

    class MockTool(llm.Tool):
        name = "HassTurnOn"
        description = "Turn on a device"
        parameters = vol.Schema(
            {
                vol.Required("entity_id"): str,
            }
        )

        async def async_call(self, hass, tool_input, llm_context):
            return {"success": True}

    tool = MockTool()
    result = _ha_tool_to_dict(tool)

    assert result["name"] == "HassTurnOn"
    assert result["description"] == "Turn on a device"
    assert "properties" in result["parameters"]
    assert "entity_id" in result["parameters"]["properties"]


async def test_async_langchain_stream_with_tool_calls() -> None:
    """Test that tool_calls from LLM are converted to HA ToolInput in stream."""
    client = MagicMock()

    async def _fake_astream(messages):
        yield AIMessageChunk(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "HassTurnOn",
                    "args": {"entity_id": "light.kitchen"},
                },
            ],
        )

    client.astream = _fake_astream

    deltas = []
    async for delta in _async_langchain_stream(client, []):
        deltas.append(delta)

    assert len(deltas) == 1
    assert deltas[0]["role"] == "assistant"
    assert "tool_calls" in deltas[0]
    assert len(deltas[0]["tool_calls"]) == 1
    tc = deltas[0]["tool_calls"][0]
    assert isinstance(tc, llm.ToolInput)
    assert tc.tool_name == "HassTurnOn"
    assert tc.tool_args == {"entity_id": "light.kitchen"}
    assert tc.id == "call_1"


async def test_handle_message_with_llm_api(
    hass: HomeAssistant, mock_llm_client, user_input
) -> None:
    """Test _async_handle_message with LLM Hass API configured."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "Test prompt.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
        CONF_LLM_HASS_API: "assist",
    }
    entry.runtime_data = mock_llm_client

    ent = SmartChainConversationEntity(entry)
    ent.hass = hass

    chat_log = _make_chat_log()

    with patch.object(
        chat_log,
        "async_provide_llm_data",
        new_callable=AsyncMock,
    ) as mock_provide:
        chat_log.llm_api = None
        await ent._async_handle_message(user_input, chat_log)

    mock_provide.assert_called_once()
    assert mock_provide.call_args[0][1] == "assist"


async def test_handle_message_no_llm_api_sets_prompt_manually(
    hass: HomeAssistant, entity, user_input, mock_chat_log
) -> None:
    """Test that without LLM API configured, system prompt is set manually."""
    await entity._async_handle_message(user_input, mock_chat_log)

    assert isinstance(mock_chat_log.content[0], SystemContent)
    assert "test assistant" in mock_chat_log.content[0].content


async def test_tool_calling_loop_e2e(hass: HomeAssistant, mock_llm_client) -> None:
    """E2E test: LLM calls a tool, gets result, then returns final response.

    Simulates the full tool calling loop:
    1. User says "Turn on kitchen light"
    2. LLM returns tool_call for HassTurnOn
    3. HA executes tool, returns result
    4. LLM returns final text "Done! Kitchen light is on."
    """
    import voluptuous as vol

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "Test prompt.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
        CONF_LLM_HASS_API: "assist",
    }
    entry.runtime_data = mock_llm_client

    ent = SmartChainConversationEntity(entry)
    ent.hass = hass

    # Track iteration to switch LLM behavior
    iteration = 0
    unresponded = [True]  # mutable flag

    async def _tool_call_stream(messages):
        """First call: return tool_call. Second call: return text."""
        nonlocal iteration
        iteration += 1
        if iteration == 1:
            yield AIMessageChunk(
                content="",
                tool_calls=[
                    {
                        "id": "call_abc",
                        "name": "HassTurnOn",
                        "args": {"entity_id": "light.kitchen"},
                    },
                ],
            )
        else:
            yield AIMessageChunk(content="Done! Kitchen light is on.")

    mock_llm_client.astream = _tool_call_stream

    # Create a mock tool
    class MockHassTurnOn(llm.Tool):
        name = "HassTurnOn"
        description = "Turn on a device"
        parameters = vol.Schema({vol.Required("entity_id"): str})

        async def async_call(self, hass, tool_input, llm_context):
            return {"success": True}

    mock_llm_api = MagicMock()
    mock_llm_api.tools = [MockHassTurnOn()]

    # Build chat_log that simulates HA's tool execution loop
    chat_log = MagicMock()
    chat_log.conversation_id = "test-conv-tool"
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="Turn on kitchen light"),
    ]
    chat_log.llm_api = mock_llm_api

    # unresponded_tool_results: True after tool_call, False after final text
    type(chat_log).unresponded_tool_results = property(lambda self: unresponded[0])

    async def _mock_add_delta_stream(agent_id, stream):
        collected_content = ""
        collected_tool_calls = []
        async for delta in stream:
            if "content" in delta:
                collected_content += delta["content"]
            if "tool_calls" in delta:
                collected_tool_calls.extend(delta["tool_calls"])

        if collected_tool_calls:
            tc = collected_tool_calls[0]
            content = AssistantContent(
                agent_id=agent_id,
                content=collected_content or "",
                tool_calls=collected_tool_calls,
            )
            chat_log.content.append(content)
            # Simulate HA executing the tool and adding result
            chat_log.content.append(
                ToolResultContent(
                    agent_id=agent_id,
                    tool_call_id=tc.id,
                    tool_name=tc.tool_name,
                    tool_result={"success": True},
                )
            )
            yield content
        else:
            # Final response — no more tool calls
            unresponded[0] = False
            content = AssistantContent(agent_id=agent_id, content=collected_content)
            chat_log.content.append(content)
            yield content

    chat_log.async_add_delta_content_stream = _mock_add_delta_stream

    # Mock bind_tools to return the client itself (tools already bound)
    mock_llm_client.bind_tools = MagicMock(return_value=mock_llm_client)

    with patch.object(
        chat_log, "async_provide_llm_data", new_callable=AsyncMock
    ):
        result = await ent._async_handle_message(
            _make_input(text="Turn on kitchen light"), chat_log
        )

    # Verify the loop ran twice (tool call + final response)
    assert iteration == 2

    # Verify chat_log has correct content sequence:
    # [system, user, assistant(tool_call), tool_result, assistant(final)]
    assert len(chat_log.content) == 5
    assert isinstance(chat_log.content[0], SystemContent)
    assert isinstance(chat_log.content[1], UserContent)
    assert isinstance(chat_log.content[2], AssistantContent)
    assert chat_log.content[2].tool_calls is not None
    assert isinstance(chat_log.content[3], ToolResultContent)
    assert chat_log.content[3].tool_result == {"success": True}
    assert isinstance(chat_log.content[4], AssistantContent)
    assert chat_log.content[4].content == "Done! Kitchen light is on."

    # Verify bind_tools was called with the tool definition
    mock_llm_client.bind_tools.assert_called_once()
    tools_arg = mock_llm_client.bind_tools.call_args[0][0]
    assert len(tools_arg) == 1
    assert tools_arg[0]["name"] == "HassTurnOn"
