"""Reconnect is a lifecycle operation, and every other one is serialised.

`_reconnect_server` was the one MCP lifecycle path outside any lock, and it is
the one reached from a tool call — i.e. from an LLM turn, concurrently with
other LLM turns and with `smartchain.reload_tools`. It has two yield points
(`client.close()` and awaiting the cancelled task), so two tool calls that both
fail against the same dead server each ran the whole teardown-and-relaunch:
two `_run_server` tasks, two clients, two subprocesses, and nobody left holding
a reference to the first. `registered_names` was emptied by the first pass, so
the second `_unregister_tools` took its early return and left the dead server's
tools in the registry, bound to the model.

The lock is `_rebuild_lock` — the same one every rebuild and teardown of the
shared subsystems takes — because a reconnect racing a rebuild is the other
half of the bug: `_rebuild_subsystems` calls `configure()`, which replaces
`_servers` wholesale, and a `_run_server` relaunched a moment earlier then
raised `KeyError` on its own server name.
"""

import asyncio
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


def _dead_transport_client_class(created: list, closed: list):
    """Patch MCPClient so every call_tool fails, and both yield to the loop.

    The `sleep(0)` in each is what makes the interleaving deterministic rather
    than lucky: without a yield inside `call_tool` and `close`, two gathered
    calls would run to completion one after the other and the race under test
    would never be entered.
    """

    async def failing_call(*args, **kwargs):
        await asyncio.sleep(0)
        raise RuntimeError("transport gone")

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock()
        inst.list_tools = AsyncMock(return_value=TOOLS)
        inst.call_tool = AsyncMock(side_effect=failing_call)

        async def close():
            await asyncio.sleep(0)
            closed.append(inst)

        inst.close = AsyncMock(side_effect=close)
        created.append(inst)
        return inst

    patcher = patch("custom_components.smartchain.tools.mcp.manager.MCPClient")
    cls = patcher.start()
    cls.side_effect = make_instance
    return patcher


async def test_two_failing_calls_produce_exactly_one_reconnect(hass: HomeAssistant) -> None:
    """Two tool calls die on the same session; one replacement client is built.

    Unserialised this ends with three clients and two live `_run_server` tasks —
    the middle one owning a subprocess no code path will ever close.
    """
    created: list = []
    closed: list = []
    patcher = _dead_transport_client_class(created, closed)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()
        first = mgr._servers["fs"].client
        assert first is created[0]

        results = await asyncio.gather(
            mgr.call_tool("fs", "x", {}),
            mgr.call_tool("fs", "x", {}),
        )
        assert all("unavailable" in r.lower() for r in results)
        await mgr.wait_idle()

        # One dead client closed exactly once, one replacement built.
        assert closed == [first]
        assert len(created) == 2, f"{len(created)} clients built, expected 2"
        live = [s.task for s in mgr._servers.values() if s.task is not None and not s.task.done()]
        assert len(live) == 1
        assert mgr._servers["fs"].client is created[1]
        await mgr.stop()
    finally:
        patcher.stop()


async def test_the_second_caller_leaves_the_registry_intact(hass: HomeAssistant) -> None:
    """The replacement session's tools survive the losing reconnect.

    The second pass used to run `_unregister_tools` against a `registered_names`
    the first had already emptied — an early return that left the *new* tools
    listed while the old ones stayed bound. Here the opposite must hold: after
    both calls settle, the registry describes exactly the live session.
    """
    created: list = []
    closed: list = []
    patcher = _dead_transport_client_class(created, closed)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()

        await asyncio.gather(mgr.call_tool("fs", "x", {}), mgr.call_tool("fs", "x", {}))
        await mgr.wait_idle()

        assert registry.names() == ["fs__x"]
        assert mgr._servers["fs"].registered_names == ["fs__x"]
        await mgr.stop()
        assert registry.names() == []
    finally:
        patcher.stop()


async def test_a_reconnect_waits_for_a_rebuild_in_flight(hass: HomeAssistant) -> None:
    """While `_rebuild_lock` is held, no reconnect touches client or registry.

    This is the guarantee that keeps a reconnect from interleaving with
    `smartchain.reload_tools`, which stops the manager, re-`configure()`s it and
    restarts it under that lock.
    """
    created: list = []
    closed: list = []
    patcher = _dead_transport_client_class(created, closed)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()
        first = mgr._servers["fs"].client

        async with _rebuild_lock(hass):
            call = asyncio.create_task(mgr.call_tool("fs", "x", {}))
            # Long enough for the call to fail and reach the reconnect.
            for _ in range(20):
                await asyncio.sleep(0)
            assert closed == [], "the client was closed while a rebuild held the lock"
            assert mgr._servers["fs"].client is first
            assert registry.names() == ["fs__x"]

        assert "unavailable" in (await call).lower()
        await mgr.wait_idle()
        assert closed == [first]
        assert len(created) == 2
        await mgr.stop()
    finally:
        patcher.stop()


async def test_a_connection_that_lands_after_a_reload_is_closed_not_published(
    hass: HomeAssistant,
) -> None:
    """A connect still in flight when the table is replaced publishes nothing.

    `connect()` and `list_tools()` are two awaits during which a rebuild can
    swap `_servers`. Publishing regardless writes a live client into a state
    object nothing owns any more — `stop()` iterates the *new* table, so that
    client is never closed and its tools stay in the shared registry for the
    life of the process.
    """
    created: list = []
    closed: list = []
    gate = asyncio.Event()

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

    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        cls.side_effect = make_instance
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        task = mgr._servers["fs"].task
        for _ in range(5):
            await asyncio.sleep(0)
        assert created, "the connect task never started"

        # The reload lands while the handshake is still open.
        mgr.configure([])
        gate.set()
        await asyncio.wait_for(task, timeout=3.0)

        assert closed == [created[0]], "the orphaned session was left open"
        assert registry.names() == []


async def test_a_server_dropped_by_a_reload_does_not_crash_its_task(hass: HomeAssistant) -> None:
    """`_run_server` for a name `configure()` has since removed exits quietly.

    `_rebuild_subsystems` replaces `_servers` in one assignment. A task launched
    against the old table — by `start()` or by a reconnect a moment before — then
    looked its own name up in the new one and raised `KeyError`, which surfaces
    only as an unhandled-exception log from a background task.
    """
    created: list = []
    closed: list = []
    patcher = _dead_transport_client_class(created, closed)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        # The reload lands between the task being scheduled and its first line.
        mgr.configure([])

        await mgr._run_server("fs")

        assert created == [], "a client was built for a server that is no longer configured"
        assert registry.names() == []
    finally:
        patcher.stop()
