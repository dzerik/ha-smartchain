"""Every client the manager builds is closed, including the ones it never published.

`_run_server` builds an `MCPClient`, connects it, lists its tools, and only then
takes `_lifecycle_lock` to write it into `state.client`. Between the handshake
and that write the session exists and nothing but the local variable knows about
it: `stop()` closes `state.client`, which is still `None`.

The production shape is the one `_rebuild_lock` documents: `update_listener` and
a websocket handler answer the same subentry write, both reach `_reload_registry`,
and the winner holds the lock across `MCPManager.stop()`. A connect that lands in
that window queues for the lock, is cancelled by the `stop()` that is holding it,
and — before this file — took its live transport with it. For a stdio server that
transport is a subprocess, kept for the life of the Home Assistant process.

The counting is the point. An exception-free teardown proves nothing here: the
leak never raised, it just quietly kept a socket. So both tests compare the
number of clients built against the number closed.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.smartchain import _rebuild_lock
from custom_components.smartchain.tools.mcp.config import StdioConfig
from custom_components.smartchain.tools.mcp.manager import MCPManager
from custom_components.smartchain.tools.model import ToolRegistry

TOOLS = [
    {
        "name": "x",
        "description": "a tool",
        "inputSchema": {"type": "object", "properties": {}},
    }
]


def _gated_client_class(created: list, closed: list, gate: asyncio.Event):
    """Patch `MCPClient` so the handshake finishes only when `gate` is set."""

    async def slow_connect(*args, **kwargs):
        await gate.wait()

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock(side_effect=slow_connect)
        inst.list_tools = AsyncMock(return_value=TOOLS)

        async def close():
            closed.append(inst)

        inst.close = AsyncMock(side_effect=close)
        created.append(inst)
        return inst

    return patch(
        "custom_components.smartchain.tools.mcp.manager.MCPClient", side_effect=make_instance
    )


async def test_a_connect_cancelled_while_queued_for_the_lock_is_closed(
    hass: HomeAssistant,
) -> None:
    """The rebuild holding the lock stops the manager; the queued session still closes."""
    created: list = []
    closed: list = []
    gate = asyncio.Event()

    with _gated_client_class(created, closed, gate):
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        for _ in range(5):
            await asyncio.sleep(0)
        assert created, "the connect task never started"

        # A rebuild holds `_rebuild_lock` — exactly as `_reload_registry` does
        # around `MCPManager.stop()`.
        async with _rebuild_lock(hass):
            gate.set()
            # Long enough for the handshake to finish and the task to block on
            # the lock this coroutine is holding.
            for _ in range(20):
                await asyncio.sleep(0)
            assert mgr._servers["fs"].client is None, (
                "the publish happened without the lock; this test no longer covers the window"
            )
            await mgr.stop()

        assert len(closed) == len(created), (
            f"{len(created)} clients built, {len(closed)} closed — "
            "a connected session was dropped without being closed"
        )
        assert registry.names() == []


async def test_a_connect_cancelled_while_listing_tools_is_closed(hass: HomeAssistant) -> None:
    """The same window, one await earlier: the handshake is done, `list_tools` is not.

    A server that answers `initialize` and then takes its time over `tools/list`
    is an ordinary slow server, and a reload during it cancels the task on the
    `list_tools` await. The session is fully live by then — closing it is the
    only way its transport goes away.
    """
    created: list = []
    closed: list = []
    hang = asyncio.Event()

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock()

        async def never_answers(*a, **kw):
            await hang.wait()
            return TOOLS

        inst.list_tools = AsyncMock(side_effect=never_answers)

        async def close():
            closed.append(inst)

        inst.close = AsyncMock(side_effect=close)
        created.append(inst)
        return inst

    with patch(
        "custom_components.smartchain.tools.mcp.manager.MCPClient", side_effect=make_instance
    ):
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        for _ in range(5):
            await asyncio.sleep(0)
        assert created, "the connect task never started"
        assert mgr._servers["fs"].client is None

        await mgr.stop()

        assert len(closed) == len(created), (
            f"{len(created)} clients built, {len(closed)} closed — "
            "a session cancelled mid-handshake was dropped without being closed"
        )


async def test_a_close_that_fails_during_cancellation_is_logged(
    hass: HomeAssistant, caplog
) -> None:
    """A session that cannot be closed must not disappear silently.

    The whole failure mode this file exists for is an invisible one, so the
    fallback for "closing it did not work either" is a log line, not silence.
    """
    created: list = []
    gate = asyncio.Event()

    def make_instance(*args, **kwargs):
        inst = AsyncMock()

        async def slow_connect(*a, **kw):
            await gate.wait()

        inst.connect = AsyncMock(side_effect=slow_connect)
        inst.list_tools = AsyncMock(return_value=TOOLS)
        inst.close = AsyncMock(side_effect=OSError("transport already gone"))
        created.append(inst)
        return inst

    with patch(
        "custom_components.smartchain.tools.mcp.manager.MCPClient", side_effect=make_instance
    ):
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        for _ in range(5):
            await asyncio.sleep(0)

        with caplog.at_level(logging.ERROR):
            async with _rebuild_lock(hass):
                gate.set()
                for _ in range(20):
                    await asyncio.sleep(0)
                await mgr.stop()

        assert created, "the connect task never started"
        assert "Error closing MCP client for fs" in caplog.text, (
            "a client that refused to close left no trace in the log"
        )


async def test_a_close_cut_short_by_a_second_cancellation_is_logged(
    hass: HomeAssistant, caplog
) -> None:
    """The last stop on the way down still speaks.

    One `cancel()` is delivered once, so the close above runs to completion. A
    second one — a shutdown landing on top of a reload — can interrupt the close
    itself, and then the session really is lost. There is nothing left to try at
    that point; the only thing that must not happen is silence.
    """
    gate = asyncio.Event()

    def make_instance(*args, **kwargs):
        inst = AsyncMock()

        async def slow_connect(*a, **kw):
            await gate.wait()

        async def cancelled_close():
            raise asyncio.CancelledError

        inst.connect = AsyncMock(side_effect=slow_connect)
        inst.list_tools = AsyncMock(return_value=TOOLS)
        inst.close = AsyncMock(side_effect=cancelled_close)
        return inst

    with patch(
        "custom_components.smartchain.tools.mcp.manager.MCPClient", side_effect=make_instance
    ):
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        for _ in range(5):
            await asyncio.sleep(0)

        with caplog.at_level(logging.WARNING):
            async with _rebuild_lock(hass):
                gate.set()
                for _ in range(20):
                    await asyncio.sleep(0)
                await mgr.stop()

    assert "the close was itself cancelled" in caplog.text, (
        "a session lost to a second cancellation left no trace in the log"
    )
