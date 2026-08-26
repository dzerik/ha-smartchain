"""A built-in's name is reserved against MCP servers too, not only tools.yaml.

`loader.py` refuses a reserved name in the file and `config_flow` refuses one in
the panel. The third source of tool names — whatever an MCP server happens to
advertise — checked nothing. With `prefix: ""` (documented in USAGE §8.2) the
registry name is the server's own name for the tool, so a server exposing
`search_memory` puts a second `search_memory` into `bind_tools`: a 400 from
OpenAI and Anthropic, or a dispatch that resolves to the MCP tool while the
model reads the built-in's description.

`registry.get(...)` does not close this: the built-ins are never in the
`ToolRegistry` at all — they are attached at bind time — so the pre-existing
collision check sees nothing to collide with.
"""

import logging
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.mcp.config import StdioConfig
from custom_components.smartchain.tools.mcp.manager import MCPManager
from custom_components.smartchain.tools.model import ToolRegistry
from tests.conftest import BUILT_IN_TOOL_NAMES


def _client_class(tools: list[dict]):
    """Patch MCPClient so the server advertises exactly `tools`."""

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock()
        inst.list_tools = AsyncMock(return_value=tools)
        inst.close = AsyncMock()
        return inst

    patcher = patch("custom_components.smartchain.tools.mcp.manager.MCPClient")
    cls = patcher.start()
    cls.side_effect = make_instance
    return patcher


def _tool(name: str) -> dict:
    return {
        "name": name,
        "description": f"the server's {name}",
        "inputSchema": {"type": "object", "properties": {}},
    }


@pytest.mark.parametrize("reserved", sorted(BUILT_IN_TOOL_NAMES))
async def test_unprefixed_mcp_tool_may_not_take_a_built_in_name(
    hass: HomeAssistant, caplog, reserved: str
) -> None:
    """All six built-ins, parametrised so a seventh cannot quietly reopen the gap."""
    patcher = _client_class([_tool(reserved)])
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx", prefix="")])
        with caplog.at_level(logging.ERROR):
            await mgr.start()
            await mgr.wait_idle()

        assert registry.get(reserved) is None
        assert registry.names() == []
        await mgr.stop()
    finally:
        patcher.stop()

    # A visible refusal, not a silent drop: the user has to be able to find the
    # server and the tool that were rejected.
    assert "reserved" in caplog.text.lower()
    assert "fs" in caplog.text
    assert reserved in caplog.text


async def test_the_refusal_is_confined_to_the_reserved_name(hass: HomeAssistant) -> None:
    """The server's other tools still register — the skip is per tool, not per server."""
    patcher = _client_class([_tool("search_memory"), _tool("read_file")])
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx", prefix="")])
        await mgr.start()
        await mgr.wait_idle()

        assert registry.names() == ["read_file"]
        assert mgr._servers["fs"].registered_names == ["read_file"]
        await mgr.stop()
        # And the survivor is still deregistered on stop, i.e. the skipped name
        # did not corrupt the bookkeeping that removes what was registered.
        assert registry.names() == []
    finally:
        patcher.stop()


async def test_a_prefixed_built_in_name_is_not_a_collision(hass: HomeAssistant) -> None:
    """`fs__search_memory` shadows nothing and must keep working.

    The reservation is on the *registry* name. Narrowing it to the server's raw
    name would refuse tools that never collide with anything.
    """
    patcher = _client_class([_tool("search_memory")])
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()

        assert registry.get("fs__search_memory") is not None
        await mgr.stop()
    finally:
        patcher.stop()
