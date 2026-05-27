"""Execute an MCP action — defers to the MCPManager in hass.data."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import DOMAIN
from ..model import MCPAction

LOGGER = logging.getLogger(__name__)


async def execute_mcp(
    hass: HomeAssistant,
    action: MCPAction,
    args: dict[str, Any],
) -> str:
    """Look up the MCPManager and ask it to call the configured tool."""
    domain_data = hass.data.get(DOMAIN) or {}
    manager = domain_data.get("mcp_manager")
    if manager is None:
        return f"Error: MCP server {action.server} is unavailable"
    return await manager.call_tool(action.server, action.tool_name, args)
