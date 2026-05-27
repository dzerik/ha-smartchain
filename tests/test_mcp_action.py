"""Tests for execute_mcp (dispatcher's fifth branch)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.actions.mcp_action import execute_mcp
from custom_components.smartchain.tools.model import MCPAction


@pytest.fixture
def manager_in_hass(hass: HomeAssistant):
    manager = MagicMock()
    manager.call_tool = AsyncMock(return_value="OK")
    hass.data.setdefault(DOMAIN, {})["mcp_manager"] = manager
    return manager


async def test_execute_mcp_routes_to_manager(hass: HomeAssistant, manager_in_hass) -> None:
    action = MCPAction(server="fs", tool_name="read_file")
    result = await execute_mcp(hass, action, {"path": "/x"})
    assert result == "OK"
    manager_in_hass.call_tool.assert_awaited_once_with("fs", "read_file", {"path": "/x"})


async def test_execute_mcp_with_no_manager_returns_unavailable(
    hass: HomeAssistant,
) -> None:
    """If no manager is in hass.data (defensive), we still return cleanly."""
    hass.data.pop(DOMAIN, None)
    action = MCPAction(server="fs", tool_name="read_file")
    result = await execute_mcp(hass, action, {})
    assert "unavailable" in result.lower()


async def test_dispatch_via_dispatcher_routes_to_mcp(hass: HomeAssistant, manager_in_hass) -> None:
    """Sanity: the dispatcher branch added in Task 3 now hits the real executor."""
    from custom_components.smartchain.tools.dispatcher import dispatch
    from custom_components.smartchain.tools.model import CustomTool

    tool = CustomTool(
        name="fs__read_file",
        description="Read a file",
        parameters={"type": "object", "properties": {}},
        action=MCPAction(server="fs", tool_name="read_file"),
    )
    result = await dispatch(hass, tool, {})
    assert result == "OK"
