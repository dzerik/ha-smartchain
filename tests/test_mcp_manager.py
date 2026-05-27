"""Tests for MCPManager — lifecycle, registry registration, reconnect."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.mcp.config import StdioConfig
from custom_components.smartchain.tools.mcp.manager import MCPManager
from custom_components.smartchain.tools.model import (
    MCPAction,
    ToolRegistry,
)


@pytest.fixture
def fake_client_class():
    """Patch MCPClient to a controllable mock."""
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        instance = AsyncMock()
        instance.list_tools = AsyncMock(
            return_value=[
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]
        )
        instance.call_tool = AsyncMock(return_value="file contents")
        cls.return_value = instance
        yield cls, instance


async def test_start_registers_discovered_tools(hass: HomeAssistant, fake_client_class) -> None:
    """After start(), discovered tools land in the registry as MCPAction."""
    _cls, _instance = fake_client_class
    registry = ToolRegistry()
    mgr = MCPManager(hass, registry)
    mgr.configure([StdioConfig(name="fs", command="npx")])
    await mgr.start()
    await mgr.wait_idle()

    tool = registry.get("fs__read_file")
    assert tool is not None
    assert isinstance(tool.action, MCPAction)
    assert tool.action.server == "fs"
    assert tool.action.tool_name == "read_file"
    await mgr.stop()


async def test_disabled_server_skipped(hass: HomeAssistant, fake_client_class) -> None:
    _cls, _ = fake_client_class
    registry = ToolRegistry()
    mgr = MCPManager(hass, registry)
    mgr.configure([StdioConfig(name="fs", command="npx", enabled=False)])
    await mgr.start()
    await mgr.wait_idle()

    assert registry.names() == []
    _cls.assert_not_called()


async def test_call_tool_routes_through_client(hass: HomeAssistant, fake_client_class) -> None:
    _cls, instance = fake_client_class
    registry = ToolRegistry()
    mgr = MCPManager(hass, registry)
    mgr.configure([StdioConfig(name="fs", command="npx")])
    await mgr.start()
    await mgr.wait_idle()

    result = await mgr.call_tool("fs", "read_file", {"path": "/x"})
    assert result == "file contents"
    instance.call_tool.assert_awaited_once_with("read_file", {"path": "/x"})
    await mgr.stop()


async def test_call_tool_unknown_server_returns_unavailable(
    hass: HomeAssistant, fake_client_class
) -> None:
    _cls, _ = fake_client_class
    registry = ToolRegistry()
    mgr = MCPManager(hass, registry)
    mgr.configure([])
    await mgr.start()
    await mgr.wait_idle()

    result = await mgr.call_tool("nope", "read_file", {})
    assert "unavailable" in result.lower()


async def test_stop_closes_client_and_removes_tools(hass: HomeAssistant, fake_client_class) -> None:
    _cls, instance = fake_client_class
    registry = ToolRegistry()
    mgr = MCPManager(hass, registry)
    mgr.configure([StdioConfig(name="fs", command="npx")])
    await mgr.start()
    await mgr.wait_idle()
    assert registry.get("fs__read_file") is not None

    await mgr.stop()
    assert registry.get("fs__read_file") is None
    instance.close.assert_awaited()


async def test_connect_failure_triggers_reconnect_attempt(
    hass: HomeAssistant,
) -> None:
    """A failing connect() schedules a retry; tools stay absent meanwhile."""
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        attempts = {"n": 0}

        async def connect_side_effect():
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise RuntimeError("boom")

        def make_instance(*args, **kwargs):
            inst = AsyncMock()
            inst.connect = AsyncMock(side_effect=connect_side_effect)
            inst.list_tools = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            return inst

        cls.side_effect = make_instance

        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        # Tighten delays for the test.
        mgr._initial_delay = 0.01
        mgr._max_delay = 0.05
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        # Wait long enough for the retry.
        await mgr.wait_idle(timeout=2.0)

        assert attempts["n"] >= 2
        await mgr.stop()


async def test_call_tool_failure_triggers_reconnect(
    hass: HomeAssistant,
) -> None:
    """A call_tool exception schedules a fresh connect task."""
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        first = AsyncMock()
        first.list_tools = AsyncMock(
            return_value=[
                {
                    "name": "x",
                    "description": "",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]
        )
        first.call_tool = AsyncMock(side_effect=RuntimeError("transport gone"))
        first.close = AsyncMock()

        second = AsyncMock()
        second.list_tools = AsyncMock(return_value=[])
        second.close = AsyncMock()

        cls.side_effect = [first, second]

        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr._initial_delay = 0.01
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()

        # First call surfaces "unavailable" AND triggers a fresh connect.
        result = await mgr.call_tool("fs", "x", {})
        assert "unavailable" in result.lower()

        # Wait for the new task to settle.
        await mgr.wait_idle(timeout=2.0)
        assert cls.call_count == 2

        await mgr.stop()
