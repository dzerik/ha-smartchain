"""The per-call budget on `MCPManager.call_tool`.

USAGE.md §8.3 promises "per-call timeout (default 30 s)". Nothing measured it:
replacing `asyncio.timeout(self._call_timeout)` with `asyncio.timeout(None)`
left every MCP test green, and an MCP server that accepts a call and then never
answers would hang the conversation turn forever.

`MCPAction.timeout` is written by `_register_tools` and read by nobody. It is
kept as a mirror of the bound the manager enforces — there is no YAML key that
sets a per-tool budget, and `MCPAction` is constructed only by the manager — so
the test below pins the two together instead of letting them drift apart in
silence.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import MCP_CALL_TIMEOUT_DEFAULT
from custom_components.smartchain.tools.mcp.config import StdioConfig
from custom_components.smartchain.tools.mcp.manager import MCPManager
from custom_components.smartchain.tools.model import ToolRegistry

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file",
        "inputSchema": {"type": "object", "properties": {}},
    }
]


def _hanging_client_class(hang: asyncio.Event):
    """Patch MCPClient so call_tool never returns until `hang` is set."""

    async def never_answers(*args, **kwargs):
        await hang.wait()
        return "too late"

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock()
        inst.list_tools = AsyncMock(return_value=TOOLS)
        inst.call_tool = AsyncMock(side_effect=never_answers)
        inst.close = AsyncMock()
        return inst

    patcher = patch("custom_components.smartchain.tools.mcp.manager.MCPClient")
    cls = patcher.start()
    cls.side_effect = make_instance
    return patcher


def test_default_call_timeout_is_thirty_seconds() -> None:
    """The documented default, pinned to the constant the manager reads."""
    assert MCP_CALL_TIMEOUT_DEFAULT == 30


async def test_manager_adopts_the_default_call_timeout(hass: HomeAssistant) -> None:
    mgr = MCPManager(hass, ToolRegistry())
    assert mgr._call_timeout == MCP_CALL_TIMEOUT_DEFAULT


async def test_hanging_server_call_gives_up_and_returns_an_error(
    hass: HomeAssistant, caplog
) -> None:
    """A server that never answers must not hold the conversation turn open."""
    hang = asyncio.Event()
    patcher = _hanging_client_class(hang)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr._call_timeout = 0.05
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()

        with caplog.at_level(logging.WARNING):
            # The outer bound is the test's own tripwire: if the manager stops
            # enforcing its budget this raises instead of asserting.
            result = await asyncio.wait_for(
                mgr.call_tool("fs", "read_file", {"path": "/x"}), timeout=3.0
            )

        assert result == "Error: MCP call timed out"
        assert "timed out" in caplog.text
        await mgr.stop()
    finally:
        hang.set()
        patcher.stop()


async def test_a_timed_out_call_does_not_tear_down_a_healthy_connection(
    hass: HomeAssistant,
) -> None:
    """One slow call is not a dead server: the session and its tools survive.

    The reconnect branch sits below the timeout branch; if a TimeoutError ever
    reached it, a single slow tool would deregister the server's whole toolset
    and drop the live session.
    """
    hang = asyncio.Event()
    patcher = _hanging_client_class(hang)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr._call_timeout = 0.05
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()
        client_before = mgr._servers["fs"].client
        assert client_before is not None

        await asyncio.wait_for(mgr.call_tool("fs", "read_file", {}), timeout=3.0)

        assert mgr._servers["fs"].client is client_before
        assert registry.get("fs__read_file") is not None
        client_before.close.assert_not_awaited()
        await mgr.stop()
    finally:
        hang.set()
        patcher.stop()


async def test_a_prompt_answer_is_returned_untouched(hass: HomeAssistant) -> None:
    """The bound must not truncate or reshape a call that answers in time."""
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:

        async def answers_slowly(*args, **kwargs):
            await asyncio.sleep(0)
            return "file contents"

        def make_instance(*args, **kwargs):
            inst = AsyncMock()
            inst.connect = AsyncMock()
            inst.list_tools = AsyncMock(return_value=TOOLS)
            inst.call_tool = AsyncMock(side_effect=answers_slowly)
            inst.close = AsyncMock()
            return inst

        cls.side_effect = make_instance
        mgr = MCPManager(hass, ToolRegistry())
        mgr._call_timeout = 0.5
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()

        assert await mgr.call_tool("fs", "read_file", {}) == "file contents"
        await mgr.stop()


@pytest.mark.parametrize("budget", [7, 30])
async def test_registered_action_mirrors_the_budget_the_manager_enforces(
    hass: HomeAssistant, budget: int
) -> None:
    """`MCPAction.timeout` records the bound in force, never a different number.

    Nothing reads the field today, so a wrong value would surface only in the
    tool inventory and the websocket API, where it would misinform the user
    about how long a call may run.
    """
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:

        def make_instance(*args, **kwargs):
            inst = AsyncMock()
            inst.connect = AsyncMock()
            inst.list_tools = AsyncMock(return_value=TOOLS)
            inst.close = AsyncMock()
            return inst

        cls.side_effect = make_instance
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr._call_timeout = budget
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()

        tool = registry.get("fs__read_file")
        assert tool is not None
        assert tool.action.timeout == budget
        assert tool.action.timeout == mgr._call_timeout
        await mgr.stop()
