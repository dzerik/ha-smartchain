"""Tests for SmartChain state history tool."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from custom_components.smartchain.const import (
    HISTORY_TOOL_MAX_HOURS,
    HISTORY_TOOL_NAME,
)
from custom_components.smartchain.conversation import _handle_history_tool_calls
from custom_components.smartchain.history_tool import (
    execute_history_tool,
    get_history_tool_definition,
)


def test_history_tool_definition():
    """Test that history tool definition has correct structure."""
    defn = get_history_tool_definition()
    assert defn["name"] == HISTORY_TOOL_NAME
    assert "description" in defn
    assert "parameters" in defn
    assert defn["parameters"]["type"] == "object"
    assert "entity_id" in defn["parameters"]["properties"]
    assert "hours" in defn["parameters"]["properties"]
    assert defn["parameters"]["required"] == ["entity_id"]


async def test_execute_history_tool_with_states(hass: HomeAssistant):
    """Test execute_history_tool returns formatted state changes."""
    mock_state1 = MagicMock()
    mock_state1.state = "on"
    mock_state1.last_changed = datetime(2026, 3, 11, 10, 0, 0)

    mock_state2 = MagicMock()
    mock_state2.state = "off"
    mock_state2.last_changed = datetime(2026, 3, 11, 11, 0, 0)

    with patch(
        "homeassistant.components.recorder.history.get_significant_states",
        return_value={"light.kitchen": [mock_state1, mock_state2]},
    ):
        result = await execute_history_tool(hass, "light.kitchen", 2.0)

    assert "light.kitchen" in result
    assert "on" in result
    assert "off" in result
    assert "2026-03-11 10:00:00" in result
    assert "2026-03-11 11:00:00" in result


async def test_execute_history_tool_no_states(hass: HomeAssistant):
    """Test execute_history_tool when no states found."""
    with patch(
        "homeassistant.components.recorder.history.get_significant_states",
        return_value={},
    ):
        result = await execute_history_tool(hass, "sensor.missing", 1.0)

    assert "No history found" in result
    assert "sensor.missing" in result


async def test_execute_history_tool_max_hours(hass: HomeAssistant):
    """Test that hours are capped at HISTORY_TOOL_MAX_HOURS."""
    with patch(
        "homeassistant.components.recorder.history.get_significant_states",
        return_value={},
    ) as mock_get:
        await execute_history_tool(hass, "sensor.temp", 999.0)

    # Verify the time window is capped
    call_args = mock_get.call_args[0]
    start_time = call_args[1]
    end_time = call_args[2]
    delta = end_time - start_time
    assert delta <= timedelta(hours=HISTORY_TOOL_MAX_HOURS + 0.1)


async def test_execute_history_tool_truncates_to_20(hass: HomeAssistant):
    """Test that output is limited to last 20 state changes."""
    states = []
    for i in range(30):
        s = MagicMock()
        s.state = f"state_{i}"
        s.last_changed = datetime(2026, 3, 11, 0, i, 0)
        states.append(s)

    with patch(
        "homeassistant.components.recorder.history.get_significant_states",
        return_value={"sensor.many": states},
    ):
        result = await execute_history_tool(hass, "sensor.many", 1.0)

    # Should contain last 20 states (10-29), not first 10
    assert "state_10" in result
    assert "state_29" in result
    assert "10 more entries omitted" in result


async def test_handle_history_tool_calls_executes_pending(hass: HomeAssistant):
    """Test _handle_history_tool_calls executes pending history tool calls."""
    tool_call = llm.ToolInput(
        tool_name=HISTORY_TOOL_NAME,
        tool_args={"entity_id": "light.test", "hours": 2.0},
        id="tc_1",
        external=True,
    )
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="What happened?"),
        AssistantContent(
            agent_id="test_agent",
            content=None,
            tool_calls=[tool_call],
        ),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    with patch(
        "custom_components.smartchain.conversation.execute_history_tool",
        new_callable=AsyncMock,
        return_value="State history for light.test (last 2.0h):\n  2026-03-11 10:00:00: on",
    ) as mock_exec:
        await _handle_history_tool_calls(hass, chat_log, "test_agent")

    mock_exec.assert_called_once_with(hass, "light.test", 2.0)
    chat_log.async_add_assistant_content_without_tools.assert_called_once()
    result_content = chat_log.async_add_assistant_content_without_tools.call_args[0][0]
    assert isinstance(result_content, ToolResultContent)
    assert result_content.tool_call_id == "tc_1"
    assert result_content.tool_name == HISTORY_TOOL_NAME
    assert "light.test" in result_content.tool_result


async def test_handle_history_tool_calls_skips_already_resolved(hass: HomeAssistant):
    """Test _handle_history_tool_calls skips tool calls that already have results."""
    tool_call = llm.ToolInput(
        tool_name=HISTORY_TOOL_NAME,
        tool_args={"entity_id": "light.test"},
        id="tc_1",
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
            tool_call_id="tc_1",
            tool_name=HISTORY_TOOL_NAME,
            tool_result="already done",
        ),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    with patch(
        "custom_components.smartchain.conversation.execute_history_tool",
        new_callable=AsyncMock,
    ) as mock_exec:
        await _handle_history_tool_calls(hass, chat_log, "test_agent")

    mock_exec.assert_not_called()
    chat_log.async_add_assistant_content_without_tools.assert_not_called()


async def test_handle_history_tool_calls_ignores_non_history_tools(hass: HomeAssistant):
    """Test _handle_history_tool_calls ignores non-history external tool calls."""
    tool_call = llm.ToolInput(
        tool_name="some_other_tool",
        tool_args={"arg": "value"},
        id="tc_2",
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

    with patch(
        "custom_components.smartchain.conversation.execute_history_tool",
        new_callable=AsyncMock,
    ) as mock_exec:
        await _handle_history_tool_calls(hass, chat_log, "test_agent")

    mock_exec.assert_not_called()
