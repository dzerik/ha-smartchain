"""Execute an MCP action — defers to the MCPManager.

This file is a stub for Task 3. The real implementation lands in Task 10
once MCPManager is in place; for now we expose a callable that raises so
the dispatcher branch is wired but the unimplemented path is loud.
"""

from typing import Any

from homeassistant.core import HomeAssistant

from ..model import MCPAction


async def execute_mcp(
    hass: HomeAssistant,
    action: MCPAction,
    args: dict[str, Any],
) -> str:
    """Stub — replaced in Task 10 with the real MCPManager-backed call."""
    raise NotImplementedError("execute_mcp not implemented until Task 10")
