"""A connection that dies quietly has to be noticed.

README and USAGE both promise auto-reconnect. What existed was reconnect on
*connect* failure and reconnect as a side effect of an exception inside
`call_tool`. Between those two, a session that had connected once was assumed
alive forever: the server task sat in `while not self._stopped: await sleep(60)`,
`state.client` kept pointing at a dead transport, and its tools stayed in the
`ToolRegistry` and went out in every `bind_tools`. A server that died at 3am
came back only when a model happened to call one of its tools — and then only
after burning that tool call on an error.

The probe is an MCP `ping` round-trip, because it is the only check that
distinguishes "the process object still exists" from "the peer still answers".
"""

import asyncio
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.mcp.config import StdioConfig
from custom_components.smartchain.tools.mcp.manager import (
    MCP_HEALTH_CHECK_INTERVAL,
    MCPManager,
)
from custom_components.smartchain.tools.model import ToolRegistry


def _tools(name: str) -> list[dict]:
    return [
        {
            "name": name,
            "description": "a tool",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]


def _client_class(created: list, closed: list, pings: list, alive: dict):
    """Patch MCPClient: session N advertises `tool{N}`, ping obeys `alive`.

    `alive["ok"]` False makes every subsequent ping raise, the way a broken
    transport does; `alive["hang"]` makes it never answer, the way a wedged
    peer does.
    """

    def make_instance(*args, **kwargs):
        index = len(created) + 1
        inst = AsyncMock()
        inst.connect = AsyncMock()
        inst.list_tools = AsyncMock(return_value=_tools(f"tool{index}"))

        async def ping():
            pings.append(inst)
            if alive.get("hang"):
                await asyncio.Event().wait()
            if not alive.get("ok", True):
                raise RuntimeError("transport closed")

        async def close():
            closed.append(inst)

        inst.ping = AsyncMock(side_effect=ping)
        inst.close = AsyncMock(side_effect=close)
        created.append(inst)
        return inst

    patcher = patch("custom_components.smartchain.tools.mcp.manager.MCPClient")
    cls = patcher.start()
    cls.side_effect = make_instance
    return patcher


async def _wait_for(predicate, timeout: float = 3.0) -> None:
    """Poll until `predicate()` or fail the test with the reason it never held."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition never became true within the timeout")


def test_the_health_interval_is_a_minute() -> None:
    """Pinned so a debugging value cannot be left behind: a one-second ping to
    every configured MCP server, forever, is a very different program."""
    assert MCP_HEALTH_CHECK_INTERVAL == 60.0


async def test_a_fresh_manager_adopts_the_module_interval(hass: HomeAssistant) -> None:
    assert MCPManager(hass, ToolRegistry())._health_interval == MCP_HEALTH_CHECK_INTERVAL


async def test_a_silently_dropped_connection_is_replaced_without_a_tool_call(
    hass: HomeAssistant,
) -> None:
    """No `call_tool` anywhere in this test — the drop is found by the probe alone."""
    created: list = []
    closed: list = []
    pings: list = []
    alive = {"ok": True}
    patcher = _client_class(created, closed, pings, alive)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr._health_interval = 0.005
        mgr._initial_delay = 0.001
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()
        first = mgr._servers["fs"].client
        assert registry.names() == ["fs__tool1"]

        # The peer goes away without telling anyone.
        alive["ok"] = False

        await _wait_for(lambda: len(created) == 2)
        await _wait_for(lambda: registry.names() == ["fs__tool2"])

        assert closed == [first], "the dead session was not closed"
        assert mgr._servers["fs"].client is created[1]
        # The dead server's tools are gone from the registry, not merely joined
        # by the new ones — they would otherwise still be bound to the model.
        assert registry.get("fs__tool1") is None
        await mgr.stop()
    finally:
        patcher.stop()


async def test_a_ping_that_never_answers_counts_as_dead(hass: HomeAssistant) -> None:
    """A wedged peer holds the socket open and answers nothing; that is not alive."""
    created: list = []
    closed: list = []
    pings: list = []
    alive = {"hang": True}
    patcher = _client_class(created, closed, pings, alive)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr._health_interval = 0.005
        mgr._initial_delay = 0.001
        mgr._call_timeout = 0.02
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()
        first = mgr._servers["fs"].client

        await _wait_for(lambda: len(created) >= 2)
        assert closed[0] is first
        await mgr.stop()
    finally:
        patcher.stop()


async def test_a_healthy_connection_is_left_alone(hass: HomeAssistant) -> None:
    """Many probes, one session: the check must not itself be a reconnect loop."""
    created: list = []
    closed: list = []
    pings: list = []
    alive = {"ok": True}
    patcher = _client_class(created, closed, pings, alive)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr._health_interval = 0.005
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()
        first = mgr._servers["fs"].client

        # Enough time for several probes to have run.
        await _wait_for(lambda: len(pings) >= 3)

        assert created == [first], "a healthy server was reconnected"
        assert closed == []
        assert registry.names() == ["fs__tool1"]
        assert mgr._servers["fs"].client is first
        await mgr.stop()
    finally:
        patcher.stop()


async def test_the_probe_is_a_round_trip_to_the_server(hass: HomeAssistant) -> None:
    """The check must reach the peer. A local `client is not None` test would
    pass forever against a dead subprocess."""
    created: list = []
    closed: list = []
    pings: list = []
    patcher = _client_class(created, closed, pings, {"ok": True})
    try:
        mgr = MCPManager(hass, ToolRegistry())
        mgr._health_interval = 0.005
        mgr.configure([StdioConfig(name="fs", command="npx")])
        await mgr.start()
        await mgr.wait_idle()

        await _wait_for(lambda: pings != [])
        assert pings[0] is created[0]
        await mgr.stop()
    finally:
        patcher.stop()


async def test_a_dropped_connection_retries_from_the_initial_delay(hass: HomeAssistant) -> None:
    """The ramp resets on a working connection, including one this loop reconnects itself.

    The task no longer exits when a session dies — it loops round inside
    `_run_server` — so the fresh-task-fresh-`delay` accident that used to
    provide this reset no longer applies. Without an explicit reset, a server
    that took a few tries to come up in the morning would still be waiting out
    the escalated delay when it blipped in the evening.
    """
    server = {"connect_failures": 2, "alive": True}
    recorded: list[float] = []
    real_sleep = asyncio.sleep

    def make_instance(*args, **kwargs):
        inst = AsyncMock()

        async def connect():
            if server["connect_failures"] > 0:
                server["connect_failures"] -= 1
                raise RuntimeError("boom")

        async def ping():
            if not server["alive"]:
                raise RuntimeError("transport closed")

        inst.connect = AsyncMock(side_effect=connect)
        inst.ping = AsyncMock(side_effect=ping)
        inst.list_tools = AsyncMock(return_value=_tools("t"))
        inst.close = AsyncMock()
        return inst

    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        cls.side_effect = make_instance
        mgr = MCPManager(hass, ToolRegistry())
        mgr._health_interval = 0.005
        mgr._initial_delay = 0.02
        mgr._max_delay = 1.0
        mgr.configure([StdioConfig(name="fs", command="npx")])

        async def recording_sleep(delay, *args, **kwargs):
            task = asyncio.current_task()
            if (
                task is not None
                and task.get_name() == "smartchain_mcp_fs"
                and delay != mgr._health_interval
            ):
                recorded.append(delay)
                return await real_sleep(0)
            return await real_sleep(delay, *args, **kwargs)

        with patch("asyncio.sleep", recording_sleep):
            await mgr.start()
            await mgr.wait_idle(timeout=3.0)
            assert recorded == [0.02, 0.04], recorded

            # A live session, then a silent death; the next connect fails once.
            server["connect_failures"] = 1
            server["alive"] = False
            await _wait_for(lambda: len(recorded) >= 3)

            assert recorded[2] == mgr._initial_delay, recorded
            await mgr.stop()
