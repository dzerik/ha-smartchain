"""Tests for SmartChain agent delegation tool."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from langchain_core.messages import AIMessage

from custom_components.smartchain.const import DELEGATE_TOOL_NAME
from custom_components.smartchain.conversation import _handle_delegate_tool_calls
from custom_components.smartchain.delegate_tool import (
    execute_delegate_tool,
    get_delegate_tool_definition,
)


def test_delegate_tool_definition():
    """Test that delegate tool definition has correct structure."""
    agents = [
        {"name": "Weather Agent", "sub_id": "sub1"},
        {"name": "Home Agent", "sub_id": "sub2"},
    ]
    defn = get_delegate_tool_definition(agents)
    assert defn["name"] == DELEGATE_TOOL_NAME
    assert "Weather Agent" in defn["description"]
    assert "Home Agent" in defn["description"]
    assert defn["parameters"]["properties"]["agent_name"]["enum"] == [
        "Weather Agent",
        "Home Agent",
    ]
    assert defn["parameters"]["required"] == ["agent_name", "message"]


async def test_execute_delegate_tool_success():
    """Test successful delegation to another agent."""
    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="It's 20°C and sunny.")

    clients = {"sub_weather": mock_client}
    agent_map = {"Weather Agent": "sub_weather"}

    result = await execute_delegate_tool(clients, agent_map, "Weather Agent", "What's the weather?")

    assert result == "It's 20°C and sunny."
    mock_client.ainvoke.assert_called_once()
    call_messages = mock_client.ainvoke.call_args[0][0]
    assert len(call_messages) == 2
    assert call_messages[1].content == "What's the weather?"


async def test_execute_delegate_tool_agent_not_found():
    """Test delegation to non-existent agent."""
    result = await execute_delegate_tool({}, {}, "Unknown Agent", "Hello")
    assert "not found" in result


async def test_execute_delegate_tool_client_not_available():
    """Test delegation when client is missing."""
    agent_map = {"Weather Agent": "sub_weather"}
    result = await execute_delegate_tool({}, agent_map, "Weather Agent", "Hello")
    assert "not available" in result


async def test_handle_delegate_tool_calls_executes_pending(hass: HomeAssistant):
    """Test _handle_delegate_tool_calls executes pending delegate calls."""
    tool_call = llm.ToolInput(
        tool_name=DELEGATE_TOOL_NAME,
        tool_args={"agent_name": "Weather Agent", "message": "What's the weather?"},
        id="tc_d1",
        external=True,
    )
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="Ask weather agent"),
        AssistantContent(
            agent_id="test_agent",
            content=None,
            tool_calls=[tool_call],
        ),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="Sunny, 25°C")

    clients = {"sub_w": mock_client}
    agent_map = {"Weather Agent": "sub_w"}

    await _handle_delegate_tool_calls(clients, agent_map, chat_log, "test_agent")

    chat_log.async_add_assistant_content_without_tools.assert_called_once()
    result_content = chat_log.async_add_assistant_content_without_tools.call_args[0][0]
    assert isinstance(result_content, ToolResultContent)
    assert result_content.tool_call_id == "tc_d1"
    assert result_content.tool_name == DELEGATE_TOOL_NAME
    assert "Sunny" in result_content.tool_result


async def test_handle_delegate_tool_calls_skips_resolved(hass: HomeAssistant):
    """Test that already-resolved delegate calls are skipped."""
    tool_call = llm.ToolInput(
        tool_name=DELEGATE_TOOL_NAME,
        tool_args={"agent_name": "Agent", "message": "Hi"},
        id="tc_d2",
        external=True,
    )
    chat_log = MagicMock()
    chat_log.content = [
        AssistantContent(
            agent_id="test_agent",
            content=None,
            tool_calls=[tool_call],
        ),
        ToolResultContent(
            agent_id="test_agent",
            tool_call_id="tc_d2",
            tool_name=DELEGATE_TOOL_NAME,
            tool_result="already done",
        ),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    await _handle_delegate_tool_calls({}, {}, chat_log, "test_agent")

    chat_log.async_add_assistant_content_without_tools.assert_not_called()


async def test_handle_delegate_tool_calls_ignores_other_tools(hass: HomeAssistant):
    """Test that non-delegate tool calls are ignored."""
    tool_call = llm.ToolInput(
        tool_name="some_other_tool",
        tool_args={"arg": "val"},
        id="tc_other",
        external=True,
    )
    chat_log = MagicMock()
    chat_log.content = [
        AssistantContent(
            agent_id="test_agent",
            content=None,
            tool_calls=[tool_call],
        ),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    await _handle_delegate_tool_calls({}, {}, chat_log, "test_agent")

    chat_log.async_add_assistant_content_without_tools.assert_not_called()
